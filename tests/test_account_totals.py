"""Account totals come from the lines the source presents as the account, or not at all."""

import pytest

from approps.normalization.account_totals import account_series, account_totals


def _row(**kw):
    base = {
        "row_id": "R1:00001", "report_id": "R1", "fiscal_year": 2020, "chamber": "senate", "stage": "committee",
        "subcommittee": "Interior-Environment", "account_key": "014-1036",
        "account_key_title": "Operation of the National Park System, National Park Service, Interior",
        "line_item_text": "Operation of the National Park System", "designation": "base",
        "is_subtotal": False, "is_memo": False, "column_layout": "standard", "verification_tier": "string_match",
        "prior_year_enacted": 900, "budget_estimate": 1100, "committee_recommendation": 1000,
    }
    base.update(kw)
    return base


def test_single_keyed_line_is_the_total():
    [t] = account_totals([_row()])
    assert (t.method, t.committee_recommendation, t.verified_lines) == ("single_line", 1000, 1)


def test_account_line_wins_over_its_breakdown_and_nothing_is_double_counted():
    rows = [
        _row(row_id="R1:1"),
        _row(row_id="R1:2", line_item_text="Park management", committee_recommendation=700, prior_year_enacted=600, budget_estimate=800),
        _row(row_id="R1:3", line_item_text="Park support", committee_recommendation=300, prior_year_enacted=300, budget_estimate=300),
    ]
    [t] = account_totals(rows)
    assert (t.method, t.committee_recommendation, t.row_ids) == ("account_line", 1000, ["R1:1"])


def test_largest_breakdown_line_is_not_promoted_to_a_total():
    rows = [
        _row(row_id="R1:2", line_item_text="Park management", committee_recommendation=700),
        _row(row_id="R1:3", line_item_text="Park support", committee_recommendation=300),
    ]
    [t] = account_totals(rows)
    assert (t.method, t.committee_recommendation, t.n_lines) == ("unresolved", None, 2)


def test_designations_of_the_account_line_are_summed_and_listed():
    rows = [
        _row(row_id="R1:1"),
        _row(row_id="R1:2", line_item_text="Operation of the National Park System (emergency)", designation="emergency", committee_recommendation=50),
        _row(row_id="R1:3", line_item_text="Park support", committee_recommendation=300),
    ]
    [t] = account_totals(rows)
    assert (t.committee_recommendation, t.designations) == (1050, ["base", "emergency"])


def test_memos_subtotals_and_mislabeled_layouts_are_not_candidates():
    rows = [
        _row(row_id="R1:1"),
        _row(row_id="R1:2", is_memo=True, line_item_text="(By transfer)"),
        _row(row_id="R1:3", is_subtotal=True, line_item_text="Total, National Park Service"),
        _row(row_id="R1:4", column_layout="text_in_amount"),
    ]
    [t] = account_totals(rows)
    assert (t.method, t.row_ids) == ("single_line", ["R1:1"])


def test_series_never_mixes_chambers_or_stages():
    rows = [
        _row(report_id="S20", row_id="S20:1", fiscal_year=2020, committee_recommendation=1000),
        _row(report_id="H20", row_id="H20:1", fiscal_year=2020, chamber="house", committee_recommendation=990),
        _row(report_id="E20", row_id="E20:1", fiscal_year=2020, chamber="house", stage="enacted", committee_recommendation=995),
        _row(report_id="S21", row_id="S21:1", fiscal_year=2021, committee_recommendation=1010),
    ]
    s = account_series(account_totals(rows), "014-1036")
    got = {(x["chamber"], x["stage"]): [(p["fiscal_year"], p["value"]) for p in x["points"]] for x in s["series"]}
    assert got == {
        ("house", "committee"): [(2020, 990)],
        ("house", "enacted"): [(2020, 995)],
        ("senate", "committee"): [(2020, 1000), (2021, 1010)],
    }


def test_two_reports_claiming_one_year_are_a_conflict_not_a_sum():
    rows = [_row(report_id="A", row_id="A:1"), _row(report_id="B", row_id="B:1", committee_recommendation=5)]
    [series] = account_series(account_totals(rows), "014-1036")["series"]
    assert series["points"] == [{"fiscal_year": 2020, "value": None, "conflict": ["A", "B"]}]


def test_unresolved_reports_are_listed_not_hidden():
    rows = [_row(row_id="R1:2", line_item_text="Park management"), _row(row_id="R1:3", line_item_text="Park support")]
    s = account_series(account_totals(rows), "014-1036")
    assert s["series"] == [] and s["unresolved"][0]["n_lines"] == 2


def test_unknown_metric_is_refused():
    with pytest.raises(ValueError):
        account_series([], "014-1036", metric="delta_vs_enacted")


def test_a_lone_program_line_is_not_an_account_total():
    [t] = account_totals([_row(line_item_text="Park management", committee_recommendation=700)])
    assert (t.method, t.committee_recommendation) == ("unresolved", None)


def test_a_component_qualifier_is_not_stripped_into_the_account_title():
    row = _row(account_key="012-3539", account_key_title="Child Nutrition Programs, Food and Nutrition Service",
               line_item_text="Child Nutrition Programs (Entitlement Commodities)", committee_recommendation=465)
    [t] = account_totals([row])
    assert t.method == "unresolved"


def test_citation_parentheticals_do_not_block_the_title_match():
    [t] = account_totals([_row(line_item_text="Operation of the National Park System (Sec. 115)")])
    assert t.method == "single_line"
