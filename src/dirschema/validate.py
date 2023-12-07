"""Validation API functionality for DirSchema."""
from __future__ import annotations

import copy
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel
from ruamel.yaml import YAML

from .adapters import IDirectory, get_adapter_for
from .core import DSRule, MetaConvention, PathSlice, Rule, TypeEnum
from .json.parse import load_json, to_uri
from .json.validate import (
    JSONValidationErrors,
    ValidationHandler,
    resolve_validator,
    validate_metadata,
)
from .log import logger

yaml = YAML(typ="safe")
yaml.default_flow_style = False


def loc_to_jsonpointer(lst) -> str:
    """Convert a list of string keys and int indices to a JSON Pointer string."""
    return "/" + "/".join(map(str, lst))


def json_dict(model, **kwargs):
    """Given a Pydantic model, convert it to a raw JSON compatible dict.

    This uses a round-trip via JSON-serialization and deserialization to get rid
    of non-JSON entities (the `BaseModel.dict()` method yields possibly non-JSON dicts).
    """
    return json.loads(model.json(**kwargs))


class DSValidationError(BaseModel):
    """A single Dirschema validation error."""

    path: str
    """File path that was evaluated (possibly a result of applied rewrites)."""

    err: Union[str, JSONValidationErrors]
    """Error object (error message or a dict with refined validation errors)."""


DSValidationErrors = Dict[Tuple[Union[str, int], ...], DSValidationError]
"""Dict mapping from error locations in schema to errors.

The keys of this dict can be used to access the corresponding sub-rule
if the schema is loaded as a JSON dict.
"""

DSValidationResult = Dict[str, DSValidationErrors]
"""The validation result is a mapping from file/directory paths to
corresponding validation errors for all entities where validation failed.
"""


class DSEvalCtx(BaseModel):
    """DirSchema evaluation context, used like a Reader Monad.

    Contains information that is required to evaluate a rule for a path.
    """

    class Config:  # noqa: D106
        arbitrary_types_allowed = True

    dirAdapter: IDirectory
    """Adapter to access metadata files and get paths from."""

    metaConvention: MetaConvention = MetaConvention()
    """Convention to use for validMeta."""

    # ----

    errors: DSValidationErrors = {}
    failed: bool = False

    filePath: str = ""
    """Path of currently checked file (possibly rewritten)."""

    location: List[Union[str, int]] = []
    """Relative location of current rule."""

    # passed down from parent rule / overridden with current rule:

    matchStart: int = 0
    matchStop: int = 0
    matchPat: Optional[re.Pattern] = None

    @classmethod
    def fresh(cls, rule: DSRule, **kwargs):
        """Initialize a fresh evaluation context."""
        ret = DSEvalCtx(**kwargs)  # initialize most fields from passed kwargs
        return ret.descend(rule)  # initialize match* fields from rule

    def descend(
        self,
        rule: DSRule,
        filepath: Optional[str] = None,
        reachedVia: Optional[Any] = None,
    ) -> DSEvalCtx:
        """Return a new context updated with fields from the given rule.

        Input must be the next sub-rule, the possibly rewritten entity path
        and the key in the parent rule that is used to access the sub-rule.

        This will not preserve the parent errors (use `add_errors` to merge).
        """
        ret = self.copy()
        ret.errors = {}
        ret.location = list(self.location)

        if isinstance(rule.__root__, Rule):
            # override match configuration and pattern, if specified in child rule
            rl: Rule = rule.__root__
            if rl.matchStart:
                ret.matchStart = rl.matchStart
            if rl.matchStop:
                ret.matchStart = rl.matchStop
            if rl.match:
                ret.matchPat = rl.match

        if filepath is not None:
            ret.filePath = filepath

        if reachedVia is not None:
            ret.location.append(reachedVia)

        return ret

    def add_error(
        self,
        err: Any,
        child: Optional[Union[str, int]] = None,
        path: Optional[str] = None,
    ):
        """Add an error object at current location.

        Will extend current location with `child`, if given,
        will use passed `path`, if given.
        """
        loc = self.location if child is None else self.location + [child]
        fp = path or self.filePath
        self.errors[tuple(loc)] = DSValidationError(path=fp, err=err)

    def add_errors(self, *err_dicts):
        """Merge all passed error dicts into the errors of this context."""
        for err_dict in err_dicts:
            self.errors.update(err_dict)


