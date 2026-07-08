"""Tests for cross-year account authority (follow one account through time).

The authority groups crosswalk-keyed rows by account_key — the identity that
survives a title change — and reconstructs the money series, the label timeline,
and the classified title changes across fiscal years.
"""

from approps.normalization.account_authority import (
    classify_title_change,
    trace_account,
    trace_accounts,
)


def _row(**kw):
    """A minimal enriched output row. Sensible defaults; override per test."""
    base = {
        "report_id": "R1",
        "account_key": "070-0110",
        "account_key_title": "Operations and Support, Departmental Management",
        "account": "Operations and Support",
        "account_effective": None,  # let account fall through when unset
        "account_inferred": None,
        "fiscal_year": 2020,
        "chamber": "house",
        "stage": "committee",
        "committee_recommendation": 1000,
        "prior_year_enacted": None,
        "budget_estimate": None,
        "is_subtotal": False,
        "line_item_text": "Operations and Support",
    }
    base.update(kw)
    # One report per fiscal year unless a test pins report_id explicitly (the
    # representative is deduped per report+key, so same-report rows collapse).
    if "report_id" not in kw:
        base["report_id"] = f"R{base['fiscal_year']}"
    # mirror api.data._finalize: coalesce account_effective from account
    base["account_effective"] = base.get("account_effective") or base.get("account")
    return base


# --- title-change classification -----------------------------------------


def test_classify_case_only():
    assert classify_title_change("Mission Support", "MISSION SUPPORT") == "case"


def test_classify_prefix_expansion():
    assert (
        classify_title_change(
            "office of the secretary", "office of the secretary and executive management"
        )
        == "prefix"
    )


def test_classify_reword():
    assert classify_title_change("Salaries and Expenses", "Operations and Support") == "reword"


# --- grouping and series -------------------------------------------------


def test_groups_by_key_across_years():
    rows = [
        _row(report_id="R16", fiscal_year=2016, committee_recommendation=100),
        _row(report_id="R17", fiscal_year=2017, committee_recommendation=110),
        _row(report_id="R18", fiscal_year=2018, committee_recommendation=120),
    ]
    (auth,) = trace_accounts(rows)
    assert auth.account_key == "070-0110"
    assert auth.canonical_title == "Operations and Support, Departmental Management"
    assert auth.fiscal_years == (2016, 2017, 2018)
    assert [p.amount for p in auth.series] == [100, 110, 120]
    assert auth.report_count == 3


def test_series_is_chamber_and_stage_aware():
    rows = [
        _row(report_id="H", chamber="house", stage="committee", committee_recommendation=100),
        _row(report_id="S", chamber="senate", stage="committee", committee_recommendation=200),
    ]
    (auth,) = trace_accounts(rows)
    points = {(p.chamber, p.stage): p.amount for p in auth.series}
    assert points == {("house", "committee"): 100, ("senate", "committee"): 200}


def test_double_count_avoided_account_total_vs_program_row():
    # Same report + key: an account total (1000) and one program sub-row (400),
    # both non-subtotal. The representative is the larger — never their sum.
    rows = [
        _row(report_id="R", account="Operations and Support", committee_recommendation=1000),
        _row(report_id="R", account="Operations and Support", committee_recommendation=400),
    ]
    (auth,) = trace_accounts(rows)
    assert [p.amount for p in auth.series] == [1000]


def test_rollup_rows_are_ignored():
    rows = [
        _row(report_id="R", committee_recommendation=1000),
        _row(
            report_id="R",
            committee_recommendation=999999,
            is_subtotal=True,
            line_item_text="Total, Departmental Management",
        ),
    ]
    (auth,) = trace_accounts(rows)
    assert [p.amount for p in auth.series] == [1000]


# --- title timeline and changes ------------------------------------------


def test_detects_reword_title_change_across_years():
    rows = [
        _row(fiscal_year=2019, account="Salaries and Expenses"),
        _row(fiscal_year=2020, account="Operations and Support"),
    ]
    (auth,) = trace_accounts(rows)
    assert len(auth.title_changes) == 1
    change = auth.title_changes[0]
    assert change.fiscal_year == 2020
    assert change.from_title == "Salaries and Expenses"
    assert change.to_title == "Operations and Support"
    assert change.kind == "reword"


def test_label_timeline_records_years_per_label():
    rows = [
        _row(fiscal_year=2018, account="Salaries and Expenses"),
        _row(fiscal_year=2019, account="Salaries and Expenses"),
        _row(fiscal_year=2020, account="Operations and Support"),
    ]
    (auth,) = trace_accounts(rows)
    spans = {s.title: s.fiscal_years for s in auth.labels}
    assert spans["Salaries and Expenses"] == (2018, 2019)
    assert spans["Operations and Support"] == (2020,)


def test_case_only_drift_produces_no_title_change():
    # Case/punctuation-only drift is pure noise: it is suppressed before it can
    # register as a change (normalized-equal labels are never a transition).
    rows = [
        _row(fiscal_year=2019, account="Mission Support"),
        _row(fiscal_year=2020, account="MISSION SUPPORT:"),
    ]
    (auth,) = trace_accounts(rows)
    assert auth.title_changes == ()


# --- filters and single-account trace ------------------------------------


def test_min_years_filters_single_year_accounts():
    rows = [_row(fiscal_year=2020)]
    assert trace_accounts(rows, min_years=2) == []
    assert len(trace_accounts(rows, min_years=1)) == 1


def test_unkeyed_rows_are_out_of_scope():
    rows = [_row(account_key=None), _row(account_key="")]
    assert trace_accounts(rows) == []


def test_trace_single_account_by_key():
    rows = [
        _row(account_key="070-0110", fiscal_year=2019),
        _row(account_key="070-0110", fiscal_year=2020),
        _row(account_key="099-9999", fiscal_year=2020, account_key_title="Something Else"),
    ]
    auth = trace_account(rows, "070-0110")
    assert auth is not None
    assert auth.account_key == "070-0110"
    assert auth.fiscal_years == (2019, 2020)
    assert trace_account(rows, "000-0000") is None


def test_metric_selects_the_money_column():
    rows = [
        _row(fiscal_year=2019, committee_recommendation=100, prior_year_enacted=90),
        _row(fiscal_year=2020, committee_recommendation=110, prior_year_enacted=95),
    ]
    (auth,) = trace_accounts(rows, metric="prior_year_enacted")
    assert [p.amount for p in auth.series] == [90, 95]
    assert auth.metric == "prior_year_enacted"
