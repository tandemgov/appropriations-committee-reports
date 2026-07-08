"""Tests for the dollar amount parser."""

from approps.extraction.dollar_parser import parse_dollar


def test_basic_amount():
    result = parse_dollar("$1,368,969,000")
    assert result.value == 1_368_969_000
    assert result.raw_text == "$1,368,969,000"


def test_amount_without_dollar_sign():
    result = parse_dollar("1,497,069,000")
    assert result.value == 1_497_069_000


def test_amount_with_leading_spaces():
    result = parse_dollar("       358,466,000")
    assert result.value == 358_466_000


def test_negative_with_sign():
    result = parse_dollar("-123,337,000")
    assert result.value == -123_337_000


def test_positive_with_sign():
    result = parse_dollar("+46,900")
    assert result.value == 46_900


def test_parenthesized_negative():
    result = parse_dollar("(500,000)")
    assert result.value == -500_000


def test_parenthesized_in_thousands():
    result = parse_dollar("(34,000)", in_thousands=True)
    assert result.value == -34_000_000


def test_dash_zero():
    result = parse_dollar("---")
    assert result.value is None


def test_spaced_dashes():
    result = parse_dollar("- - -")
    assert result.value is None


def test_dot_leader_zero():
    result = parse_dollar("................")
    assert result.value is None


def test_empty_string():
    result = parse_dollar("")
    assert result.value is None


def test_in_thousands():
    result = parse_dollar("112,340", in_thousands=True)
    assert result.value == 112_340_000


def test_in_thousands_with_dollar():
    result = parse_dollar("$190,193,000", in_thousands=False)
    assert result.value == 190_193_000


def test_small_amount():
    result = parse_dollar("150")
    assert result.value == 150


def test_preserves_raw_text():
    raw = "   $1,234,567   "
    result = parse_dollar(raw)
    assert result.raw_text == raw
    assert result.value == 1_234_567


def test_negative_delta():
    result = parse_dollar("-2,812", in_thousands=True)
    assert result.value == -2_812_000


def test_positive_delta():
    result = parse_dollar("+1,000", in_thousands=True)
    assert result.value == 1_000_000
