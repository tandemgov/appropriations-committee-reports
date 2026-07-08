"""Tests for the enacted-stage explanatory-statement extractor helpers."""

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
