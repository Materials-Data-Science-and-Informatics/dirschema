"""Core types of dirschema."""

from __future__ import annotations

import io
import json
import re
from enum import Enum
from pathlib import Path
from typing import (
    Iterable,
    List,
    Mapping,
    Optional,
    Pattern,
    Sequence,
    Set,
    TypeVar,
    Union,
)

from jsonschema import Draft202012Validator
from pydantic import BaseModel, Extra, Field
from ruamel.yaml import YAML
from typing_extensions import Final

yaml = YAML(typ="safe")


class MetaConvention(BaseModel):
    """
    Filename convention for metadata files that are associated with other entities.

    It defines where to look for metadata for files that are not themselves known as json,
    or metadata concerning directories.

    At the same time, these files are ignored by themselves and act as "sidecar" files.

    At least file prefix or suffix must be non-empty for correct behaviour.
    """

    pathPrefix: str = ""
    pathSuffix: str = ""
    filePrefix: str = ""
    fileSuffix: str = "_meta.json"

    @classmethod
    def from_tuple(cls, pp: str, ps: str, fp: str, fs: str):
        """Return new metadata file convention."""
        return MetaConvention(
            pathPrefix=pp, pathSuffix=ps, filePrefix=fp, fileSuffix=fs
        )

    def is_meta(self, path: str) -> bool:
        """Check whether given path is a metadata file according to the convention."""
        prts = Path(path).parts
        if len(prts) == 0:  # root dir
            return False
        if self.filePrefix != "" and not prts[-1].startswith(self.filePrefix):
            return False
        if self.fileSuffix != "" and not prts[-1].endswith(self.fileSuffix):
            return False
        pieces = int(self.pathPrefix != "") + int(self.pathSuffix != "")
        if len(prts) < 1 + pieces:
            return False
        pp = self.pathPrefix == "" or prts[0] == self.pathPrefix
        ps = self.pathSuffix == "" or prts[-2] == self.pathSuffix
        return pp and ps

    def meta_for(self, path: str, is_dir: bool = False) -> str:
        """Return metadata filename for provided path, based on this convention."""
        ps = list(Path(path).parts)
        newp = []

        if self.pathPrefix != "":
            newp.append(self.pathPrefix)
        newp += ps[:-1]
        if not is_dir and self.pathSuffix != "":
            newp.append(self.pathSuffix)
        name = ps[-1] if len(ps) > 0 else ""

        if is_dir:
            newp.append(name)
            if self.pathSuffix != "":
                newp.append(self.pathSuffix)
            metaname = self.filePrefix + self.fileSuffix
            newp.append(metaname)
        else:
            metaname = self.filePrefix + name + self.fileSuffix
            newp.append(metaname)
        return str(Path().joinpath(*newp))


class PathSlice(BaseModel):
    """
    Helper class to slice into segments of a path, match a regex and perform substitutions.

    Invariant: into(path, sl).unslice() == path for all sl and path.
    """

    slicePre: Optional[str]
    sliceStr: str
    sliceSuf: Optional[str]

    @classmethod
    def into(
        cls, path: str, start: Optional[int] = None, stop: Optional[int] = None
    ) -> PathSlice:
        """
        Slice into a path, splitting on the slashes.

        Slice semantics is mostly like Python, except that stop=0 means
        "until the end", so that [0:0] means the full path.
        """
        segs = path.split("/")
        pref = "/".join(segs[: start if start else 0])
        inner = "/".join(segs[start : stop if stop != 0 else None])  # noqa: E203
        suf = "/".join(segs[stop:] if stop else [])
        return PathSlice(
            slicePre=pref if pref else None,
            sliceStr=inner,
            sliceSuf=suf if suf else None,
        )

    def unslice(self) -> str:
        """Inverse of slice operation (recovers complete path string)."""
        return "/".join([x for x in [self.slicePre, self.sliceStr, self.sliceSuf] if x])

    _def_pat = re.compile("(.*)")
    """Default pattern (match anything, put into capture group)."""

    def rewrite(
        self, pat: Optional[Union[re.Pattern, str]] = None, sub: Optional[str] = None
    ) -> Optional[PathSlice]:
        """
        Match and rewrite in the slice string and return a new PathSlice.

        If no pattern given, default pattern is used.
        If no substitution is given, just match on pattern is performed.
        Returns new PathSlice with possibly rewritten slice.
        Returns None if match fails.
        Raises exception of rewriting fails due to e.g. invalid capture groups.
        """
        pat = pat or self._def_pat
        if isinstance(pat, str):
            pat = re.compile(pat)

        m = pat.fullmatch(self.sliceStr)
        if m:
            ret = self.copy()
            if sub is not None:
                ret.sliceStr = m.expand(sub)
            return ret
        return None


class JSONSchemaObj(BaseModel):
    """Helper class wrapping an arbitrary JSON Schema to be acceptable for pydantic."""

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        Draft202012Validator.check_schema(v)  # throws SchemaError if schema is invalid
        return v


