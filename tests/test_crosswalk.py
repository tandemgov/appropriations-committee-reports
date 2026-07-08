"""Tests for the authoritative account crosswalk matcher."""

from approps.normalization.crosswalk import match_account


def test_exact_match():
    m = match_account("international disaster assistance", "state foreign ops usaid")
    assert m.account_key == "072-1035"
    assert m.method == "exact"
    assert m.needs_review is False


def test_agency_scoped_disambiguation():
    # "salaries and expenses" matches 130+ accounts; context must pick the right one.
    fbi = match_account("salaries and expenses", "commerce justice science federal bureau of investigation justice")
    assert fbi.account_key == "015-0200"
    assert fbi.method == "agency_scoped"
    assert fbi.needs_review is False


def test_over_merge_guard_distinct_keys():
    # The scoping hazard: textually similar but DIFFERENT accounts must not collapse.
    ctx = "state foreign ops treasury international"
    af_fund = match_account("contribution to the african development fund", ctx)
    as_fund = match_account("contribution to the asian development fund", ctx)
    assert af_fund.account_key and as_fund.account_key
    assert af_fund.account_key != as_fund.account_key


def test_fuzzy_is_suggestion_only():
    # A fuzzy hit may carry a suggested key but must be flagged for review, never trusted.
    m = match_account("asian development bank", "state foreign ops treasury international")
    if m.method == "fuzzy":
        assert m.needs_review is True


def test_unmatched_program_level():
    # A clearly program-level / non-account string resolves to unmatched.
    m = match_account("advanced placement", "labor hhs education")
    assert m.account_key == "" or m.needs_review


def test_empty_is_unmatched():
    m = match_account("", "")
    assert m.method == "unmatched"
