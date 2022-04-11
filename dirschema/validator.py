"""Validation API functionality for DirSchema."""
from __future__ import annotations

import copy
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Union, cast

import jsonschema
from ruamel.yaml import YAML

from .adapters import IDirectory, get_adapter_for
from .core import DSRule, MetaConvention, PathSlice, Rule, TypeEnum, untruthy_str
from .parse import load_json, to_uri

yaml = YAML(typ="safe")

# custom validators with syntax v#ENTRYPOINT://args
# the plugin then is passed the current path to check and the args-string


@dataclass
class DSEvalCtx:
    """
    DirSchema evaluation context, used like a Reader Monad.

    Contains information that is required to evaluate a rule for a path.
    """

    dirAdapter: IDirectory
    metaConvention: MetaConvention = MetaConvention()

    matchStart: int = 0
    matchStop: int = 0
    matchPat: Optional[re.Pattern] = None

    # debug: bool = True

    def updated_context(self, rule: Rule) -> DSEvalCtx:
        """Return a new context updated with fields from the given rule."""
        ret = copy.copy(self)
        if rule.matchStart:
            ret.matchStart = rule.matchStart
        if rule.matchStop:
            ret.matchStart = rule.matchStop
        if rule.match:
            ret.matchPat = rule.match
        return ret


