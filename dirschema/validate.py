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
from .json.validate import JSONValidationErrors, validate_metadata
from .log import logger

yaml = YAML(typ="safe")
yaml.default_flow_style = False


def loc_to_jsonpointer(lst) -> str:
    """Convert a list of string keys and int indices to a JSON Pointer string."""
    return "/" + "/".join(map(str, lst))


def json_dict(model, **kwargs):
    """
    Given a Pydantic model, convert it to a raw JSON compatible dict.

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
    """
    DirSchema evaluation context, used like a Reader Monad.

    Contains information that is required to evaluate a rule for a path.
    """

    class Config:
        arbitrary_types_allowed = True

    dirAdapter: IDirectory
    """Adapter to access metadata files and get paths from."""

    metaConvention: MetaConvention = MetaConvention()
    """Convention to use for validMeta."""

    # ----

    errors: DSValidationErrors = {}

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
        # default_handler: Optional[str] = None,
    ) -> None:
        """
        Construct validator instance from given schema or schema location.

        Accepts DSRule, raw bool or Rule, or a str/Path that is interpreted as location.
        """
        self.meta_conv = meta_conv or MetaConvention()
        self.local_basedir = local_basedir
        # self.default_handler = default_handler

        # take care of the passed schema based on its type
        if isinstance(schema, bool) or isinstance(schema, Rule):
            self.schema = DSRule(__root__=schema)
        elif isinstance(schema, DSRule):
            self.schema = schema
        elif isinstance(schema, str) or isinstance(schema, Path):
            uri = to_uri(str(schema), self.local_basedir)
            dat = load_json(uri, local_basedir=self.local_basedir)
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

    def validate(
        self, root_path: Union[Path, IDirectory], **kwargs
    ) -> DSValidationResult:
        """
        Validate a directory and return all validation errors (unsatisfied rules).

        If `root_path` is an instance of `IDirectory`, it will be used directly.

        If `root_path` is a `Path`, this function will try to pick the correct interface
        for interpreting "files" and "directories", depending on whether the provided file
        is a directory or a supported kind of archive file with internal structure.

        Depending on the used metadata convention, the companion metadata files matching
        the convention will be filtered out from the set of validated paths.

        Returns:
            Error dict that is empty in case of success, or otherwise contains
            for each path with validation errors another dict with the errors.
        """
        logger.debug(f"Starting validation of {root_path}")
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
            logger.debug(f"Running validation for '{p}'")
            self.validate_path(p, self.schema, ctx)
            if ctx.errors:
                errors[p] = ctx.errors
        return errors

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
        """
        Report errors as YAML output.

        If a stream is provided, prints it out. Otherwise, returns it as string.
        """
        of = stream or io.StringIO()
        yaml.dump(cls.errors_to_json(errs), of)
        if not stream:
            return of.getvalue()
        return None

    def validate_path(self, path: str, rule: DSRule, curCtx: DSEvalCtx) -> bool:
        """
        Apply given rule to path of file or directory under given evaluation context.

        Will collect errors in the context object.

        Note that not all errors might be reported, as the sub-rules are evaluated in
        different stages and each stage aborts evaluation on failure (i.e. match/rewrite,
        primitive rules, complex rules, `then` sub-rule)

        Returns True iff no errors were added to the context.
        """
        rl = rule.__root__  # used to check constraints
        if isinstance(rl, bool):  # trivial rule
            if not rule.__root__:
                curCtx.add_error("Reached 'false' rule")
            return False

        # print("validate_rule", f"for '{path}' rule:\n", str(curCtx.location), repr(rl))
        # print("match/rewrite")

        # 1. match / rewrite
        # if rewrite is set, don't need do do separate match and just try rewriting
        # match alone does not raise errors
        psl = PathSlice.into(path, curCtx.matchStart, curCtx.matchStop)
        thenPath: str = path  # to be used for implication later on
        if rl.match or rl.rewrite:
            rewritten = psl.rewrite(curCtx.matchPat, rl.rewrite)
            if rewritten is not None:
                thenPath = rewritten.unslice()
            else:  # failed match or rewrite
                op = "rewrite" if rl.rewrite else "match"
                pat = curCtx.matchPat or psl._def_pat
                matchPat = f"match '{pat.pattern}'"
                rewritePat = (
                    f" and rewrite to '{str(rl.rewrite)}'" if rl.rewrite else ""
                )
                curCtx.add_error(f"Failed to {matchPat}{rewritePat}", op)
                return False

        # print("primitive")

        # 2. proceed with the other primitive constraints
        primitiveErrors = False

        # take care of type constraint
        is_file = curCtx.dirAdapter.is_file(path)
        is_dir = curCtx.dirAdapter.is_dir(path)
        if rl.type is not None and not rl.type.is_satisfied(is_file, is_dir):
            primitiveErrors = True
            msg = f"Entity does not have expected type: '{rl.type.value}'"
            if rl.type == TypeEnum.ANY:
                msg = "Entity must exist (type: true)"
            elif rl.type == TypeEnum.MISSING:
                msg = "Entity must not exist (type: false)"
            curCtx.add_error(msg, "type")

        # take care of metadata JSON Schema validation constraint
        for key in ("valid", "validMeta"):
            if rl.__dict__[key] is None:  # attribute not set
                continue

            if not is_file and not is_dir:
                # original path does not exist -> cannot proceed
                primitiveErrors = True
                curCtx.add_error(f"Path '{path}' does not exist", key)
                continue

            # use metadata convention for validMeta
            metapath = path
            if key == "validMeta":
                metapath = curCtx.metaConvention.meta_for(path, is_dir=is_dir)

            # try loading the metadata
            dat = curCtx.dirAdapter.load_meta(metapath)
            if dat is None:
                # failed loading metadata file -> cannot proceed
                primitiveErrors = True
                curCtx.add_error(
                    f"File '{metapath}' could not be loaded", key, metapath
                )
                continue

            # apply validation (JSON Schema or custom plugin)
            schema = rl.__dict__[key]
            valErrs = validate_metadata(dat, schema, self.local_basedir)
            if valErrs:
                primitiveErrors = True
                curCtx.add_error(valErrs, key, metapath)

        if primitiveErrors:
            return False  # stop validation if primitive checks failed

        # print("complex")

        # 3. check the complex constraints
        for op in ("allOf", "anyOf", "oneOf"):
            val = rl.__dict__[op]
            opCtx = curCtx.descend(rule, None, op)

            num_rules = len(val)
            if num_rules == 0:
                continue  # empty list of rules -> nothing to do

            suberrs: List[DSValidationErrors] = []
            for idx, r in enumerate(val):
                subCtx = opCtx.descend(r, None, idx)
                self.validate_path(path, r, subCtx)
                if not subCtx.errors and op == "anyOf":
                    suberrs = []  # don't care about the errors on success
                    break  # we have a satisfied rule -> enough
                elif subCtx.errors:
                    suberrs.append(subCtx.errors)

            num_fails = len(suberrs)
            if op == "allOf" and num_fails > 0:
                curCtx.add_error("All sub-rules must be satisfied", op)
                curCtx.add_errors(*suberrs)
                return False
            elif op == "oneOf" and num_fails != num_rules - 1:
                curCtx.add_error("Exactly one sub-rule must be satisfied", op)
                curCtx.add_errors(*suberrs)
                return False
            elif op == "anyOf" and num_fails == num_rules:
                curCtx.add_error("At least one sub-rule must be satisfied", op)
                curCtx.add_errors(*suberrs)
                return False

        if rl.not_ is not None:
            notCtx = curCtx.descend(rl.not_, path, "not")
            if self.validate_path(path, rl.not_, notCtx):
                curCtx.add_error("Sub-rule satisfied, but should have failed", "not")
                return False

        # 4. perform implication / "then" constraint, on possibly rewritten path
        if rl.then is not None:
            # print("then")
            thenCtx = curCtx.descend(rl.then, thenPath, "then")
            if not self.validate_path(thenPath, rl.then, thenCtx):
                curCtx.add_errors(thenCtx.errors)
                return False

        return True
