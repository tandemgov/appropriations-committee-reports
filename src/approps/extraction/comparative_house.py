"""Parse House comparative statement tables from PDF using vision models.

House reports have comparative statement tables as IMAGES in the PDF.
pdfplumber cannot extract text from these image-based pages.

Strategy:
1. Identify image-bearing pages in the PDF (pages 140+ typically)
2. Convert each page to a high-resolution image
3. Send to a vision model for structured extraction
4. Parse the JSON response into ComparativeStatementLine objects
5. Verify extracted amounts

Supports three backends:
- "gemini": Google Gemini Flash (free tier, 15 RPM) — recommended default
- "openai-compat": Any OpenAI-compatible API (LM Studio, ollama, vLLM, etc.)
- "anthropic": Claude Vision API (requires ANTHROPIC_API_KEY)

Configure via environment variables:
  VISION_BACKEND=gemini  (default)
  GEMINI_API_KEY=your-key  (get free at https://aistudio.google.com/apikey)
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from pathlib import Path

import httpx
import pdfplumber

from approps.config import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    GEMINI_VERTEX,
    VISION_API_KEY,
    VISION_BACKEND,
    VISION_BASE_URL,
    VISION_MODEL,
    gemini_client,
)
from approps.extraction.dollar_parser import parse_dollar
from approps.extraction.hierarchy import is_subtotal_line
from approps.output.schemas import (
    Chamber,
    ComparativeStatementLine,
    ExtractionMethod,
    HierarchyLevel,
    Stage,
)

logger = logging.getLogger(__name__)

# The structured prompt for vision models
_EXTRACTION_PROMPT = """You are extracting data from a comparative statement table in a Congressional appropriations committee report.

This table shows line items with these columns:
1. Item name (left side, hierarchically indented)
2. Prior year enacted appropriation (first number column)
3. Budget estimate (second number column)
4. Committee recommendation (third number column)
5. Committee recommendation compared with prior year (fourth column, + or -)
6. Committee recommendation compared with budget estimate (fifth column, + or -)

All values are in THOUSANDS of dollars.

Extract EVERY line item from this page. For each line item, output a JSON object with:
- "text": the item name exactly as it appears
- "indent": approximate indentation level (0=leftmost, 1=slightly indented, 2=more, etc.)
- "is_subtotal": true if this is a Total or Subtotal line
- "col1": prior year enacted (as string, e.g., "112,340" or "" if blank/dots)
- "col2": budget estimate (as string)
- "col3": committee recommendation (as string)
- "col4": delta vs prior year (as string, including + or - sign)
- "col5": delta vs budget estimate (as string, including + or - sign)

Use empty string "" for columns with dots (.......) or dashes (---) meaning zero/not applicable.
Use parentheses for negative amounts shown in parens, e.g., "(34,000)".

