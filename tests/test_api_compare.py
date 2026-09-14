"""`/api/line_items/compare` returns account totals per chamber and stage, and refuses to mix real and nominal dollars."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from approps.api.routes import line_items
from approps.normalization.account_totals import account_totals


def _row(report_id, fy, chamber="senate", stage="committee", rec=1000, text="Operation of the National Park System"):
    return {
        "row_id": f"{report_id}:1", "report_id": report_id, "fiscal_year": fy, "chamber": chamber, "stage": stage,
        "subcommittee": "Interior-Environment", "account_key": "014-1036",
        "account_key_title": "Operation of the National Park System, National Park Service, Interior",
        "line_item_text": text, "designation": "base", "is_subtotal": False, "is_memo": False,
        "column_layout": "standard", "verification_tier": "string_match",
        "prior_year_enacted": None, "budget_estimate": None, "committee_recommendation": rec,
    }


def _client(monkeypatch, rows):
    totals = account_totals(rows)
    monkeypatch.setattr(line_items, "load_account_totals", lambda: totals)
    app = FastAPI()
    app.include_router(line_items.router)
    return TestClient(app)


def test_series_are_separate_per_chamber_and_stage(monkeypatch):
    client = _client(monkeypatch, [
        _row("S20", 2020), _row("H20", 2020, chamber="house", rec=990), _row("E20", 2020, chamber="house", stage="enacted", rec=995),
    ])
    body = client.get("/api/line_items/compare", params={"account_key": "014-1036"}).json()
    assert {(s["chamber"], s["stage"]): s["points"][0]["value"] for s in body["series"]} == {
        ("senate", "committee"): 1000, ("house", "committee"): 990, ("house", "enacted"): 995,
    }


def test_account_key_is_required(monkeypatch):
    client = _client(monkeypatch, [_row("S20", 2020)])
    assert client.get("/api/line_items/compare", params={"account": "park"}).status_code == 422


def test_real_dollars_fail_when_a_year_has_no_deflator(monkeypatch):
    client = _client(monkeypatch, [_row("S24", 2024), _row("S27", 2027)])
    resp = client.get("/api/line_items/compare", params={"account_key": "014-1036", "real": "true"})
    assert resp.status_code == 422
    assert "2027" in resp.json()["detail"]


def test_real_dollars_convert_when_every_year_has_a_deflator(monkeypatch):
    client = _client(monkeypatch, [_row("S16", 2016, rec=240_007), _row("S24", 2024, rec=313_689)])
    body = client.get("/api/line_items/compare", params={"account_key": "014-1036", "real": "true"}).json()
    [series] = body["series"]
    assert [p["value"] for p in series["points"]] == [313_689, 313_689]
    assert series["points"][0]["nominal_value"] == 240_007


def test_unknown_account_is_404(monkeypatch):
    client = _client(monkeypatch, [_row("S20", 2020)])
    assert client.get("/api/line_items/compare", params={"account_key": "999-9999"}).status_code == 404
