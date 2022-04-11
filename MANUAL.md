# DirSchema Manual

DirSchema was created to describe the structure of datasets as well as metadata
requirements, under the assumption that the metadata for files is stored in separate JSON
files that follow a reasonable and consistent naming convention throughout the dataset.

For this purpose, it lifts JSON Schema validation from the level of individual JSON files
to hierarchical directory-like structures, i.e. besides actual files and directories it is
easily possible to use a DirSchema for validating archive files, like a HDF5 or ZIP file.

## Adapter Interface

A DirSchema can be evaluated on any kind of tree-shaped hierarchical entity that
supports the following operations:

* return a list of paths to all "files" and "directories" (normalized as described below)
* test whether a path is a "directory" (inner node)
* test whether a path is a "file" (leaf)
* load a "file" (typically JSON) to perform JSON Schema or custom validation on it

In the following we will use the language of **directories** and **files** and will refer
to the whole tree structure as the **dataset**. Other directory/file-like structures can
be processed if a suitable adapter implementing the required interface is provided.

## Path Convention

DirSchema rules are evaluated on a set of paths and rely on pattern matching to determine
which rule(s) must be applied to which path. Therefore, it is important to understand how
files and directories are uniquely mapped to paths.

* The set of paths in a dataset always contains at least the empty path
    (representing the root directory)
* Furthermore, it contains all contained subdirectories and files
    (except for ones that are ignored, e.g., hidden files etc.)

In order to have a unique representation of paths that can be used in regex patterns,
all paths are normalized such that:

* each path is relative to the directory root (which is represented by the empty string)
* slashes are used to separate "segments" (i.e. directories, possibly ending with a file)
* each segment between two slashes is non-empty
* there is neither a leading nor a trailing slash (`/`)
* paths do not contain special "file names" like `.` (current dir) or `..` (parent dir)

## Metadata Convention

JSON metadata can be provided for each file and directory. By default, it is assumed that
for each file named `FILE` the metadata is located in a file named `FILE_meta.json`,
whereas for a directory `DIR` the metadata is in `DIR/_meta.json`.

The convention can be configured by overriding the path and file prefix and suffixes.
The general pattern is as follows:

For a path `a/b/c/d`, the metadata is located in:

* `<PATH_PREFIX/>a/b/c</PATH_SUFFIX>/<FILE_PREFIX>d<FILE_SUFFIX>` if `d` is a file
* `<PATH_PREFIX/>a/b/c/d</PATH_SUFFIX>/<FILE_PREFIX><FILE_SUFFIX>` if `d` is a directory

All these prefixes and suffixes are optional, except for the requirement that either a
file prefix or a file suffix must be provided.

**All files following the used metadata naming convention are automatically excluded from
the set of validated files**. These files are seen as merely "companion files" to other
files in the dataset. This simplifies the writing of DirSchemas, as otherwise these files
would have to be excluded in an ad-hoc manner, which would fix the convention inside a
DirSchema. Excluding them allows for changing the convention or using the DirSchema
with datasets following different conventions, without changing the DirSchema itself.

## DirSchema Evaluation

When validating a dataset, the DirSchema is evaluated for each path individually and
therefore rule violations are also reported for each path separately. For each path, the
validation returns a (part of) the unsatisfied constraints as response. Rule evaluation
proceeds recursively as follows.

1. If a `match` key is present, the path is matched against the expression.
2. Primitive constraints `type`, `valid` and `validMeta` are evaluated.
3. Logical constraints `not`, `allOf`, `anyOf` and `oneOf` are evaluated.
4. The `then` rule is evaluated on the path (possibly rewritten by `rewrite`), if present.

Whenever a step fails, the evaluation of the current rule is aborted.
In the following, all available constraints and other keys are explained in more detail.

## DirSchema Rules

A DirSchema rule is - similar to a JSON Schema - either a boolean (rule that is trivially
`true` or `false`), or a conjunction of at most one of each kind of possible primitive
and/or complex constraints. A constraint is primitive iff it does not contain any nested
constraint (i.e. primitive rules are leaves in the tree of nested rules).

DirSchema rules are assumed to be JSON or YAML files. In the following it is assumed that
JSON and YAML syntax is understood and only the key/value pairs for defining constraints
are presented.

### Matching and Rewriting

As explained above, the complete rule expression is evaluated on each path. To
apply different rules to different paths and express dependencies between related paths,
DirSchema provides regex matching and substitution for paths.

#### match

**Value:**
string (containing a regex pattern)

**Description:**
Require that the path must fully match the provided regex.

If the match fails, it is assumed that the current rule is not intended for the current
path and therefore further evaluation of this rule is aborted.

