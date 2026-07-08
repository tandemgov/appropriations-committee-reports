"""API routes for querying line items across all reports."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query

from approps.api.data import METRICS, filter_items, load_line_items

router = APIRouter(prefix="/api/line_items", tags=["line_items"])

# Fields returned per line item (keeps the payload lean and stable).
_ITEM_FIELDS = (
    "report_id", "congress", "chamber", "fiscal_year", "subcommittee", "stage",
    "title_name", "department", "agency", "account", "account_inferred",
    "non_add_inferred", "account_effective", "program", "line_item_text",
    "prior_year_enacted", "budget_estimate", "committee_recommendation",
    "delta_vs_enacted", "delta_vs_estimate",
    "account_key", "account_key_title", "account_key_agency", "account_key_bureau", "designation",
    "hierarchy_depth", "verified", "verification_tier", "column_layout", "extraction_method",
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
    """Query line items across all reports with filtering and pagination."""
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
    account: str | None = Query(None, description="Account name substring to compare"),
    account_key: str | None = Query(None, description="Exact crosswalk key (preferred)"),
    chamber: str | None = Query(None),
    subcommittee: str | None = Query(None),
    stage: str | None = Query(None),
    metric: str = Query("committee_recommendation", description=f"one of {METRICS}"),
    real: bool = Query(False, description="Inflation-adjust to 2024 dollars via real_factor_2024"),
) -> dict:
    """Longitudinal comparison: one account's money across fiscal years.

    Provide `account_key` (exact, preferred — joins the same account across years)
    or `account` (substring). Returns one summed point per fiscal year.
    """
    if metric not in METRICS:
        raise HTTPException(400, f"metric must be one of {METRICS}")
    if not account and not account_key:
        raise HTTPException(400, "Provide account_key (preferred) or account")

    rows = filter_items(
        account=account,
        account_key=account_key,
        chamber=chamber,
        subcommittee=subcommittee,
        stage=stage,
        include_subtotals=False,
    )

    by_year: dict[int, float] = defaultdict(float)
    keys: set[str] = set()
    titles: set[str] = set()
    for r in rows:
        val = r.get(metric)
        if val is None or r["fiscal_year"] is None:
            continue
        if real and r.get("real_factor_2024"):
            val = val * r["real_factor_2024"]
        by_year[r["fiscal_year"]] += val
        if r["account_key"]:
            keys.add(r["account_key"])
        if r["account_key_title"]:
            titles.add(r["account_key_title"])

    years = [
        {"fiscal_year": fy, "value": round(by_year[fy])}
        for fy in sorted(by_year)
    ]
    return {
        "query": {"account": account, "account_key": account_key, "metric": metric, "real": real},
        "matched_account_keys": sorted(keys),
        "matched_titles": sorted(titles),
        "years": years,
    }