class DSValidator:
    """Validator class that performs dirschema validation for a given dirschema."""

    def __init__(
        self,
        schema: Union[bool, Rule, DSRule, str, Path],
        meta_conv: Optional[MetaConvention] = None,
        default_handler: Optional[str] = None,
        local_schema_basedir: Optional[Path] = None,
    ) -> None:
        """
        Construct validator instance from given schema or schema location.

        Accepts DSRule, naked bool or Rule, or a str/Path that is interpreted as location.
        """
        self.meta_conv = meta_conv or MetaConvention()
        self.default_handler = default_handler or "cwd://"
        self.local_schema_basedir = local_schema_basedir

        if isinstance(schema, bool) or isinstance(schema, Rule):
            self.schema = DSRule(__root__=schema)
        elif isinstance(schema, DSRule):
            self.schema = schema
        elif isinstance(schema, str) or isinstance(schema, Path):
            uri = to_uri(str(schema), self.local_schema_basedir)
            dat = load_json(uri, local_basedir=self.local_schema_basedir)
            # use deepcopy to get rid of jsonref (see jsonref issue #9)
            # otherwise we will get problems with pydantic serialization later
            self.schema = DSRule.parse_obj(copy.deepcopy(dat))
        else:
            raise ValueError(f"Do not know how to process provided schema: {schema}")

    def validate(self, path: Path, **kwargs) -> Dict[str, DSRule]:
        """
        Validate a directory and return all validation errors (unsatisfied rules).

        This function will pick the correct interface for interpreting "files" and
        "directories", depending on whether the provided file is a directory or a
        supported kind of archive file.
        Depending on the used metadata convention, the companion metadata files will be
        filtered out from the set of validated paths.

        In case of success the returned dict is empty.
        Otherwise the dict contains for each path with validation errors
        a residual rule that was not satisfied.
        """
        dir: IDirectory = get_adapter_for(path)
        paths = [p for p in dir.get_paths() if not self.meta_conv.is_meta(p)]
        ctx = DSEvalCtx(dirAdapter=dir, metaConvention=self.meta_conv, **kwargs)
        errors = {}
        for p in paths:
            res = self.validate_path(p, self.schema, ctx)
            if res:
                errors[p] = res
        return errors

    def format_errors(self, errs, stream=None) -> Optional[str]:
        """
        Report errors (i.e. unsatisfied rules) as YAML output.

        If a stream is provided, prints it out. Otherwise, returns string.
        """
        of = stream or io.StringIO()
        # this round-trip is ugly, but the simplest way to get nice YAML output.
        # need to use pydantic's .json() to eliminate non-standard types before YAMLizing
        tmp = {k: json.loads(v.json(exclude_defaults=True)) for k, v in errs.items()}
        yaml.dump(tmp, of)
        if not stream:
            return of.getvalue()
        return None

    def validate_path(
        self, path: str, rule: DSRule, ctx: DSEvalCtx
    ) -> Optional[DSRule]:
        """
        Apply rule to path under given evaluation context.

        Return None on success or a partial rule indicating violated constraints.
        """
        if isinstance(rule.__root__, bool):  # trivial rule
            return None if rule.__root__ else rule.copy()

        # if ctx.debug:
        #     print("validate_rule", f"for '{path}' rule:", repr(rule.__root__))

        rl: Rule = cast(Rule, rule.__root__)  # used to check constraints
        curCtx = ctx.updated_context(rl)  # derived from parent ctx + current settings
        err = Rule()  # type: ignore # used to collect errors

        # 1. match / rewrite
        # if rewrite is set, don't need do do separate match and just try rewriting
        psl = PathSlice.into(path, curCtx.matchStart, curCtx.matchStop)
        thenPath: str = path  # to be used for implication later on
        if rl.match or rl.rewrite:
            rewritten = psl.rewrite(curCtx.matchPat, rl.rewrite)
            if rewritten:
                thenPath = rewritten.unslice()
            else:  # failed match or rewrite
                err.match = curCtx.matchPat
                return DSRule(__root__=err)

        # 2. proceed with the other primitive constraints

        # take care of type constraint
        is_file = curCtx.dirAdapter.is_file(path)
        is_dir = curCtx.dirAdapter.is_dir(path)
        if rl.type == TypeEnum.MISSING and (is_file or is_dir):
            err.type = rl.type
        elif rl.type == TypeEnum.ANY and not (is_file or is_dir):
            err.type = rl.type
        elif rl.type == TypeEnum.DIR and not is_dir:
            err.type = rl.type
        elif rl.type == TypeEnum.FILE and not is_file:
            err.type = rl.type
        # print("path: ", path, "type: ", err.type)

        # take care of metadata JSON Schema validation constraint
        for key in ("valid", "validMeta"):
            if rl.__dict__[key] is None:  # attribute not set
                continue

            if not is_file and not is_dir:
                # original path does not exist -> cannot proceed
                err.__dict__["metaPath"] = untruthy_str(path)
                continue

            # use metadata convention for validMeta
            metapath = path
            if key == "validMeta":
                metapath = curCtx.metaConvention.meta_for(path, is_dir=is_dir)

            # try loading the metadata
            dat = ctx.dirAdapter.load_meta(metapath)
            if dat is None:
                # failed loading metadata file -> cannot proceed
                err.__dict__["metaPath"] = untruthy_str(metapath)
                continue

            # TODO: validation handler
            schema = rl.__dict__[key]
            try:
                jsonschema.validate(dat, schema.__root__)
            except jsonschema.ValidationError:
                err.__dict__[key] = schema

        if err:
            return DSRule(__root__=err)

        # 3. check the complex constraints
        for op in ("allOf", "anyOf", "oneOf"):
            val = rl.__dict__[op]
            num_rules = len(val)
            if num_rules == 0:
                continue  # empty list of rules -> nothing to do

            num_fails = 0
            suberrs = []
            for r in val:
                e = self.validate_path(path, r, curCtx)
                suberrs.append(e if e is not None else DSRule(True))
                if e is not None:
                    num_fails += 1
                elif op == "anyOf":
                    break  # we have a satisfied rule

            if op == "allOf" and num_fails > 0:
                err.__dict__[op] = suberrs
            elif op == "oneOf" and num_fails != num_rules - 1:
                err.__dict__[op] = suberrs
            elif op == "anyOf" and num_fails == num_rules:
                err.__dict__[op] = suberrs
            # print("num rules:", num_rules, "num fails: ", num_fails)

        if rl.not_:
            negErr = self.validate_path(thenPath, rl.not_, curCtx)
            if negErr is None:
                err.not_ = rl.not_

        if err:
            return DSRule(__root__=err)

        # 4. perform implication / "then" constraint
        # on failure, set the rewritten path into the error (if different to normal path)
        if rl.then:
            thenErr = self.validate_path(thenPath, rl.then, curCtx)
            if thenErr is not None:
                err = cast(Rule, thenErr.__root__)  # technically a lie, but morally ok
                if not isinstance(err, bool) and thenPath != path:
                    old = err.__dict__.get("rewritePath")
                    err.__dict__["rewritePath"] = old or untruthy_str(thenPath)

        if err:
            return DSRule(__root__=err)

        return None  # no errors
