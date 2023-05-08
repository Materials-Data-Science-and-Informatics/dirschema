"""Interface to perform DirSchema validation on various directory-like structures."""

import io
import itertools
import json
import zipfile as zip
from abc import ABC, abstractmethod
from pathlib import Path
from typing import IO, Any, Iterable, Optional, Set

import ruamel.yaml.parser as yaml_parser

from .json.parse import yaml

try:
    import h5py
    import numpy
except ImportError:
    _has_h5 = False
else:
    _has_h5 = True


def _require_h5py():
    """Raise exception if h5py is not installed."""
    if not _has_h5:
        raise ImportError("Install dirschema with [h5] extra for HDF5 support!")


# NOTE: currently, completely ignores existence of symlinks
# the h5py visit function does ignore them too,
# also reasonable validation behavior is unclear.
# either stick to this, or find a reasonable semantics + workaround for HDF5


class IDirectory(ABC):
    """Abstract interface for things that behave like directories and files.

    An adapter is intended to be instantiated mainly using `for_path`,
    based on a regular path in the file system.

    Use the constructor to initialize an adapter for a more general data
    source (such as an object to work with an open archive file, etc.)
    """

    @abstractmethod
    def __init__(cls, obj: object) -> None:
        """Initialized an instance for a suitable directory-like object."""

    @classmethod
    @abstractmethod
    def for_path(cls, path: Path):
        """Return an instance for a path to a archive file or a directory.

        Args:
            path: Path to a file or directory compatible with the adapter.
        """

    @abstractmethod
    def get_paths(self) -> Iterable[str]:
        """Return paths relative to root directory that are to be checked."""

    @abstractmethod
    def is_dir(self, path: str) -> bool:
        """Return whether the path is (like) a directory."""

    @abstractmethod
    def is_file(self, path: str) -> bool:
        """Return whether the path is (like) a file."""

    @abstractmethod
    def open_file(self, path: str) -> Optional[IO[bytes]]:
        """Try loading data from file at given path (to perform validation on it)."""

    def decode_json(self, data: IO[bytes], path: str) -> Optional[Any]:
        """Try parsing binary data stream as JSON (to perform validation on it).

        Second argument is the path of the opened stream.

        Default implementation will first try parsing as JSON, then as YAML.
        """
        try:
            return json.load(data)
        except json.JSONDecodeError:
            try:
                return yaml.load(data)
            except yaml_parser.ParserError:
                return None

    def load_meta(self, path: str) -> Optional[Any]:
        """Use open_file and decode_json to load JSON metadata."""
        f = self.open_file(path)
        return self.decode_json(f, path) if f is not None else None


class RealDir(IDirectory):
    """Pass-through implementation for working with actual file system."""

    def __init__(self, path: Path) -> None:
        """Initialize adapter for a plain directory path."""
        self.base = path

    @classmethod
    def for_path(cls, path: Path):
        """See [dirschema.adapters.IDirectory.for_path][]."""
        return cls(path)

    def get_paths(self) -> Iterable[str]:
        """See [dirschema.adapters.IDirectory.get_paths][]."""
        paths = filter(lambda p: not p.is_symlink(), sorted(self.base.rglob("*")))
        return itertools.chain(
            [""], map(lambda p: str(p.relative_to(self.base)), paths)
        )

    def open_file(self, path: str) -> Optional[IO[bytes]]:
        """See [dirschema.adapters.IDirectory.open_file][]."""
        try:
            return open(self.base / path, "rb")
        except (FileNotFoundError, IsADirectoryError):
            return None

    def is_dir(self, dir: str) -> bool:
        """See [dirschema.adapters.IDirectory.is_dir][]."""
        return (self.base / dir).is_dir()

    def is_file(self, dir: str) -> bool:
        """See [dirschema.adapters.IDirectory.is_file][]."""
        return (self.base / dir).is_file()


class ZipDir(IDirectory):
    """Adapter for working with zip files (otherwise equivalent to `RealDir`)."""

    def __init__(self, zip_file: zip.ZipFile):
        """Initialize adapter for a zip file."""
        self.file: zip.ZipFile = zip_file
        self.names: Set[str] = set(self.file.namelist())
        self.names.add("/")

    @classmethod
    def for_path(cls, path: Path):
        """See [dirschema.adapters.IDirectory.for_path][]."""
        opened = zip.ZipFile(path, "r")  # auto-closed on GC, no need to do anything
        return cls(opened)

    def get_paths(self) -> Iterable[str]:
        """See [dirschema.adapters.IDirectory.get_paths][]."""
        return itertools.chain(map(lambda s: s.rstrip("/"), sorted(self.names)))

    def open_file(self, path: str) -> Optional[IO[bytes]]:
        """See [dirschema.adapters.IDirectory.open_file][]."""
        try:
            return self.file.open(path)
        except (KeyError, IsADirectoryError):
            return None

    # as is_dir and is_file of zip.Path appear to work purely syntactically,
    # they're useless for us. We rather just lookup in the list of paths we need anyway

    def is_dir(self, dir: str) -> bool:
        """See [dirschema.adapters.IDirectory.is_dir][]."""
        cand_name: str = dir.rstrip("/") + "/"
        return cand_name in self.names

    def is_file(self, dir: str) -> bool:
        """See [dirschema.adapters.IDirectory.is_file][]."""
        cand_name: str = dir.rstrip("/")
        return cand_name in self.names


