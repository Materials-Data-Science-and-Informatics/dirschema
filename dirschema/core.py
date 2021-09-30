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

from pydantic import BaseModel, Field
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

        Slice semantics is mostly like Python, except that [x:x] is forbidden,
        unless [0:0], which means the full path.
        """
        if start and stop:
            if start == stop != 0 or start < 0 < stop:
                raise ValueError(f"Invalid slice: {start}:{stop}")
            if stop < start and (0 <= stop or start <= 0):
                raise ValueError(f"Invalid slice: {start}:{stop}")

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


class JSONObj(BaseModel):
    """Helper class wrapping an arbitrary JSON object to be acceptable for pydantic."""

    @classmethod
    def __get_validators__(cls):  # noqa: D105
        yield cls.validate

    @classmethod
    def validate(cls, v):  # noqa: D102
        return v


class JSONSchema(BaseModel):
    """A JSON Schema is just a boolean or some (further unvalidated) JSON object."""

    __root__: Union[bool, JSONObj]


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
    """
    A DirSchema is a JSON Schema like specification for directories and files.

    It lifts validation from the level of individual JSON files to hierarchical
    directory-like structures (which can also be an archive like a HDF5 or ZIP file). In
    the explanations we will use the language of directories and files, even though other
    directory/file-like structures can be processed, if a suitable adapter implementing
    the required interface is provided.

    Roughly, using a DirSchema one can ensure the (possibly dependent) existence/absence
    of files and directories as well as the existence of companion metadata files that are
    valid according to some JSON Schema.

    ## Paths in DirSchema

    DirSchema rules are evaluated against a set of paths.

    * The set of paths always contains at least the empty path (representing the root dir)
    * furthermore, it contains all subdirectories and files
      (except for ones that should be ignored, e.g., hidden files etc.)

    In order to have a unique representation of paths that can be used in regex patterns,
    all paths are normalized such that each path...
    * is relative to the directory root (which is represented by the empty string)
    * slashes separate the path "segments" (i.e. directories and possibly file leaves)
    * each segment between two slashes is non-empty
    * has neither leading nor trailing slashes (/)
    * does not contain special "file names" like . (current dir) or .. (parent dir)

    ## DirSchema Rules

    A DirSchema rule is, similar to a JSON Schema, either a boolean (trivial rule) or
    understood as the conjunction of a subset of at most one of each kind of possible
    atomic and complex constraints. A constraint is atomic iff it does not contain any
    nested constraint (i.e. allow rules that are leaves in the tree of nested rules)

    ### Primitive Rules

    The path...
    * is an entity of following type: file/directory/any (it exists)/missing (is absent)
    * validates against a given JSON Schema
      (returns false if the path is a directory or cannot be parsed as JSON)
    * has a metadata file (according to chosen convention) that
      validates against a given JSON Schema (works for both files and directories)
      (returns false if the metadata file does not exist)

    ### Combinations of Rules

    To build more complex rules, the operators

    * allOf (conjunction)
    * anyOf (disjunction), and
    * oneOf (exactly 1 of N)

    are provided with similar semantics as in JSON Schema.

    Notice that contrary to the typical semantics, empty lists for oneOf/anyOf
    evaluate to true, because they are interpreted as "not existing" instead of being
    treated as empty existentials. For each path, the rules are checked in listed order
    ("short circuiting").

    Negation is not supported directly (yet), because it is hard to provide good error
    messages. To express the negation of a property, it is required to push the negation
    through to the leaves, i.e. in a kind of negation normal form.

    Furthermore, the combinator `then` is provided and represents an implication.
    The implied rule is only evaluated and required to be successful, if the rule
    containing the implication is satisfied (except for the implied, nested rule).
    This mechanism exists first and foremost in order to be used in combination with the
    matching capabilities to allow conditional rule application based on pattern matching.

    ### Matching and Rewriting

    For each path in the provided directory the whole rule tree is interpreted, but
    clearly to be of any use, one needs to be able to apply different rules based on the
    shape of the paths (described by a regex). In order to enable such a pattern-based
    rule dispatch, a regex matching and rewriting mechanism for paths is provided.

    If the match expression is set, the path must match the expression in order for the
    rule to be satisfied. To focus the matching to parts of the path (like only the file
    name, or conversely, only the path of a file), one can define a slice (with
    Python-like semantics) to first cut out a sub-path to which the expression will be
    applied. The match must be a full match on the path slice. On success, the match
    determines the capture groups.

    To state relationships between paths, the rewrite keyword allows to apply a regex
    substitution to matched paths and validate the resulting new paths.
    In the substitution, the capture groups of the closest match rule can be used.
    If no match has been performed, the capture is the full current path or slice.

    If the rewrite clause is present, it changes the semantics of the implication
    constraint so that instead of the original path the nested rule is applied to
    the rewritten rule.

    Notice that this can be used to emulate the functionality of the validMeta rule
    in combination with the MetaConvention, but as metadata requirements are one of the
    main features of DirSchema, validMeta obviously is the preferable syntactic sugar to
    be used in this case (instead of doing the rewriting on ad-hoc basis).

    ## Evaluation

    A DirSchema is evaluated on a path, with a specified metadata file convention.
    The evaluation proceeds like a DFS traversal and reduction of the rule graph.
    Rules that are satisfied are removed, while unsatisfied rules remain, possibly
    enriched by extra information. The traversal keeps track of the evaluation context,
    which consists of the latest slice indices and last match result.

    Given a path, first the match is evaluated, if any stated.
    Next the primitive constraints that are set in the rule are evaluated.
    Then the logical combinators (anyOf, allOf, etc.) are evaluated.
    If all of these succeed, the rewrite (if any, otherwise "identity rewrite") is
    performed and the implication rule is evaluated on the (possibly rewritten) path, if
    provided. If no implication is provided or the current rule is not satisfied,
    the implication is considered as trivially satisfied.

    A directory is checked by checking the DirSchema on every single path (except for
    deliberately omitted ones, and implicitly ignored paths based on the meta convention)
    and validation succeeds iff it succeeds on every path.

    ## Modularity

    In DirSchemas one can use `$ref` to reference both other DirSchemas as well as
    required JSON Schemas, both in YAML as well as JSON files, located at a remote or
    local location (in case of relative paths, these are resolved based on the directory
    containing the initial rule). This can be used to reuse rules and schemas without
    duplicating them.
    """

    # primitive:
    type: Optional[TypeEnum] = Field(
        description="Check that path is a file / is a dir."
    )

    valid: Optional[JSONSchema] = Field(description="Validate against provided schema.")

    # only set for output in case of errors! NOT for the user
    _metaPath: Optional[str]  # = Field(alias="metaPath")

    # this will use the provided metadataConvention for rewriting to the right path
    validMeta: Optional[JSONSchema] = Field(
        description="Validate external metadata against provided schema."
    )

    # these are JSON-Schema-like logical operators:

    allOf: List[DSRule] = Field([], description="Conjunction of rules (eval in order).")

    anyOf: List[DSRule] = Field([], description="Disjunction of rules (eval in order).")

    oneOf: List[DSRule] = Field(
        [], description="Exact-1-of-N for rules (eval in order)."
    )

    # if rewrite is set, apply then to rewritten path instead of original
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
    # matchSegStart < matchSegEnd (unless matchSegEnd negative and start positive)
    # matchStart = -1 = match only in final segment
    # it's python slice without step option
    # this means, missing segments are ignored
    # to have "exact" number of segments, match on a pattern with required # of / first
    matchStart: Optional[int]
    matchStop: Optional[int]

    # only do rewrite if match was successful
    rewrite: Optional[str]
    # only set for output in case of errors! NOT for the user
    _rewritePath: Optional[str]  # = Field(alias="rewritePath")

    # ----

    def __bool__(self) -> bool:
        """
        Return True if any field is truthy, i.e. non-empty and not None/False/0/"".

        During validation, successful fields are removed, i.e. remaining fields indicate
        validation errors. Hence, this can be used to check presence of any errors.
        """
        return any(self.__dict__[v] for v in vars(self))

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
        Override default dict creation to include certain private fields.

        These are used for extra annotations in error reporting,
        but keeping them private makes them forbidden for setting by the user.
        """
        d = super().dict(**kwargs)
        try:
            d["metaPath"] = self._metaPath
        except AttributeError:
            pass

        try:
            d["rewritePath"] = self._rewritePath
        except AttributeError:
            pass

        return d

    class Config:
        extra = "forbid"
        underscore_attrs_are_private = True


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
