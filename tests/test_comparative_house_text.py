"""Tests for the born-digital (typeset) House text extractor helpers."""

from approps.extraction.comparative_house_text import (
    _account_name,
    _norm,
    _parse_recap,
    _to_int,
    _trailing_amounts,
    reconcile,
)


def test_norm_maps_gpo_minus_glyphs():
    # GPO substitutes a yen sign / slashed-O for a leading minus.
    assert _norm("Contract award delay ¥6,820") == "Contract award delay -6,820"
    assert _norm("AIR EXPENDABLE COUNTERMEASURES 121,059 110,798 Ø10,261") == (
        "AIR EXPENDABLE COUNTERMEASURES 121,059 110,798 -10,261"
    )


def test_trailing_amounts_three_columns():
    text, amts = _trailing_amounts("12 CH-47 HELICOPTER 210,645 666,645 456,000")
    assert text == "12 CH-47 HELICOPTER"
    assert amts == ["210,645", "666,645", "456,000"]


def test_trailing_amounts_ignores_numbers_inside_item_name():
    # "5 INCH/54" embeds digits, but only the trailing run is the columns.
    text, amts = _trailing_amounts("9 5 INCH/54 GUN AMMUNITION 44,136 28,627 -15,509")
    assert text == "9 5 INCH/54 GUN AMMUNITION"
    assert amts == ["44,136", "28,627", "-15,509"]


def test_trailing_amounts_two_column_offset():
    text, amts = _trailing_amounts("HISTORICAL UNOBLIGATED BALANCES -239,000 -239,000")
    assert text == "HISTORICAL UNOBLIGATED BALANCES"
    assert amts == ["-239,000", "-239,000"]


def test_to_int_handles_signs_and_blanks():
    assert _to_int("210,645") == 210_645
    assert _to_int("-15,509") == -15_509
    assert _to_int("..........") is None


def test_account_name_joins_comma_wrapped_heading():
    # RDT&E headings wrap; a trailing comma marks the continuation.
    lines = [
        (1, "RESEARCH, DEVELOPMENT, TEST AND EVALUATION,"),
        (1, "ARMY"),
        (1, "The Committee recommends the following appropriations for Re-"),
    ]
    assert _account_name(lines, 2) == "RESEARCH, DEVELOPMENT, TEST AND EVALUATION, ARMY"


def test_account_name_does_not_absorb_prior_total_fragment():
    # The previous account's TOTAL wraps ("...NAVY AND MARINE" + "CORPS"); the new
    # heading must not pick up that fragment (no trailing comma to continue).
    lines = [
        (1, "TOTAL, PROCUREMENT OF AMMUNITION, NAVY AND MARINE"),
        (1, "CORPS"),
        (1, "SHIPBUILDING AND CONVERSION, NAVY"),
        (1, "The Committee recommends the following appropriations for"),
    ]
    assert _account_name(lines, 3) == "SHIPBUILDING AND CONVERSION, NAVY"


def test_reconcile_leaf():
    ledger = [
        {"kind": "value", "req": 10, "rec": 10},
        {"kind": "value", "req": 5, "rec": 5},
        {"kind": "total", "label": "TOTAL, X", "account": "X", "req": 15, "rec": 15},
    ]
    r = reconcile(ledger)
    assert (r["leaf"], r["rollup"], r["bad"]) == (1, 0, 0)


def test_reconcile_rollup_handles_nested_grand_total():
    # Personnel/DHP pattern: a leaf subtotal, then more items, then a grand total
    # that equals the prior subtotal plus the new items.
    ledger = [
        {"kind": "value", "req": 10, "rec": 10},
        {"kind": "total", "label": "TOTAL, TITLE I, X", "account": "X", "req": 10, "rec": 10},
        {"kind": "value", "req": 4, "rec": 4},
        {"kind": "total", "label": "TOTAL, X", "account": "X", "req": 14, "rec": 14},
    ]
    r = reconcile(ledger)
    assert (r["leaf"], r["rollup"], r["bad"]) == (1, 1, 0)


def test_parse_recap_titles_grand_and_dedup():
    # Title VIII has a blank request (2 amounts); the recap is reprinted -> dedup;
    # the grand total's change column is dots, so numbers aren't trailing.
    lines = [
        (2, "Title I—Military Personnel...................... 205,121,200 204,152,890 -968,310"),
        (2, "Title VIII—General Provisions.................. 12,859,835 +12,859,835"),
        (2, "Total, Department of Defense........ 1,072,683,299 1,072,683,299 ........."),
        (9, "Title I—Military Personnel...................... 205,121,200 204,152,890 -968,310"),
    ]
    recap = _parse_recap(lines)
    assert [r["name"] for r in recap] == [
        "Title I—Military Personnel", "Title VIII—General Provisions",
        "Total, Department of Defense"]  # deduped
    assert recap[0]["req"] == 205121200 and recap[0]["rec"] == 204152890
    assert recap[1]["req"] is None and recap[1]["rec"] == 12859835  # blank request
    assert recap[2]["rec"] == 1072683299


def test_reconcile_flags_real_mismatch():
    ledger = [
        {"kind": "value", "req": 10, "rec": 10},
        {"kind": "total", "label": "TOTAL, X", "account": "X", "req": 99, "rec": 99},
    ]
    r = reconcile(ledger)
    assert r["bad"] == 1
    assert r["mismatches"][0]["account"] == "X"
