"""Loading of the validation handlers found in the current environment."""

import entrypoints

from .handler import ValidationHandler

loaded_handlers = {
    ep.name: ep.load() for ep in entrypoints.get_group_all(group="dirschema_validator")
}
"""
Dict mapping from registered ValidationHandlers to the corresponding classes.
"""

for k, v in loaded_handlers.items():  # pragma: no cover
    if not issubclass(v, ValidationHandler):
        msg = f"Registered validation handler not subclass of ValidationHandler: '{k}'"
        raise RuntimeError(msg)
