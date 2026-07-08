"""API routes for report metadata and data."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from approps.api.deps import get_catalog, get_extracted_data
from approps.output.schemas import ReportMetadata

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=list[ReportMetadata])
def list_reports(
    congress: int | None = Query(None, description="Filter by congress number"),
    chamber: str | None = Query(None, description="Filter by chamber (house/senate)"),
    subcommittee: str | None = Query(None, description="Filter by subcommittee"),
    fiscal_year: int | None = Query(None, description="Filter by fiscal year"),
    stage: str | None = Query(None, description="Filter by stage"),
) -> list[ReportMetadata]:
    """List all reports in the catalog with optional filtering."""
    reports = get_catalog()

    if congress is not None:
        reports = [r for r in reports if r.congress == congress]
    if chamber is not None:
        reports = [r for r in reports if r.chamber.value == chamber.lower()]
    if subcommittee is not None:
        reports = [r for r in reports if r.subcommittee == subcommittee]
    if fiscal_year is not None:
        reports = [r for r in reports if r.fiscal_year == fiscal_year]
    if stage is not None:
        reports = [r for r in reports if r.stage.value == stage.lower()]

    return reports


@router.get("/{package_id}", response_model=ReportMetadata)
def get_report(package_id: str) -> ReportMetadata:
    """Get metadata for a single report."""
    catalog = get_catalog()
    for report in catalog:
        if report.package_id == package_id:
            return report
    raise HTTPException(status_code=404, detail=f"Report {package_id} not found")


@router.get("/{package_id}/line_items")
def get_report_line_items(package_id: str) -> dict:
    """Get extracted line items for a report."""
    data = get_extracted_data(package_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"No extracted data for {package_id}. Run extraction first.",
        )
    return data
