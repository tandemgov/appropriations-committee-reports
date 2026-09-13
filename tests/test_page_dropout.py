"""A page whose table is dropped whole must still reach the Gemini fallback.

CRPT-118hrpt557 lost its Title III Procurement block this way, unflagged, and reconciliation still scored it 18 of 21 totals OK.
"""

from __future__ import annotations

from approps.extraction.hybrid import _statement_edge_pages, _statement_gap_pages
from approps.extraction.nemotron_parse import _money_dense_tabular

# Title III as it actually appears, with the header garbled the way the scan garbled it.
MONEY_TABLE = (
    r"\begin{tabular}{cccccc}"
    "\n & **Smudged** & **Illegible** & **Gone** & **Blurred** & **Lost**\\\\"
    "\nAircraft Procurement, Army..... & 3,207,997 & 3,764,195 & 3,518,727 & +310,730 & -245,468\\\\"
    "\nMissile Procurement, Army..... & 4,022,213 & 5,246,770 & 5,175,564 & +1,153,351 & -71,206\\\\"
    "\nWeapons Procurement, Navy..... & 5,870,628 & 5,000,327 & 6,049,295 & +178,667 & -551,232\\\\"
    "\nOther Procurement, Army..... & 8,026,297 & 9,516,524 & 8,490,205 & +463,908 & -1,026,319\\\\"
    r"\end{tabular}"
)

# One stray money row is not a statement page; only a dense table earns a Gemini call.
SMALL_MONEY_TABLE = (
    r"\begin{tabular}{cc}"
    "\nTotal available..... & 1,720,550\\\\"
    "\nPrior year..... & 1,786,779\\\\"
    r"\end{tabular}"
)

PROSE_TABLE = (
    r"\begin{tabular}{cc}"
    "\nMr. Aderholt & Mr. Aguilar\\\\"
    "\nMrs. Bice & Mr. Bishop\\\\"
    r"\end{tabular}"
)


def _line(page: int) -> dict:
    return {"line_number": page * 100}


def test_money_table_is_ambiguous_not_ignorable():
    assert _money_dense_tabular(MONEY_TABLE)


def test_vote_roster_is_not_a_money_table():
    assert not _money_dense_tabular(PROSE_TABLE)


def test_a_stray_small_money_table_is_below_the_bar():
    assert not _money_dense_tabular(SMALL_MONEY_TABLE)


def test_gap_inside_a_statement_run_is_flagged():
    lines = [_line(p) for p in (294, 299, 301, 302, 303)]
    gaps = _statement_gap_pages(lines, image_pages=list(range(285, 308)))
    assert gaps == {295, 296, 297, 298, 300}


def test_pages_outside_any_run_are_left_alone():
    # A lone early table is not a statement, so nothing between it and the real one is escalated.
    lines = [_line(p) for p in (10, 294, 295, 296)]
    assert _statement_gap_pages(lines, image_pages=list(range(9, 300))) == set()


def test_a_run_needs_three_pages_before_it_asserts_anything():
    lines = [_line(p) for p in (294, 297)]
    assert _statement_gap_pages(lines, image_pages=list(range(290, 300))) == set()


def test_non_image_pages_are_never_escalated():
    lines = [_line(p) for p in (294, 296, 298)]
    # Only 295 is an image page; 297 is text and cannot be sent to a vision fallback.
    assert _statement_gap_pages(lines, image_pages=[293, 294, 295, 297]) == {295}


def test_dropped_first_and_last_pages_of_a_statement_are_flagged():
    # CRPT-119hrpt696: the opening page and the Grand Total page produced no rows.
    lines = [_line(p) for p in (351, 352, 353, 354)]
    assert _statement_edge_pages(lines, image_pages=list(range(339, 360))) == {350, 355}


def test_edge_pages_that_are_text_are_never_escalated():
    lines = [_line(p) for p in (351, 352, 353)]
    assert _statement_edge_pages(lines, image_pages=[349, 350, 351, 352]) == {350}


def test_a_short_run_has_no_edges():
    lines = [_line(p) for p in (351, 352)]
    assert _statement_edge_pages(lines, image_pages=list(range(339, 360))) == set()
