"""Parse dollar amounts from appropriations report text.

Handles all observed formats:
- $1,368,969,000 and 1,368,969,000 (with/without $ sign)
- (500,000) — parenthesized: a non-add memo in comparative statements, a negative under the
  accounting convention. Which one is a property of the source table, not of the token, so
  every caller must decide it explicitly via ``paren_negative``.
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
    raw_text: str, in_thousands: bool = False, *, paren_negative: bool
) -> DollarAmount:
    """Parse a single dollar amount from raw text.

    Args:
        raw_text: The text to parse (e.g., "$1,234,567" or "(500,000)" or "---")
        in_thousands: If True, multiply the parsed value by 1,000
        paren_negative: What a bare ``(500,000)`` means in *this* source table. False for
            every comparative statement in this corpus, House and Senate alike: parentheses
            mark a non-add memo component -- a limitation, a transfer authority, an "of which"
            or "(Appropriations)" gross figure -- which is positive and already counted inside
            a sibling line. In those tables sign is conveyed only by an explicit + or -. True
            applies the accounting convention, where the parentheses themselves mean negative.

            Required, and deliberately not defaulted. Which convention a table uses is a
            property of the document, never of the token, and a wrong guess here is invisible
            downstream: the raw text still string-matches the source, and negating every column
            of a row preserves its delta identity. Only a subtotal can catch it. It went
            unnoticed on the Senate track for the life of the project because the default said
            "negative" and nobody had to disagree with it out loud.

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
    text: str,
    column_positions: list[tuple[int, int]],
    in_thousands: bool = False,
    *,
    paren_negative: bool,
) -> list[DollarAmount]:
    """Parse multiple dollar amounts from a fixed-width line using column positions.

    Args:
        text: A single line of text
        column_positions: List of (start, end) character positions for each column
        in_thousands: Whether values are in thousands
        paren_negative: The source table's parenthesis convention; see ``parse_dollar``.

    Returns:
        List of DollarAmount, one per column
    """
    results = []
    for start, end in column_positions:
        raw = text[start:end] if end <= len(text) else text[start:]
        results.append(
            parse_dollar(raw.strip(), in_thousands=in_thousands, paren_negative=paren_negative)
        )
    return results


def is_paren_memo(amount: DollarAmount | None) -> bool:
    """Whether this amount is a parenthesized non-add memo, and so must not be summed.

    Under the comparative-statement convention (``paren_negative=False``) a bare ``(35,000)``
    is a limitation, a transfer authority, or an "of which" breakout: positive, and already
    counted inside a sibling line. Summing it double-counts.

    An inner minus (``(-2,491)``) is a real rescission, not a memo, so a negative value never
    qualifies. Requiring a positive value also means this returns False on any amount parsed
    with ``paren_negative=True`` -- which is the point. A row whose parentheses were read as a
    negative cannot be recognized as a memo, and will surface as a subtotal that does not add
    up rather than being quietly excluded from its own block.
    """
    if amount is None or amount.value is None or amount.value <= 0:
        return False
    raw = (amount.raw_text or "").strip()
    return raw.startswith("(") and "-" not in raw
