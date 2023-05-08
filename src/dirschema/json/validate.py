"""Helper functions to perform validation of JSON-compatible metadata files."""

from pathlib import Path
from typing import Dict, List, Optional, Type, Union

from jsonschema import Draft202012Validator

from .handler import ValidationHandler
from .handlers import loaded_handlers
from .parse import load_json, to_uri

JSONValidationErrors = Dict[str, List[str]]
"""JSON validation errors mapping from JSON Pointers to of error message lists."""


def plugin_from_uri(custom_uri: str) -> ValidationHandler:
    """Parse a validation plugin pseudo-URI, return the plugin class and args string."""
    try:
        if not custom_uri.startswith("v#"):
            raise ValueError
        ep, args = custom_uri[2:].split("://")
        if ep == "":
            raise ValueError
    except ValueError:
        raise ValueError(f"Invalid custom validator plugin pseudo-URI: '{custom_uri}'")

    try:
        h: Type[ValidationHandler] = loaded_handlers[ep]
        return h(args)
    except KeyError:
        raise ValueError(f"Validator entry-point not found: '{ep}'")


def validate_custom(dat, plugin_str: str) -> JSONValidationErrors:
    """Perform validation based on a validation handler string."""
    h = plugin_from_uri(plugin_str)
    if h._for_json:
        return h.validate_json(dat, h.args)
    else:
        return h.validate_raw(dat, h.args)


def validate_jsonschema(dat, schema: Union[bool, Dict]) -> JSONValidationErrors:
    """Perform validation of a dict based on a JSON Schema."""
    v = Draft202012Validator(schema=schema)  # type: ignore
    errs: Dict[str, List[str]] = {}
    for verr in sorted(v.iter_errors(dat), key=lambda e: e.path):  # type: ignore
        key = "/" + "/".join(map(str, verr.path))  # JSON Pointer into document
        if key not in errs:
            errs[key] = []
        errs[key].append(verr.message)
    return errs


def resolve_validator(
    schema_or_ref: Union[bool, str, Dict],
    *,
    local_basedir: Optional[Path] = None,
    relative_prefix: str = "",
) -> Union[bool, Dict, ValidationHandler]:
    """Resolve passed object into a schema or validator.

    If passed object is already a schema, will return it.
    If passed object is a string, will load the referenced schema
    or instantiate the custom validator (a string starting with `v#`).
    """
    if isinstance(schema_or_ref, bool) or isinstance(schema_or_ref, dict):
        # embedded schema
        return schema_or_ref

    if not schema_or_ref.startswith("v#"):
        # load schema from URI
        uri = to_uri(schema_or_ref, local_basedir, relative_prefix)
        return load_json(uri, local_basedir=local_basedir)

    # custom validation, not json schema
    return plugin_from_uri(schema_or_ref)


def validate_metadata(
    dat,
    schema: Union[bool, str, Dict, ValidationHandler],
    *,
    local_basedir: Optional[Path] = None,
    relative_prefix: str = "",
) -> JSONValidationErrors:
    """Validate object (dict or byte stream) using JSON Schema or custom validator.

    The validator must be either a JSON Schema dict, or a string
    pointing to a JSON Schema, or a custom validator handler string.

    Returns a dict mapping from JSON Pointers to a list of errors in that location.
    If the dict is empty, no validation errors were detected.
    """
    if isinstance(schema, str):
        val = resolve_validator(
            schema, local_basedir=local_basedir, relative_prefix=relative_prefix
        )
    else:
        val = schema

    if isinstance(val, ValidationHandler):
        return val.validate(dat)
    else:
        return validate_jsonschema(dat, val)
