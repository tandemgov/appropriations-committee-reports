"""A delta read into a level column must send its page to the Gemini fallback.

The row turns unverifiable instead of failing, so the fail-page gate alone let CRPT-119hrpt696 ship deltas in place of its enacted and request amounts.
"""

from __future__ import annotations

from approps.extraction.hybrid import _shifted_column_pages


def _amount(raw: str) -> dict:
    return {"value": None, "raw_text": raw, "in_thousands": True}


def _row(page: int, enacted: str = "", request: str = "", committee: str = "") -> dict:
    return {
        "line_number": page * 100,
        "prior_year_enacted": _amount(enacted),
        "budget_estimate": _amount(request),
        "committee_recommendation": _amount(committee),
    }


def test_plus_signed_request_flags_its_page():
    lines = [_row(364, "15,384,043", "+169,485", "11,903,040"), _row(365, "6,000", "", "6,000")]
    assert _shifted_column_pages(lines) == {364}


def test_plus_signed_enacted_flags_its_page():
    assert _shifted_column_pages([_row(359, "+210,917", "", "2,207,935")]) == {359}


def test_a_rescission_in_a_level_column_is_not_a_shift():
    assert _shifted_column_pages([_row(352, "", "-712,000", "-712,000")]) == set()
