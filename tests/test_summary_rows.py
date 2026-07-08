"""Flag/drop 302(b) + outlay-projection back-matter, keep real line items."""

from __future__ import annotations

from approps.normalization.summary_rows import drop_summary_rows, summary_flags


def _rows(*texts):
    return [{"line_item_text": t} for t in texts]


def test_flags_the_302b_outlay_block_but_keeps_real_rows():
    # Mirrors the real structure: summary statement -> 302(b)/outlay block -> detailed statement.
    items = _rows(
        "FEMA",                                        # keep (end of summary statement)
        "Comparison of amounts in the bill with the allocations",  # drop (heading)
        "Discretionary",                               # drop
        "Mandatory",                                   # drop
        "Projection of outlays associated with the recommendation",  # drop (heading)
        "2025", "2026", "2029 and future years",       # drop (year rows)
        "DEPARTMENT OF HOMELAND SECURITY",             # keep (detailed statement resumes)
        "Office of the Secretary",                     # keep
    )
    flags = summary_flags(items)
    assert flags == [False, True, True, True, True, True, True, True, False, False]
    kept = [r["line_item_text"] for r in drop_summary_rows(items)]
    assert kept == ["FEMA", "DEPARTMENT OF HOMELAND SECURITY", "Office of the Secretary"]


def test_bare_year_row_is_flagged_anywhere():
    assert summary_flags(_rows("2027")) == [True]
    assert summary_flags(_rows("2029 and future years")) == [True]


def test_real_line_items_are_never_flagged():
    # "Discretionary"/"Mandatory" only drop when adjacent to a summary heading, not on their own.
    items = _rows("Operations and Support", "Discretionary grants to States", "Coast Guard")
    assert summary_flags(items) == [False, False, False]


def test_adjacency_run_stops_at_the_first_real_account():
    items = _rows("Projection of outlays", "2025", "Salaries and Expenses, State")
    assert summary_flags(items) == [True, True, False]
