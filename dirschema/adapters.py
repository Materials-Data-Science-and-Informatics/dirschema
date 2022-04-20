"""Interface to perform DirSchema validation on various directory-like structures."""

import itertools
import json
import zipfile as zip
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable, Optional

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
    def load_meta(self, path: str) -> Optional[Any]:
        """Try loading metadata file at given path (to perform validation on it)."""

    @abstractmethod
    def is_dir(self, path: str) -> bool:
        """Return whether the path is (like) a directory."""

    @abstractmethod
    def is_file(self, path: str) -> bool:
        """Return whether the path is (like) a file."""


class RealDir(IDirectory):
    """Pass-through implementation for working with actual file system."""

    def get_paths(self) -> Iterable[str]:  # noqa: D102
        paths = filter(lambda p: not p.is_symlink(), sorted(self.base.rglob("*")))
        return itertools.chain(
            [""], map(lambda p: str(p.relative_to(self.base)), paths)
        )

    def load_meta(self, path: str):  # noqa: D102
        try:
            with open(self.base / path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, IsADirectoryError, json.JSONDecodeError):
            return None

    def is_dir(self, dir: str) -> bool:  # noqa: D102
        return (self.base / dir).is_dir()

    def is_file(self, dir: str) -> bool:  # noqa: D102
        return (self.base / dir).is_file()


class ZipDir(IDirectory):
    """Adapter for working with zip files."""

    def __init__(self, dir: Path, opened_file: zip.ZipFile) -> None:  # noqa: D107
        super().__init__(dir)
        self.file = opened_file
        self.names = set(self.file.namelist())
        self.names.add("/")

    @classmethod
    def for_path(cls, dir: Path):  # noqa: D102
        opened = zip.ZipFile(dir, "r")  # auto-closed on GC, no need to do anything
        return cls(dir, opened)

    def get_paths(self) -> Iterable[str]:  # noqa: D102
        return itertools.chain(map(lambda s: s.rstrip("/"), sorted(self.names)))

    def load_meta(self, path: str):  # noqa: D102
        try:
            return json.loads(self.file.read(path).decode("utf-8"))
        except (KeyError, IsADirectoryError, json.JSONDecodeError):
            return None

    # as is_dir and is_file of zip.Path appear to work purely syntactically,
    # they're useless for us. We rather just lookup in the list of paths

    def is_dir(self, dir: str) -> bool:  # noqa: D102
        cand_name: str = dir.rstrip("/") + "/"
        return cand_name in self.names

    def is_file(self, dir: str) -> bool:  # noqa: D102
        cand_name: str = dir.rstrip("/")
        return cand_name in self.names


class H5Dir(IDirectory):
    """Adapter for working with HDF5 files."""

    ATTR_SEP = "@"
    """Separator used in paths to separate a HDF5 node from an attribute."""

    JSON_SUF = ".json"
    """Suffix used in leaf nodes to distinguish strings from JSON-serialized data."""

    def __init__(self, dir: Path, opened_file) -> None:  # noqa: D107
        super().__init__(dir)
        self.file = opened_file

    @classmethod
    def for_path(cls, dir: Path):
        require_h5py()
        opened = h5py.File(dir, "r")  # auto-closed on GC, no need to do anything
        return cls(dir, opened)

    def get_paths(self) -> Iterable[str]:  # noqa: D102
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

    def is_dir(self, path: str) -> bool:  # noqa: D102
        if path == "":
            return True
        if path.find(self.ATTR_SEP) >= 0 or path not in self.file:
            return False
        if isinstance(self.file[path], h5py.Group):
            return True
        return False

    def is_file(self, path: str) -> bool:  # noqa: D102
        # attributes (treated like special files) exist if underlying group/dataset exists
        if path.find(self.ATTR_SEP) >= 0:
            p = path.split(self.ATTR_SEP)
            p[0] = p[0] or "/"
            return p[0] in self.file and p[1] in self.file[p[0]].attrs
        else:
            # otherwise check it is a dataset (= "file")
            return path in self.file and isinstance(self.file[path], h5py.Dataset)

    def load_meta(self, path: str):  # noqa: D102
        p = path
        if p.find(self.ATTR_SEP) >= 0:
            # try treating as attribute. attributes are interpreted when possible
            f, s = p.split(self.ATTR_SEP)
            f = f or "/"
            if f in self.file and s in self.file[f].attrs:
                dat = self.file[f].attrs[s]
                if isinstance(dat, str):
                    if s.endswith(self.JSON_SUF):
                        return json.loads(dat)
                    else:
                        return dat
                elif isinstance(dat, h5py.Empty):
                    return None
                else:
                    return dat.tolist()
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

        try:  # decode string from bytes
            return json.loads(bs.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):  # failed parsing it
            return None


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
