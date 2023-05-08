"""Core types of dirschema."""

from __future__ import annotations

import io
import json
import re
from enum import Enum
from pathlib import Path
from typing import List, Optional, Pattern, Tuple, Union

from jsonschema import Draft202012Validator
from pydantic import BaseModel, Extra, Field, root_validator
from ruamel.yaml import YAML
from typing_extensions import Final

yaml = YAML(typ="safe")


class MetaConvention(BaseModel):
    """Filename convention for metadata files that are associated with other entities.

    It defines where to look for metadata for files that are not themselves known
    as json, or metadata concerning directories.

    At the same time, these files are ignored by themselves and act as "sidecar" files.
    """

    pathPrefix: str = ""
    pathSuffix: str = ""
    filePrefix: str = ""
    fileSuffix: str = "_meta.json"

    @root_validator
    def check_valid(cls, values):
        """Check that at least one filename extension is non-empty."""
        file_pref_or_suf = values.get("filePrefix", "") or values.get("fileSuffix", "")
        if not file_pref_or_suf:
            raise ValueError("At least one of filePrefix or fileSuffix must be set!")
        return values

    def to_tuple(self) -> Tuple[str, str, str, str]:
        """Convert convention instance to tuple (e.g. used within CLI)."""
        return (self.pathPrefix, self.pathSuffix, self.filePrefix, self.fileSuffix)

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
    """Helper class to slice into path segments and do regex-based match/substitution.

    Invariant: into(path, sl).unslice() == path for all sl and path.
    """

    slicePre: Optional[str]
    sliceStr: str
    sliceSuf: Optional[str]

    @classmethod
    def into(
        cls, path: str, start: Optional[int] = None, stop: Optional[int] = None
    ) -> PathSlice:
        """Slice into a path, splitting on the slashes.

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

    def match(self, pat: Optional[Union[re.Pattern, str]] = None):
        """Do full regex match on current slice."""
        pat = pat or self._def_pat
        if isinstance(pat, str):
            pat = re.compile(pat)
        return pat.fullmatch(self.sliceStr)

    def rewrite(
        self, pat: Optional[Union[re.Pattern, str]] = None, sub: Optional[str] = None
    ) -> Optional[PathSlice]:
        """Match and rewrite in the slice string and return a new PathSlice.

        If no pattern given, default pattern is used.
        If no substitution is given, just match on pattern is performed.
        Returns new PathSlice with possibly rewritten slice.
        Returns None if match fails.
        Raises exception of rewriting fails due to e.g. invalid capture groups.
        """
        if m := self.match(pat):
            ret = self.copy()
            if sub is not None:
                ret.sliceStr = m.expand(sub)
            return ret
        return None


class JSONSchema(BaseModel):
    """Helper class wrapping an arbitrary JSON Schema to be acceptable for pydantic."""

    @classmethod
    def __get_validators__(cls):  # noqa: D105
        yield cls.validate

    @classmethod
    def validate(cls, v):  # noqa: D102
        Draft202012Validator.check_schema(v)  # throws SchemaError if schema is invalid
        return v


class TypeEnum(Enum):
    """Possible values for a path type inside a dirschema rule.

    MISSING means that the path must not exist (i.e. neither file or directory),
    whereas ANY means that any of these options is fine, as long as the path exists.
    """

    MISSING = False
    FILE = "file"
    DIR = "dir"
    ANY = True

    def is_satisfied(self, is_file: bool, is_dir: bool) -> bool:
        """Check whether the flags of a path satisfy this path type."""
        if self == TypeEnum.MISSING and (is_file or is_dir):
            return False
        if self == TypeEnum.ANY and not (is_file or is_dir):
            return False
        if self == TypeEnum.DIR and not is_dir:
            return False
        if self == TypeEnum.FILE and not is_file:
            return False
        return True


DEF_MATCH: Final[str] = "(.*)"
"""Default match regex to assume when none is set, but required by semantics."""

DEF_REWRITE: Final[str] = "\\1"
"""Default rewrite rule to assume when none is set, but required by semantics."""


class DSRule(BaseModel):
    """A DirSchema rule is either a trivial (boolean) rule, or a complex object.

    Use this class for parsing, if it is not known which of these it is.
    """

    __root__: Union[bool, Rule]

    def __init__(self, b: Optional[bool] = None, **kwargs):
        """Construct wrapped boolean or object, depending on arguments."""
        if b is not None:
            return super().__init__(__root__=b)
        elif "__root__" in kwargs:
            if len(kwargs) != 1:
                raise ValueError("No extra kwargs may be passed with __root__!")
            return super().__init__(**kwargs)
        else:
            return super().__init__(__root__=Rule(**kwargs))

    def __repr__(self) -> str:
        """Make wrapper transparent and just return repr of wrapped object."""
        if isinstance(self.__root__, bool):
            return "true" if self.__root__ else "false"
        else:
            return repr(self.__root__)

    def __bool__(self):
        """Just return value for wrapped object."""
        return bool(self.__root__)


class Rule(BaseModel):
    """A DirSchema is a conjunction of a subset of distinct constraints/keywords."""

    # primitive:
    type: Optional[TypeEnum] = Field(
        description="Check that path is a file / is a dir."
    )

    valid: Optional[Union[JSONSchema, str]] = Field(
        description="Validate file against provided schema or validator."
    )

    # this will use the provided metadataConvention for rewriting to the right path
    validMeta: Optional[Union[JSONSchema, str]] = Field(
        description="Validate external metadata against provided schema or validator."
    )

    # these are JSON-Schema-like logical operators:

    allOf: List[DSRule] = Field([], description="Conjunction (evaluated in order).")

    anyOf: List[DSRule] = Field([], description="Disjunction (evaluated in order).")

    oneOf: List[DSRule] = Field([], description="Exact-1-of-N (evaluated in order).")

    not_: Optional[DSRule] = Field(description="Negation of a rule.", alias="not")

    # introduced for better error reporting (will yield no error message on failure)
    # So this is more for dirschema "control-flow"
    if_: Optional[DSRule] = Field(
        description="Depending on result of rule, will proceed with 'then' or 'else'.",
        alias="if",
    )

    then: Optional[DSRule] = Field(
        description="Evaluated if 'if' rule exists and satisfied.",
    )

    else_: Optional[DSRule] = Field(
        description="Evaluated if 'if' rule exists and not satisfied.",
        alias="else",
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

    # if rewrite is set, apply 'next' to rewritten path instead of original
    # missing rewrite is like rewrite \1, missing match is like ".*"
    next: Optional[DSRule] = Field(
        description="If current rule is satisfied, evaluate the 'next' rule."
    )

    # improve error reporting by making it customizable
    # overrides all other errors on the level of this rule (but keeps subrule errors)
    # if set to "", will report no error message for this rule
    description: Optional[str] = Field(
        None,
        description="Custom error message to be shown to the user if this rule fails.",
    )
    # used to prune noisy error message accumulation to some high level summary
    details: bool = Field(
        True,
        description="If set, keep errors from sub-rules, otherwise ignore them.",
    )

    # ----

    def __repr__(self, stream=None) -> str:
        """Print out the rule as YAML (only the non-default values)."""
        res = json.loads(self.json(exclude_defaults=True))

        if not stream:
            stream = io.StringIO()
            yaml.dump(res, stream)
            return stream.getvalue().strip()

        yaml.dump(res, stream)
        return ""

    class Config:  # noqa: D106
        extra = Extra.forbid


Rule.update_forward_refs()
DSRule.update_forward_refs()
