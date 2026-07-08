"""Parenthesized non-add memos fold into non_add_inferred; rescissions don't."""

from __future__ import annotations

from approps.output.csv_writer import _is_paren_nonadd
from approps.output.schemas import Chamber, ComparativeStatementLine, DollarAmount


def _line(value, raw):
    return ComparativeStatementLine(
        report_id="R", congress=116, chamber=Chamber.HOUSE, line_item_text="transfer authority",
        committee_recommendation=DollarAmount(value=value, raw_text=raw, in_thousands=True),
    )


def test_parenthesized_positive_is_nonadd():
    # "(1,000,000)" parses to +value -> a non-add memo (transfer/limitation/of-which).
    assert _is_paren_nonadd(_line(1_000_000_000, "(1,000,000)")) is True


def test_parenthesized_with_inner_minus_is_a_rescission_not_flagged():
    assert _is_paren_nonadd(_line(-2_491_100_000, "(-2,491,100)")) is False


def test_plain_positive_amount_is_not_nonadd():
    assert _is_paren_nonadd(_line(500_000_000, "500,000")) is False


def test_no_amount_is_not_nonadd():
    line = ComparativeStatementLine(report_id="R", congress=116, chamber=Chamber.HOUSE, line_item_text="x")
    assert _is_paren_nonadd(line) is False
