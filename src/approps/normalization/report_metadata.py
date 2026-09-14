"""Stamp report-level metadata onto line items that lost it.

A line item's `fiscal_year`, `subcommittee`, `congress`, `chamber`, and `stage` are properties of the report it came from, not of the row.
Rows merged in after extraction — `scripts/repair_dropped_pages.py` re-reads whole pages — were written without them, which left 857 House rows with no fiscal year and 362 with no subcommittee.
Those rows were in the dataset but invisible to any per-year query.

The report catalog is the authority for committee reports.
Enacted explanatory-statement prints are omnibus documents with no single subcommittee, so each row's subcommittee is read from its division heading instead (`DIVISION B—COMMERCE, JUSTICE, SCIENCE, AND`).

A fill never overwrites: a row that already carries a value keeps it, and a value that contradicts the authority is reported as a conflict rather than silently corrected.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from approps.config import REFERENCE_DIR
from approps.discovery.subcommittee_map import classify_subcommittee

#: Label drift in the extracted rows, mapped to the canonical ids in data/reference/subcommittees.json.
SUBCOMMITTEE_ALIASES = {
    "Homeland Security": "Homeland-Security",
    "State-Foreign-Operations": "State-Foreign-Ops",
}

#: Division headings the title classifier misses: omnibus prints say "DEPARTMENT OF DEFENSE" with no "appropriations", and hyphenate "FOREIGN OPER-" at the line break.
_DIVISION_PATTERNS = (
    ("department of defense", "Defense"),
    ("state, foreign oper", "State-Foreign-Ops"),
)

REPORT_FIELDS = ("congress", "chamber", "fiscal_year", "subcommittee", "stage")


def canon_subcommittee(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return SUBCOMMITTEE_ALIASES.get(value, value)


def division_subcommittee(title_name: str | None) -> str | None:
    """The subcommittee an enacted omnibus division belongs to, or None for non-bill divisions."""
    if not title_name or not title_name.upper().startswith("DIVISION"):
        return None
    lower = title_name.lower()
    for needle, sub in _DIVISION_PATTERNS:
        if needle in lower:
            return sub
    return classify_subcommittee(title_name)


def load_report_authority() -> dict[str, dict]:
    """report_id -> {congress, chamber, fiscal_year, subcommittee, stage} from the report catalog."""
    path = REFERENCE_DIR / "report_catalog.json"
    if not path.exists():
        return {}
    out = {}
    for item in json.loads(path.read_text()):
        out[item["package_id"]] = {k: item.get(k) for k in REPORT_FIELDS}
    return out


@dataclass
class FillResult:
    filled: Counter = field(default_factory=Counter)
    conflicts: list[tuple[str, str, object, object]] = field(default_factory=list)


def fill_report_metadata(
    report: dict, lines: list[dict], authority: dict[str, dict], result: FillResult | None = None
) -> FillResult:
    """Fill missing report-level fields on `lines` in place.

    Precedence for each field: the catalog entry for the report, then the extracted file's own header, then the value every other row in the report agrees on.
    A field with no unanimous source is left empty.
    """
    result = result or FillResult()
    rid = report.get("report_id")
    auth = dict(authority.get(rid) or {})
    for key in REPORT_FIELDS:
        if auth.get(key) is None and report.get(key) is not None:
            auth[key] = report[key]
        if auth.get(key) is None:
            seen = {ln.get(key) for ln in lines if ln.get(key) is not None}
            if len(seen) == 1:
                auth[key] = seen.pop()
    if auth.get("subcommittee"):
        auth["subcommittee"] = canon_subcommittee(auth["subcommittee"])

    for ln in lines:
        if ln.get("subcommittee"):
            ln["subcommittee"] = canon_subcommittee(ln["subcommittee"])
        enacted = (ln.get("stage") or auth.get("stage")) == "enacted"
        for key in REPORT_FIELDS:
            want = auth.get(key)
            if key == "subcommittee" and enacted:
                want = division_subcommittee(ln.get("title_name"))
            if want is None:
                continue
            have = ln.get(key)
            if have is None:
                ln[key] = want
                result.filled[key] += 1
            elif have != want and not (key == "stage" and auth.get(key) == "committee"):
                result.conflicts.append((rid, key, have, want))
    return result