Output ONLY a JSON array of objects. No other text."""


def _find_image_pages(pdf: pdfplumber.PDF) -> list[int]:
    """Find page indices that contain images (comparative statement pages)."""
    image_pages = []
    for i, page in enumerate(pdf.pages):
        if page.images:
            for img in page.images:
                width = img.get("width", 0)
                height = img.get("height", 0)
                if width > 200 and height > 200:
                    image_pages.append(i)
                    break
    return image_pages


def _page_to_base64_png(page: pdfplumber.pdf.Page, resolution: int = 300) -> str:
    """Convert a PDF page to a base64-encoded PNG image."""
    img = page.to_image(resolution=resolution)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")


def _extract_with_openai_compat(
    image_b64: str,
    page_number: int,
) -> list[dict]:
    """Send a page image to an OpenAI-compatible vision API (LM Studio, ollama, etc.)."""
    url = f"{VISION_BASE_URL}/chat/completions"

    payload = {
        "model": VISION_MODEL,
        "max_tokens": 8192,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": _EXTRACTION_PROMPT,
                    },
                ],
            }
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VISION_API_KEY}",
    }

    response = httpx.post(url, json=payload, headers=headers, timeout=600.0)
    response.raise_for_status()

    data = response.json()
    response_text = data["choices"][0]["message"]["content"].strip()
    return _parse_json_response(response_text, page_number)


def _extract_with_anthropic(
    image_b64: str,
    page_number: int,
) -> list[dict]:
    """Send a page image to the Claude Vision API."""
    import anthropic

    if not ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY is required when VISION_BACKEND=anthropic. "
            "Set it in your .env file."
        )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": _EXTRACTION_PROMPT,
                    },
                ],
            }
        ],
    )

    response_text = message.content[0].text.strip()
    return _parse_json_response(response_text, page_number)


def _parse_json_response(response_text: str, page_number: int) -> list[dict]:
    """Parse a JSON response from a vision model."""
    # Strip markdown code fences if present
    json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", response_text, re.DOTALL)
    if json_match:
        response_text = json_match.group(1)

    try:
        items = json.loads(response_text)
        if isinstance(items, list):
            logger.info(f"Page {page_number}: extracted {len(items)} items")
            return items
    except json.JSONDecodeError as e:
        logger.error(f"Page {page_number}: failed to parse response: {e}")
        logger.debug(f"Response was: {response_text[:500]}")

    return []


def _extract_with_gemini(
    image_b64: str,
    page_number: int,
) -> list[dict]:
    """Send a page image to the Gemini API (free tier)."""
    from google import genai

    if not GEMINI_VERTEX and not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is required when VISION_BACKEND=gemini (or set GEMINI_VERTEX=1 "
            "to use Vertex/ADC). Get a free key at https://aistudio.google.com/apikey"
        )

    client = gemini_client()

    image_bytes = base64.standard_b64decode(image_b64)

    response = client.models.generate_content(
        model=VISION_MODEL,
        contents=[
            genai.types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            _EXTRACTION_PROMPT,
        ],
    )

    response_text = response.text.strip()
    return _parse_json_response(response_text, page_number)


def _extract_page(image_b64: str, page_number: int) -> list[dict]:
    """Route to the configured vision backend."""
    if VISION_BACKEND == "gemini":
        return _extract_with_gemini(image_b64, page_number)
    elif VISION_BACKEND == "anthropic":
        return _extract_with_anthropic(image_b64, page_number)
    else:
        return _extract_with_openai_compat(image_b64, page_number)


def _items_to_lines(
    items: list[dict],
    report_id: str,
    congress: int,
    fiscal_year: int | None,
    subcommittee: str | None,
    page_number: int,
    current_title: str | None = None,
    current_dept: str | None = None,
) -> tuple[list[ComparativeStatementLine], str | None, str | None]:
    """Convert extracted items to ComparativeStatementLine objects.

    Returns (lines, updated_current_title, updated_current_dept).
    """
    results = []

    for item in items:
        text = item.get("text", "").strip()
        if not text:
            continue

        indent = item.get("indent", 0)
        is_sub = item.get("is_subtotal", False) or is_subtotal_line(text)

        # Parse amounts (in thousands). In these tables parentheses mark non-add
        # memo components (e.g. gross "(Appropriations)"), which are positive;
        # sign is given only by an explicit + or -, so paren_negative=False.
        col1 = parse_dollar(item.get("col1", ""), in_thousands=True, paren_negative=False)
        col2 = parse_dollar(item.get("col2", ""), in_thousands=True, paren_negative=False)
        col3 = parse_dollar(item.get("col3", ""), in_thousands=True, paren_negative=False)
        col4 = parse_dollar(item.get("col4", ""), in_thousands=True, paren_negative=False)
        col5 = parse_dollar(item.get("col5", ""), in_thousands=True, paren_negative=False)

        # Determine hierarchy level
        if re.match(r"TITLE\s+[IVXLC]+", text):
            level = HierarchyLevel.TITLE
            current_title = text
            current_dept = None
        elif text.isupper() and indent < 2 and not is_sub:
            level = HierarchyLevel.DEPARTMENT
            current_dept = text
        elif indent == 0:
            level = HierarchyLevel.ACCOUNT
        elif indent <= 1:
            level = HierarchyLevel.PROGRAM
        else:
            level = HierarchyLevel.SUBPROGRAM

        results.append(ComparativeStatementLine(
            report_id=report_id,
            congress=congress,
            chamber=Chamber.HOUSE,
            fiscal_year=fiscal_year,
            subcommittee=subcommittee,
            stage=Stage.COMMITTEE,
            title_name=current_title,
            department=current_dept,
            agency=None,
            account=None,
            program=text if level.value >= HierarchyLevel.PROGRAM.value else None,
            hierarchy_depth=level.value,
            line_item_text=text,
            prior_year_enacted=col1,
            budget_estimate=col2,
            committee_recommendation=col3,
            delta_vs_enacted=col4,
            delta_vs_estimate=col5,
            is_subtotal=is_sub,
            in_thousands=True,
            line_number=page_number * 100,  # Approximate
            verified=False,
            extraction_method=ExtractionMethod.LLM,
        ))

    return results, current_title, current_dept


def extract_house_comparative(
    pdf_path: Path,
    report_id: str,
    congress: int,
    fiscal_year: int | None = None,
    subcommittee: str | None = None,
    max_pages: int | None = None,
) -> list[ComparativeStatementLine]:
    """Extract all line items from a House comparative statement table via PDF.

    Uses a vision model (local or API) to read image-based table pages.

    Args:
        pdf_path: Path to the downloaded PDF file
        report_id: GovInfo package ID
        congress: Congress number
        fiscal_year: Target fiscal year
        subcommittee: Canonical subcommittee name
        max_pages: Limit number of pages to process (for testing)

    Returns:
        List of extracted ComparativeStatementLine objects
    """
    logger.info(f"Using vision backend: {VISION_BACKEND} ({VISION_MODEL})")

    pdf = pdfplumber.open(str(pdf_path))
    image_pages = _find_image_pages(pdf)

    if not image_pages:
        logger.warning(f"{report_id}: no image pages found in PDF")
        return []

    if max_pages:
        image_pages = image_pages[:max_pages]

    logger.info(
        f"{report_id}: found {len(image_pages)} image pages "
        f"(pages {image_pages[0]+1}-{image_pages[-1]+1})"
    )

    all_lines: list[ComparativeStatementLine] = []
    current_title: str | None = None
    current_dept: str | None = None

    for page_idx in image_pages:
        page = pdf.pages[page_idx]
        page_num = page_idx + 1

        logger.info(f"  Processing page {page_num}...")

        # Convert page to image at high resolution for better OCR/vision
        image_b64 = _page_to_base64_png(page, resolution=300)

        # Extract with vision model
        try:
            items = _extract_page(image_b64, page_num)
        except Exception as e:
            logger.error(f"  Page {page_num} failed: {e}")
            logger.info("  Saving partial results and stopping.")
            break

        # Convert to structured lines
        lines, current_title, current_dept = _items_to_lines(
            items=items,
            report_id=report_id,
            congress=congress,
            fiscal_year=fiscal_year,
            subcommittee=subcommittee,
            page_number=page_num,
            current_title=current_title,
            current_dept=current_dept,
        )

        all_lines.extend(lines)

    logger.info(f"{report_id}: extracted {len(all_lines)} total lines from PDF")
    return all_lines
