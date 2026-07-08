"""API route for on-demand report parsing."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["parse"])


class ParseRequest(BaseModel):
    """Request body for on-demand report parsing."""

    package_id: str | None = None
    url: str | None = None


class ParseResponse(BaseModel):
    """Response for a parse request."""

    status: str
    package_id: str | None = None
    message: str
    data: dict | None = None


@router.post("/parse_report", response_model=ParseResponse)
async def parse_report(request: ParseRequest) -> ParseResponse:
    """Parse an appropriations committee report on demand.

    Accepts either a GovInfo package ID or a direct URL.
    Downloads the report, runs the extraction pipeline, and returns structured data.

    Currently a stub — will be wired to the extraction pipeline.
    """
    if not request.package_id and not request.url:
        raise HTTPException(
            status_code=400,
            detail="Provide either package_id or url",
        )

    identifier = request.package_id or request.url

    # TODO: Wire to actual extraction pipeline
    # 1. Resolve package_id from URL if needed
    # 2. Download HTML/PDF
    # 3. Run extraction
    # 4. Run verification
    # 5. Return structured results

    return ParseResponse(
        status="stub",
        package_id=request.package_id,
        message=(
            f"On-demand parsing for '{identifier}' is under development. "
            "The extraction pipeline must be completed first."
        ),
        data=None,
    )
