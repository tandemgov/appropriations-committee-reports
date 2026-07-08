"""Tests for the enacted-stage explanatory-statement extractor helpers."""

import pytest

from approps.extraction.comparative_enacted import (
    _caps_fraction,
    _norm_nums,
    _to_dollars,
)


def test_to_dollars_in_thousands():
    # JES tables are "(In thousands of dollars)": 104,102 -> $104,102,000.
    assert _to_dollars("104,102", in_thousands=True) == 104_102_000
    assert _to_dollars("$39,183", in_thousands=True) == 39_183_000


def test_to_dollars_whole():
    assert _to_dollars("1,396", in_thousands=False) == 1_396


def test_to_dollars_rejects_nonnumeric():
    assert _to_dollars("n/a", in_thousands=True) is None


def test_norm_nums_repairs_ocr_split():
    # pdfplumber sometimes splits comma groups: "134 ,529" must become "134,529".
    assert _norm_nums("OPERATIONAL TEST 119,529 134 ,529") == "OPERATIONAL TEST 119,529 134,529"
    assert _norm_nums("1, 396") == "1,396"


def test_caps_fraction_distinguishes_account_from_delta():
    # ALL-CAPS account rows vs lowercase "program increase" delta rows.
    assert _caps_fraction("OPERATIONAL TEST AND EVALUATION") == 1.0
    assert _caps_fraction("Program increase—red team automation") < 0.3
    assert _caps_fraction("") == 0.0


# --- Page scale: thousands requires positive evidence (docs/KNOWN_ISSUES.md #4) -------------
#
# The CPRT explanatory-statement prints publish most tables in whole dollars and mark the
# thousands ones with a repeated column header. The extractor once defaulted to thousands and
# multiplied every unmarked amount by 1,000 — all 11,829 enacted rows. Nothing caught it,
# because the delta identity survives a uniform rescale. These pin the default.

from approps.extraction.comparative_enacted import (  # noqa: E402
    _is_thousands_marker,
    extract_enacted_pages,
)

_MARKER = "[Budget authority in thousands of dollars]"


def _amount_of(page_text: str) -> int | None:
    lines = extract_enacted_pages([page_text], "TEST", 118, 2024)
    assert len(lines) == 1, f"expected one line, got {len(lines)}"
    return lines[0].committee_recommendation.value


def test_unmarked_page_is_whole_dollars():
    page = "Fulbright Program ...................... $5,250,000\n"
    assert _amount_of(page) == 5_250_000


def test_marked_page_scales_by_thousand():
    page = f"{_MARKER}\nFulbright Program ...................... 5,250\n"
    assert _amount_of(page) == 5_250_000


def test_same_real_amount_either_notation():
    """$5,250,000 in dollars and 5,250 under a thousands header are the same money."""
    unmarked = "Fulbright Program ...................... $5,250,000\n"
    marked = f"{_MARKER}\nFulbright Program ...................... 5,250\n"
    assert _amount_of(unmarked) == _amount_of(marked)


def test_scale_does_not_leak_across_pages():
    """A thousands header on one page must not scale the next, unmarked page."""
    marked = f"{_MARKER}\nAlpha Program ...................... 1,000\n"
    unmarked = "Beta Program ...................... $2,000,000\n"
    lines = extract_enacted_pages([marked, unmarked], "TEST", 118, 2024)
    by_label = {ln.line_item_text: ln for ln in lines}
    assert by_label["Alpha Program"].committee_recommendation.value == 1_000_000
    assert by_label["Beta Program"].committee_recommendation.value == 2_000_000


def test_division_total_is_not_trillions():
    """The regression that surfaced the bug: a division total read as $32.4 trillion."""
    page = "Total ...................... 32,386,831,000\n"
    assert _amount_of(page) == 32_386_831_000


# Every spelling that appears across the 16 CPRT prints. The original regex matched only the
# "in thousands of dollars" family; "[Dollars in Thousands]" tables went unrecognized, which the
# thousands-by-default behavior hid until the default was corrected.
@pytest.mark.parametrize(
    "header",
    [
        "[Budget authority in thousands of dollars]",
        "(Budget authority in thousands of dollars)",
        "[In thousands of dollars]",
        "(In thousands of dollars)",
        "[in thousands of dollars]",
        "(in thousands of dollars)",
        "[Dollars in Thousands]",
        "(Dollars in Thousands)",
        "[Dollars in thousands]",
        "(Dollars in thousands)",
        "(dollars in thousands)",
        "[$ in thousands]",
        "($ in thousands)",
        "(Amounts in thousands)",
        "(Budget authority in thousands of dollars]",  # mismatched bracket, real occurrence
        "(In thousands of dollars) 1Program",  # trailing footnote marker, real occurrence
    ],
)
def test_thousands_marker_recognizes_every_real_header(header):
    assert _is_thousands_marker(header)


@pytest.mark.parametrize(
    "not_a_header",
    [
        "thousands);",  # fragment of a wrapped sentence
        "(6) Budget year dollars in thousands",  # enumerated legend, not a units header
        "(5) Current year dollars in thousands",
        "(Dollars)",  # explicitly whole dollars
        "d. dollar value of cargo handled;",
        # A narrative sentence mentioning the phrase is not a column header.
        "The agreement provides that amounts in the following table are displayed "
        "in thousands of dollars for the convenience of the reader.",
    ],
)
def test_thousands_marker_rejects_lookalikes(not_a_header):
    assert not _is_thousands_marker(not_a_header)


def test_dollars_in_thousands_header_scales():
    """The spelling the original regex missed — the USDA 'Office of the Secretary' tables.

    Real values: Office of Homeland Security is a $1.496M account, printed as `1,496`.
    """
    page = "[Dollars in Thousands]\nOffice of Homeland Security ............ 1,496\n"
    assert _amount_of(page) == 1_496_000
