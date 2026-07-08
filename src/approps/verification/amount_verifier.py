"""Three-tier string matching verification of extracted dollar amounts.

Modeled after the cgorski/congress-appropriations verification approach:
every extracted dollar amount must be traceable to the source text.
"""

from __future__ import annotations

import re

from approps.output.schemas import DollarAmount, VerificationResult, VerificationTier


def _normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace to single space, strip edges."""
    return re.sub(r"\s+", " ", text).strip()


def _remove_all_whitespace(text: str) -> str:
    """Remove all whitespace characters."""
    return re.sub(r"\s+", "", text)


def verify_amount(amount: DollarAmount, source_text: str) -> VerificationResult:
    """Verify that a dollar amount's raw text appears in the source document.

    Uses three tiers of matching:
    1. Exact: raw_text appears verbatim in source
    2. Normalized: after collapsing whitespace in both
    3. Spaceless: after removing all whitespace from both

    Args:
        amount: The extracted dollar amount with raw_text
        source_text: The full text of the source document

    Returns:
        VerificationResult with the tier that matched (or FAILED)
    """
    raw = amount.raw_text
    if not raw:
        return VerificationResult(
            amount=amount, tier=VerificationTier.FAILED, matched=False
        )

    # Tier 1: Exact match
    if raw in source_text:
        # Find surrounding context
        idx = source_text.index(raw)
        start = max(0, idx - 40)
        end = min(len(source_text), idx + len(raw) + 40)
        context = source_text[start:end]
        return VerificationResult(
            amount=amount,
            tier=VerificationTier.EXACT,
            matched=True,
            source_context=context,
        )

    # Tier 2: Normalized whitespace
    norm_raw = _normalize_whitespace(raw)
    norm_source = _normalize_whitespace(source_text)
    if norm_raw in norm_source:
        idx = norm_source.index(norm_raw)
        start = max(0, idx - 40)
        end = min(len(norm_source), idx + len(norm_raw) + 40)
        return VerificationResult(
            amount=amount,
            tier=VerificationTier.NORMALIZED,
            matched=True,
            source_context=norm_source[start:end],
        )

    # Tier 3: Spaceless
    spaceless_raw = _remove_all_whitespace(raw)
    spaceless_source = _remove_all_whitespace(source_text)
    if spaceless_raw in spaceless_source:
        return VerificationResult(
            amount=amount,
            tier=VerificationTier.SPACELESS,
            matched=True,
        )

    # Failed all tiers
    return VerificationResult(
        amount=amount, tier=VerificationTier.FAILED, matched=False
    )


def verify_amounts(
    amounts: list[DollarAmount], source_text: str
) -> list[VerificationResult]:
    """Verify a list of dollar amounts against source text."""
    return [verify_amount(a, source_text) for a in amounts]
