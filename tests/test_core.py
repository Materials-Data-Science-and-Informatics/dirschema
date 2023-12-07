"""Tests for dirschema core."""
import re
from typing import cast

import pytest
from dirschema.core import DSRule, MetaConvention, PathSlice, Rule, TypeEnum


def test_meta_convention():
    """Test metadata convention string rewriting."""
    conv = MetaConvention()
    assert not conv.is_meta("")
    assert not conv.is_meta("foo")
    assert not conv.is_meta("foo/bar")
    assert not conv.is_meta("foo/bar_meta.jsonbaz")
    assert not conv.is_meta("foo/bar_meta.json/baz")
    assert conv.is_meta("foo/bar_meta.json")
    assert conv.is_meta("foo/_meta.json")

    assert conv.meta_for("") == "_meta.json"
    assert conv.meta_for("foo") == "foo_meta.json"
    assert conv.meta_for("foo", is_dir=True) == "foo/_meta.json"

    conv.filePrefix = "mymeta_"
    assert not conv.is_meta("foo/bar_meta.json")
    assert not conv.is_meta("foo/mymeta_bar")
    assert conv.is_meta("foo/mymeta_bar_meta.json")
    assert conv.is_meta("foo/mymeta__meta.json")

    assert conv.meta_for("") == "mymeta__meta.json"
    assert conv.meta_for("foo") == "mymeta_foo_meta.json"
    assert conv.meta_for("foo", is_dir=True) == "foo/mymeta__meta.json"

    conv.pathPrefix = "meta_prefix"
    assert not conv.is_meta("foo/mymeta_bar_meta.json")
    assert not conv.is_meta("bla/foo/mymeta_bar_meta.json")
    assert not conv.is_meta("bla/meta_prefix/foo/mymeta_bar_meta.json")
    assert not conv.is_meta("meta_prefix/foo/bar_meta.json")
    assert not conv.is_meta("meta_prefix/foo/mymeta_bar")
    assert conv.is_meta("meta_prefix/foo/mymeta__meta.json")
    assert conv.is_meta("meta_prefix/foo/mymeta_bar_meta.json")

    assert conv.meta_for("") == "meta_prefix/mymeta__meta.json"
    assert conv.meta_for("foo") == "meta_prefix/mymeta_foo_meta.json"
    assert conv.meta_for("foo", is_dir=True) == "meta_prefix/foo/mymeta__meta.json"

    conv.pathSuffix = "meta_suffix"
    assert not conv.is_meta("meta_prefix/mymeta_bar_meta.json")
    assert not conv.is_meta("meta_prefix/meta_suffix/foo/mymeta_bar_meta.json")
    assert not conv.is_meta("meta_suffix/mymeta_bar_meta.json")
    assert not conv.is_meta("meta_suffix/meta_prefix/mymeta_bar_meta.json")
    assert conv.is_meta("meta_prefix/meta_suffix/mymeta__meta.json")
    assert conv.is_meta("meta_prefix/meta_suffix/mymeta_bar_meta.json")
    assert conv.is_meta("meta_prefix/foo/meta_suffix/mymeta_bar_meta.json")

    assert conv.meta_for("") == "meta_prefix/meta_suffix/mymeta__meta.json"
    assert conv.meta_for("foo") == "meta_prefix/meta_suffix/mymeta_foo_meta.json"
    assert (
        conv.meta_for("foo", is_dir=True)
        == "meta_prefix/foo/meta_suffix/mymeta__meta.json"
    )
    assert (
        conv.meta_for("foo/bar") == "meta_prefix/foo/meta_suffix/mymeta_bar_meta.json"
    )


def test_rewrite():
    """Test rewriting of paths."""
    # edge cases, with identity transform. check slice/unslice invariant
    for start in [None, 0]:
        for end in [None, 0, 4, 5]:
            assert PathSlice.into("", start, end).rewrite().unslice() == ""
            assert PathSlice.into("hello", start, end).rewrite().unslice() == "hello"
            assert (
                PathSlice.into("a/b/c/d", start, end).rewrite().unslice() == "a/b/c/d"
            )

    # non-trivial slices
    arr = ["a", "b", "c"]
    slices = [(None, 1), (0, 2), (1, 3), (-2, -1), (1, -1), (-3, 2)]
    for start, end in slices:
        sl = PathSlice.into("a/b/c", start, end).sliceStr
        assert sl == "/".join(arr[start:end])
        assert len(sl) > 0
    assert PathSlice.into("a/b/c", 1, 0).sliceStr == "b/c"  # special case: end = 0

    # empty slices
    for start, end in [(-1, 1), (-1, -2), (1, 1), (2, 1)]:
        assert PathSlice.into("a/b/c", start, end).sliceStr == ""

    psl = PathSlice.into("a/bbc/d", 1, 2)
    assert psl.sliceStr == "bbc"
    assert psl.rewrite("b") is None  # not full match!
    assert psl.rewrite("b", "c") is None  # same
    assert psl.rewrite("b*c").unslice() == "a/bbc/d"  # full match, no substitution
    assert psl.rewrite("(b*)(c)", "\\2\\1\\2").unslice() == "a/cbbc/d"  # rewrite
    assert psl.sliceStr == "bbc"  # original slice object still as before
    with pytest.raises(re.error):
        assert psl.rewrite("(b*)c", "\\2")  # invalid capture group

    # rewrite multiple segments
    psl = PathSlice.into("a/b/c/d", 1, 3)
    assert psl.rewrite("([^/]+)/(.+)", "\\2/\\1").unslice() == "a/c/b/d"
    assert psl.rewrite("([^/]+)/(.+)", "").unslice() == "a/d"


def test_type_enum():
    assert TypeEnum.MISSING.is_satisfied(False, False)
    assert TypeEnum.FILE.is_satisfied(True, False)
    assert TypeEnum.DIR.is_satisfied(False, True)
    assert TypeEnum.ANY.is_satisfied(True, False)
    assert TypeEnum.ANY.is_satisfied(False, True)

    assert not TypeEnum.MISSING.is_satisfied(True, False)
    assert not TypeEnum.MISSING.is_satisfied(False, True)
    assert not TypeEnum.FILE.is_satisfied(False, True)
    assert not TypeEnum.DIR.is_satisfied(True, False)
    assert not TypeEnum.ANY.is_satisfied(False, False)


def test_magic():
    """Test magic methods and convenience constructors."""
    # test the DSRule constructor (that dispatch to bool/rule works)
    assert DSRule(True).__root__ == True  # noqa: E712
    assert DSRule(False).__root__ == False  # noqa: E712
    assert DSRule(None).__root__ == Rule.construct()
    assert DSRule(type="file").__root__ == Rule.construct(type=TypeEnum.FILE)
    assert DSRule(
        __root__=Rule.construct(type=TypeEnum.FILE)
    ).__root__ == Rule.construct(type=TypeEnum.FILE)

    # test representation
    assert repr(DSRule(True)) == "true"
    assert repr(DSRule(False)) == "false"
    assert repr(DSRule(None)).strip() == "{}"
    assert repr(DSRule(type="file")).strip() == "{type: file}"

    # special "private" fields that are to be included in serialization
    r = DSRule()
    cast(Rule, r.__root__).__dict__["metaPath"] = "meta"
    cast(Rule, r.__root__).__dict__["rewritePath"] = "test"
    assert repr(r).strip() == "{metaPath: meta, rewritePath: test}"
