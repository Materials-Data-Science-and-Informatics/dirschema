"""Helper functions to perform validation of JSON-compatible metadata files."""

from pathlib import Path
from typing import Dict, List, Optional, Union

from jsonschema import Draft202012Validator

from .handler import ValidationHandler
from .handlers import loaded_handlers
from .parse import load_json, to_uri

JSONValidationErrors = Dict[str, List[str]]
"""JSON metadata validation errors mapping from JSON Pointers to lists of error messages."""


def validate_custom(dat, plugin_str: str) -> JSONValidationErrors:
    """Perform validation based on a validation handler string."""
    try:
        if not plugin_str.startswith("v#"):
            raise ValueError
        ep, args = plugin_str[2:].split("://")
        if ep == "":
            raise ValueError
    except ValueError:
        raise ValueError(f"Invalid custom validator string: '{plugin_str}'")

    try:
        h: ValidationHandler = loaded_handlers[ep]
        return h.validate(dat, args)
    except KeyError:
        raise ValueError(f"Validator entry-point not found: '{ep}'")


def validate_jsonschema(dat, schema) -> JSONValidationErrors:
    """Perform validation based on a JSON Schema."""
    v = Draft202012Validator(schema=schema)  # type: ignore
    errs: Dict[str, List[str]] = {}
    for verr in sorted(v.iter_errors(dat), key=lambda e: e.path):  # type: ignore
        key = "/" + "/".join(map(str, verr.path))  # JSON Pointer into document
        if key not in errs:
            errs[key] = []
        errs[key].append(verr.message)
    return errs


def validate_metadata(
    dat, schema: Union[str, Dict], local_basedir: Optional[Path]
) -> JSONValidationErrors:
    """Validate metadata object (loaded dict) using JSON Schema or custom validator.

    The validator must be either a JSON Schema dict, or a string
    pointing to a JSON Schema, or a custom validator handler string.

    Returns a dict mapping from JSON Pointers to a list of errors in that location.
    If the dict is empty, no validation errors were detected.
    """
    is_jsonschema = True
    if isinstance(schema, str):
        if schema.startswith("v#"):
            is_jsonschema = False  # custom validation, not json schema!
        else:  # load schema from URI
            uri = to_uri(schema)
            schema = load_json(uri, local_basedir=local_basedir)
    if is_jsonschema:
        assert isinstance(schema, bool) or isinstance(schema, dict)
        return validate_jsonschema(dat, schema)
    else:
        assert isinstance(schema, str)
        return validate_custom(dat, schema)