The behavior of `match` can be modified by setting `matchStart` and/or `matchStop` to
restrict the matching scope to certain path segments. Such an interval is called **path
slice**.

For example, given the path `a/b/c/d` with `matchStart: 1` and `matchStop: -1`, the match
(and possible rewrite) is performed only on the path slice `b/c`.

Capture groups defined by parenthesis in the regex can be used for the `rewrite` in the
current or any nested rule, unless overridden by a different `match`.

#### matchStart

**Value:**
integer (default: 0)

**Description:**
Defines the index of the first path segment to be included in the match.

Negative indices work the same as in Python.

For example, to match only in the file name, `matchStart` can be set to `-1`.

This setting is inherited into contained rules until overridden.

#### matchStop

**Value:**
integer (default: 0)

**Description:**
Defines the index of the first path segment after `matchStart` that is **not** to be
included in the match.

Negative indices work the same as in Python.

Contrary to Python, a value of 0 means "until the end", like leaving out the end index in
a Python slice.

This setting is inherited into contained rules until overridden.

#### rewrite

**Value:**
string (substitution, possibly containing capture references)

**Description:**

Rewrite (parts of) the current path.

**The rewritten path is used instead of the current path in the** `then` **rule,
all constraints on the same level as the rewrite are evaluated on the *original* path!**.
Therefore having a `rewrite` without a `then` rule has no effect.

Capture groups of the most recent `match` (i.e. on the same or level or in an ancestor
rule) can be used in the substitution. If there is no applicable `match`, a default match
for the pattern `(.*)` is assumed and therefore `\\1` references the whole matched path or
path slice (determined by the currently active `matchStart`/`matchStop`).

In principle, this can be used to roughly emulate the functionality of `validMeta`,
but as metadata requirements are one of the main use cases, validMeta
is preferable, as it is not hard-coding a metadata file naming convention.

But in a case where more than one metadata file is required for a single file, the
non-standard file could be validated by a combination of `rewrite` and `valid`, if
there is no other way to express the desired constraints.

### Primitive Rules

Beside `match`, the following primitive rules are provided:

#### type

**Value:**
boolean, "file" or "dir"

**Description:**
Require that the path:

* `true`: exists (either file or directory)
* `false`: does not exist
* `"file"`: is a file
* `"dir"`: is a directory

#### valid

**Value:**
JSON Schema

**Description:**
Require that the path is a JSON file (**YAML is not allowed**) that successfully validates
against the JSON Schema provided as the value.

Validation fails if the path does not exist, cannot be loaded by the adapter or is not
valid according to the validation handler.

#### validMeta

**Value:**
JSON Schema

**Description:**
Require that the metadata file of the current path (according to the used convention)
is a JSON file (**YAML is not allowed**) that successfully validates
against the JSON Schema provided as the value.

Validation fails if the path does not exist, the metadata file does not exist, the
metadata file cannot be loaded by the adapter or is not valid according to the validation
handler.

### Combinations of Rules

To build more complex rules, DirSchema provides the same logical connectives that can be
used with JSON Schema. Additionally, an implication keyword `then` is provided explicitly
and described further below.

Notice that contrary to typical logical semantics (and just as in JSON Schema),
`oneOf/anyOf` evaluate to **true** for empty arrays, because they are interpreted as "not
existing" instead of being treated as empty existentials.

For each path, the rules are checked in the listed order ("short circuiting"), which
matters for `anyOf` - once a rule in the array is satisfied, the following rules are not
evaluated. So prefer putting simpler/the most common case first.

#### not

**Value:**
DirSchema

**Description:**
Logical negation.

#### allOf

**Value:**
Array of DirSchema

**Description:**
Logical conjunction.

#### anyOf

**Value:**
Array of DirSchema

**Description:**
Logical disjunction.

#### oneOf

**Value:**
Array of DirSchema

**Description:**
Satisfied if **exactly** one rule in the array of DirSchemas is satisfied.

#### then

**Value:**
DirSchema

If all other constraints in the current rule are satisfied, require that the rule provided
in the value is also satisfied on the (possibly rewritten) path.

This mechanism exists first and foremost in order to be used in combination with
`rewrite`, as just combining multiple rules can be achieved using `allOf`.

Additionally, this can be used for sequential "short circuiting" of rule evaluation to
modify or refine the four evaluation phases outlined above.

## Modularity

In any place where a DirSchema or JSON Schema is expected, one can use `$ref` to reference
them, both in YAML as well as JSON format, located at a remote or local location. In case
of relative paths, these are resolved based on the directory containing the initial rule.
This can and should be used to reuse rules and schemas without duplicating them.

## Examples

Show non-trivial example for match slice/rewrite and scoping

Show example how then can be used for short circuiting

Show mutex example?
