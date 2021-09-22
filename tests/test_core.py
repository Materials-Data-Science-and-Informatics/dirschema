"""Tests for dirschema core."""

from dirschema.core import MetaConvention, Rewrite


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
    """Test rewriting rules for dirschemas."""
    assert Rewrite()("hello") == "hello"
    assert Rewrite()("hello/world") == "hello/world"

    assert Rewrite(sub="\\2")("hello again") == "hello again"
    assert Rewrite(sub="\\1")("hello again") == ""
    assert Rewrite(sub="\\1")("hello/a gain/my friends") == "hello/a gain/"
    assert Rewrite(sub="\\1\\2\\2")("hello w/orld/a b") == "hello w/orld/a ba b"
    assert Rewrite(pat="(hel)(lo)", sub="\\1p \\2\\2")("hello world") == "help lolo"
    assert Rewrite(pat="hello", sub="world")("test") is None

    assert Rewrite(inName=True, sub="a_\\2_b")("") == "a__b"
    assert Rewrite(inName=True, sub="a_\\2_b")("x") == "a_x_b"
    assert Rewrite(inName=True, sub="a_\\2_b")("x/y") == "x/a_y_b"
    assert Rewrite(inName=True, sub="a_\\2_b")("x/y/z") == "x/y/a_z_b"
    assert Rewrite(inName=True, pat="(.*)foo", sub="\\1bar")("x/y/zfoo") == "x/y/zbar"
    assert Rewrite(inName=True, pat="(.*)foo", sub="\\1bar")("x/y/zfo") is None
