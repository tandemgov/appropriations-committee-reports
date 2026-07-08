"""Tests for the verification framework."""

from approps.output.schemas import DollarAmount, VerificationTier
from approps.verification.amount_verifier import verify_amount


SOURCE_TEXT = """
Appropriation, fiscal year 2024.......................      $404,695,000
Budget request, fiscal year 2025......................       358,466,000
Recommended in the bill...............................       281,358,000
"""


def test_exact_match():
    amount = DollarAmount(value=404_695_000, raw_text="$404,695,000")
    result = verify_amount(amount, SOURCE_TEXT)
    assert result.matched is True
    assert result.tier == VerificationTier.EXACT


def test_normalized_match():
    # Extra whitespace in raw_text that gets collapsed
    amount = DollarAmount(value=358_466_000, raw_text="358,466,000")
    result = verify_amount(amount, SOURCE_TEXT)
    assert result.matched is True


def test_spaceless_match():
    # Whitespace difference that only spaceless catches
    source = "  1,234  ,  567  "
    amount = DollarAmount(value=1_234_567, raw_text="1,234,567")
    result = verify_amount(amount, source)
    assert result.matched is True
    assert result.tier == VerificationTier.SPACELESS


def test_failed_verification():
    amount = DollarAmount(value=999_999, raw_text="$999,999")
    result = verify_amount(amount, SOURCE_TEXT)
    assert result.matched is False
    assert result.tier == VerificationTier.FAILED


def test_empty_raw_text():
    amount = DollarAmount(value=0, raw_text="")
    result = verify_amount(amount, SOURCE_TEXT)
    assert result.matched is False
    assert result.tier == VerificationTier.FAILED


def test_context_captured():
    amount = DollarAmount(value=281_358_000, raw_text="281,358,000")
    result = verify_amount(amount, SOURCE_TEXT)
    assert result.matched is True
    assert result.source_context is not None
    assert "281,358,000" in result.source_context
