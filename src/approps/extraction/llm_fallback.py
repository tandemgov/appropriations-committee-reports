"""Claude API fallback for sections where rule-based parsing fails.

Used when:
- Comparative statement formatting is too irregular for the rule-based parser
- PDF table extraction via pdfplumber produces garbled output
- Older report formats differ significantly from expected patterns

All LLM-extracted data goes through the same verification pipeline and
is flagged with extraction_method="llm" for transparency.

This is Sprint 4+ work — stub for now.
"""

from __future__ import annotations


def extract_with_llm(text: str, report_id: str, context: str = "") -> dict:
    """Use Claude to extract structured data from difficult text sections.

    Args:
        text: The problematic text section to extract from
        report_id: GovInfo package ID for provenance
        context: Additional context about what we expect to find

    Returns:
        Dict matching the extraction schema
    """
    # TODO: Implement using Anthropic SDK
    # 1. Build prompt with schema description and text
    # 2. Call Claude API
    # 3. Parse response JSON
    # 4. Validate against Pydantic schema
    raise NotImplementedError("LLM fallback extraction is under development")
