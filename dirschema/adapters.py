"""Interface to perform DirSchema validation on various directory-like structures."""

import itertools
import json
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

# NOTE: currently, completely ignores existence of symlinks
# the h5py visit function does ignore them too and also reasonable validation behavior unclear
# either stick to this, or find a reasonable semantics + workaround for HDF5 files

# NOTE: another useful adapter could be a zip adapter


class IDirectory(ABC):
    """Abstract interface for things that behave like directories and files."""

    def __init__(self, dir: Path) -> None:
        """Initialize interface object."""
        self.base = dir

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
    def load_meta(self, path: str) -> Optional[Any]:
        """Try loading metadata file at given path (to perform validation on it)."""


class RealDir(IDirectory):
    """Pass-through implementation for working with actual file system."""

    def get_paths(self) -> Iterable[str]:  # noqa: D102
        paths = filter(lambda p: not p.is_symlink(), sorted(self.base.rglob("*")))
        return itertools.chain(
            [""], map(lambda p: str(p.relative_to(self.base)), paths)
        )

    def is_dir(self, dir: str) -> bool:  # noqa: D102
        return self.base.joinpath(Path(dir)).is_dir()

    def is_file(self, dir: str) -> bool:  # noqa: D102
        return self.base.joinpath(Path(dir)).is_file()

    def load_meta(self, path: str):  # noqa: D102
        try:
            with open(self.base.joinpath(Path(path)), "r") as f:
                return json.load(f)
        except (FileNotFoundError, IsADirectoryError, json.JSONDecodeError):
            return None


H5_ATTR_SEP = "@"
"""Separator used in paths to separate a HDF5 node from an attribute."""

H5_JSON_SUF = ".json"
"""Suffix used in leaf nodes to distinguish strings from JSON-serialized data."""


class H5Dir(IDirectory):
    """Adapter for working with HDF5 files."""

    def __init__(self, dir: Path) -> None:  # noqa: D107
        if not _has_h5:
            raise ImportError("Install dirschema with [h5] extra for HDF5 support!")

        super().__init__(dir)
        self.file = h5py.File(dir, "r")  # auto-closed on GC, no need to do anything

    def get_paths(self) -> Iterable[str]:  # noqa: D102
        ret = [""]
        for atr in self.file["/"].attrs.keys():
            ret.append(f"{H5_ATTR_SEP}{atr}")

        def collect(name: str) -> None:
            if name.find(H5_ATTR_SEP) >= 0:
                raise ValueError(f"Invalid name, must not contain {H5_ATTR_SEP}!")
            ret.append(name)
            for atr in self.file[name].attrs.keys():
                ret.append(f"{name}{H5_ATTR_SEP}{atr}")

        self.file.visit(collect)
        return ret

    def is_dir(self, path: str) -> bool:  # noqa: D102
        if path == "":
            return True
        if path.find(H5_ATTR_SEP) >= 0 or path not in self.file:
            return False
        if isinstance(self.file[path], h5py.Group):
            return True
        return False

    def is_file(self, path: str) -> bool:  # noqa: D102
        # attributes (treated like special files) exist if underlying group/dataset exists
        if path.find(H5_ATTR_SEP) >= 0:
            p = path.split(H5_ATTR_SEP)
            p[0] = p[0] or "/"
            return p[0] in self.file and p[1] in self.file[p[0]].attrs
        else:
            # otherwise check it is a dataset (= "file")
            return path in self.file and isinstance(self.file[path], h5py.Dataset)

    def load_meta(self, path: str):  # noqa: D102
        p = path
        if p.find(H5_ATTR_SEP) >= 0:
            # try treating as attribute
            f, s = p.split(H5_ATTR_SEP)
            f = f or "/"
            if f in self.file and s in self.file[f].attrs:
                dat = self.file[f].attrs[s]
                if isinstance(dat, str):
                    if s.endswith(H5_JSON_SUF):
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

        # try decoding as bytes
        try:
            if isinstance(bs, bytes):  # non-wrapped string (must not contain NUL)
                return json.loads(bs.decode("utf-8"))
            elif isinstance(bs, numpy.void):  # void-wrapped bytes
                return json.loads(bs.tobytes().decode("utf-8"))

        except (UnicodeDecodeError, json.JSONDecodeError):  # failed parsing it
            return None


def get_adapter_for(path: Path) -> IDirectory:
    """Return suitable interface adapter for given path."""
    if path.is_dir():
        return RealDir(path)

    if path.is_file():
        try:
            f = h5py.File(path, "r")
            f.close()
            return H5Dir(path)
        except OSError:
            # apparently not HDF5 file
            pass

    raise ValueError(f"Found no suitable dirschema adapter for path: {path}")
