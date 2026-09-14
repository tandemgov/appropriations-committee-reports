"""Senate rows whose leading columns are blank keep every value in its own column.

A label long enough to reach the value columns prints no dot leader, so the first dot run on the line is a blank column's placeholder.
The dot-leader reader split there, swallowed that column, and slid every value one slot left: `.... | .... | 505,000 | +505,000 | +505,000` became request 505,000, recommendation 505,000, delta 505,000.
Found by the bounded accuracy review in CRPT-114srpt79 and CRPT-114srpt243.
"""

from __future__ import annotations

from approps.extraction.comparative_senate import extract_senate_comparative

W, C = 60, 18
RULE = "-" * 160


def _hdr(*words: str) -> str:
    return " " * W + "".join(w.rjust(C) for w in words)


def _row(label: str, *values: str, leader: bool = True) -> str:
    head = label.ljust(W, ".") if leader else label.ljust(W)
    return head + "".join(v.rjust(C) for v in values)


def _dots() -> str:
    return "." * 14


def _statement(header: list[str], rows: list[str]) -> str:
    lines = [
        "   COMPARATIVE STATEMENT OF NEW BUDGET (OBLIGATIONAL) AUTHORITY FOR FISCAL YEAR 2016",
        "                            [In thousands of dollars]",
        RULE, *header, RULE, *rows,
    ]
    return "<pre>" + "\n".join(lines) + "</pre>"


FIVE = [
    _hdr("2015", "Budget", "Committee", "Committee rec", "Committee rec"),
    _hdr("appropriation", "estimate", "recommendation", "compared with", "compared with"),
    _hdr("", "", "", "2015 approp", "budget estimate"),
]


def _vals(row):
    return tuple(
        getattr(row, k).value if getattr(row, k) is not None else None
        for k in ("prior_year_enacted", "budget_estimate", "committee_recommendation", "delta_vs_enacted", "delta_vs_estimate")
    )


def test_blank_leading_columns_do_not_shift_values_left():
    rows = [
        _row("Diplomatic programs", "1,000", "1,200", "1,100", "+100", "-100"),
        _row("Consular programs", "2,000", "2,300", "2,100", "+100", "-200"),
        _row("Contributions for International Peacekeeping Activities,", _dots(), _dots(), "505,000", "+505,000", "+505,000", leader=False),
        _row("Educational exchanges", "3,000", "3,100", "3,050", "+50", "-50"),
    ]
    out = extract_senate_comparative(_statement(FIVE, rows), "TEST-1", 114, 2016, "State-Foreign-Ops")
    peace = next(r for r in out if r.line_item_text.startswith("Contributions"))
    assert _vals(peace) == (None, None, 505_000_000, 505_000_000, 505_000_000)


def test_ordinary_dot_leader_rows_are_unchanged():
    rows = [
        _row("Diplomatic programs", "1,000", "1,200", "1,100", "+100", "-100"),
        _row("New initiative", _dots(), "4,000", "4,000", "+4,000", _dots()),
    ]
    out = extract_senate_comparative(_statement(FIVE, rows), "TEST-2", 114, 2016, "State-Foreign-Ops")
    assert _vals(out[0]) == (1_000_000, 1_200_000, 1_100_000, 100_000, -100_000)
    assert _vals(out[1])[1:4] == (4_000_000, 4_000_000, 4_000_000)


THREE = [
    _hdr("", "", "Committee rec"),
    _hdr("2025", "Committee", "compared with"),
    _hdr("appropriation", "recommendation", "2025 approp"),
]


def test_uncounted_delta_column_does_not_overwrite_the_recommendation():
    # CRPT-119srpt37: the delta column is mostly dot runs, so the header reading names two columns and the third token fell back onto the recommendation.
    rows = [
        _row("Office of the Secretary", "7,000", "7,000", _dots()),
        _row("Office of Tribal Relations", "5,190", "5,190", _dots()),
        _row("Departmental Administration", "23,500", "20,000", "-3,500"),
        _row("Child nutrition programs", "33,250,226", "36,269,402", "+3,019,176"),
        _row("Farm to School", "5,000", "5,000", _dots()),
        _row("Office of Budget", "12,500", "12,500", _dots()),
        _row("Office of the Chief Economist", "30,000", "30,000", _dots()),
    ]
    out = extract_senate_comparative(_statement(THREE, rows), "TEST-4", 119, 2026, "Agriculture")
    got = {r.line_item_text: r.committee_recommendation.value if r.committee_recommendation else None for r in out}
    assert got["Office of the Secretary"] == 7_000_000
    assert got["Child nutrition programs"] == 36_269_402_000
    assert all(r.prior_year_enacted is not None for r in out)
