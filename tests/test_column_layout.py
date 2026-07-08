"""Flag category-split tables mis-mapped into the standard comparative schema."""

from __future__ import annotations

from approps.output.csv_writer import _column_layout
from approps.output.schemas import Chamber, ComparativeStatementLine, DollarAmount


def _amt(v):
    return DollarAmount(value=v, raw_text=str(v), in_thousands=True)


def _line(pe=None, be=None, cr=None, de=None, dt=None, text="SALT RIVER PROJECT"):
    return ComparativeStatementLine(
        report_id="R", congress=114, chamber=Chamber.HOUSE, line_item_text=text,
        prior_year_enacted=_amt(pe) if pe is not None else None,
        budget_estimate=_amt(be) if be is not None else None,
        committee_recommendation=_amt(cr) if cr is not None else None,
        delta_vs_enacted=_amt(de) if de is not None else None,
        delta_vs_estimate=_amt(dt) if dt is not None else None,
    )


def test_category_split_signature_flagged():
    # 649 + 250 = 899, and the deltas echo the two category columns.
    assert _column_layout(_line(pe=649, be=250, cr=899, de=649, dt=250)) == "category_split"


def test_normal_comparative_row_is_standard():
    # prior=100, request=150, rec=120: deltas are real (120-100=20, 120-150=-30).
    assert _column_layout(_line(pe=100, be=150, cr=120, de=20, dt=-30)) == "standard"


def test_coincidental_sum_without_delta_echo_is_standard():
    # prior+request happens to equal rec, but the deltas are real -> not category-split.
    assert _column_layout(_line(pe=100, be=50, cr=150, de=50, dt=100)) == "standard"


def test_missing_columns_is_standard():
    assert _column_layout(_line(cr=899)) == "standard"


def test_bare_procurement_number_label_is_flagged():
    assert _column_layout(_line(be=12938, de=12338, text="30")) == "procurement_qty"


def test_real_named_row_is_not_procurement_qty():
    assert _column_layout(_line(pe=100, be=150, cr=120, de=20, dt=-30, text="Aircraft Procurement, Army")) == "standard"
