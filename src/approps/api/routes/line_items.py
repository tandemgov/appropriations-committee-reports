"""API routes for querying line items across all reports."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from approps.api.data import METRICS, filter_items, load_account_totals
from approps.normalization.account_totals import account_series
from approps.normalization.inflation import load_deflators

router = APIRouter(prefix="/api/line_items", tags=["line_items"])

_REAL_BASE_YEAR = 2024

# Fields returned per line item (keeps the payload lean and stable).
_ITEM_FIELDS = (
    "row_id", "report_id", "congress", "chamber", "fiscal_year", "subcommittee", "stage",
    "title_name", "department", "agency", "account", "account_inferred",
    "is_memo", "account_effective", "program", "line_item_text",
    "prior_year_enacted", "budget_estimate", "committee_recommendation",
    "delta_vs_enacted", "delta_vs_estimate",
    "account_key", "account_key_title", "account_key_agency", "account_key_bureau", "account_match",
    "account_key_withheld", "designation",
    "hierarchy_depth", "verified", "verification_tier", "verification_method",
    "column_layout", "column_repair", "extraction_method",
)


def _project(row: dict) -> dict:
    return {k: row.get(k) for k in _ITEM_FIELDS}


@router.get("")
def list_line_items(
    congress: int | None = Query(None),
    chamber: str | None = Query(None, description="house / senate"),
    subcommittee: str | None = Query(None),
    stage: str | None = Query(None, description="committee / enacted"),
    fiscal_year: int | None = Query(None),
    fiscal_year_min: int | None = Query(None, description="Minimum fiscal year"),
    fiscal_year_max: int | None = Query(None, description="Maximum fiscal year"),
    account: str | None = Query(None, description="Account/line-item substring match"),
    account_key: str | None = Query(None, description="Exact crosswalk account key"),
    designation: str | None = Query(None, description="e.g. base / OCO / emergency"),
    include_subtotals: bool = Query(False, description="Include subtotal rows"),
    limit: int = Query(100, le=2000),
    offset: int = Query(0, ge=0),
) -> dict:
    """Query line items across all reports with filtering and pagination.

    This returns rows, not totals: an account's own line and its program breakdown are separate rows, so do not sum them. Use `/compare` for account totals.
    """
    matched = filter_items(
        congress=congress,
        chamber=chamber,
        subcommittee=subcommittee,
        stage=stage,
        fiscal_year=fiscal_year,
        fiscal_year_min=fiscal_year_min,
        fiscal_year_max=fiscal_year_max,
        account=account,
        account_key=account_key,
        designation=designation,
        include_subtotals=include_subtotals,
    )
    page = matched[offset : offset + limit]
    return {
        "items": [_project(r) for r in page],
        "total": len(matched),
        "limit": limit,
        "offset": offset,
    }


@router.get("/compare")
def compare_line_items(
    account_key: str = Query(..., description="Exact crosswalk account key, e.g. 014-1036"),
    metric: str = Query("committee_recommendation", description=f"one of {METRICS}"),
    real: bool = Query(False, description="Express values in constant FY2024 dollars (CPI-U)"),
) -> dict:
    """One account's total through time, one series per chamber and stage.

    Each point is the account total for one report, selected by `normalization.account_totals` (the account's own line, never a sum of its breakdown).
    Chambers and stages are never combined. Reports whose total cannot be resolved are listed under `unresolved` rather than guessed.
    With `real=true`, each point is deflated from its price year — the report's fiscal year, or the year before for `prior_year_enacted` — and if any price year lacks a deflator the request fails with 422 rather than mixing real and nominal dollars.
    """
    if metric not in METRICS:
        raise HTTPException(400, f"metric must be one of {METRICS}")

    result = account_series(load_account_totals(), account_key, metric)
    if not result["series"] and not result["unresolved"]:
        raise HTTPException(404, f"No resolved account totals for account_key {account_key!r}")

    if real:
        deflators = load_deflators()
        # A report's prior-year column is last year's enacted level, in last year's dollars; the request and recommendation are in the report's year.
        lag = 1 if metric == "prior_year_enacted" else 0
        years = {p["fiscal_year"] - lag for s in result["series"] for p in s["points"] if p["value"] is not None}
        missing = sorted(y for y in years if y not in deflators)
        if missing:
            raise HTTPException(
                422,
                f"No CPI-U deflator for price year(s) {missing}, so this series cannot be expressed in FY{_REAL_BASE_YEAR} dollars. "
                "Request nominal values (real=false).",
            )
        for s in result["series"]:
            for p in s["points"]:
                if p["value"] is not None:
                    p["price_year"] = p["fiscal_year"] - lag
                    p["nominal_value"] = p["value"]
                    p["value"] = round(p["value"] * deflators[_REAL_BASE_YEAR] / deflators[p["price_year"]])

    result["real"] = real
    result["base_year"] = _REAL_BASE_YEAR if real else None
    return result
