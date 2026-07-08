"""Extract inline narrative funding tables from report HTML text.

Senate format:
    Appropriations, 2023....................................  $1,368,969,000
    Budget estimate, 2024...................................   1,497,069,000
    Committee recommendation................................   1,371,619,000

House format:
    Appropriation, fiscal year 2024.......................      $404,695,000
    Budget request, fiscal year 2025......................       358,466,000
    Recommended in the bill...............................       281,358,000
    Bill compared with:
        Appropriation, fiscal year 2024...................      -123,337,000
        Budget request, fiscal year 2025..................       -77,108,000
"""

from __future__ import annotations

import re

from approps.extraction.dollar_parser import parse_dollar
from approps.output.schemas import Chamber, DollarAmount, InlineFundingTable

# Pattern matching a line with a label, dot leaders, and a dollar amount (or dashes)
_FUNDING_LINE_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?P<label>[A-Za-z][\w\s,()\\/*]+?)"  # label text
    r"\.{3,}\s*"  # dot leaders
    r"(?P<amount>.+?)\s*$"  # dollar amount or dashes
)

# Patterns that identify the START of an inline funding block
_SENATE_START_RE = re.compile(r"^\s*Appropriations?,\s*\d{4}\s*\.{3,}")
_HOUSE_START_RE = re.compile(r"^\s*Appropriation,\s*fiscal\s+year\s+\d{4}")

# "Bill compared with:" header line (House reports)
_BILL_COMPARED_RE = re.compile(r"^\s*Bill compared with:\s*$")

# Heading patterns: all-caps OR title-case line, indented, with at least 5 chars
_HEADING_ALL_CAPS_RE = re.compile(r"^\s{0,30}[A-Z][A-Z\s,\-\(\)&]{4,}\s*$")
_HEADING_TITLE_CASE_RE = re.compile(r"^\s{4,30}[A-Z][a-zA-Z\s,\-\(\)&\']{4,}\s*$")


# Born-digital Senate PDFs (e.g. CRPT-119srpt55) typeset each section header with a
# large decorative drop-cap; the PDF text layer omits that first letter, leaving a
# truncated ALL-CAPS heading. Restore the known cases so the heading matches the
# account crosswalk. Keyed on the first whitespace/comma-delimited token so a correct
# heading is never touched. Extend as new born-digital reports surface truncations.
_DROPCAP_REPAIRS = {
    "ENSION": "P",  # PENSION
    "FFICE": "O",  # OFFICE
    "DUCATION": "E",  # EDUCATION
}


def _repair_dropcap(heading: str) -> str:
    """Prepend a dropped decorative drop-cap letter to a truncated heading, if known."""
    if not heading:
        return heading
    first = re.split(r"[ ,]", heading.strip(), maxsplit=1)[0]
    letter = _DROPCAP_REPAIRS.get(first)
    return letter + heading if letter else heading


def _find_nearest_heading(lines: list[str], line_idx: int) -> str:
    """Look backward from line_idx to find the nearest heading.

    Prefers title-case headings (closer to the table, more specific)
    over all-caps headings (section-level, more general).
    """
    # First pass: look for a title-case heading (indented, closer)
    for i in range(line_idx - 1, max(line_idx - 15, -1), -1):
        if i < 0:
            break
        line = lines[i]
        stripped = line.strip()
        if stripped and _HEADING_TITLE_CASE_RE.match(line) and len(stripped) > 4:
            return stripped

    # Second pass: look for an all-caps heading (broader section)
    for i in range(line_idx - 1, max(line_idx - 30, -1), -1):
        if i < 0:
            break
        line = lines[i]
        stripped = line.strip()
        if stripped and _HEADING_ALL_CAPS_RE.match(line) and len(stripped) > 4:
            return stripped

    return ""


def _parse_label_type(label: str) -> str | None:
    """Classify a funding line label into a semantic type.

    Returns one of: "prior_year", "budget_estimate", "committee_recommendation",
    "delta_vs_enacted", "delta_vs_estimate", or None.
    """
    label_lower = label.strip().lower()

    # Prior year
    if label_lower.startswith(("appropriation,", "appropriations,")):
        return "prior_year"

    # Budget estimate / request
    if label_lower.startswith(("budget estimate", "budget request")):
        return "budget_estimate"

    # Committee recommendation
    if label_lower.startswith(("committee recommendation", "recommended in the bill")):
        return "committee_recommendation"

    # Offsetting collections (special case in Senate)
    if "offsetting" in label_lower:
        return None  # skip these for now

    return None


def _is_delta_line(label: str, indent: int) -> str | None:
    """Check if a line in the 'Bill compared with' section is a delta.

    Returns "delta_vs_enacted" or "delta_vs_estimate" or None.
    """
    label_lower = label.strip().lower()

    # Indented lines after "Bill compared with:" are deltas
    if indent >= 4:
        if label_lower.startswith(("appropriation,", "appropriations,")):
            return "delta_vs_enacted"
        if label_lower.startswith(("budget request", "budget estimate")):
            return "delta_vs_estimate"

    return None


def extract_inline_tables(
    text: str,
    report_id: str,
    congress: int,
    chamber: str,
    fiscal_year: int | None = None,
    subcommittee: str | None = None,
) -> list[InlineFundingTable]:
    """Extract all inline funding tables from a report's text content.

    Args:
        text: Full text content of the report (from HTML <pre> block)
        report_id: GovInfo package ID
        congress: Congress number
        chamber: "house" or "senate"
        fiscal_year: Target fiscal year
        subcommittee: Canonical subcommittee name

    Returns:
        List of extracted InlineFundingTable objects
    """
    lines = text.split("\n")
    chamber_enum = Chamber.HOUSE if chamber == "house" else Chamber.SENATE
    results: list[InlineFundingTable] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect start of a funding block
        is_start = _SENATE_START_RE.match(line) or _HOUSE_START_RE.match(line)
        if not is_start:
            i += 1
            continue

        # Found a block start — collect all lines in the block
        block_start = i
        block_lines: list[str] = []

        while i < len(lines):
            current = lines[i]

            # Check for "Bill compared with:" header
            if _BILL_COMPARED_RE.match(current):
                block_lines.append(current)
                i += 1
                continue

            # Check if this line is a funding line (label + dots + amount)
            match = _FUNDING_LINE_RE.match(current)
            if match:
                block_lines.append(current)
                i += 1
                continue

            # Empty or whitespace-only lines within a block are ok
            if not current.strip() and block_lines:
                # Check if the NEXT non-empty line is still part of the block
                next_nonempty = None
                for j in range(i + 1, min(i + 3, len(lines))):
                    if lines[j].strip():
                        next_nonempty = lines[j]
                        break

                if next_nonempty and _FUNDING_LINE_RE.match(next_nonempty):
                    block_lines.append(current)
                    i += 1
                    continue

                # End of block
                break

            # Not a funding line or empty — end of block
            break

        # Parse the collected block
        if len(block_lines) >= 2:
            table = _parse_block(
                block_lines=block_lines,
                block_start=block_start,
                all_lines=lines,
                report_id=report_id,
                congress=congress,
                chamber_enum=chamber_enum,
                fiscal_year=fiscal_year,
                subcommittee=subcommittee,
            )
            if table:
                results.append(table)

        # Guarantee forward progress. A block-start line that is not itself a funding
        # line — e.g. "Appropriation, fiscal year 2026 cost of direct loan   $11,710,000"
        # (spaces, no dot leaders) matches _HOUSE_START_RE but not _FUNDING_LINE_RE — would
        # otherwise leave i pinned at block_start and loop forever.
        if i == block_start:
            i += 1

    return results


def _parse_block(
    block_lines: list[str],
    block_start: int,
    all_lines: list[str],
    report_id: str,
    congress: int,
    chamber_enum: Chamber,
    fiscal_year: int | None,
    subcommittee: str | None,
) -> InlineFundingTable | None:
    """Parse a collected block of funding lines into an InlineFundingTable."""
    heading = _repair_dropcap(_find_nearest_heading(all_lines, block_start))
    raw_text_block = "\n".join(block_lines)

    prior_year: DollarAmount | None = None
    budget_estimate: DollarAmount | None = None
    committee_rec: DollarAmount | None = None
    delta_enacted: DollarAmount | None = None
    delta_estimate: DollarAmount | None = None

    in_compared_section = False

    for line in block_lines:
        if _BILL_COMPARED_RE.match(line):
            in_compared_section = True
            continue

        match = _FUNDING_LINE_RE.match(line)
        if not match:
            continue

        indent = len(match.group("indent"))
        label = match.group("label")
        amount_text = match.group("amount")
        amount = parse_dollar(amount_text)

        if in_compared_section:
            delta_type = _is_delta_line(label, indent)
            if delta_type == "delta_vs_enacted":
                delta_enacted = amount
            elif delta_type == "delta_vs_estimate":
                delta_estimate = amount
        else:
            label_type = _parse_label_type(label)
            if label_type == "prior_year":
                prior_year = amount
            elif label_type == "budget_estimate":
                budget_estimate = amount
            elif label_type == "committee_recommendation":
                committee_rec = amount

    # Need at least prior_year or recommendation to be a valid block
    if not prior_year and not committee_rec:
        return None

    return InlineFundingTable(
        report_id=report_id,
        congress=congress,
        chamber=chamber_enum,
        fiscal_year=fiscal_year,
        subcommittee=subcommittee,
        context_heading=heading,
        account_name=heading if heading else None,
        prior_year=prior_year,
        budget_estimate=budget_estimate,
        committee_recommendation=committee_rec,
        delta_vs_enacted=delta_enacted,
        delta_vs_estimate=delta_estimate,
        raw_text_block=raw_text_block,
        line_number=block_start + 1,  # 1-indexed
    )


def extract_inline_tables_from_pdf(
    pdf_path,
    report_id: str,
    congress: int,
    chamber: str,
    fiscal_year: int | None = None,
    subcommittee: str | None = None,
) -> list[InlineFundingTable]:
    """Extract inline funding tables from a born-digital PDF's text layer.

    Some reports are published only as a born-digital PDF with no HTML rendering
    (GovInfo serves a cover-page stub) -- e.g. Senate Labor-HHS FY2026
    (CRPT-119srpt55), whose comparative figures live in per-account prose
    mini-tables rather than a comparative statement. Read the PDF text layer and
    run the same parser used for HTML <pre> text.
    """
    import pdfplumber

    with pdfplumber.open(str(pdf_path)) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)

    return extract_inline_tables(
        text=text,
        report_id=report_id,
        congress=congress,
        chamber=chamber,
        fiscal_year=fiscal_year,
        subcommittee=subcommittee,
    )
