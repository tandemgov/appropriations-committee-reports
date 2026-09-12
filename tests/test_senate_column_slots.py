"""Senate value columns are placed by the header's names, not by their order.

FY2026 Senate statements print three columns (prior appropriation, committee recommendation, delta) where earlier years printed five. Read positionally, the recommendation lands in `budget_estimate` and a delta lands in `committee_recommendation`, which string-matching cannot catch because every digit is genuinely on the page.
"""

from __future__ import annotations

from approps.extraction.comparative_senate import _column_slots, _slot_for

W, C = 44, 16  # label width, value column width


def _row(label: str, *values: str) -> str:
    """A fixed-width row: the parser finds columns by where the numbers line up."""
    return label.ljust(W, ".") + "".join(v.rjust(C) for v in values)


def _hdr(*words: str) -> str:
    """One line of a stacked header, each word over its own column."""
    return " " * W + "".join(w.rjust(C) for w in words)


RULE = "-" * 110

FIVE_COL = [
    RULE,
    _hdr("2023", "Budget", "Committee", "Committee", "Committee"),
    _hdr("appropriation", "estimate", "recommendation", "compared with", "compared with"),
    _hdr("", "", "", "2023 approp", "budget estimate"),
    RULE,
    _row("Salaries and Expenses", "10,000", "11,000", "12,000", "+2,000", "+1,000"),
]

_THREE_HEADER = [
    RULE,
    _hdr("2025", "Committee", "compared with"),
    _hdr("appropriation", "recommendation", "(+ or -) 2025"),
    _hdr("", "", "appropriation"),
    RULE,
]

THREE_COL = _THREE_HEADER + [
    _row("Forestry management", "10,381", "9,342", "-1,039"),
    _row("Rangeland management", "107,846", "107,846", "......"),
    _row("Wild horse management", "141,972", "130,972", "-11,000"),
    _row("Cultural resources", "19,225", "15,225", "-4,000"),
    _row("Land acquisition", "25,000", "20,000", "-5,000"),
    _row("Wildlife management", "30,000", "24,000", "-6,000"),
]


def test_delta_column_is_named_not_positional():
    assert _slot_for("Senate Committee recommendation compared with (+ or -) 2025 appropriation") == 3
    assert _slot_for("Committee recommendation") == 2
    assert _slot_for("2025 appropriation") == 0
    assert _slot_for("Budget estimate") == 1


def test_three_column_statement_maps_recommendation_to_its_own_slot():
    slots = _column_slots(THREE_COL, 0)
    assert slots == [0, 2, 3]


def test_five_column_statement_keeps_the_positional_reading():
    # Identity mapping returns None so the existing reader is left completely alone.
    assert _column_slots(FIVE_COL, 0) is None


def test_a_header_reading_the_arithmetic_contradicts_is_refused():
    # Same header, but the deltas no longer equal recommendation minus appropriation, so the
    # mapping is not trusted and the caller falls back.
    broken = _THREE_HEADER + [
        _row("Forestry management", "10,381", "9,342", "-9,999"),
        _row("Wild horse management", "141,972", "130,972", "-7,777"),
        _row("Cultural resources", "19,225", "15,225", "-8,888"),
        _row("Land acquisition", "25,000", "20,000", "-6,666"),
        _row("Wildlife management", "30,000", "24,000", "-5,555"),
        _row("Forest health", "12,000", "9,000", "-4,444"),
    ]
    assert _column_slots(broken, 0) is None
