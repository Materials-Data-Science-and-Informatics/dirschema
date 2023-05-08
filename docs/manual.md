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
    (except for ones that are ignored due to metadata convention (see later)
    or adapter configuration (e.g. ignoring hidden files etc.)

In order to have a unique representation of paths that can be used in regex patterns,
all paths are normalized such that:

* each path is relative to the directory root (which is represented by the empty string)
* slashes are used to separate "segments"
    (i.e. a sequence of directories, possibly ending with a file)
* each segment between two slashes is non-empty
* there is neither a leading nor a trailing slash (`/`)
* paths do not contain special "file names" like `.` (current dir) or `..` (parent dir)

**Example:** `""`, `"a"`, `"a/b/c"` are all valid paths as provided by the normalization

## Metadata Convention

JSON metadata can be provided for each file and directory. By default, it is assumed that
for each file named `FILE` the metadata is located in a file named `FILE_meta.json`,
whereas for a directory `DIR` the metadata is in `DIR/_meta.json`.

The convention can be configured by overriding the prefixes and suffixes
that are attached to the path itself and to the filename.
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

**Example:**

With the default settings, the metadata file for `/a/b/c/d` is expected to be found at:

* `/a/b/c/d_meta.json` if `d` is a file
* `/a/b/c/d/_meta.json` if `d` is a directory

If we would also add a path suffix equal to `metadata`, we would get:

* `/a/b/c/metadata/d_meta.json` if `d` is a file
* `/a/b/c/d/metadata/_meta.json` if `d` is a directory

## Validation by JSON Schemas and custom plugins

In any context where JSON validation is to be performed and a schema can be provided,
it is possible to supply one of the following in the corresponding location of the schema:

* a JSON Schema (directly embedded)
* an URI pointing to a JSON Schema
* a special URI pointing to a custom validation plugin

For referencing JSON Schemas stored outside of the dirschema,
the following possibilities exist:

* a `http(s)://` URI
* a `file://` URI or an absolute path (equivalent)
* a `local://` URI (resolved relative to the directory of the used dirschema by default)
* a `cwd://` URI (resolved relative to the current working directory)
* a relative path (treated as a `cwd://` path by default)

To access a custom validation plugin, a pseudo-URI starting with `v#VALIDATOR://` is
recognized, where `VALIDATOR` is a registered plugin.

The `cwd://` URI is an explicit version that behaves like normal "relative paths", i.e.
when the validation tool is launched in `/a/b`,
a path `cwd://c/d` is expanded to `/a/b/c/d`.

By default, `local://` URIs are expanded relative to the location of the main dirschema
file. The reference directory for interpreting `local://` paths can also be overridden to
resolve to an arbitrary different path supplied to the validator during initialization.

**Example:**

Consider the following setup:

* the dirschema lives in `/my/dirschemas/example.dirschema.yaml`
* the dirschema validation is launched in directory `/my/workdir`
* A custom validator called `myvalidator` is registered as a plugin

Now let us see how the paths are resolved:

* A JSON Schema referenced as `https://www.example.org/schemas/some_schema.json`
    remains unchanged (the schema will be downloaded)
* A JSON Schema referenced as `file:///schemas/some_schema.json`
    remains unchanged
* A JSON Schema referenced as `cwd://schemas/some_schema.json`
    expands to `file:///my/workdir/schemas/some_schema.json`
* A JSON Schema referenced as `local://schemas/some_schema.json`
    will expand to `file:///my/dirschemas/schemas/some_schema.json` by default
    (or some other path, if the local base directory is overridden)
* A JSON Schema referenced as `/schemas/some_schema.json`
    expands to `file:///schemas/some_schema.json`
* A JSON Schema referenced as `schemas/some_schema.json`
    expands to `file:///my/workdir/schemas/some_schema.json` by default
    (if overridden, any prefix can be added to modify the interpretation of relative paths)
* A pseudo-URI `v#myvalidator://something` will call the validation plugin
  with the current file or directory path and the string `something` as argument
  (the argument can tell the plugin what kind of validation to perform or schema to use).

Thus, custom validation plugins can be used to serve two purposes:

* perform validation beyond what is possible with JSON Schema
* still use JSON Schema internally, but allow to use JSON Schemas
    that cannot be addressed using the built-in supported protocols

Except for custom validation plugins, all these URIs and pseudo-URIs can be used
also as values for `$ref` inside the dirschema or JSON Schemas. The custom plugin
Pseudo-URIs may only be used with the corresponding validation keywords of DirSchema.

Relative paths can be used for convenience throughout the schema and expanded to any
builtin JSON Schema access protocol or custom validator by setting the relative schema
base prefix when launching the validator. Notice that using a custom plugin prefix will
break `$ref` resolving of relative paths (you should not use `$ref` without access
protocol anyway). If you do it anyway and want relative paths to consistently be resolved
as expected in `$ref`s, you must prefix the relative sub-schema location with
`cwd://` or `local://` stating your intended semantics.

While all the provided ways to refer to external schemas can be useful for applying
dirschema in various contexts, consider mixing too many, especially multiple "relative"
modes of accessing a validator or JSON Schema as a bad practice. It can make your schemas
harder to understand and to reuse.

## DirSchema keywords

The keywords used in dirschema can be classified into some groups:

* **Primitive rules**: `type`, `valid`, `validMeta`

The primitive rules are those which perform the actual desired validation on a path.

* **Logical connectives**: `not`, `anyOf`, `allOf`, `oneOf`

The logical connectives work in the same way as in JSON Schema and are used to
build more complex rules from the primitive rules.

* **Syntactic sugar**: `if`, `then`, `else`

Technically, `if`/`then`/`else` is redundant, as its complete behaviour can be
replicated from logical connectives and suitable use of the `description` and `details`
settings.

Practically, it is added as syntactic sugar for the often needed case where a "meta-level"
implication such as "if precondition X is true, validate rule Y" is desired, but the user
should not be bothered with errors concerning violations of "X" because this is not a
real validation error.

To have more human-readable schemas and better error reporting, the guideline is to use
`if/then/else` for rule selection and "control flow", whereas the logical connectives are
to be used for actual complex validation rules.

* **Pattern matching**: `match`, `rewrite`, `next`

The pattern matching keywords are the mechanism for selecting which rules to apply to
which paths and constructing relations between paths.

* **Settings**: `matchStart`, `matchStop`, `description`, `details`

The setting keywords affect the behaviour of the evaluation, but have no "truth value".


## DirSchema Evaluation

When validating a dataset, the DirSchema is evaluated for each path individually and
therefore rule violations are also reported for each path separately. For each path, the
validation returns a (part of) the unsatisfied constraints as response. Rule evaluation
proceeds recursively as follows.

1. If a `match` key is present, the path is matched against the expression.
2. Primitive constraints `type`, `valid` and `validMeta` are evaluated.
3. Logical constraints `not`, `allOf`, `anyOf` and `oneOf` and `if/then/else` are evaluated.
4. The `next` rule is evaluated on the path (possibly rewritten by `rewrite`), if present.

Whenever one of these stages fails, the evaluation of the current rule is aborted.
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

Capture groups (defined by parentheses in the regex) can be used for the `rewrite` in the
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

**The rewritten path is used instead of the current path in the** `next` **rule,
all constraints on the same level as the rewrite are evaluated on the *original* path!**
Therefore having a `rewrite` without a `next` rule has no effect.

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
JSON Schema or string

**Description:**
Require that the path is loadable as JSON by the used adapter and is successfully
validated by the referenced JSON Schema or custom validator.

Validation fails if the path does not exist, cannot be loaded by the adapter or is not
valid according to the validation handler.

#### validMeta

**Value:**
JSON Schema or string

**Description:**
Require that the metadata file of the current path (according to the used convention)
is loadable as JSON by the used adapter and is successfully validated by
the referenced JSON Schema or custom validator.

Validation fails if the path does not exist, the metadata companion file does not exist,
the metadata file cannot be loaded by the adapter or is not valid according to the
validation handler.

### Combinations of Rules

To build more complex rules, DirSchema provides the same logical connectives that can be
used with JSON Schema. Additionally, an implication keyword `next` is provided explicitly
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

#### next

**Value:**
DirSchema

**Description:**
If all other constraints in the current rule are satisfied, require that the rule provided
in the value is also satisfied on the (possibly rewritten) path.

This mechanism exists first and foremost in order to be used in combination with
`rewrite`, as just combining multiple rules can be achieved using `allOf`.

Additionally, this can be used for sequential "short circuiting" of rule evaluation to
modify or refine the four evaluation phases outlined above.

### if-then-else

#### if

**Value:**
DirSchema

**Description:**
If specified, will be evaluated on current path.
Depending on result, either the `then` or the `else` rule will be evaluated.

#### then

**Value:**
DirSchema

**Description:** If given, must be satisfied in case that the `if` rule is satisfied.

#### else

**Value:**
DirSchema

**Description:** If given, must be satisfied in case that the `if` rule is violated.

### Error reporting

#### description

**Value:**
string

**Description:** If given, will override all other error messages from immediate
child keys of this rule. To completely silence errors from this rule, set to empty string.

If you want to have multiple custom error messages for keys in this rule (e.g. checking
both `type` and `validMeta` with separate error messages), move these keys into `allOf`,
and add individual `description` strings to the sub-rules inside `allOf`.

#### details

**Value:**
boolean (true by default)

**Description:**  If true, will preserve error messages reported from nested sub-rules
e.g. from logical connectives etc. If false, will discard them. This can be used
in combination with `description` to provide higher-level errors for logically complex
rules where the default error report is not helpful.

## Modularity

In any place where a DirSchema or JSON Schema is expected, one can also use `$ref` to
reference them, both in YAML as well as JSON format, located at a remote or local
location. This works for all supported protocols except for custom validation plugins
(i.e. custom validator pseudo-URIs are only permitted as values for `valid` and `validMeta`).

## Examples

**TODO:**

Show non-trivial example for match slice/rewrite and scoping

Show example how next can be used for short circuiting

Show mutex example?
