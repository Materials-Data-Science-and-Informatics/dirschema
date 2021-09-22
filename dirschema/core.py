"""Core types of dirschema."""
from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import List, Optional, Pattern, Union

from pydantic import BaseModel, Field


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


class Rewrite(BaseModel):
    r"""
    Regex substitution pattern applied to a match in the path to obtain another path.

    The match begins at the start of the path (unless inName is
    set - in that case, the match begins at the start of the file name).

    The default values yield an identity transformation.
    The default pattern splits the path and the name into capture groups that
    can be used in the substitution and the default substitution concatenates them back.
    So when matching "prefix/path/file", we have \1="path/prefix/" and \2="file".

    This can be useful e.g. if you only need to add a prefix or suffix to the file name,
    in which case only the substitution string needs to be provided.

    Notice that this can be used to emulate the functionality of the validMeta rule
    in combination with the MetaConvention, but as metadata requirements are one of the
    main features of DirSchema, validMeta obviously is the preferable syntactic sugar to
    be used in this case.
    """

    inName: bool = Field(
        False,
        description="If true, match and substitute only in "
        "name part, keeping the path prefix unchanged. If false, uses full path.",
    )

    pat: Pattern = Field(
        re.compile("^(.*/)?([^/]*)$"),
        description="Pattern to be used for defining capture groups in the path.",
    )
    sub: str = "\\1\\2"

    # NOTE: of questionable use + would be inefficient... only add if really needed
    # isPat: bool = Field(
    #     False,
    #     description="Indicate that the resulting string is a regex pattern itself, "
    #     "not a literal path. NOTE: This is expensive, do not overuse it!",
    # )

    # def __hash__(self):
    #     return hash((type(self),) + tuple(self.__dict__.values()))

    def __call__(self, path: str) -> Optional[str]:
        """
        Perform the rewrite in the matching part of a path.

        Convenience wrapper to treat this object like a str -> str function.
        """
        pref = None
        x = path
        if self.inName:
            ps = path.split("/")
            if len(ps) >= 2:
                pref = "/".join(ps[:-1])
                x = ps[-1]

        match = self.pat.match(x)
        if not match:
            return None

        ret = self.pat.sub(self.sub, match[0])
        return ret if not pref else f"{pref}/{ret}"


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


class RewriteRule(BaseModel):
    """
    Pair of rewrite substitutions and rules to be applied to those paths.

    In contrast to the top-level patterns list, here **all** rewrite rules are
    evaluated, and also must match successfully.

    The reasoning is as follows:
    The outer pattern picks out a path of a certain shape using a full match, while a
    rewrite rule is supposed to transform this path to obtain a derivative path and
    apply some other validation to it. Having no match at all is almost certainly not
    intended and might lead to false positive validation due to mistakes in the regex,
    if the default would be to just ignore the rewrite rule for that path.

    The rewriting rule pattern does not need to match the full filepath or name, it is
    only required that a (possibly empty) match exists.

    To actually simulate "conditional" rewrite rules that are ignored when not matched,
    you need to reformulate your constraints to express the dependent path as an
    independent top-level-match.

    Considering an example of mutually exclusive extra files, it means e.g. instead of:
        `a -> [ b(a) v c(a), b(a) -> !c(a),  c(a) -> !b(a) ]`
        ("For all paths matching expression a, there exists either a
        derivative path b(a), or c(a), but not both")
    you must write:
        `a -> b(a) v c(a), b_a -> !c_a, c_a -> !b_a`
    where e.g. `b_a` is the equivalent of the inner rewrite rule `b(a)`, but independent
    of `a` and located as a top level, fully matching pattern in the schema.
    """

    rewrite: Union[Rewrite, str]
    rule: Rule

    class Config:
        extra = "forbid"


class JSONObj(BaseModel):
    """Helper class wrapping an arbitrary JSON object to be acceptable for pydantic."""

    @classmethod
    def __get_validators__(cls):  # noqa: D105
        yield cls.validate

    @classmethod
    def validate(cls, v):  # noqa: D102
        return v


class JSONSchema(BaseModel):
    """A JSON Schema is either a boolean or a JSON object."""

    __root__: Union[bool, JSONObj]


