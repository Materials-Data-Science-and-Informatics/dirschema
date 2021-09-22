"""Tests for dirschema adapters."""
import json
from pathlib import Path

import h5py
import numpy
import pytest

from dirschema.adapters import H5_ATTR_SUF, H5Dir, RealDir, get_adapter_for


def prep_realdir(path: Path):
    """Prepare a real directory for tests."""
    base = path / "dataset"

    base.mkdir()
    (base / "foo").mkdir()
    (base / "foo" / "bar").mkdir()
    (base / "qux").mkdir()

    (base / "_meta.json").touch()
    (base / "readme.txt").touch()
    (base / "binary.dat").touch()
    (base / "foo" / "data.bin").touch()

    meta = {"hello": "world"}
    with open(base / "foo" / "data.bin_meta.json", "w") as f:
        json.dump(meta, f)

    with open(base / "foo" / "notReally.json", "w") as f:
        f.write("this is not valid JSON")
    return base


def prep_hdf5dir(path: Path):
    """Prepare an HDF5 file for tests."""
    base = path / "dataset.h5"
    with h5py.File(base, "w") as f:
        # test attributes
        f["/"].attrs["someBool"] = True
        f["/"].attrs["someInt"] = 42
        f["/"].attrs["someFloat"] = 3.14
        f["/"].attrs["someString"] = "hello"
        f["/"].attrs["someArray"] = [1, 2, 3]
        f["/"].attrs["someUnknown"] = numpy.void("surprise".encode("utf-8"))

        f.create_group("foo/bar")

        f.create_dataset("foo/data", data=numpy.random.randint(0, 10, size=(5, 5)))
        # with attribute
        f["foo/data"].attrs["filename"] = "data.bin"
        # and also metadata
        meta = {"hello": "world"}
        metabytes = json.dumps(meta).encode("utf-8")
        f.create_dataset("foo/data_meta.json", data=metabytes)
        f.create_dataset("foo/wrapped.json", data=numpy.void(metabytes))
        f.create_dataset("foo/notReally.json", data=numpy.void(b"notJSON"))

        f.create_group("qux")
    return base


def test_realdir(tmp_path):
    """Test adapter for real directories."""
    base = prep_realdir(tmp_path)
    inst = RealDir(base)

    paths = inst.get_paths()
    expected = [
        "",
        "_meta.json",
        "binary.dat",
        "foo",
        "foo/bar",
        "foo/data.bin",
        "foo/data.bin_meta.json",
        "foo/notReally.json",
        "qux",
        "readme.txt",
    ]
    assert list(paths) == expected

    assert not inst.is_dir("invalid")
    assert inst.is_dir("")
    assert inst.is_dir("foo")
    assert inst.is_dir("foo/bar")
    assert not inst.is_dir("foo/data.bin")
    assert not inst.is_dir("foo/data.bin_meta.json")

    assert not inst.is_file("invalid")
    assert not inst.is_file("")
    assert not inst.is_file("foo")
    assert not inst.is_file("foo/bar")
    assert inst.is_file("foo/data.bin")
    assert inst.is_file("foo/data.bin_meta.json")

    assert inst.load_json("") is None
    assert inst.load_json("invalid") is None
    assert inst.load_json("foo/data.bin") is None
    assert inst.load_json("foo/notReally.json") is None
    assert inst.load_json("foo/data.bin_meta.json") == {"hello": "world"}


def test_hdf5dir(tmp_path):
    """Test adapter for HDF5 files."""
    base = prep_hdf5dir(tmp_path)
    inst = H5Dir(base)

    paths = inst.get_paths()
    expected = [
        "",
        H5_ATTR_SUF,
        "foo",
        "foo/bar",
        "foo/data",
        "foo/data" + H5_ATTR_SUF,
        "foo/data_meta.json",
        "foo/notReally.json",
        "foo/wrapped.json",
        "qux",
    ]
    assert list(paths) == expected

    assert not inst.is_dir("invalid")
    assert inst.is_dir("")
    assert not inst.is_dir(H5_ATTR_SUF)
    assert inst.is_dir("foo")
    assert inst.is_dir("foo/bar")
    assert not inst.is_dir("foo/data")
    assert not inst.is_dir("foo/data" + H5_ATTR_SUF)
    assert not inst.is_dir("foo/data_meta.json")
    assert not inst.is_dir("foo/data_meta.json" + H5_ATTR_SUF)

    assert not inst.is_file("invalid")
    assert not inst.is_file("")
    assert inst.is_file(H5_ATTR_SUF)
    assert not inst.is_file("foo")
    assert not inst.is_file("foo/bar")
    assert inst.is_file("foo/data")
    assert inst.is_file("foo/data" + H5_ATTR_SUF)
    assert inst.is_file("foo/data_meta.json")
    assert not inst.is_file("foo/data_meta.json" + H5_ATTR_SUF)

    # test loading attributes as JSON
    expected = {
        "someBool": True,
        "someInt": 42,
        "someFloat": 3.14,
        "someString": "hello",
        "someArray": [1, 2, 3],
        "someUnknown": None,
    }
    meta = inst.load_json(H5_ATTR_SUF)
    assert meta == expected
    assert inst.load_json("foo/data" + H5_ATTR_SUF) == {"filename": "data.bin"}
    assert inst.load_json("foo/invalid" + H5_ATTR_SUF) is None

    # test loading datasets as JSON
    assert inst.load_json("") is None
    assert inst.load_json("invalid") is None
    assert inst.load_json("foo") is None
    assert inst.load_json("foo/data") is None
    assert inst.load_json("foo/notReally.json") is None
    assert inst.load_json("foo/data_meta.json") == {"hello": "world"}
    assert inst.load_json("foo/wrapped.json") == {"hello": "world"}


def test_getadapter(tmp_path):
    """Test automatic adapter selection."""
    realpath = prep_realdir(tmp_path)
    h5path = prep_hdf5dir(tmp_path)

    unknown = tmp_path / "tempfile.tmp"
    unknown.touch()

    assert isinstance(get_adapter_for(realpath), RealDir)
    assert isinstance(get_adapter_for(h5path), H5Dir)
    with pytest.raises(ValueError):
        get_adapter_for(unknown)