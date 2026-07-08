"""Registry of enacted-stage explanatory-statement prints (GovInfo CPRT collection).

The final enacted appropriations detail for FY2016–FY2024 lives in the House Rules
Committee "Consolidated Appropriations Act, {year}" prints, issued as a two-book pair per
fiscal year (bill text + Joint Explanatory Statement). These are not discoverable via the
per-subcommittee CRPT title scan (they are omnibus, multi-subcommittee), so they are
curated here from the enacted-stage discovery probe. Congress and report number are
derived from the package ID; fiscal year is the analytic key.

FY2025 is intentionally absent: it was a full-year continuing resolution with no new
program-level explanatory statement on GovInfo.
"""

from __future__ import annotations

import re

from approps.config import GOVINFO_CONTENT_URL
from approps.output.schemas import Chamber, ReportMetadata, Stage

# package_id -> fiscal_year. Two books per year unless the omnibus had a single vehicle.
ENACTED_PRINTS: dict[str, int] = {
    "CPRT-114HPRT98155": 2016, "CPRT-114HPRT98369": 2016,
    "CPRT-115HPRT25289": 2017,
    "CPRT-115HPRT29456": 2018, "CPRT-115HPRT29457": 2018,
    "CPRT-116HPRT35160": 2019,
    "CPRT-116HPRT38678": 2020, "CPRT-116HPRT38679": 2020,
    "CPRT-117HPRT43749": 2021, "CPRT-117HPRT43750": 2021,
    "CPRT-117HPRT47047": 2022, "CPRT-117HPRT47048": 2022,
    "CPRT-117HPRT50347": 2023, "CPRT-117HPRT50348": 2023,
    "CPRT-118HPRT55008": 2024, "CPRT-118HPRT56550": 2024,
}

_PKG_RE = re.compile(r"^CPRT-(\d+)HPRT(\d+)$")


def enacted_report_metadata(
    min_congress: int | None = None, max_congress: int | None = None
) -> list[ReportMetadata]:
    """Build ReportMetadata entries for the enacted prints, optionally within a congress
    range (matched on the congress derived from each package ID)."""
    out: list[ReportMetadata] = []
    for package_id, fiscal_year in ENACTED_PRINTS.items():
        m = _PKG_RE.match(package_id)
        if not m:
            continue
        congress, report_number = int(m.group(1)), int(m.group(2))
        if min_congress is not None and congress < min_congress:
            continue
        if max_congress is not None and congress > max_congress:
            continue
        out.append(
            ReportMetadata(
                package_id=package_id,
                congress=congress,
                chamber=Chamber.HOUSE,  # House Rules Committee print
                report_number=report_number,
                title=f"Consolidated Appropriations Act explanatory statement, FY{fiscal_year}",
                subcommittee=None,
                fiscal_year=fiscal_year,
                stage=Stage.ENACTED,
                date_issued=None,
                html_url="",  # CPRT prints have no HTML; extraction uses the PDF
                pdf_url=f"{GOVINFO_CONTENT_URL}/{package_id}/pdf/{package_id}.pdf",
            )
        )
    return out