class Rule(BaseModel):
    """Rule specifying the validation to be applied for a path."""

    type: Optional[TypeEnum] = Field(
        description="Check that path is a file / is a dir."
    )

    # NOTE: parse the schemas as string here,
    # later in the validation step it will be parsed as JSON Schema or $ref to one
    valid: Optional[JSONSchema] = Field(description="Validate against provided schema.")

    metaPath: Optional[str]  # only set in case of errors! NOT for the user
    validMeta: Optional[JSONSchema] = Field(
        description="Validate external metadata against provided schema."
    )

    allOf: List[Rule] = []
    anyOf: List[Rule] = []
    oneOf: List[Rule] = []

    rewrites: List[RewriteRule] = Field([], alias="do")

    def __bool__(self) -> bool:
        """
        Return True if any field is truthy, i.e. non-empty and not None/False/0/"".

        During validation, successful fields are removed, i.e. remaining fields indicate
        validation errors. Hence, this can be used to check presence of any errors.
        """
        return any(self.__dict__[v] for v in vars(self))

    class Config:
        extra = "forbid"


Rule.update_forward_refs()
RewriteRule.update_forward_refs()


class PatPair(BaseModel):
    """Pair of a regex pattern and a rule to be evaluated in case of a match."""

    pat: Pattern = Field(
        description="Regex pattern that must match the whole filename "
        "(no leading/trailing slash)."
    )
    rule: Rule = Field(
        description="Rule to be validated, in case that a path matches the pattern."
    )

    class Config:
        extra = "forbid"


class DirSchema(BaseModel):
    """
    A dirschema is a sequence of pairs of regexes+rules that applied to a set of paths.

    The set of paths always contains at least the empty path representing the root
    directory of e.g. a dataset, and furthermore it contains all subdirectories and files,
    except for ones that should be ignored (e.g. hidden files etc.).

    All paths are normalized such that...
    * they are relative to the directory root (which is represented by the empty string)
    * have neither leading nor trailing slashes (/)
    * each segment between two slashes is not empty
    * they do not contain special "file names" like . (current dir) or .. (parent dir)

    For each path, the patterns are matched in listed order and for the first expression
    that completely matches the path the corresponding associated rule is evaluated.

    A single rule for a matched path can express the following properties: The path...
    * is a file/directory/exists/is absent
    * validates against a given JSON Schema
      (false if path is a directory or cannot be parsed as JSON)
    * has a metadata file (according to chosen convention) that
      validates against a given JSON Schema (works for both files and directories)
      (false if the metadata file does not exist)

    To state relationships between paths, the rewrite keyword allows to apply a regex
    substitution to matched paths and validate the resulting new paths against other
    rules.

    The semantics is similar to JSON Schema in that the validation is only done for
    successfully matched paths (somewhat similar to "patternProperties").
    If a path is not matched by any expression, then there are no constraints to satisfy
    for that path.

    To disallow "unknown" paths, add a catch-all pattern .* with the rule {type: false}.
    This is similar to stating "additionalProperties: false" in a JSON Schema.

    To make certain fixed paths mandatory (i.e. like "required" in JSON Schema), use the
    fact that the empty path (i.e. directory root) always exists and is validated, so that
    existence of other files of directories can be stated in the rule for "" as rewrite
    rules. This should be the first rule in your pattern list.

    To build more complex rules, operators allOf, anyOf and oneOf are provided with
    similar semantics as in JSON Schema (representing con-/disjunction and 1-of-n).

    Negation is not supported directly, because it is hard to provide good error messages.
    To express the negation of a property, it is required to push the negation through to
    the leaves, i.e. in a kind of negation normal form.

    Combinations of all these features allow to express e.g.:
    * the existence or absence of certain paths (possibly depending on other paths)
    * the mutual existence or exclusion of certain paths
    * what metadata is attached (in separate JSON files) to the files and directories
    """

    title: Optional[str]
    description: Optional[str]

    metaConvention: MetaConvention = MetaConvention()

    patterns: List[PatPair] = []

    class Config:
        extra = "forbid"
