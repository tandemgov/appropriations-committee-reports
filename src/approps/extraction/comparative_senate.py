"""Parse Senate comparative statement tables from HTML text.

Senate reports contain the comparative statement as TEXT in their HTML.
Format: fixed-width columnar data in a <pre> block.

The table has 5 numeric columns:
    1. Prior year appropriation
    2. Budget estimate
    3. Committee recommendation
    4. Committee vs prior year (delta)
    5. Committee vs budget estimate (delta)

Values are in thousands of dollars.

Hierarchy is indicated by:
    - TITLE I-- lines (all caps, title level)
    - ALL CAPS lines (agency/bureau level)
    - Title Case lines (account level)
    - Indented lines with colons (sub-category headers, e.g., "Land Resources:")
    - Further indented lines (program/subprogram level)
    - Subtotal/Total lines
"""

from __future__ import annotations

import re

from approps.extraction.dollar_parser import is_paren_memo, parse_dollar
from approps.extraction.hierarchy import is_subtotal_line
from approps.output.schemas import (
    Chamber,
    ComparativeStatementLine,
    HierarchyLevel,
    Stage,
)

# Regex to find the start of the comparative statement section
_COMP_START_RE = re.compile(r"COMPARATIVE STATEMENT OF NEW BUDGET", re.IGNORECASE)

# Separator line (all dashes or equals)
_SEPARATOR_RE = re.compile(r"^\s*[-=]{20,}\s*$")

# A data line: text on the left, then numbers/dots on the right
# Numbers are right-aligned in fixed-width columns
_DATA_LINE_RE = re.compile(
    r"^(?P<text>.+?)"  # item text (left side)
    r"(?P<numbers>(?:\s{2,}(?:[\d,]+|\([\d,+]+\)|[+\-][\d,]+|\.\.\.*|(?:\+\([\d,]+\))|\(-[\d,]+\)))+)"  # numeric columns
    r"\s*$"
)

# Alternative: detect lines with at least 2 number-like patterns separated by whitespace
_HAS_NUMBERS_RE = re.compile(
    r"(?:[\d,]{3,}|\([\d,]+\)|[+\-][\d,]+|\.{4,})"
)

# Title line pattern
_TITLE_RE = re.compile(r"^\s*TITLE\s+[IVXLC]+")

# "In thousands" indicator
_THOUSANDS_RE = re.compile(r"\[In thousands of dollars\]", re.IGNORECASE)

# One numeric cell: a dollar amount, a signed delta, a parenthesized memo, or a run of dots
# standing in for a blank column. Shared by the dot-leader and the column-aligned readers.
_NUM_TOKEN = re.compile(r"(?:\(\+?[\d,]+\))|(?:[+\-][\d,]+)|(?:[\d,]{3,})|(?:\.{4,})")

# A dot leader trailing to end of line, used to strip it off a label.
_TRAIL_DOTS = re.compile(r"\.{2,}\s*$")

# A wrapped-label continuation line: word text (no digits) ending in a dot leader, e.g.
# "       this bill.............................................." -- the tail of a label too
# long to fit on the row that carried its numbers. Requires a letter so a bare dashed
# separator never matches.
_CONTINUATION_RE = re.compile(r"^(?=.*[A-Za-z])[^\d]*?\.{2,}\s*$")

# How far a numeric token's right edge may sit from a declared column edge and still count as
# occupying that column. The columns are right-aligned, so the right edge is the stable signal.
_EDGE_TOLERANCE = 2


def _columnar_split(line: str, edges: list[int]) -> tuple[str, list[str]] | None:
    """Split a data line into ``(label, five column tokens)`` using the table's column edges.

    The dot-leader reader (below) fails on rows whose label is long enough to squeeze the
    leader down to one or two dots, or off the line entirely -- the numbers still print in
    their fixed-width columns, but there is no ``...`` to split on. Those rows were silently
    dropped, deleting real line items (many of them ``Total`` rows, whose loss also corrupts
    the block structure the reconciler recovers from document order).

    Here the columns adjudicate instead of the leader: a token counts only if its right edge
    lands on a declared column edge, which excludes numbers embedded in the label (a public
    law cite, a fiscal year) because those do not align. The label is everything left of the
    leftmost aligned cell, so a blank leading column printed as a dot run is kept out of it.
    Requires at least two aligned numeric cells, so a lone coincidental alignment is not read
    as a data row.
    """
    aligned: list[tuple[int, int, str]] = []  # (column index, start position, token)
    for match in _NUM_TOKEN.finditer(line):
        j = min(range(len(edges)), key=lambda k: abs(match.end() - edges[k]))
        if abs(match.end() - edges[j]) <= _EDGE_TOLERANCE:
            aligned.append((j, match.start(), match.group()))

    numeric = [tok for _, _, tok in aligned if not tok.startswith(".")]
    if len(numeric) < 2:
        return None

    start = min(pos for _, pos, _ in aligned)
    label = _TRAIL_DOTS.sub("", line[:start]).strip()
    if not label:
        return None

    slots = [""] * len(edges)
    for j, _, tok in aligned:
        slots[j] = tok
    return label, slots


