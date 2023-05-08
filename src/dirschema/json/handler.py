"""Interface for custom validation handlers."""

from abc import ABC
from typing import IO, Any, Dict, List


class ValidationHandler(ABC):  # we don't use @abstractmethod on purpose # noqa: B024
    """Interface for custom validators that can be registered via entrypoints.

    Only one of validate or validate_json may be implemented.

    These can be used instead of JSON Schemas inside a dirschema like this:

    `validMeta: "v#ENTRYPOINT://any args for validator, e.g. schema name"`
    """

    def __init__(self, args: str):
        """Store passed arguments in instance."""
        self.args = args

    @property
    def _for_json(self) -> bool:
        """Return whether this handler is for JSON (i.e. overrides validate_json)."""
        return type(self).validate_json != ValidationHandler.validate_json

    def validate(self, data) -> Dict[str, List[str]]:
        """Run validation on passed metadata object."""
        if self._for_json:
            return self.validate_json(data, self.args)
        else:
            return self.validate_raw(data, self.args)

    # ----

    @classmethod
    def validate_raw(cls, data: IO[bytes], args: str) -> Dict[str, List[str]]:
        """Perform custom validation on passed raw binary stream.

        This can be used to implement validators for files that are not JSON
        or not parsable as JSON by the adapter used in combination with the handler.

        Args:
            data: Binary data stream
            args: String following the entry-point prefix, i.e.
                when used as `v#ENTRYPOINT://a` the `args` value will be "a".

        Returns:
            The output is a dict mapping from paths (JSON Pointers) inside the
            object to respective collected error messages.

            If there are no errors, an empty dict is returned.
        """
        raise NotImplementedError

    @classmethod
    def validate_json(cls, data: Any, args: str) -> Dict[str, List[str]]:
        """Perform custom validation on passed JSON dict.

        Args:
            data: Valid JSON dict loaded by a dirschema adapter.
            args: String following the entry-point prefix, i.e.
                when used as `v#ENTRYPOINT://a` the `args` value will be "a".

        Returns:
            The output is a dict mapping from paths (JSON Pointers) inside the
            object to respective collected error messages.

            If there are no errors, an empty dict is returned.
        """
        raise NotImplementedError