class DSValidator:
    """Validator class that performs dirschema validation for a given dirschema."""

    def __init__(
        self,
        schema: Union[bool, Rule, DSRule, str, Path],
        meta_conv: Optional[MetaConvention] = None,
        local_basedir: Optional[Path] = None,
        relative_prefix: str = "",
    ) -> None:
        """Construct validator instance from given schema or schema location.

        Accepts DSRule, raw bool or Rule, or a str/Path that is interpreted as location.
        """
        self.meta_conv = meta_conv or MetaConvention()
        self.local_basedir = local_basedir
        self.relative_prefix = relative_prefix

        # if the passed relative prefix is a custom plugin, we cannot use this
        # for $ref resolving, so we will ignore it in the Json/Yaml loader
        is_plugin_prefix = relative_prefix.find("v#") < relative_prefix.find("://") == 0

        # take care of the passed schema based on its type
        if isinstance(schema, bool) or isinstance(schema, Rule):
            self.schema = DSRule(__root__=schema)
        elif isinstance(schema, DSRule):
            self.schema = schema
        elif isinstance(schema, str) or isinstance(schema, Path):
            uri = to_uri(str(schema), self.local_basedir, self.relative_prefix)
            dat = load_json(
                uri,
                local_basedir=self.local_basedir,
                relative_prefix=self.relative_prefix if not is_plugin_prefix else "",
            )
            # use deepcopy to get rid of jsonref (see jsonref issue #9)
            # otherwise we will get problems with pydantic serialization later
            self.schema = DSRule.parse_obj(copy.deepcopy(dat))
        else:
            raise ValueError(f"Do not know how to process provided schema: {schema}")

        logger.debug(
            "Initialized dirschema validator\n"
            f"schema: {self.schema}\n"
            f"meta_conv: {self.meta_conv}\n"
            f"local_basedir: {self.local_basedir}\n"
        )

    @classmethod
    def errors_to_json(cls, errs: DSValidationResult) -> Dict[str, Any]:
        """Convert the validation result to a JSON-compatible dict.

        Resulting structure is (file path -> schema location -> error message or dict).
        """
        return {
            file_path: {
                loc_to_jsonpointer(err_loc): json_dict(err_obj, exclude_defaults=True)
                for err_loc, err_obj in file_errors.items()
            }
            for file_path, file_errors in errs.items()
        }

    @classmethod
    def format_errors(cls, errs: DSValidationResult, stream=None) -> Optional[str]:
        """Report errors as YAML output.

        If a stream is provided, prints it out. Otherwise, returns it as string.
        """
        of = stream or io.StringIO()
        yaml.dump(cls.errors_to_json(errs), of)
        if not stream:
            return of.getvalue()
        return None

    def validate(
        self, root_path: Union[Path, IDirectory], **kwargs
    ) -> DSValidationResult:
        """Validate a directory, return all validation errors (unsatisfied rules).

        If `root_path` is an instance of `IDirectory`, it will be used directly.

        If `root_path` is a `Path`, this function will try to pick the correct
        interface for interpreting "files" and "directories", depending on
        whether the provided file is a directory or a supported kind of archive
        file with internal structure.

        Depending on the used metadata convention, the companion metadata files
        matching the convention will be filtered out from the set of validated
        paths.

        Returns
            Error dict that is empty in case of success, or otherwise contains
            for each path with validation errors another dict with the errors.
        """
        logger.debug(f"validate '{root_path}' ...")
        if isinstance(root_path, Path):
            root_path = get_adapter_for(root_path)
        paths = [p for p in root_path.get_paths() if not self.meta_conv.is_meta(p)]
        errors: Dict[str, Any] = {}
        # run validation for each filepath, collect errors separately
        for p in paths:
            ctx = DSEvalCtx.fresh(
                self.schema,
                dirAdapter=root_path,
                metaConvention=self.meta_conv,
                filePath=p,
                **kwargs,
            )
            logger.debug(f"validate_path '{p}' ...")
            success = self.validate_path(p, self.schema, ctx)
            logger.debug(f"validate_path '{p}' -> {success}")
            if not success:
                errors[p] = ctx.errors or {
                    (): DSValidationError(
                        path=p, err="Validation failed (no error log available)."
                    )
                }
        return errors

    def validate_path(self, path: str, rule: DSRule, curCtx: DSEvalCtx) -> bool:
        """Apply rule to path of file/directory under given evaluation context.

        Will collect errors in the context object.

        Note that not all errors might be reported, as the sub-rules are
        evaluated in different stages and each stage aborts evaluation on
        failure (i.e. match/rewrite, primitive rules, complex logic rules,
        `next` sub-rule)

        Returns True iff validation of this rule was successful.
        """
        logger.debug(f"validate_path '{path}', at rule location: {curCtx.location}")

        # special case: trivial bool rule
        if isinstance(rule.__root__, bool):
            logger.debug(curCtx.location, "trivial rule")
            if not rule.__root__:
                curCtx.failed = True
                curCtx.add_error("Reached unsatisfiable 'false' rule")
            return not curCtx.failed

        rl = rule.__root__  # unpack rule
        # assert isinstance(rl, Rule)

        # 1. match / rewrite
        # if rewrite is set, don't need to do separate match,just try rewriting
        # match/rewrite does not produce an error on its own, but can fail
        # because "match failure" is usually not "validation failure"
        psl = PathSlice.into(path, curCtx.matchStart, curCtx.matchStop)
        nextPath: str = path  # to be used for implication later on
        if rl.match or rl.rewrite:
            # important! using the match pattern from the context (could be inherited)
            rewritten = psl.rewrite(curCtx.matchPat, rl.rewrite)
            if rewritten is not None:
                nextPath = rewritten.unslice()
            else:  # failed match or rewrite
                op = "rewrite" if rl.rewrite else "match"
                pat = curCtx.matchPat or psl._def_pat
                matchPat = f"match '{pat.pattern}'"
                rwPat = f" and rewrite to '{str(rl.rewrite)}'" if rl.rewrite else ""

                if rl.description:  # add custom error without expanding groups
                    curCtx.add_error(rl.description, op)
                else:
                    curCtx.add_error(f"Failed to {matchPat}{rwPat}", op)
                curCtx.failed = True
                return False

        # 2. proceed with the other primitive constraints

        def add_error(*args):
            """If desc is set, add desc error once and else add passed error."""
            if rl.description is None:
                curCtx.add_error(*args)
            elif rl.description != "" and not curCtx.failed:
                # add error with expanded groups for better error messages
                curCtx.add_error(psl.match(curCtx.matchPat).expand(rl.description))
            curCtx.failed = True

        # take care of type constraint
        is_file = curCtx.dirAdapter.is_file(path)
        is_dir = curCtx.dirAdapter.is_dir(path)
        if rl.type is not None and not rl.type.is_satisfied(is_file, is_dir):
            msg = f"Entity does not have expected type: '{rl.type.value}'"
            if rl.type == TypeEnum.ANY:
                msg = "Entity must exist (type: true)"
            elif rl.type == TypeEnum.MISSING:
                msg = "Entity must not exist (type: false)"
            add_error(msg, "type", None)

        # take care of metadata JSON Schema validation constraint
        for key in ("valid", "validMeta"):
            if rl.__dict__[key] is None:  # attribute not set
                continue

            if not is_file and not is_dir:
                add_error(f"Path '{path}' does not exist", key, None)
                continue

            # use metadata convention for validMeta
            metapath = path
            if key == "validMeta":
                metapath = curCtx.metaConvention.meta_for(path, is_dir=is_dir)

            # load metadata file
            dat = curCtx.dirAdapter.open_file(metapath)
            if dat is None:
                add_error(f"File '{metapath}' could not be loaded", key, metapath)
                continue

            # prepare correct validation method (JSON Schema or custom plugin)
            schema_or_plugin = resolve_validator(
                rl.__dict__[key],
                local_basedir=self.local_basedir,
                relative_prefix=self.relative_prefix,
            )

            # check whether loaded metadata file should be parsed as JSON
            parse_json = (
                not isinstance(schema_or_plugin, ValidationHandler)
                or not schema_or_plugin._for_json
            )
            if parse_json:
                # not a handler plugin for raw data -> load as JSON
                dat = curCtx.dirAdapter.decode_json(dat, metapath)
                if dat is None:
                    add_error(f"File '{metapath}' could not be parsed", key, metapath)
                    continue

            valErrs = validate_metadata(dat, schema_or_plugin)
            if valErrs:
                add_error(valErrs, key, metapath)

        if curCtx.failed:
            return False  # stop validation if primitive checks failed

        # 3. check the complex constraints

        # if-then-else
        if rl.if_ is not None:
            ifCtx = curCtx.descend(rl.if_, path, "if")
            if self.validate_path(path, rl.if_, ifCtx):
                if rl.then is not None:
                    thenCtx = curCtx.descend(rl.then, path, "then")
                    if not self.validate_path(path, rl.then, thenCtx):
                        curCtx.failed = True
                        # add_error("'if' rule satisfied, but 'then' rule violated", "then")  # noqa: E501
                        if rl.details:
                            curCtx.add_errors(thenCtx.errors)
            else:
                if rl.else_ is not None:
                    elseCtx = curCtx.descend(rl.else_, path, "else")
                    if not self.validate_path(path, rl.else_, elseCtx):
                        curCtx.failed = True
                        # add_error("'if' rule violated and also 'else' rule violated", "else")  # noqa: E501

                        if rl.details:
                            curCtx.add_errors(elseCtx.errors)

        # logical operators
        for op in ("allOf", "anyOf", "oneOf"):
            val = rl.__dict__[op]
            opCtx = curCtx.descend(rule, None, op)

            num_rules = len(val)
            if num_rules == 0:
                continue  # empty list of rules -> nothing to do

            num_fails = 0
            suberrs: List[DSValidationErrors] = []
            for idx, r in enumerate(val):
                subCtx = opCtx.descend(r, None, idx)
                success = self.validate_path(path, r, subCtx)
                if success and op == "anyOf":
                    suberrs = []  # don't care about the errors on success
                    break  # we have a satisfied rule -> enough
                elif not success:
                    num_fails += 1
                    if subCtx.errors:
                        suberrs.append(subCtx.errors)

            num_sat = num_rules - num_fails
            err_msg = ""
            if op == "allOf" and num_fails > 0:
                err_msg = "All"
            elif op == "oneOf" and num_fails != num_rules - 1:
                err_msg = "Exactly 1"
            elif op == "anyOf" and num_fails == num_rules:
                err_msg = "At least 1"
            if err_msg:
                err_msg += f" of {num_rules} sub-rules must be satisfied "
                err_msg += f"(satisfied: {num_sat})"
                add_error(err_msg, op, None)
                if rl.details:
                    curCtx.add_errors(*suberrs)

        if rl.not_ is not None:
            notCtx = curCtx.descend(rl.not_, path, "not")
            if self.validate_path(path, rl.not_, notCtx):
                add_error(
                    "Negated sub-rule satisfied, but should have failed", "not", None
                )

        if curCtx.failed:
            return False  # stop validation here if logical expressions failed

        # 4. perform "next" rule, on possibly rewritten path
        if rl.next is not None:
            nextCtx = curCtx.descend(rl.next, nextPath, "next")
            if not self.validate_path(nextPath, rl.next, nextCtx):
                if rl.details:
                    curCtx.add_errors(nextCtx.errors)
                return False

        # assert curCtx.failed == False
        return True