class JSONSchema(BaseModel):
    """A JSON Schema is just a boolean or some (further unvalidated) JSON object.

    We need this indirection to have the correct truthiness in `Rule` for `valid[Meta]`.
    """

    __root__: JSONSchemaObj


class TypeEnum(Enum):
    """
    Possible values for a path type inside a dirschema rule.

    MISSING means that the path may not exist (i.e. neither file or directory),
    whereas ANY means that any of these options is fine, as long as the path exists.
    """

    MISSING = False
    FILE = "file"
    DIR = "dir"
    ANY = True


DEF_MATCH: Final[str] = "(.*)"
"""Default match regex to assume when none is set, but required by semantics."""

DEF_REWRITE: Final[str] = "\\1"
"""Default rewrite rule to assume when none is set, but required by semantics."""


class untruthy_str(str):
    """Override truthiness of strings to be True even for empty string."""

    def __bool__(self) -> bool:
        """Any string is true-ish."""
        return True


class DSRule(BaseModel):
    """
    A DirSchema rule is either a trivial (boolean) rule, or a complex object.

    Use this class for parsing, if it is not known which of these it is.
    """

    __root__: Union[bool, Rule]

    def __init__(self, b: Optional[bool] = None, **kwargs):
        """Construct wrapped boolean or object, depending on arguments."""
        if b is not None:
            return super().__init__(__root__=b)
        elif "__root__" in kwargs:
            return super().__init__(**kwargs)
        else:
            return super().__init__(__root__=Rule(**kwargs))

    def __repr__(self) -> str:
        """Make wrapper transparent and just return repr of wrapped object."""
        if isinstance(self.__root__, bool):
            return json.dumps(self.__root__)
        else:
            return repr(self.__root__)

    def __bool__(self):
        """Just return value for wrapped object."""
        return bool(self.__root__)


class Rule(BaseModel):
    """A DirSchema is a conjunction of at most one of each possible constraint/keyword."""

    # primitive:
    type: Optional[TypeEnum] = Field(
        description="Check that path is a file / is a dir."
    )

    valid: Optional[Union[JSONSchema, str]] = Field(
        description="Validate file against provided schema or validator."
    )

    # only set for output in case of errors! NOT for the user
    # _metaPath: Optional[untruthy_str] = None  # = Field(alias="metaPath")

    # this will use the provided metadataConvention for rewriting to the right path
    validMeta: Optional[Union[JSONSchema, str]] = Field(
        description="Validate external metadata against provided schema or validator."
    )

    # these are JSON-Schema-like logical operators:

    allOf: List[DSRule] = Field([], description="Conjunction (evaluated in order).")

    anyOf: List[DSRule] = Field([], description="Disjunction (evaluated in order).")

    oneOf: List[DSRule] = Field([], description="Exact-1-of-N (evaluated in order).")

    not_: Optional[DSRule] = Field(description="Negation of a rule.", alias="not")

    # if rewrite is set, apply 'then' to rewritten path instead of original
    # missing rewrite is like rewrite \1, missing match is like ".*"
    then: Optional[DSRule] = Field(
        description="If this rule is true, evaluate then rule."
    )

    # match and rewrite (path inspection and manipulation):

    # we keep the total match and the capture groups for possible rewriting
    # the match data + start/end is also inherited down into children
    match: Optional[Pattern] = Field(
        description="Path must match. Sets capture groups."
    )

    # indices of path segments (i.e. array parts after splitting on /)
    # matchStart < matchEnd (unless start pos. and end neg.)
    # matchStart = -1 = match only in final segment
    # it's python slice without 'step' option
    # this means, missing segments are ignored
    # to have "exact" number of segments, match on a pattern with required # of / first
    matchStart: Optional[int]
    matchStop: Optional[int]

    # only do rewrite if match was successful
    rewrite: Optional[str]

    # only set for output in case of errors! NOT for the user
    # _rewritePath: Optional[untruthy_str] = None  # = Field(alias="rewritePath")

    # ----

    def __bool__(self) -> bool:
        """
        Return True if any field is truthy, i.e. non-empty and not None/False/0/"".

        During validation, successful fields are removed, i.e. remaining fields indicate
        validation errors. Hence, this can be used to check presence of any errors.
        """
        return any(list(vars(self).values()))

    def __repr__(self, stream=None) -> str:
        """Print out the rule as YAML (only the non-default values)."""
        res = json.loads(self.json(exclude_defaults=True))

        if not stream:
            stream = io.StringIO()
            yaml.dump(res, stream)
            return stream.getvalue()

        yaml.dump(res, stream)
        return ""

    def dict(self, **kwargs):
        """
        Override default dict creation to rename fields or include private fields.

        These are used for extra annotations in error reporting,
        but keeping them private makes them forbidden for setting by the user.
        """
        d = super().dict(**kwargs)
        if self.not_:
            d["not"] = d.pop("not_")

        return d

    class Config:
        extra = Extra.forbid


Rule.update_forward_refs()
DSRule.update_forward_refs()


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