def _find_comparative_section(lines: list[str]) -> tuple[int, int] | None:
    """Find the start and end line indices of the comparative statement section.

    Must distinguish the actual section heading from table-of-contents references.
    The real heading is typically preceded by a separator line (------) and followed
    by "[In thousands of dollars]".
    """
    start = None
    for i, line in enumerate(lines):
        if _COMP_START_RE.search(line):
            # Verify this is the actual section, not a TOC reference.
            # TOC lines have page numbers after dots (e.g., "Comparative Statement...  284")
            # The real heading should be followed within ~5 lines by "[In thousands of dollars]"
            is_real = False
            for j in range(i, min(i + 8, len(lines))):
                if _THOUSANDS_RE.search(lines[j]):
                    is_real = True
                    break
            if is_real:
                start = i
                break

    if start is None:
        return None

    # Find the end: look for the next major non-table section or end of document
    # The table typically runs to the end of the document, or until MINORITY/DISSENTING VIEWS
    end = len(lines)
    for i in range(start + 20, len(lines)):
        line = lines[i].strip()
        if line in ("MINORITY VIEWS", "DISSENTING VIEWS", "ADDITIONAL VIEWS"):
            end = i
            break

    return start, end


def _find_column_positions(lines: list[str], section_start: int) -> list[tuple[int, int]] | None:
    """Detect column positions from the header area of the comparative statement.

    Scans the first data lines to find where numeric columns are positioned.
    Returns list of (start, end) character positions for each of 5 columns.
    """
    # Strategy: find the first few data lines and identify column boundaries
    # by looking at where numbers cluster horizontally
    number_positions: list[list[int]] = []

    for i in range(section_start, min(section_start + 50, len(lines))):
        line = lines[i]
        if _SEPARATOR_RE.match(line):
            continue

        # Find all number-like tokens and their positions
        for match in re.finditer(r"(?:[\d,]{3,}|\([\d,+]+\)|[+\-][\d,]+)", line):
            end_pos = match.end()
            number_positions.append([end_pos])

    if not number_positions:
        return None

    # Flatten and find clusters of right-edge positions
    all_ends = sorted([p[0] for p in number_positions])

    if len(all_ends) < 5:
        return None

    # Cluster the end positions to find column boundaries
    clusters = _cluster_positions(all_ends, tolerance=3)

    if len(clusters) < 5:
        # Try again with larger tolerance
        clusters = _cluster_positions(all_ends, tolerance=5)

    if len(clusters) < 5:
        return None

    # Take the 5 most common clusters as column right edges
    clusters.sort(key=lambda c: len(c), reverse=True)
    col_ends = sorted([int(sum(c) / len(c)) for c in clusters[:5]])

    # Derive column boundaries (start, end)
    # Each column starts where the previous one ends (with some gap)
    positions = []
    for j, end in enumerate(col_ends):
        if j == 0:
            start = end - 20  # first column starts ~20 chars before its right edge
        else:
            start = col_ends[j - 1] + 1
        positions.append((max(0, start), end + 2))

    return positions


def _cluster_positions(values: list[int], tolerance: int = 3) -> list[list[int]]:
    """Cluster nearby integer values together."""
    if not values:
        return []

    clusters: list[list[int]] = [[values[0]]]
    for v in values[1:]:
        if abs(v - clusters[-1][-1]) <= tolerance:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return clusters


