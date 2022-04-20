"""Interface for custom validation handlers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class ValidationHandler(ABC):
    """
    Interface for custom validators that can be registered via entrypoints.

    These can be used instead of JSON Schemas inside a dirschema like this:

    `validMeta: "v#ENTRYPOINT://any args for validator, e.g. schema name"`
    """

    @classmethod
    @abstractmethod
    def validate(cls, metadata: Any, args: str) -> Dict[str, List[str]]:
        """Perform custom validation on passed JSON dict.

        Args:
            metadata: Valid JSON dict loaded by a dirschema adapter.
            args: String following the entry-point prefix, i.e.
                when used as `v#ENTRYPOINT://a` the `args` value will be "a".

        Returns:
            The output is a dict mapping from paths (JSON Pointers) inside the
            object to respective collected error messages.

            If there are no errors, an empty dict is returned.
        """
        raise NotImplementedError  # pragma: no cover
