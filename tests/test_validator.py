"""Tests for dirschema validator."""

import json

from dirschema.core import DirSchema, PatPair, Rule
from dirschema.parse import loads_json, to_uri
from dirschema.validator import DirSchemaValidator


def test_construct(tmp_path):
    """Test loading a dirschema from object or file."""
    ds = DirSchema()
    dsv = DirSchemaValidator(ds)
    assert dsv.schema == ds

    with open(tmp_path / "empty.dirschema.json", "w") as f:
        f.write(ds.json())
    dsv2 = DirSchemaValidator(tmp_path / "empty.dirschema.json")
    assert dsv2.schema == ds


def test_validate_basic(tmp_path):
    """Test trivial rules, type and valid/validMeta rules."""
    ds = DirSchema()
    dsv = DirSchemaValidator(ds)
    dsv.schema_uri = to_uri(str(tmp_path))
    assert not dsv.validate(tmp_path)  # trivial (no rules)

    ds.patterns = [PatPair(pat="", rule=Rule())]
    assert not dsv.validate(tmp_path)  # trivial (empty rule)

    ds.patterns = [PatPair(pat="", rule=Rule(type="dir"))]
    assert not dsv.validate(tmp_path)  # still trivial (root is always "dir")
    dsv.schema.patterns[0].rule = Rule(type="file")
    assert dsv.validate(tmp_path)  # contradiction
    dsv.schema.patterns[0].rule = Rule(type=True)
    assert not dsv.validate(tmp_path)  # trivial if it exists
    dsv.schema.patterns[0].rule = Rule(type=False)
    assert dsv.validate(tmp_path)  # contradiction if it exists

    dsv.schema.patterns[0].rule = Rule(valid="true")
    assert dsv.validate(tmp_path)  # not a file
    dsv.schema.patterns[0].rule = Rule(validMeta="true")
    assert dsv.validate(tmp_path)  # not existing

    with open(tmp_path / "_meta.json", "w") as f:
        f.write("not JSON")
    dsv.schema.patterns[0] = PatPair(pat="_meta\\.json", rule=Rule(type="file"))
    assert not dsv.validate(tmp_path)  # is a file
    dsv.schema.patterns[0].rule = Rule(type="dir")
    assert dsv.validate(tmp_path)  # file is not a dir
    dsv.schema.patterns[0].rule = Rule(type=True)
    assert not dsv.validate(tmp_path)  # trivial if it exists
    dsv.schema.patterns[0].rule = Rule(type=False)
    assert dsv.validate(tmp_path)  # contradiction if it exists

    dsv.schema.patterns[0].rule = Rule(valid="true")
    assert dsv.validate(tmp_path)  # not valid json file
    dsv.schema.patterns[0] = PatPair(pat="", rule=Rule(validMeta="true"))
    assert dsv.validate(tmp_path)  # not valid json file

    with open(tmp_path / "_meta.json", "w") as f:
        f.write("{}")
    dsv.schema.patterns[0] = PatPair(pat="_meta\\.json", rule=Rule(valid="true"))
    assert not dsv.validate(tmp_path)  # ok
    dsv.schema.patterns[0] = PatPair(pat="", rule=Rule(validMeta="true"))
    assert not dsv.validate(tmp_path)  # ok

    with open(tmp_path / "text.schema.json", "w") as f:
        json.dump(
            {
                "type": "object",
                "properties": {"author": {"type": "string"}},
                "required": ["author"],
            },
            f,
        )

    textSchema = json.dumps({"$ref": str(tmp_path / "text.schema.json")})

    dsv.schema.patterns[0] = PatPair(pat="_meta\\.json", rule=Rule(valid=textSchema))
    assert dsv.validate(tmp_path)  # not valid according to schema
    dsv.schema.patterns[0] = PatPair(pat="", rule=Rule(validMeta=textSchema))
    assert dsv.validate(tmp_path)  # same here

    with open(tmp_path / "_meta.json", "w") as f:
        json.dump({"author": "Jane Doe"}, f)
    dsv.schema.patterns[0] = PatPair(pat="_meta\\.json", rule=Rule(valid="true"))
    assert not dsv.validate(tmp_path)  # valid
    dsv.schema.patterns[0] = PatPair(pat="", rule=Rule(validMeta="true"))
    assert not dsv.validate(tmp_path)  # valid


