"""Test both custom and normal JSON validation."""

import json
from typing import List

import pytest
from dirschema.json.handler_pydantic import PydanticHandler
from dirschema.json.validate import (
    validate_custom,
    validate_jsonschema,
    validate_metadata,
)
from pydantic import BaseModel, StrictBool, StrictInt, StrictStr


class SubModel(BaseModel):
    b: StrictInt
    c: StrictBool
    d: List[StrictStr]


class SomeModel(BaseModel):
    a: SubModel


test_schema = {
    "type": "object",
    "properties": {
        "a": {
            "type": "object",
            "properties": {
                "b": {"type": "number"},
                "c": {"type": "boolean"},
                "d": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["b", "c", "d"],
        }
    },
}

bad_instance = {"a": {"b": True, "c": "hello", "d": ["hello", None]}}
good_instance = {"a": {"b": 123, "c": True, "d": ["good"]}}


def test_validate_jsonschema():
    assert not validate_jsonschema(good_instance, test_schema)
    assert validate_jsonschema(bad_instance, test_schema) == {
        "/a/b": ["True is not of type 'number'"],
        "/a/c": ["'hello' is not of type 'boolean'"],
        "/a/d/1": ["None is not of type 'string'"],
    }


def test_validate_custom():
    # invalid validator pseudo-URIs
    with pytest.raises(ValueError) as e:
        validate_custom(bad_instance, "pydantic://some_model")
    assert str(e).lower().find("invalid custom") >= 0
    with pytest.raises(ValueError) as e:
        validate_custom(bad_instance, "v#://something")
    assert str(e).lower().find("invalid custom") >= 0
    with pytest.raises(ValueError) as e:
        validate_custom(bad_instance, "v#invalid://something")
    assert str(e).lower().find("not found") >= 0

    validator_str = "v#pydantic://some_model"

    # unknown model for built-in basic pydantic validator plugin
    with pytest.raises(ValueError) as e:
        validate_custom(bad_instance, validator_str)
    assert str(e).lower().find("model") >= 0

    PydanticHandler.MODELS["some_model"] = SomeModel  # a valid model

    class DummyClass:
        pass  # an invalid class registered as model

    PydanticHandler.MODELS["invalid"] = DummyClass  # type: ignore

    with pytest.raises(ValueError) as e:  # try invalid pydantic validator
        validate_custom(bad_instance, "v#pydantic://invalid")
    assert str(e).lower().find("invalid") >= 0

    assert not validate_custom(good_instance, validator_str)
    assert validate_custom(bad_instance, validator_str) == {
        "/a/b": ["value is not a valid integer"],
        "/a/c": ["value is not a valid boolean"],
        "/a/d/1": ["none is not an allowed value"],
    }

    PydanticHandler.MODELS = {}  # unregister models


def test_validate_metadata(tmp_path):
    # test automatic detection based on passed URI

    PydanticHandler.MODELS["some_model"] = SomeModel  # a valid model
    with open(tmp_path / "schema.json", "w") as f:
        json.dump(test_schema, f)

    assert not validate_metadata(good_instance, "v#pydantic://some_model")
    assert not validate_metadata(
        good_instance, "local://schema.json", local_basedir=tmp_path
    )

    PydanticHandler.MODELS = {}  # unregister models
