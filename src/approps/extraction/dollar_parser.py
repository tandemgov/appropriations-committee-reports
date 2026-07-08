"""Parse dollar amounts from appropriations report text.

Handles all observed formats:
- $1,368,969,000 and 1,368,969,000 (with/without $ sign)
- (500,000) — parenthesized (negative or mandatory spending)
- --- or - - - or ................ — zero/not applicable
- +46,900 or -134,367 — signed deltas
- [In thousands of dollars] context — multiply by 1,000
"""

from __future__ import annotations

import re

from approps.output.schemas import DollarAmount

# Matches a dollar amount: optional sign, optional $, digits with commas
_AMOUNT_RE = re.compile(
    r"""
    (?P<paren_open>\()?          # optional opening paren
    (?P<sign>[+\-])?             # optional sign
    \$?                          # optional dollar sign
    (?P<digits>[\d,]+)           # digits with commas
    (?P<paren_close>\))?         # optional closing paren
    """,
    re.VERBOSE,
)

# Matches "not applicable" / zero markers
_ZERO_RE = re.compile(r"^[\s.]*[-–—]+[\s.]*$|^[\s.]+$|^-\s*-\s*-$")


def parse_dollar(
    raw_text: str, in_thousands: bool = False, paren_negative: bool = True
) -> DollarAmount:
    """Parse a single dollar amount from raw text.

    Args:
        raw_text: The text to parse (e.g., "$1,234,567" or "(500,000)" or "---")
        in_thousands: If True, multiply the parsed value by 1,000
        paren_negative: If True (default), a parenthesized number with no explicit
            sign is treated as negative (accounting convention). Set False for
            House comparative statements, where parentheses mark a non-add memo
            component (e.g. "(Appropriations)" gross figures) that is positive;
            in those tables sign is conveyed only by an explicit + or -.

    Returns:
        DollarAmount with the parsed integer value and original text
    """
    text = raw_text.strip()

    # Check for zero/not-applicable markers
    if not text or _ZERO_RE.match(text):
        return DollarAmount(value=None, raw_text=raw_text, in_thousands=in_thousands)

    match = _AMOUNT_RE.search(text)
    if not match:
        return DollarAmount(value=None, raw_text=raw_text, in_thousands=in_thousands)

    digits_str = match.group("digits").replace(",", "")
    try:
        value = int(digits_str)
    except ValueError:
        return DollarAmount(value=None, raw_text=raw_text, in_thousands=in_thousands)

    # Handle sign: an explicit +/- always wins; a bare parenthesized number is
    # negative only when paren_negative is set (accounting convention).
    is_negative = False
    if match.group("sign") == "-":
        is_negative = True
    elif match.group("sign") == "+":
        is_negative = False
    elif paren_negative and match.group("paren_open") and match.group("paren_close"):
        is_negative = True

    if is_negative:
        value = -value

    # Apply thousands multiplier
    if in_thousands:
        value *= 1_000

    return DollarAmount(value=value, raw_text=raw_text, in_thousands=in_thousands)


def parse_dollar_columns(
    text: str, column_positions: list[tuple[int, int]], in_thousands: bool = False
) -> list[DollarAmount]:
    """Parse multiple dollar amounts from a fixed-width line using column positions.

    Args:
        text: A single line of text
        column_positions: List of (start, end) character positions for each column
        in_thousands: Whether values are in thousands

    Returns:
        List of DollarAmount, one per column
    """
    results = []
    for start, end in column_positions:
        raw = text[start:end] if end <= len(text) else text[start:]
        results.append(parse_dollar(raw.strip(), in_thousands=in_thousands))
    return results
