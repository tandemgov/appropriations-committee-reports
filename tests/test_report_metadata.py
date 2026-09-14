"""Report-level metadata is stamped onto rows that lost it, never overwritten."""

from approps.normalization.report_metadata import (
    canon_subcommittee,
    division_subcommittee,
    fill_report_metadata,
)


def _line(**kw):
    base = {"report_id": "R", "congress": 119, "chamber": "house", "fiscal_year": 2026,
            "subcommittee": "Interior-Environment", "stage": "committee", "title_name": None}
    base.update(kw)
    return base


def test_repair_merged_rows_get_the_catalog_fiscal_year():
    lines = [_line(), _line(fiscal_year=None, subcommittee=None)]
    authority = {"R": {"congress": 119, "chamber": "house", "fiscal_year": 2026,
                       "subcommittee": "Interior-Environment", "stage": "committee"}}
    result = fill_report_metadata({"report_id": "R"}, lines, authority)
    assert lines[1]["fiscal_year"] == 2026
    assert lines[1]["subcommittee"] == "Interior-Environment"
    assert result.filled == {"fiscal_year": 1, "subcommittee": 1}
    assert result.conflicts == []


def test_unanimous_rows_stand_in_when_the_catalog_has_no_entry():
    lines = [_line(), _line(), _line(fiscal_year=None)]
    fill_report_metadata({"report_id": "R"}, lines, {})
    assert lines[2]["fiscal_year"] == 2026


def test_disagreeing_rows_are_not_used_as_an_authority():
    lines = [_line(fiscal_year=2026), _line(fiscal_year=2027), _line(fiscal_year=None)]
    fill_report_metadata({"report_id": "R"}, lines, {})
    assert lines[2]["fiscal_year"] is None


def test_a_contradiction_is_reported_not_corrected():
    lines = [_line(fiscal_year=2025)]
    authority = {"R": {"fiscal_year": 2026}}
    result = fill_report_metadata({"report_id": "R"}, lines, authority)
    assert lines[0]["fiscal_year"] == 2025
    assert result.conflicts == [("R", "fiscal_year", 2025, 2026)]


def test_enacted_rows_take_their_subcommittee_from_the_division():
    lines = [
        _line(stage="enacted", subcommittee=None, title_name="DIVISION B—COMMERCE, JUSTICE, SCIENCE, AND"),
        _line(stage="enacted", subcommittee=None, title_name="DIVISION C—DEPARTMENT OF DEFENSE"),
        _line(stage="enacted", subcommittee=None, title_name="DIVISION K—DEPARTMENT OF STATE, FOREIGN OPER-"),
    ]
    fill_report_metadata({"report_id": "R"}, lines, {})
    assert [ln["subcommittee"] for ln in lines] == ["Commerce-Justice-Science", "Defense", "State-Foreign-Ops"]


def test_non_bill_divisions_stay_unassigned():
    assert division_subcommittee("DIVISION N—OTHER MATTERS") is None
    assert division_subcommittee(None) is None


def test_subcommittee_label_drift_is_canonicalized():
    assert canon_subcommittee("Homeland Security") == "Homeland-Security"
    assert canon_subcommittee("State-Foreign-Operations") == "State-Foreign-Ops"
    lines = [_line(subcommittee="Homeland Security")]
    fill_report_metadata({"report_id": "R"}, lines, {"R": {"subcommittee": "Homeland-Security"}})
    assert lines[0]["subcommittee"] == "Homeland-Security"
