"""Tests for JSON parsing functions."""

import json
import os
from pathlib import Path

import pytest
from dirschema.json.parse import load_json, loads_json, to_uri


def test_to_uri(tmp_path):
    cwd = Path(os.getcwd())

    for path in ["file:///hello/world", "http://www.example.com", "https://a/b/c"]:
        assert to_uri(path) == path  # return unchanged

    # absolute local path -> add prefix
    assert to_uri("/some/path") == "file:///some/path"

    # explicit CWD
    assert to_uri("cwd://some/path") == f"file://{cwd}/some/path"
    assert to_uri("cwd:///some/path") == f"file://{cwd}/some/path"

    # local without base_dir, with and without leading slash
    assert to_uri("local://some/path") == f"file://{cwd}/some/path"
    assert to_uri("local:///another/path") == f"file://{cwd}/another/path"
    # local with base_dir
    assert to_uri("local://a/b", tmp_path) == f"file://{tmp_path}/a/b"

    # relative with default resolving -> use CWD
    assert to_uri("some/path") == f"file://{cwd}/some/path"
    # relative with custom prefix -> resolve relative as "local"
    assert to_uri("a/b", tmp_path, "local://") == f"file://{tmp_path}/a/b"
    # relative with custom prefix -> resolve relative as absolute path
    assert to_uri("a/b", None, "/c/d/") == "file:///c/d/a/b"

    # test with invalid protocol
    with pytest.raises(ValueError):
        to_uri("invalid://uri")


def test_load_loads_json(tmp_path):
    # test extended JSON and YAML loader with relative, local and absolute path support

    # prepare some files
    abs_file = tmp_path / "absolute.yaml"
    rel_file = tmp_path / "relative.json"
    loc = tmp_path / "subdir"
    loc.mkdir()
    loc_file = loc / "local.yml"

    with open(abs_file, "w") as f:
        f.write("- valid\n- yaml\n")
    with open(rel_file, "w") as f:
        f.write('{"valid": "JSON"}')
    with open(loc_file, "w") as f:
        f.write("- another\n- yaml\n")

    obj = {
        "absolute": {"$ref": str(abs_file)},
        "file": {"$ref": to_uri(abs_file)},
        "relative": {"$ref": str(rel_file)},
        "local": {"$ref": "local://local.yml"},
    }
    with open(tmp_path / "schema.json", "w") as f:
        json.dump(obj, f)

    # load once from data and once from file. should succeed
    from_str = loads_json(json.dumps(obj), local_basedir=loc)
    from_file = load_json(tmp_path / "schema.json", local_basedir=loc)
    assert from_str == from_file
    assert from_str["absolute"] == ["valid", "yaml"]
