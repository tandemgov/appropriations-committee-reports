"""The magnitude tripwire: catch a units bug that arithmetic verification structurally cannot.

Every internal-consistency gate is scale-invariant, so a uniform rescale passes them all. See
approps.verification.magnitude and docs/KNOWN_ISSUES.md #4.
"""

from __future__ import annotations

from approps.output.schemas import (
    Chamber,
    ComparativeStatementLine,
    DollarAmount,
    Stage,
)
from approps.verification.magnitude import (
    LINE_ITEM_CEILING,
    oversized_line_items,
)


def _line(amount: int | None, text: str = "Total", **kw) -> ComparativeStatementLine:
    return ComparativeStatementLine(
        report_id=kw.get("report_id", "CPRT-118HPRT56550"),
        congress=118,
        chamber=Chamber.HOUSE,
        fiscal_year=2024,
        stage=Stage.ENACTED,
        line_item_text=text,
        committee_recommendation=(
            None if amount is None else DollarAmount(value=amount, raw_text=f"{amount:,}")
        ),
    )


def test_flags_the_regression_that_started_this():
    """CPRT-118HPRT56550 'Total' was stored as $32.4 trillion — 1000x its true value."""
    findings = oversized_line_items([_line(32_386_831_000_000)])

    assert len(findings) == 1
    assert findings[0].amount == 32_386_831_000_000
    assert "ceiling" in findings[0].reason


def test_passes_the_true_value_of_that_same_line():
    assert oversized_line_items([_line(32_386_831_000)]) == []


def test_passes_the_largest_legitimate_line_in_the_corpus():
    """A real House 'Grand Total' row reaches $1.7T and must not trip the wire."""
    assert oversized_line_items([_line(1_700_604_977_000, "Grand Total")]) == []


def test_flags_negative_amounts_too():
    """A rescaled rescission is just as wrong. Magnitude, not sign."""
    findings = oversized_line_items([_line(-32_386_831_000_000, "Rescission")])

    assert len(findings) == 1


def test_ignores_lines_with_no_amount():
    assert oversized_line_items([_line(None, "TITLE I—HEADING")]) == []


def test_one_finding_per_line_not_per_column():
    line = _line(32_386_831_000_000)
    line.prior_year_enacted = DollarAmount(value=28_000_000_000_000, raw_text="28,000,000,000")

    assert len(oversized_line_items([line])) == 1


def test_ceiling_is_configurable():
    assert oversized_line_items([_line(5_000_000_000)], ceiling=1_000_000_000)
    assert oversized_line_items([_line(5_000_000_000)], ceiling=10_000_000_000) == []


def test_ceiling_sits_between_real_data_and_the_bug():
    """Pin the two numbers the ceiling has to separate."""
    largest_real = 1_700_604_977_000
    smallest_bug = 3_191_250_000_000  # 'Total, All Activities', 1000x-scaled

    assert largest_real < LINE_ITEM_CEILING < smallest_bug


def test_blind_spot_is_documented_behavior():
    """A 1000x rescale of a SMALL line slips under the ceiling. Known, and why the real fix
    is requiring positive evidence to scale in the extractor, not this backstop."""
    assert oversized_line_items([_line(5_250_000_000)]) == []  # $5.25M line, 1000x-scaled