class H5Dir(IDirectory):
    """Adapter for working with HDF5 files.

    Attributes do not fit nicely into the concept of just directories and files.
    The following conventions are used to checking attributes:

    An attribute 'attr' of some dataset or group '/a/b'
    is mapped to the path '/a/b@attr' and is interpreted as a file.

    Therefore, '@' MUST NOT be used in names of groups, datasets or attributes.

    Only JSON is supported for the metadata, assuming that HDF5 files are usually not
    constructed by hand (which is the main reason for YAML support in the other cases).

    All stored metadata entities must have a name ending with ".json"
    in order to distinguish them from plain strings. This is done because datasets
    or attributes are often used for storing simple values that could also be
    validated using a JSON Schema.
    """

    _ATTR_SEP = "@"
    """Separator used in paths to separate a HDF5 node from an attribute."""

    _JSON_SUF = ".json"
    """Suffix used in leaf nodes to distinguish strings from JSON-serialized data."""

    def __init__(self, hdf5_file: h5py.File) -> None:
        """Initialize adapter for a HDF5 file."""
        self.file: h5py.File = hdf5_file

    @classmethod
    def for_path(cls, dir: Path):
        """See [dirschema.adapters.IDirectory.for_path][]."""
        _require_h5py()
        opened = h5py.File(dir, "r")  # auto-closed on GC, no need to do anything
        return cls(opened)

    def get_paths(self) -> Iterable[str]:
        """See [dirschema.adapters.IDirectory.get_paths][]."""
        ret = [""]
        for atr in self.file["/"].attrs.keys():
            ret.append(f"{self._ATTR_SEP}{atr}")

        def collect(name: str) -> None:
            if name.find(self._ATTR_SEP) >= 0:
                raise ValueError(f"Invalid name, must not contain {self._ATTR_SEP}!")
            ret.append(name)
            for atr in self.file[name].attrs.keys():
                ret.append(f"{name}{self._ATTR_SEP}{atr}")

        self.file.visit(collect)
        return ret

    def is_dir(self, path: str) -> bool:
        """See [dirschema.adapters.IDirectory.is_dir][]."""
        if path == "":
            return True  # root directory
        if path.find(self._ATTR_SEP) >= 0 or path not in self.file:
            return False  # not existing or is an attribute
        if isinstance(self.file[path], h5py.Group):
            return True  # is a group
        return False  # something that exists, but is not a group

    def is_file(self, path: str) -> bool:
        """See [dirschema.adapters.IDirectory.is_file][]."""
        # attributes (treated like special files) exist
        # if underlying group/dataset exists
        if path.find(self._ATTR_SEP) >= 0:
            p = path.split(self._ATTR_SEP)
            p[0] = p[0] or "/"
            return p[0] in self.file and p[1] in self.file[p[0]].attrs
        else:
            # otherwise check it is a dataset (= "file")
            return path in self.file and isinstance(self.file[path], h5py.Dataset)

    def decode_json(self, data: IO[bytes], path: str) -> Optional[Any]:
        """See [dirschema.adapters.IDirectory.decode_json][]."""
        bs = data.read()
        try:
            ret = json.loads(bs)
        except json.JSONDecodeError:
            return None

        if isinstance(ret, dict) and not path.endswith(self._JSON_SUF):
            return bs
        else:
            return ret

    def open_file(self, path: str) -> Optional[IO[bytes]]:
        """See [dirschema.adapters.IDirectory.open_file][]."""
        p = path
        if p.find(self._ATTR_SEP) >= 0:
            # try treating as attribute, return data if it is a string
            f, s = p.split(self._ATTR_SEP)
            f = f or "/"
            if f in self.file and s in self.file[f].attrs:
                dat = self.file[f].attrs[s]
                if isinstance(dat, h5py.Empty):
                    return None
                if isinstance(dat, str):
                    if not path.endswith(self._JSON_SUF):
                        dat = f'"{dat}"'  # JSON-encoded string
                else:
                    dat = json.dumps(dat.tolist())
                return io.BytesIO(dat.encode("utf-8"))
            else:
                return None

        # check that the path exists and is a dataset, but not a numpy array
        if p not in self.file:
            return None

        dat = self.file[p]
        if not isinstance(dat, h5py.Dataset):
            return None

        bs: Any = dat[()]
        if isinstance(bs, numpy.ndarray):
            return None

        # the only kinds of datasets we accept are essentially utf-8 strings
        # which are represented as possibly wrapped bytes
        if isinstance(bs, numpy.void):  # void-wrapped bytes -> unpack
            bs = bs.tobytes()

        return io.BytesIO(bs)


def get_adapter_for(path: Path) -> IDirectory:
    """Return suitable interface adapter based on path and file extension.

    Args:
        path: Path to directory or archive file

    Returns:
        An adapter instance that can be used for dirschema validation.

    Raises:
        ValueError: If no suitable adapter was found for the path.
    """
    if path.is_dir():
        return RealDir.for_path(path)

    if path.is_file():
        if path.name.endswith("zip"):
            return ZipDir.for_path(path)
        elif path.name.endswith(("h5", "hdf5")):
            _require_h5py()
            return H5Dir.for_path(path)

    raise ValueError(f"Found no suitable dirschema adapter for path: {path}")