def test_combinations(tmp_path):
    """Test allOf, anyOf and oneOf rules."""
    ds = DirSchema()
    dsv = DirSchemaValidator(ds)

    ds.patterns = [PatPair(pat="", rule=Rule())]
    assert not dsv.validate(tmp_path)

    ds.patterns = [PatPair(pat="", rule=Rule(allOf=[]))]
    assert not dsv.validate(tmp_path)
    ds.patterns = [PatPair(pat="", rule=Rule(allOf=[Rule(), Rule(type="dir")]))]
    assert not dsv.validate(tmp_path)
    ds.patterns = [PatPair(pat="", rule=Rule(allOf=[Rule(), Rule(type="file")]))]
    assert dsv.validate(tmp_path)

    ds.patterns = [PatPair(pat="", rule=Rule(anyOf=[]))]
    assert not dsv.validate(tmp_path)
    ds.patterns = [PatPair(pat="", rule=Rule(anyOf=[Rule(), Rule(type="file")]))]
    assert not dsv.validate(tmp_path)
    ds.patterns = [PatPair(pat="", rule=Rule(anyOf=[Rule(), Rule(type="dir")]))]
    assert not dsv.validate(tmp_path)
    ds.patterns = [
        PatPair(pat="", rule=Rule(anyOf=[Rule(type=False), Rule(type="file")]))
    ]
    assert dsv.validate(tmp_path)

    ds.patterns = [PatPair(pat="", rule=Rule(oneOf=[]))]
    assert not dsv.validate(tmp_path)
    ds.patterns = [PatPair(pat="", rule=Rule(oneOf=[Rule(), Rule(type="file")]))]
    assert not dsv.validate(tmp_path)
    ds.patterns = [
        PatPair(pat="", rule=Rule(oneOf=[Rule(type="file"), Rule(type="dir")]))
    ]
    assert not dsv.validate(tmp_path)
    ds.patterns = [PatPair(pat="", rule=Rule(oneOf=[Rule(), Rule(type="dir")]))]
    assert dsv.validate(tmp_path)


mutex_yaml = """patterns:
- pat: (.*/)?a_[^/]*
  rule:
    anyOf:
    - {type: dir}
    - do:
      - rewrite: {inName: true, pat: a_(.*), sub: b_\\1}
        rule: {type: false}
- pat: (.*/)?b_[^/]*
  rule:
    anyOf:
    - {type: dir}
    - do:
      - rewrite: {inName: true, pat: b_(.*), sub: a_\\1}
        rule: {type: false}
- pat: (.*/)?[^/]+
  rule:
    anyOf:
    - {type: dir}
    - do:
      - rewrite: {inName: true, sub: a_\\2}
        rule: {type: file}
    - do:
      - rewrite: {inName: true, sub: b_\\2}
        rule: {type: file}
"""


def test_example_forall_mutex(tmp_path):
    """
    Non-trival test - mutual exclusion for dependent paths.

    For each file **/ITEM that does not start with a_ or b_,
    require that either a_ITEM or b_ITEM must exist, but not both.
    """
    ds = DirSchema.parse_obj(loads_json(mutex_yaml))
    dsv = DirSchemaValidator(ds)

    assert not dsv.validate(tmp_path)

    (tmp_path / "blub").mkdir()
    assert not dsv.validate(tmp_path)

    (tmp_path / "blub/foo").mkdir()
    assert not dsv.validate(tmp_path)

    (tmp_path / "blub/a_qux").mkdir()
    assert not dsv.validate(tmp_path)

    (tmp_path / "blub/bar").touch()
    assert dsv.validate(tmp_path)  # a_bar or b_bar file missing

    (tmp_path / "blub/a_bar").mkdir()
    assert dsv.validate(tmp_path)  # a_bar is not a file

    (tmp_path / "blub/a_bar").rmdir()
    (tmp_path / "blub/a_bar").touch()
    assert not dsv.validate(tmp_path)

    (tmp_path / "blub/b_bar").touch()
    assert dsv.validate(tmp_path)  # a_bar and b_bar BOTH exist

    (tmp_path / "blub/a_bar").unlink()
    assert not dsv.validate(tmp_path)