def _parse_hierarchy_context(
    text: str, indent: int
) -> tuple[HierarchyLevel, bool]:
    """Determine the hierarchy level and whether this is a subtotal line."""
    stripped = text.strip()

    if not stripped:
        return HierarchyLevel.TITLE, False

    subtotal = is_subtotal_line(stripped)

    # TITLE line
    if _TITLE_RE.match(stripped):
        return HierarchyLevel.TITLE, subtotal

    # All caps = higher level (department/agency)
    # Check if the text portion (before dots) is all uppercase
    text_part = stripped.split("...")[0].strip().rstrip(".")
    if text_part and text_part.replace(",", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "").isupper():
        if indent < 8:
            return HierarchyLevel.DEPARTMENT, subtotal
        return HierarchyLevel.AGENCY, subtotal

    # Category header lines end with ":"
    if stripped.endswith(":"):
        return HierarchyLevel.ACCOUNT, False

    # Indentation-based
    if indent < 4:
        return HierarchyLevel.ACCOUNT, subtotal
    if indent < 8:
        return HierarchyLevel.PROGRAM, subtotal
    return HierarchyLevel.SUBPROGRAM, subtotal


def _extract_numbers_from_line(line: str, item_text_end: int) -> list[str]:
    """Extract number tokens from the right portion of a line.

    Args:
        line: Full line text
        item_text_end: Character position where the item text (including dots) ends
    """
    right_part = line[item_text_end:]

    # Find all number-like tokens
    tokens = re.findall(
        r"(?:\([\d,+\-]+\))|(?:[+\-][\d,]+)|(?:[\d,]{3,})|(?:\.{4,})",
        right_part,
    )
    return tokens


