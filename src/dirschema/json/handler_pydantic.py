"""Minimal handler for using Pydantic models."""

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

from .handler import ValidationHandler


class PydanticHandler(ValidationHandler):
    """Validation handler using `parse_obj` of pydantic models instead of JSON Schema.

    Can serve as a simple template for other handlers, or be subclassed
    to properly register your own models and used from your unique entry-point.

    In principle, you can also override/add to the `MODELS` of this class
    programmatically, but then you must accept the following disadvantages:

    * your dirschema using this handler cannot be checked from the CLI
    * your models are registered "globally", which might lead to collisions
    """

    MODELS: Dict[str, Type[BaseModel]] = {}

    @classmethod
    def validate_json(cls, metadata: Any, args: str) -> Dict[str, List[str]]:
        """See [dirschema.json.handler.ValidationHandler.validate_json][]."""
        model: Optional[Type[BaseModel]] = cls.MODELS.get(args)
        if model is None:
            raise ValueError(f"Unknown pydantic model: '{args}'")
        if not issubclass(model, BaseModel):
            raise ValueError(f"Invalid pydantic model: '{args}'")
        try:
            model.parse_obj(metadata)
        except ValidationError as e:
            errs: Dict[str, List[str]] = {}
            for verr in e.errors():
                key = "/" + "/".join(map(str, verr["loc"]))
                if key not in errs:
                    errs[key] = []
                errs[key].append(verr["msg"])
            return errs
        return {}
