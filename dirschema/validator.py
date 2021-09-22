"""Validation API functionality for DirSchema."""

import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import (
    Dict,
    Iterable,
    Mapping,
    Optional,
    Sequence,
    Set,
    TypeVar,
    Union,
    cast,
)

import jsonschema
from ruamel.yaml import YAML

from .adapters import IDirectory, get_adapter_for
from .core import DirSchema, PatPair, Rewrite, Rule, TypeEnum
from .parse import load_json, to_uri

yaml = YAML(typ="safe")

T = TypeVar("T")


def first_match_key(pats: Mapping[T, re.Pattern], path: str) -> Optional[T]:
    """Return index or keys of first full match in traversal order of passed container."""
    for i, pat in pats.items():
        if pat.fullmatch(path):
            return i
    return None


def all_matches_keys(pats: Mapping[T, re.Pattern], paths: Iterable[str]) -> Iterable[T]:
    """Return keys of patterns fully matched by at least one path."""
    # do this a bit more intelligently, don't match already matched expressions
    # we also collect the remaining instead of done to not iterate them in inner loop
    unmatched_pats: Set[T] = set(pats.keys())
    for p in paths:
        matched = set()
        for k in unmatched_pats:
            if pats[k].fullmatch(p):
                matched.add(k)
        unmatched_pats -= matched
        if not unmatched_pats:
            break
    return set(pats.keys()) - unmatched_pats


def first_match(pats: Sequence[re.Pattern], path: str) -> Optional[int]:
    """Return index of first pattern fully matching the given path."""
    return first_match_key(dict(enumerate(pats)), path)


def all_matches(pats: Sequence[re.Pattern], path: str) -> Iterable[int]:
    """Return indices of all patterns fully matching the given path."""
    return all_matches_keys(dict(enumerate(pats)), [path])


class DirSchemaValidator:
    """Validator class that performs dirschema validation for a given dirschema."""

    def __init__(self, schema: Union[str, Path, DirSchema]) -> None:
        """Construct validator instance from given schema or schema location."""
        if isinstance(schema, DirSchema):
            self.schema_uri = None
            self.schema = schema
        elif isinstance(schema, str) or isinstance(schema, Path):
            self.schema_uri = to_uri(str(schema))
            # use deepcopy to get rid of jsonref (see jsonref issue #9)
            # otherwise we will get problems with pydantic serialization later
            self.schema = DirSchema.parse_obj(
                deepcopy(load_json(self.schema_uri, base_uri=self.schema_uri))
            )

    def validate_rule(
        self, dir: IDirectory, path: str, rule: Optional[Rule]
    ) -> Optional[Rule]:
        """Apply rule to path, return rule with only the unsatisfied constraints."""
        # print("validate_rule", rule, f"for '{path}'")
        if rule is None:
            return None

        errors = rule.copy()  # shallow copy

        # take care of type constraint
        is_file = dir.is_file(path)
        is_dir = dir.is_dir(path)
        if rule.type == TypeEnum.MISSING and not is_file and not is_dir:
            errors.type = None
        elif rule.type == TypeEnum.ANY and (is_file or is_dir):
            errors.type = None
        elif rule.type == TypeEnum.DIR and is_dir:
            errors.type = None
        elif rule.type == TypeEnum.FILE and is_file:
            errors.type = None

        # take care of metadata JSON Schema validation constraint
        for key in ("valid", "validMeta"):
            val = rule.__dict__[key]
            if val is not None:
                schema = val.__root__

                metapath = path
                if key == "validMeta":
                    metapath = self.schema.metaConvention.meta_for(path)

                dat = dir.load_json(metapath)
                validationError = False
                if dat is not None:
                    try:
                        jsonschema.validate(dat, schema)
                        errors.__dict__[key] = None  # success -> remove from rule
                    except jsonschema.ValidationError:
                        validationError = True
                if key == "validMeta" and (not dat or validationError):
                    # in case of validation error, enrich with the file path
                    errors.metaPath = metapath

        for op in ("allOf", "anyOf", "oneOf"):
            val = rule.__dict__[op]
            num_rules = len(val)

            if num_rules == 0:
                continue

            suberr = [self.validate_rule(dir, path, r) for r in val]
            num_fails = 0
            for e in suberr:
                if e is not None:
                    num_fails += 1

            if op == "allOf" and num_fails == 0:
                errors.__dict__[op] = []
            elif op == "anyOf" and num_fails < num_rules:
                errors.__dict__[op] = []
            elif op == "oneOf" and num_fails == num_rules - 1:
                errors.__dict__[op] = []
            else:
                errors.__dict__[op] = suberr  # keep results -> indicate failure of op

        # take care of rewrite rules
        errors.rewrites = []
        for rr in rule.rewrites:
            rpath = cast(Rewrite, rr.rewrite)(path)
            if not rpath:
                raise ValueError(
                    f"No match for {path} in rewrite pattern {rr.rewrite}!"
                )

            rrerr = rr.copy()  # rewrite rule error
            rrerr.rewrite = rpath
            rerr = self.validate_rule(dir, rpath, rr.rule)
            if rerr:  # if there were errors, store this rewriterule with them
                rrerr.rule = rerr
                errors.rewrites.append(rrerr)

        # print("return validate_rule", path, ":", errors)
        if errors:
            return errors
        return None

    def validate_path(self, dir: IDirectory, path: str) -> Optional[PatPair]:
        """
        Find the first matching rule for a path and validate it.

        If there are no errors, returns None. Otherwise, returns matched pair
        with the partial rule containing fields that failed validation.
        """
        midx = first_match(list(map(lambda x: x.pat, self.schema.patterns)), path)
        match = self.schema.patterns[midx] if midx is not None else None
        if match is None:
            return None
        ret = match.copy()
        errors = self.validate_rule(dir, path, match.rule if match else None)
        if errors is None:
            return None
        ret.rule = errors
        return ret

    def validate(self, path: Path, **kwargs) -> Dict[str, PatPair]:
        """
        Validate a directory and return all validation errors (unsatisfied rules).

        In case of success the returned dict is empty.
        """
        dir: IDirectory = get_adapter_for(path)
        paths = [
            p for p in dir.get_paths() if not self.schema.metaConvention.is_meta(p)
        ]
        errors = {}
        for p in paths:
            res = self.validate_path(dir, p)
            if res:  # or ("all_results" in kwargs and kwargs["all_results"]):
                errors[p] = res
        return errors

    def format_errors(self, errors: Dict[str, PatPair], stream=sys.stdout):
        """Dump YAML of violated schema constraints as error."""
        errs = {k: json.loads(v.json(exclude_defaults=True)) for k, v in errors.items()}
        yaml.dump(errs, stream)
