"""Flag back-of-report summary tables so they don't masquerade as line items.

After the comparative statement, committee reports print compliance/summary tables — the
"Comparison of amounts in the bill with the applicable allocations" (302(b)), the
projection of outlays by year, and similar. The vision pass reads these as rows, and their
columns force-map into the comparative schema meaninglessly (a `Discretionary` row's three
figures are budget authority / allocation / outlays, not recommendation / prior / delta;
rows labelled `2025`, `2026`, `2029 and future years` are outlay projections). They are not
appropriations line items and are excluded from `comparative_statements` output.

Detection is conservative: a bare-fiscal-year row is always summary; otherwise a report
enters "summary mode" only when an unambiguous back-matter heading appears in the *latter*
part of the report, after which the trailing rows (the whole closing section) are summary.
"""

from __future__ import annotations

import re

# Unambiguous headings that only appear in the closing compliance/summary section.
_HEADING = re.compile(
    r"comparison of amounts in the bill"
    r"|projection of outlays"
    r"|outlays? associated with"
    r"|applicable (budget )?allocation"
    r"|302\s*\([ab]\)",
    re.IGNORECASE,
)
# A row labelled only by a fiscal year (± "and future years") — an outlay-projection line.
_YEAR = re.compile(r"^(19|20)\d\d(\s*(and (future years|beyond|outyears)))?[.:]?$", re.IGNORECASE)
# Rows that belong to a 302(b)/outlay summary table when adjacent to its heading.
_SUMMARY_LABEL = re.compile(r"^(discretionary|mandatory|defense|non-?defense)\b|^\(", re.IGNORECASE)


def _is_summary_row(text: str) -> bool:
    return bool(_YEAR.match(text) or _HEADING.search(text) or _SUMMARY_LABEL.match(text) or not text)


def summary_flags(items: list[dict]) -> list[bool]:
    """Per-row `True` where the row is 302(b)/outlay summary-table boilerplate, not a line item.

    A bare-year row is always summary. Otherwise a summary heading opens a *contiguous* run
    of summary-type rows (Discretionary/Mandatory, year projections, further headings, blanks)
    that ends the moment a real account line appears — these tables sit between the summary and
    detailed comparative statements, so flagging must be local, never to end-of-report.
    `items` are one report's `comparative_lines` in source order."""
    n = len(items)
    flags = [False] * n
    i = 0
    while i < n:
        text = (items[i].get("line_item_text") or "").strip()
        if _YEAR.match(text):
            flags[i] = True
            i += 1
        elif _HEADING.search(text):
            flags[i] = True
            j = i + 1
            while j < n and _is_summary_row((items[j].get("line_item_text") or "").strip()):
                flags[j] = True
                j += 1
            i = j
        else:
            i += 1
    return flags


def drop_summary_rows(items: list[dict]) -> list[dict]:
    """Return `items` with the closing summary-table rows removed."""
    return [it for it, flag in zip(items, summary_flags(items), strict=True) if not flag]
