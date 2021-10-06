"""Tests for dirschema validator."""

import copy
import json

from dirschema.core import DSRule, MetaConvention, Rule
from dirschema.parse import loads_json, to_uri
from dirschema.validator import DSValidator


def rule_from_yaml(yml: str, base_uri=None) -> DSRule:
    """Load from YAML string, expanding $refs."""
    base_uri = base_uri if not base_uri else to_uri(str(base_uri))
    return DSRule.parse_obj(copy.deepcopy(loads_json(yml, base_uri=base_uri)))


def test_construct(tmp_path):
    """Test loading a dirschema from object or file."""
    ds = DSRule()
    dsv = DSValidator(ds)
    assert dsv.schema == ds

    with open(tmp_path / "empty.dirschema.json", "w") as f:
        f.write(ds.json(by_alias=True))
    dsv2 = DSValidator(tmp_path / "empty.dirschema.json")
    assert dsv2.schema == ds


def test_validate_basic(tmp_path):
    """Test trivial rules, type and valid/validMeta rules."""
    dsv = DSValidator(rule_from_yaml("{}"))
    dsv.schema_uri = to_uri(str(tmp_path))
    assert not dsv.validate(tmp_path)  # trivial (empty rule)

    dsv.schema = rule_from_yaml('anyOf:\n- match: ""\n  then: {type: dir}')
    assert not dsv.validate(tmp_path)  # still trivial (root is always "dir")
    dsv.schema = rule_from_yaml('anyOf:\n- match: ""\n  then: {type: file}')
    assert dsv.validate(tmp_path)  # contradiction
    dsv.schema = rule_from_yaml('anyOf:\n- match: ""\n  then: {type: true}')
    assert not dsv.validate(tmp_path)  # trivial if it exists
    dsv.schema = rule_from_yaml('anyOf:\n- match: ""\n  then: {type: false}')
    assert dsv.validate(tmp_path)  # contradiction if it exists

    dsv.schema = rule_from_yaml('anyOf:\n- match: ""\n  then: {valid: true}')
    assert dsv.validate(tmp_path)  # not a file
    dsv.schema = rule_from_yaml('anyOf:\n- match: ""\n  then: {validMeta: true}')
    assert dsv.validate(tmp_path)  # not existing

    with open(tmp_path / "_mymeta.json", "w") as f:
        f.write("not JSON")
    dsv.schema = rule_from_yaml(
        'anyOf: [{match: ""}, {match: "_mymeta\\\\.json", then: {type: file}}]'
    )
    assert not dsv.validate(tmp_path)  # is a file
    dsv.schema = rule_from_yaml(
        'anyOf: [{match: ""}, {match: "_mymeta\\\\.json", then: {type: dir}}]'
    )
    assert dsv.validate(tmp_path)  # file is not dir

    dsv.metaConvention = MetaConvention(fileSuffix="_mymeta.json")
    assert not dsv.validate(tmp_path)  # file is not checked anymore
    dsv.metaConvention = MetaConvention()

    dsv.schema = rule_from_yaml(
        'anyOf: [{match: ""}, {match: "_mymeta\\\\.json", then: {type: true}}]'
    )
    assert not dsv.validate(tmp_path)  # trivial if it exists
    dsv.schema = rule_from_yaml(
        'anyOf: [{match: ""}, {match: "_mymeta\\\\.json", then: {type: false}}]'
    )
    assert dsv.validate(tmp_path)  # contradiction if it exists

    dsv.schema = rule_from_yaml(
        'anyOf: [{match: ""}, {match: "_mymeta\\\\.json", then: {valid: true}}]'
    )
    assert dsv.validate(tmp_path)  # not valid json file

    with open(tmp_path / "_mymeta.json", "w") as f:
        f.write("{}")
    assert not dsv.validate(tmp_path)  # now it is valid

    dsv.schema = rule_from_yaml(
        'anyOf: [{match: "", validMeta: true}, {match: "_mymeta\\\\.json"}]'
    )
    assert dsv.validate(tmp_path)  # wrong convention
    dsv.metaConvention = MetaConvention(fileSuffix="_mymeta.json")
    dsv.schema = rule_from_yaml('{match: "", validMeta: true}')
    assert not dsv.validate(tmp_path)  # ok with that convention
    dsv.metaConvention = MetaConvention()

    (tmp_path / "_mymeta.json").unlink()


