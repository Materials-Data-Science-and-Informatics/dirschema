"""Interface to perform DirSchema validation on various directory-like structures."""

import io
import itertools
import json
import zipfile as zip
from abc import ABC, abstractmethod
from pathlib import Path
from typing import IO, Any, Iterable, Optional

import ruamel.yaml.parser as yaml_parser

from .json.parse import yaml

try:
    import h5py
    import numpy
except ImportError:
    _has_h5 = False
else:
    _has_h5 = True


def require_h5py():
    """Raise exception if h5py is not installed."""
    if not _has_h5:
        raise ImportError("Install dirschema with [h5] extra for HDF5 support!")


# NOTE: currently, completely ignores existence of symlinks
# the h5py visit function does ignore them too and also reasonable validation behavior unclear
# either stick to this, or find a reasonable semantics + workaround for HDF5 files


class IDirectory(ABC):
    """Abstract interface for things that behave like directories and files."""

    def __init__(self, dir: Path) -> None:
        """Initialize interface object."""
        self.base = dir

    @classmethod
    def for_path(cls, dir: Path):
        """Return an instance given a path to a archive file or a directory.

        Default implementation just passes through the path to the constructor.
        """
        return cls(dir)

    @abstractmethod
    def get_paths(self) -> Iterable[str]:
        """Return paths relative to give base directory that are to be checked."""

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

    def get_paths(self) -> Iterable[str]:
        paths = filter(lambda p: not p.is_symlink(), sorted(self.base.rglob("*")))
        return itertools.chain(
            [""], map(lambda p: str(p.relative_to(self.base)), paths)
        )

    def open_file(self, path: str) -> Optional[IO[bytes]]:
        try:
            return open(self.base / path, "rb")
        except (FileNotFoundError, IsADirectoryError):
            return None

    def is_dir(self, dir: str) -> bool:
        return (self.base / dir).is_dir()

    def is_file(self, dir: str) -> bool:
        return (self.base / dir).is_file()


class ZipDir(IDirectory):
    """Adapter for working with zip files (otherwise equivalent to `RealDir`)."""

    def __init__(self, dir: Path, opened_file: zip.ZipFile):
        super().__init__(dir)
        self.file = opened_file
        self.names = set(self.file.namelist())
        self.names.add("/")

    @classmethod
    def for_path(cls, dir: Path):
        opened = zip.ZipFile(dir, "r")  # auto-closed on GC, no need to do anything
        return cls(dir, opened)

    def get_paths(self) -> Iterable[str]:
        return itertools.chain(map(lambda s: s.rstrip("/"), sorted(self.names)))

    def open_file(self, path: str) -> Optional[IO[bytes]]:
        try:
            return self.file.open(path)
        except (KeyError, IsADirectoryError):
            return None

    # as is_dir and is_file of zip.Path appear to work purely syntactically,
    # they're useless for us. We rather just lookup in the list of paths we need anyway

    def is_dir(self, dir: str) -> bool:
        cand_name: str = dir.rstrip("/") + "/"
        return cand_name in self.names

    def is_file(self, dir: str) -> bool:
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

    ATTR_SEP = "@"
    """Separator used in paths to separate a HDF5 node from an attribute."""

    JSON_SUF = ".json"
    """Suffix used in leaf nodes to distinguish strings from JSON-serialized data."""

    def __init__(self, dir: Path, opened_file) -> None:
        super().__init__(dir)
        self.file = opened_file

    @classmethod
    def for_path(cls, dir: Path):
        require_h5py()
        opened = h5py.File(dir, "r")  # auto-closed on GC, no need to do anything
        return cls(dir, opened)

    def get_paths(self) -> Iterable[str]:
        ret = [""]
        for atr in self.file["/"].attrs.keys():
            ret.append(f"{self.ATTR_SEP}{atr}")

        def collect(name: str) -> None:
            if name.find(self.ATTR_SEP) >= 0:
                raise ValueError(f"Invalid name, must not contain {self.ATTR_SEP}!")
            ret.append(name)
            for atr in self.file[name].attrs.keys():
                ret.append(f"{name}{self.ATTR_SEP}{atr}")

        self.file.visit(collect)
        return ret

    def is_dir(self, path: str) -> bool:
        if path == "":
            return True  # root directory
        if path.find(self.ATTR_SEP) >= 0 or path not in self.file:
            return False  # not existing or is an attribute
        if isinstance(self.file[path], h5py.Group):
            return True  # is a group
        return False  # something that exists, but is not a group

    def is_file(self, path: str) -> bool:
        # attributes (treated like special files) exist if underlying group/dataset exists
        if path.find(self.ATTR_SEP) >= 0:
            p = path.split(self.ATTR_SEP)
            p[0] = p[0] or "/"
            return p[0] in self.file and p[1] in self.file[p[0]].attrs
        else:
            # otherwise check it is a dataset (= "file")
            return path in self.file and isinstance(self.file[path], h5py.Dataset)

    def decode_json(self, data: IO[bytes], path: str) -> Optional[Any]:
        bs = data.read()
        try:
            ret = json.loads(bs)
        except json.JSONDecodeError:
            return None

        if isinstance(ret, dict) and not path.endswith(self.JSON_SUF):
            return bs
        else:
            return ret

    def open_file(self, path: str) -> Optional[IO[bytes]]:
        p = path
        if p.find(self.ATTR_SEP) >= 0:
            # try treating as attribute, return data if it is a string
            f, s = p.split(self.ATTR_SEP)
            f = f or "/"
            if f in self.file and s in self.file[f].attrs:
                dat = self.file[f].attrs[s]
                if isinstance(dat, h5py.Empty):
                    return None
                if isinstance(dat, str):
                    if not path.endswith(self.JSON_SUF):
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
    """Return suitable interface adapter for given path (selected by file extension)."""
    if path.is_dir():
        return RealDir.for_path(path)

    if path.is_file():
        if path.name.endswith("zip"):
            return ZipDir.for_path(path)
        elif path.name.endswith(("h5", "hdf5")):
            require_h5py()
            return H5Dir.for_path(path)

    raise ValueError(f"Found no suitable dirschema adapter for path: {path}")
