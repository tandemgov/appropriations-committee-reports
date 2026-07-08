"""Tests for the dollar amount parser.

``paren_negative`` is required and has no default, so every test states which source
convention it is exercising. The comparative statements in this corpus are all
``paren_negative=False``; ``memo`` is the alias used below for that reading.
"""

import pytest

from approps.extraction.dollar_parser import parse_dollar


def memo(raw, **kw):
    """Parse under the comparative-statement convention: parentheses mark a non-add memo."""
    return parse_dollar(raw, paren_negative=False, **kw)


def accounting(raw, **kw):
    """Parse under the accounting convention: parentheses mean negative."""
    return parse_dollar(raw, paren_negative=True, **kw)


def test_basic_amount():
    result = memo("$1,368,969,000")
    assert result.value == 1_368_969_000
    assert result.raw_text == "$1,368,969,000"


def test_amount_without_dollar_sign():
    assert memo("1,497,069,000").value == 1_497_069_000


def test_amount_with_leading_spaces():
    assert memo("       358,466,000").value == 358_466_000


def test_negative_with_sign():
    assert memo("-123,337,000").value == -123_337_000


def test_positive_with_sign():
    assert memo("+46,900").value == 46_900


def test_the_parenthesis_convention_must_be_stated_by_the_caller():
    """The bug this guards: a default here is a silent claim about a document nobody read."""
    with pytest.raises(TypeError):
        parse_dollar("(500,000)")  # type: ignore[call-arg]


def test_parentheses_are_a_non_add_memo_in_comparative_statements():
    assert memo("(500,000)").value == 500_000
    assert memo("(34,000)", in_thousands=True).value == 34_000_000
    assert memo("(+35,000)").value == 35_000


def test_parentheses_are_negative_under_the_accounting_convention():
    assert accounting("(500,000)").value == -500_000
    assert accounting("(34,000)", in_thousands=True).value == -34_000_000


def test_an_explicit_minus_is_negative_under_either_convention():
    """Rescissions and offsetting collections print their own sign, so the convention
    never decides them. `(-2,491)` and `-2,000` are negative both ways."""
    for parse in (memo, accounting):
        assert parse("(-2,491)").value == -2_491
        assert parse("-2,000").value == -2_000


def test_dash_zero():
    assert memo("---").value is None


def test_spaced_dashes():
    assert memo("- - -").value is None


def test_dot_leader_zero():
    assert memo("................").value is None


def test_empty_string():
    assert memo("").value is None


def test_in_thousands():
    assert memo("112,340", in_thousands=True).value == 112_340_000


def test_in_thousands_with_dollar():
    assert memo("$190,193,000", in_thousands=False).value == 190_193_000


def test_small_amount():
    assert memo("150").value == 150


def test_preserves_raw_text():
    raw = "   $1,234,567   "
    result = memo(raw)
    assert result.raw_text == raw
    assert result.value == 1_234_567


def test_negative_delta():
    assert memo("-2,812", in_thousands=True).value == -2_812_000


def test_positive_delta():
    assert memo("+1,000", in_thousands=True).value == 1_000_000
