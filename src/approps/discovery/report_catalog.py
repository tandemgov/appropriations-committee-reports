"""Build and manage a catalog of appropriations committee reports."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from approps.config import GOVINFO_CONTENT_URL, MAX_CONGRESS, MIN_CONGRESS, REFERENCE_DIR
from approps.discovery.govinfo_api import GovInfoClient
from approps.discovery.subcommittee_map import (
    classify_stage,
    classify_subcommittee,
    extract_fiscal_year,
)
from approps.output.schemas import Chamber, ReportMetadata

logger = logging.getLogger(__name__)

CATALOG_PATH = REFERENCE_DIR / "report_catalog.json"

# Start dates for each congress (approximate, for API queries)
CONGRESS_START_DATES: dict[int, str] = {
    114: "2015-01-01",
    115: "2017-01-01",
    116: "2019-01-01",
    117: "2021-01-01",
    118: "2023-01-01",
    119: "2025-01-01",
}


def _parse_package_to_metadata(package_id: str, summary: dict) -> ReportMetadata | None:
    """Convert a GovInfo package summary to a ReportMetadata object.

    Returns None if the package is not an appropriations committee report.
    """
    title = summary.get("title", "")
    doc_class = summary.get("docClass", "")

    # Determine chamber from document class
    if doc_class == "HRPT":
        chamber = Chamber.HOUSE
    elif doc_class == "SRPT":
        chamber = Chamber.SENATE
    else:
        return None

    # Extract report number from package ID (e.g., CRPT-118hrpt553 -> 553)
    try:
        num_str = package_id.split("rpt")[-1]
        report_number = int(num_str)
    except (ValueError, IndexError):
        logger.warning(f"Could not parse report number from {package_id}")
        return None

    subcommittee = classify_subcommittee(title)
    fiscal_year = extract_fiscal_year(title)
    stage = classify_stage(title, package_id)
    congress = int(summary.get("congress", 0))
    date_issued = summary.get("dateIssued", "")

    html_url = f"{GOVINFO_CONTENT_URL}/{package_id}/html/{package_id}.htm"
    pdf_url = f"{GOVINFO_CONTENT_URL}/{package_id}/pdf/{package_id}.pdf"

    return ReportMetadata(
        package_id=package_id,
        congress=congress,
        chamber=chamber,
        report_number=report_number,
        title=title,
        subcommittee=subcommittee,
        fiscal_year=fiscal_year,
        stage=stage,
        date_issued=date_issued,
        html_url=html_url,
        pdf_url=pdf_url,
    )


def _is_appropriations_report_title(title: str) -> bool:
    """Whether a GovInfo package title is an appropriations *committee report*.

    Rules Committee resolutions carry "appropriation" in the referenced bill's name but
    are not committee reports and yield no comparative statement. They come in several
    title shapes — "PROVIDING FOR [FURTHER] CONSIDERATION OF THE BILL (H.R. ...) MAKING
    APPROPRIATIONS ..." and "RELATING TO CONSIDERATION OF THE SENATE AMENDMENT TO THE
    BILL (H.R. ...) MAKING APPROPRIATIONS ..." (e.g. CRPT-114hrpt595) — but all describe
    the *consideration* of a bill rather than being the bill's report. A genuine committee
    report's title is the bill name itself ("... APPROPRIATIONS BILL, YYYY") and never
    contains "consideration", so that word is a clean discriminator: drop any
    appropriation-mentioning title that also references "consideration".
    """
    # Rejoin line-break hyphenation before the keyword check: some GovInfo titles split
    # a word across a line as "AP- PROPRIATIONS" (e.g. CRPT-119hrpt686, House THUD FY2027),
    # which hides the "appropriation" substring and would drop a real committee report.
    t = title.lower().replace("- ", "")
    if "appropriation" not in t:
        return False
    if "consideration" in t:
        return False
    return True


async def discover_reports(
    client: GovInfoClient,
    min_congress: int = MIN_CONGRESS,
    max_congress: int = MAX_CONGRESS,
) -> list[ReportMetadata]:
    """Discover all appropriations committee reports across a range of congresses.

    Uses the GovInfo published endpoint to find CRPT packages, then filters
    for appropriations-related reports by checking if the title matches
    a known subcommittee pattern.
    """
    all_reports: list[ReportMetadata] = []

    for congress in range(min_congress, max_congress + 1):
        start_date = CONGRESS_START_DATES.get(congress, f"{2015 + (congress - 114) * 2}-01-01")
        logger.info(f"Discovering reports for Congress {congress} (from {start_date})...")

        packages = await client.list_all_published(
            start_date=start_date,
            collection="CRPT",
            congress=congress,
        )

        logger.info(f"  Found {len(packages)} total CRPT packages for Congress {congress}")

        # Filter and enrich: get summaries for packages that look like appropriations reports
        for pkg in packages:
            package_id = pkg.get("packageId", "")
            title = pkg.get("title", "")

            # Quick pre-filter: keep appropriations committee reports, drop Rules
            # Committee resolutions about appropriations/authorization bills.
            if not _is_appropriations_report_title(title):
                continue

            # Get full summary for metadata
            try:
                summary = await client.get_package_summary(package_id)
            except Exception as e:
                logger.warning(f"  Failed to get summary for {package_id}: {e}")
                continue

            report = _parse_package_to_metadata(package_id, summary)
            if report and report.subcommittee:
                all_reports.append(report)
                logger.info(
                    f"  Found: {package_id} -> {report.subcommittee} "
                    f"FY{report.fiscal_year} ({report.chamber.value})"
                )

    logger.info(f"Total appropriations reports discovered: {len(all_reports)}")
    return all_reports


def save_catalog(reports: list[ReportMetadata], path: Path = CATALOG_PATH) -> None:
    """Save the report catalog to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [r.model_dump(mode="json") for r in reports]
    path.write_text(json.dumps(data, indent=2))
    logger.info(f"Saved {len(reports)} reports to {path}")


def load_catalog(path: Path = CATALOG_PATH) -> list[ReportMetadata]:
    """Load the report catalog from a JSON file."""
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [ReportMetadata(**item) for item in data]
