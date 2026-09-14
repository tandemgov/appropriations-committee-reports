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


def _raw(v, raw):
    return DollarAmount(value=v, raw_text=raw, in_thousands=True)


def test_words_in_a_value_cell_are_text_in_amount():
    # A Community Project Funding row: project names landed in the value columns, one amount among them.
    line = ComparativeStatementLine(
        report_id="R", congress=118, chamber=Chamber.HOUSE, line_item_text="Environmental Protection Agency",
        prior_year_enacted=_raw(None, "STAG-Clean Water State Revolving Fund"),
        committee_recommendation=_raw(None, "Village of Elbridge for Joint Water System Improvements Project"),
        delta_vs_enacted=_raw(2_250_000_000, "2,250,000"),
    )
    assert _column_layout(line) == "text_in_amount"


def test_designation_words_and_dashes_are_not_text():
    line = _line(pe=100, be=150, cr=120, de=20, dt=-30, text="Operations")
    line.committee_recommendation = _raw(120, "(emergency)")
    assert _column_layout(line) == "standard"


def test_enacted_program_increase_is_adjustment_detail():
    line = _line(cr=10_000, text="Program increase—PFAS remediation")
    line.stage = "enacted"
    assert _column_layout(line) == "adjustment_detail"


def test_committee_program_increase_is_not_flagged():
    assert _column_layout(_line(cr=10_000, text="Program increase—PFAS remediation")) == "standard"


def test_isolation_empties_only_the_untrusted_columns():
    from approps.output.csv_writer import _isolate_nonstandard

    line = _line(pe=649, be=250, cr=899, de=649, dt=250)
    row = {"row_id": "R:00001", "report_id": "R", "line_item_text": "SALT RIVER PROJECT", "column_layout": "category_split",
           "prior_year_enacted": 649, "budget_estimate": 250, "committee_recommendation": 899,
           "delta_vs_enacted": 649, "delta_vs_estimate": 250, "verified": True, "verification_method": "delta_arithmetic",
           "verification_tier": "delta_arithmetic"}
    record = _isolate_nonstandard(line, row)
    assert row["committee_recommendation"] == 899
    assert row["prior_year_enacted"] is None and row["delta_vs_estimate"] is None
    assert (row["verified"], row["verification_tier"]) == (False, "none")
    assert record["prior_year_enacted"] == 649 and record["verification_method"] == "delta_arithmetic"


def test_figure_in_the_label_is_amount_in_label():
    # CRPT-119hrpt652: the enacted amount stayed in the label and the bill and delta slid into prior and recommendation.
    assert _column_layout(_line(pe=850_000, cr=-85_000, text="Aeronautics..... 935,000")) == "amount_in_label"


def test_a_section_number_in_the_label_is_not_an_amount():
    assert _column_layout(_line(pe=100, be=150, cr=120, de=20, dt=-30, text="Operating Expenses (Sec. 130)")) == "standard"


def test_plus_signed_level_is_signed_level():
    # CRPT-119srpt37: "Child nutrition programs 33,250,226 | 36,269,402 | +3,019,176" lost its recommendation and kept the delta in its place.
    line = _line(pe=33_250_226, text="Child nutrition programs")
    line.committee_recommendation = _raw(3_019_176, "+3,019,176")
    assert _column_layout(line) == "signed_level"


def test_plus_in_a_delta_column_is_standard():
    line = _line(pe=100, be=150, cr=120, text="Operations")
    line.delta_vs_enacted = _raw(20, "+20")
    assert _column_layout(line) == "standard"