def test_ref_resolving(tmp_path):
    """Test a non-trivial schema with nested references."""
    with open(tmp_path / "text.schema.json", "w") as f:
        textSchema = {
            "type": "object",
            "properties": {"author": {"type": "string"}},
            "required": ["author"],
        }
        json.dump(textSchema, f)

    with open(tmp_path / "partial.dirschema.json", "w") as f:
        partialSchema = {
            "match": "",
            "validMeta": {"$ref": str(tmp_path / "text.schema.json")},
        }
        json.dump(partialSchema, f)

    with open(tmp_path / "outer.dirschema.yaml", "w") as f:
        f.write(
            'anyOf: [{match: ".*\\\\.(dir)?schema\\\\.(json|yaml)"},{"$ref": "'
            + str(tmp_path / "partial.dirschema.json")
            + '"}]'
        )

    dsv = DSValidator(tmp_path / "outer.dirschema.yaml")
    assert dsv.validate(tmp_path)  # not existing root metadata
    (tmp_path / "_meta.json").touch()
    assert dsv.validate(tmp_path)  # not valid root metadata
    with open(tmp_path / "_meta.json", "w") as f:
        json.dump({"author": "Jane Doe"}, f)
    assert not dsv.validate(tmp_path)  # ok


def test_combinations(tmp_path):
    """Test allOf, anyOf and oneOf rules."""
    ds = Rule()
    dsv = DSValidator(ds)

    dsv.schema = rule_from_yaml('match: ""\nthen: {}')
    assert not dsv.validate(tmp_path)

    dsv.schema = rule_from_yaml("allOf: []")
    assert not dsv.validate(tmp_path)
    dsv.schema = rule_from_yaml("allOf: [{type: dir}]")
    assert not dsv.validate(tmp_path)
    dsv.schema = rule_from_yaml("allOf: [{},{type: file}]")
    assert dsv.validate(tmp_path)

    dsv.schema = rule_from_yaml("anyOf: []")
    assert not dsv.validate(tmp_path)
    dsv.schema = rule_from_yaml("anyOf: [{}, {type: file}]")
    assert not dsv.validate(tmp_path)
    dsv.schema = rule_from_yaml("anyOf: [{}, {type: dir}]")
    assert not dsv.validate(tmp_path)
    dsv.schema = rule_from_yaml("anyOf: [{type: false}, {type: file}]")
    assert dsv.validate(tmp_path)

    dsv.schema = rule_from_yaml("oneOf: []")
    assert not dsv.validate(tmp_path)
    dsv.schema = rule_from_yaml("oneOf: [{}, {type: file}]")
    assert not dsv.validate(tmp_path)
    dsv.schema = rule_from_yaml("oneOf: [{type: dir}, {type: file}]")
    assert not dsv.validate(tmp_path)
    dsv.schema = rule_from_yaml("oneOf: [{type: dir}, {}]")
    assert dsv.validate(tmp_path)

    dsv.schema = rule_from_yaml("not: {type: file}")
    assert not dsv.validate(tmp_path)
    dsv.schema = rule_from_yaml("not: {type: dir}")
    assert dsv.validate(tmp_path)


mutex_yaml = """matchStart: -1
anyOf:
- type: dir
- match: a_(.*)
  rewrite: b_\\1
  then:
    type: false
- match: b_(.*)
  rewrite: a_\\1
  then:
    type: false
- match: (.*)
  then:
    anyOf:
    - rewrite: a_\\1
      then:
        type: file
    - rewrite: b_\\1
      then:
        type: file
"""


def test_example_forall_mutex(tmp_path):
    """
    Non-trival test - mutual exclusion for dependent paths.

    For each file **/ITEM that does not start with a_ or b_,
    require that either a_ITEM or b_ITEM must exist, but not both.
    """
    ds = rule_from_yaml(mutex_yaml)
    dsv = DSValidator(ds)

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