def extract_senate_comparative(
    text: str,
    report_id: str,
    congress: int,
    fiscal_year: int | None = None,
    subcommittee: str | None = None,
) -> list[ComparativeStatementLine]:
    """Extract all line items from a Senate comparative statement table."""
    lines = text.split("\n")

    # Find the comparative statement section
    section = _find_comparative_section(lines)
    if section is None:
        return []

    section_start, section_end = section

    # Column right edges, used to read rows whose dot leader was squeezed out (see
    # _columnar_split). None when the header geometry is unclear, in which case only the
    # dot-leader reader runs -- no regression, just no recovery for that report.
    positions = _find_column_positions(lines, section_start)
    edges = [end - 2 for _, end in positions] if positions else None

    # Check for "In thousands of dollars"
    in_thousands = False
    for i in range(section_start, min(section_start + 10, len(lines))):
        if _THOUSANDS_RE.search(lines[i]):
            in_thousands = True
            break

    # Skip past the header area (find the separator after column headers)
    data_start = section_start
    separator_count = 0
    for i in range(section_start, min(section_start + 20, len(lines))):
        if _SEPARATOR_RE.match(lines[i]):
            separator_count += 1
            if separator_count >= 3:  # After the third separator, data begins
                data_start = i + 1
                break

    # Track hierarchy context
    current_title: str | None = None
    current_dept: str | None = None
    current_agency: str | None = None
    current_account: str | None = None

    results: list[ComparativeStatementLine] = []

    i = data_start
    while i < section_end:
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines and separator lines
        if not stripped or _SEPARATOR_RE.match(line):
            i += 1
            continue

        # Skip header repeat lines (page breaks within the table)
        if "Item" in stripped and "appropriation" in stripped.lower():
            i += 1
            continue
        if "Budget estimate" in stripped or "Committee recommendation" in stripped:
            if "compared with" in stripped.lower() or "recommendation" in stripped:
                i += 1
                continue
        if _THOUSANDS_RE.search(stripped):
            i += 1
            continue

        indent = len(line) - len(line.lstrip())

        # Check if this line has numbers (data line vs header line)
        number_matches = list(_HAS_NUMBERS_RE.finditer(line))
        has_numbers = len(number_matches) >= 1

        # Two readers produce the same ``(item_text, num_tokens)`` shape. The dot-leader reader
        # is the original path and handles the common row; the column reader recovers rows whose
        # leader was squeezed out (see _columnar_split) and is tried only when the first fails.
        item_text: str | None = None
        num_tokens: list[str] | None = None

        if has_numbers and "..." in line:
            # A data line with a dot leader separating text from numbers. Split at the FIRST
            # dot leader -- everything before is the item name, everything after is the columns.
            # Dots WITHIN the number columns represent "no change" / zero.
            dot_match = re.search(r"\.{3,}", line)
            if dot_match:
                item_text = line[: dot_match.start()].rstrip()
                num_tokens = _NUM_TOKEN.findall(line[dot_match.end():])
            else:
                item_text = stripped
                num_tokens = _NUM_TOKEN.findall(line)
        elif has_numbers and edges is not None:
            split = _columnar_split(line, edges)
            if split is not None:
                item_text, num_tokens = split
                # A label too long for its row wraps its tail onto the next line, which carries
                # the leader but no numbers (e.g. "Total, ... appropriated in" / "this bill...").
                # Stitch it back and consume it, so it is neither dropped nor mistaken for a
                # header that would corrupt the hierarchy context for the rows below.
                if i + 1 < section_end and _CONTINUATION_RE.match(lines[i + 1].strip()):
                    tail = _TRAIL_DOTS.sub("", lines[i + 1].strip()).strip()
                    item_text = f"{item_text} {tail}".strip()
                    i += 1

        if item_text is not None and num_tokens is not None:
            # Pad to 5 columns
            while len(num_tokens) < 5:
                num_tokens.append("")

            # Parse each column. Parentheses in a comparative statement mark a non-add memo --
            # a limitation, a transfer authority, an "of which" breakout -- which is positive
            # and already counted inside a sibling line. They are NOT the accounting
            # convention for a negative: real negatives print an explicit minus (`-2,000`),
            # and the token regex above hands those to parse_dollar without their parens. So
            # paren_negative=False, exactly as the House comparative statements do.
            #
            # Reading `(35,000)` as -35,000 is invisible to both of the row-local gates -- the
            # raw text still string-matches the source, and negating every column preserves the
            # delta identity -- and surfaces only against the printed subtotal. See
            # verification.reconcile and tests/test_comparative_senate.py.
            amounts = [
                parse_dollar(t, in_thousands=in_thousands, paren_negative=False)
                for t in num_tokens[:5]
            ]

            # Determine hierarchy
            level, is_sub = _parse_hierarchy_context(item_text, indent)

            # Update hierarchy context
            if level == HierarchyLevel.TITLE:
                current_title = item_text.strip()
                current_dept = None
                current_agency = None
                current_account = None
            elif level == HierarchyLevel.DEPARTMENT:
                current_dept = item_text.strip()
                current_agency = None
                current_account = None
            elif level == HierarchyLevel.AGENCY:
                current_agency = item_text.strip()
                current_account = None
            elif level == HierarchyLevel.ACCOUNT:
                current_account = item_text.strip()

            results.append(ComparativeStatementLine(
                report_id=report_id,
                congress=congress,
                chamber=Chamber.SENATE,
                fiscal_year=fiscal_year,
                subcommittee=subcommittee,
                stage=Stage.COMMITTEE,
                title_name=current_title,
                department=current_dept,
                agency=current_agency,
                account=current_account,
                program=item_text.strip() if level.value >= HierarchyLevel.PROGRAM.value else None,
                hierarchy_depth=level.value,
                line_item_text=item_text.strip(),
                prior_year_enacted=amounts[0] if len(amounts) > 0 else None,
                budget_estimate=amounts[1] if len(amounts) > 1 else None,
                committee_recommendation=amounts[2] if len(amounts) > 2 else None,
                delta_vs_enacted=amounts[3] if len(amounts) > 3 else None,
                delta_vs_estimate=amounts[4] if len(amounts) > 4 else None,
                is_subtotal=is_sub,
                # Flag the memo rows here rather than at output time, so the extracted JSON and
                # the released CSV carry the same claim and reconciliation can run on either.
                is_memo=is_paren_memo(amounts[2] if len(amounts) > 2 else None),
                in_thousands=in_thousands,
                line_number=i + 1,
            ))

        elif not has_numbers and stripped:
            # Header line (no numbers) — update hierarchy context
            if _TITLE_RE.match(stripped):
                current_title = stripped
                current_dept = None
                current_agency = None
                current_account = None
            elif stripped.endswith(":"):
                # Sub-category header (e.g., "Land Resources:")
                current_account = stripped.rstrip(":")
            elif stripped.isupper() and len(stripped) > 3:
                # All caps = department or agency
                if indent < 20:
                    current_dept = stripped
                    current_agency = None
                    current_account = None
                else:
                    current_agency = stripped
                    current_account = None
            else:
                # Title case = account level header
                current_account = stripped

        i += 1

    return results
