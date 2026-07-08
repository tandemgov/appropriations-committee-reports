"""API route for the 'follow the money' Sankey flow."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from approps.api.data import METRICS, build_flow, facets

router = APIRouter(prefix="/api", tags=["flow"])


@router.get("/facets")
def get_facets() -> dict:
    """Distinct filter values (chambers, stages, subcommittees, years) for the UI."""
    return facets()


@router.get("/flow")
def get_flow(
    metric: str = Query("committee_recommendation", description=f"one of {METRICS}"),
    levels: str = Query(
        "subcommittee,title_name,account",
        description="Comma-separated hierarchy levels, outermost first",
    ),
    chamber: str | None = Query(None, description="house / senate"),
    subcommittee: str | None = Query(None),
    stage: str | None = Query(None, description="committee / enacted"),
    fiscal_year: int | None = Query(None),
    top: int = Query(12, ge=2, le=50, description="Max distinct values kept per level"),
) -> dict:
    """Aggregate a money metric into Sankey nodes + links for the flow diagram."""
    level_list = [lv.strip() for lv in levels.split(",") if lv.strip()]
    if len(level_list) < 2:
        raise HTTPException(400, "Provide at least two levels")
    try:
        return build_flow(
            metric=metric,
            levels=level_list,
            chamber=chamber,
            subcommittee=subcommittee,
            stage=stage,
            fiscal_year=fiscal_year,
            top=top,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
