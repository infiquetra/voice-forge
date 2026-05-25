"""Tests for the Kokoro voice-mixing spec parser."""

from __future__ import annotations

import pytest

from voice_forge.backends._mixing import parse_mix


def test_bare_name_implicit_weight_one():
    assert parse_mix("af_bella") == [("af_bella", 1.0)]


def test_explicit_weight_integer():
    assert parse_mix("af_bella(2)") == [("af_bella", 2.0)]


def test_explicit_weight_decimal():
    assert parse_mix("af_bella(0.5)") == [("af_bella", 0.5)]


def test_two_voice_mix_no_weights():
    assert parse_mix("af_bella+af_sky") == [("af_bella", 1.0), ("af_sky", 1.0)]


def test_three_voice_weighted_mix():
    assert parse_mix("af_bella(2)+af_sky(1)+am_adam(0.5)") == [
        ("af_bella", 2.0),
        ("af_sky", 1.0),
        ("am_adam", 0.5),
    ]


def test_mixed_bare_and_weighted():
    assert parse_mix("af_bella(3)+af_sky") == [
        ("af_bella", 3.0),
        ("af_sky", 1.0),
    ]


def test_whitespace_around_plus_tolerated():
    assert parse_mix("af_bella(2) + af_sky") == [
        ("af_bella", 2.0),
        ("af_sky", 1.0),
    ]


def test_leading_trailing_whitespace_stripped():
    assert parse_mix("  af_bella  ") == [("af_bella", 1.0)]


def test_hyphen_in_voice_name():
    # Some preset libraries use hyphens; the regex accepts a-zA-Z0-9_-
    assert parse_mix("british-female-1") == [("british-female-1", 1.0)]


def test_empty_spec_raises():
    with pytest.raises(ValueError, match="empty"):
        parse_mix("")
    with pytest.raises(ValueError, match="empty"):
        parse_mix("   ")


def test_empty_token_in_mix_raises():
    with pytest.raises(ValueError, match="empty token"):
        parse_mix("af_bella+")
    with pytest.raises(ValueError, match="empty token"):
        parse_mix("+af_sky")


def test_unbalanced_paren_raises():
    with pytest.raises(ValueError, match="unparseable"):
        parse_mix("af_bella(2")


def test_non_numeric_weight_raises():
    with pytest.raises(ValueError, match="unparseable"):
        parse_mix("af_bella(two)")


def test_negative_weight_raises():
    # Regex won't match a leading '-' on the weight, so this surfaces as
    # an unparseable token rather than a "must be non-negative" message —
    # either way, we reject it.
    with pytest.raises(ValueError):
        parse_mix("af_bella(-1)")


def test_special_characters_in_name_raise():
    with pytest.raises(ValueError, match="unparseable"):
        parse_mix("af bella")  # space inside name
    with pytest.raises(ValueError, match="unparseable"):
        parse_mix("af_bella!")
