"""Tests for the over-determined recommendation repair."""

from approps.verification.repair import repair_recommendation


def _amt(v):
    return {"value": v, "raw_text": str(v), "in_thousands": False}


def test_recovers_blank_from_single_derivation():
    # rec blank, only prior + delta_enacted available -> recover prior+delta.
    item = {"prior_year_enacted": _amt(994000), "delta_vs_enacted": _amt(-994000),
            "committee_recommendation": None}
    assert repair_recommendation(item) == "recovered"
    assert item["committee_recommendation"]["value"] == 0
    assert item["committee_recommendation"]["recovered"] is True


def test_recovers_blank_when_both_derivations_agree():
    item = {"prior_year_enacted": _amt(100), "delta_vs_enacted": _amt(20),
            "budget_estimate": _amt(110), "delta_vs_estimate": _amt(10),
            "committee_recommendation": None}
    assert repair_recommendation(item) == "recovered"
    assert item["committee_recommendation"]["value"] == 120


def test_does_not_recover_when_derivations_disagree():
    item = {"prior_year_enacted": _amt(100), "delta_vs_enacted": _amt(20),
            "budget_estimate": _amt(110), "delta_vs_estimate": _amt(5),
            "committee_recommendation": None}
    assert repair_recommendation(item) is None
    assert item["committee_recommendation"] is None


def test_corrects_only_when_overdetermined_and_agree():
    # both derivations agree on 120 but the stored value is 999 -> correct.
    item = {"prior_year_enacted": _amt(100), "delta_vs_enacted": _amt(20),
            "budget_estimate": _amt(110), "delta_vs_estimate": _amt(10),
            "committee_recommendation": _amt(999)}
    assert repair_recommendation(item) == "corrected"
    assert item["committee_recommendation"]["value"] == 120
    assert item["committee_recommendation"]["corrected_from"] == 999


def test_does_not_correct_on_single_derivation():
    # only one derivation available, stored value differs -> leave it (not safe).
    item = {"prior_year_enacted": _amt(100), "delta_vs_enacted": _amt(20),
            "committee_recommendation": _amt(999)}
    assert repair_recommendation(item) is None
    assert item["committee_recommendation"]["value"] == 999


def test_noop_when_consistent():
    item = {"prior_year_enacted": _amt(100), "delta_vs_enacted": _amt(20),
            "budget_estimate": _amt(110), "delta_vs_estimate": _amt(10),
            "committee_recommendation": _amt(120)}
    assert repair_recommendation(item) is None


def test_noop_without_derivations():
    item = {"committee_recommendation": None, "prior_year_enacted": _amt(100)}
    assert repair_recommendation(item) is None
