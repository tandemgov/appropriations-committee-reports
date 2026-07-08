"""Nemotron-Parse backend for House comparative-statement extraction.

Nemotron-Parse v1.2 is a document-parsing model (not an instruction model), so it
ignores the natural-language extraction prompt the other backends use. It takes a
single RGB image (<=1664x2048) plus an exact 4-token prompt and returns a structured
string: bbox-tagged, class-labelled blocks, with tables emitted as LaTeX ``tabular``.

This module renders a page to fit the model's input cap, calls the vLLM
OpenAI-compatible server, and parses the LaTeX tables back into the same
``{text, indent, is_subtotal, col1..col5}`` item dicts the other backends produce,
so the rest of the pipeline (``_items_to_lines``) is reused unchanged.

Hierarchy note: the LaTeX ``tabular`` flattens visual indentation, so ``indent`` is
always 0 here (hierarchy depth is inferred downstream from text, not x-coordinates).
This does not affect the five VALUE columns, which are what verify_house.py checks.
"""

from __future__ import annotations

import base64
import io
import logging
import re

import httpx
import pdfplumber
from PIL import Image

from approps.config import NEMOTRON_BASE_URL

logger = logging.getLogger(__name__)

# NEMOTRON_BASE_URL is the vLLM OpenAI-compatible endpoint serving this model (see config).
NEMOTRON_MODEL = "nvidia/NVIDIA-Nemotron-Parse-v1.2"

# v1.2 REQUIRES this exact 4-token prompt; output degrades badly without the 4th token.
NEMOTRON_PROMPT = (
    "</s><s><predict_bbox><predict_classes><output_markdown><predict_no_text_in_pic>"
)

# Input window (W x H), from preprocessor_config.json.
MAX_W, MAX_H = 1664, 2048

# max_model_len is 9000 (prompt + image + output); leave headroom for output.
_MAX_TOKENS = 8000

_TABULAR_RE = re.compile(r"\\begin\{tabular\}\{([^}]*)\}(.*?)\\end\{tabular\}", re.DOTALL)
_TAG_RE = re.compile(r"<(?:x|y)_[0-9.]+>|<class_[^>]+>")
_DOTS_RE = re.compile(r"\.{2,}\s*$")
_FOOTNOTE_RE = re.compile(r"_\d+/_")  # e.g. "_1/_" footnote markers inside cells
# \multicolumn{N}{align}{content} -> content (full-width banners like "Administrative
# Provisions" appear inside real comparative tables; keep their text, drop the wrapper).
_MULTICOL_RE = re.compile(r"\\multicolumn\{\d+\}\{[^}]*\}\{([^}]*)\}")

# A comparative statement is a table with an item label plus value columns that the
# HEADER names: prior-year "Enacted", the President's "Request"/"Estimate", the "Bill"
# (committee recommendation), and the "vs." deltas. The classic House layout carries all
# five value columns (6 columns total); some FY2026 bills omit the President's Request
# (and the "Bill vs. Request" delta), yielding a 4-column table with only Enacted / Bill
# / Bill vs. Enacted. We identify comparative tables — and map their columns to the fixed
# col1..col5 slots — from the header NAMES, not the column count, so either layout parses.
# Other tables (302(b) allocations, outlay projections, financial-assistance summaries)
# lack the Enacted+Bill header pair and are excluded.
_DISQUALIFYING = (
    "302(b)",
    "Budget Authority",
    "Projection of outlays",
)

# Fixed output slots (see comparative_house.py): col1 enacted, col2 request,
# col3 bill/recommendation, col4 delta-vs-enacted, col5 delta-vs-request.
_SLOT_ENACTED, _SLOT_REQUEST, _SLOT_BILL, _SLOT_D_ENACTED, _SLOT_D_REQUEST = range(5)


def _header_to_slot(cell: str) -> int | None:
    """Map a value-column header name to its fixed col1..col5 slot (0-4), or None."""
    h = _TAG_RE.sub("", cell).replace("*", "").lower().strip()
    is_delta = "vs" in h or "versus" in h or "change" in h
    wants_request = "request" in h or "estimate" in h
    wants_enacted = "enacted" in h or "prior" in h
    if is_delta:
        if wants_request:
            return _SLOT_D_REQUEST
        if wants_enacted:
            return _SLOT_D_ENACTED
        return None
    if wants_request:
        return _SLOT_REQUEST
    if wants_enacted:
        return _SLOT_ENACTED
    if "bill" in h or "recommend" in h:
        return _SLOT_BILL
    return None


def _header_slots(body: str) -> list[int | None] | None:
    """Find the header row and return the fixed slot for each value column.

    Returns a list aligned to the value columns (the header cells after the empty item
    label), or None if the table has no comparative header (it must name both an Enacted
    and a Bill column).
    """
    for raw_row in body.split(r"\\"):
        row = _MULTICOL_RE.sub(r"\1", raw_row)
        row = _TAG_RE.sub("", row).replace("\n", " ").strip()
        if not row:
            continue
        cells = [c.strip() for c in row.split("&")]
        if _DOTS_RE.sub("", cells[0]).strip():  # a header row has an empty item label
            continue
        slots = [_header_to_slot(c) for c in cells[1:]]
        if _SLOT_ENACTED in slots and _SLOT_BILL in slots:
            return slots
    return None


def _is_comparative_table(spec: str, body: str) -> bool:
    """True only for genuine comparative-statement tables (identified by header names)."""
    if any(kw in body for kw in _DISQUALIFYING):
        return False
    return _header_slots(body) is not None


# House comparative tables are scanned bitonal images embedded in the PDF. The scan
# has a fixed native resolution; rendering the whole PAGE downsamples the scan region
# (most of the page is margin), causing digit OCR errors (notably 6<->8). Cropping to
# the embedded image and rendering IT at native resolution preserves scan fidelity.
_NATIVE_DPI = 300  # at this DPI the cropped image region ~= its native pixel size


def _largest_image_bbox(page: pdfplumber.pdf.Page):
    """Return the (x0, top, x1, bottom) bbox of the largest embedded image, or None."""
    imgs = [im for im in (page.images or []) if im.get("width", 0) > 200 and im.get("height", 0) > 200]
    if not imgs:
        return None
    im = max(imgs, key=lambda i: i.get("width", 0) * i.get("height", 0))
    # Clamp to page box; pdfplumber occasionally reports bboxes slightly outside it.
    return (
        max(im["x0"], 0),
        max(im["top"], 0),
        min(im["x1"], page.width),
        min(im["bottom"], page.height),
    )


def _fit(pil: Image.Image, rotate: bool | None) -> Image.Image:
    if rotate is None:
        rotate = pil.width > pil.height
    if rotate:
        pil = pil.rotate(-90, expand=True)
    if pil.width > MAX_W or pil.height > MAX_H:
        pil.thumbnail((MAX_W, MAX_H), Image.LANCZOS)  # preserves aspect ratio
    return pil


def render_crop(page: pdfplumber.pdf.Page, rotate: bool | None = None) -> Image.Image:
    """Crop to the embedded table scan and render at native resolution, fit to cap.

    Keeps far more digit detail than a full-page render (the scan fills the frame
    instead of being downsampled with the margins), which sharply reduces 6<->8
    style OCR errors. But a tight table crop is out-of-distribution for the model and
    occasionally triggers runaway/degenerate decoding — callers should fall back to
    render_full when that happens (see extract_with_nemotron).
    """
    bbox = _largest_image_bbox(page)
    source = page.crop(bbox) if bbox else page
    return _fit(source.to_image(resolution=_NATIVE_DPI).original.convert("RGB"), rotate)


def render_full(page: pdfplumber.pdf.Page, rotate: bool | None = None) -> Image.Image:
    """Render the whole page to RGB at the largest resolution that fits the cap.

    In-distribution (full document page) so decoding is stable, but the scan region
    is downsampled — lower digit fidelity. Used as the recall-safe fallback.
    """
    if rotate is None:
        rotate = page.width > page.height
    cap_w, cap_h = (MAX_H, MAX_W) if rotate else (MAX_W, MAX_H)
    resolution = min(cap_w * 72.0 / page.width, cap_h * 72.0 / page.height)
    pil = page.to_image(resolution=resolution).original.convert("RGB")
    if rotate:
        pil = pil.rotate(-90, expand=True)
    return pil


# Back-compat alias (the probe script imports render_fit).
render_fit = render_crop


def parse_page(raw: str) -> list[dict]:
    """Parse Nemotron's raw structured string into extraction item dicts."""
    items: list[dict] = []
    for spec, body in _TABULAR_RE.findall(raw):
        if not _is_comparative_table(spec, body):
            continue
        slots = _header_slots(body)
        n_val = len(slots)  # value columns this table actually carries (3 or 5)
        for raw_row in body.split(r"\\"):
            row = _MULTICOL_RE.sub(r"\1", raw_row)
            row = _TAG_RE.sub("", row).replace("\n", " ").strip()
            if not row:
                continue
            cells = [c.strip() for c in row.split("&")]
            text = _DOTS_RE.sub("", cells[0]).strip()
            # Column-title header row (empty label, names the value columns) — skip.
            if not text and any(
                kw in row for kw in ("Enacted", "Request", "Bill")
            ):
                continue
            # Distribute the value cells into the fixed col1..col5 slots via the header
            # map. Robust to stray '&' in item names: the value columns are the LAST
            # n_val cells; everything before them is the label.
            vals = [""] * 5
            if len(cells) < 1 + n_val:
                if not text:
                    continue
                # label-only / malformed row, no values
            else:
                text = _DOTS_RE.sub("", " ".join(cells[:-n_val])).strip()
                for cell, slot in zip(cells[-n_val:], slots):
                    if slot is not None:
                        vals[slot] = _clean_value(cell)
            if not text:
                continue
            items.append(
                {
                    "text": text,
                    "indent": 0,  # LaTeX flattens indentation; inferred downstream
                    "is_subtotal": False,  # _items_to_lines ORs in is_subtotal_line(text)
                    "col1": vals[0],
                    "col2": vals[1],
                    "col3": vals[2],
                    "col4": vals[3],
                    "col5": vals[4],
                }
            )
    return items


# Some reports carry a single-column "Statement of New Budget (Obligational) Authority —
# Amounts Recommended in the Bill" instead of the multi-column comparative statement
# (Interior-Environment FY2026, CRPT-119hrpt215, is the first observed case). Each row is
# an item label plus ONE value: the committee's recommended (Bill) amount, with no
# prior-year / request / delta columns. This signature identifies the statement.
_SINGLE_COL_SIGNATURE = "RECOMMENDED IN THE BILL"


def parse_page_single_column(raw: str) -> list[dict]:
    """Parse a single-column 'Amounts Recommended in the Bill' page into item dicts.

    Each two-column ``tabular`` (item label + one value) yields items with only col3 (the
    committee recommendation) populated; col1/col2/col4/col5 stay blank. Callers must gate
    this on the single-column statement signature — a genuine comparative report should go
    through ``parse_page`` — so a stray two-column table is never misread as a Bill amount.
    """
    items: list[dict] = []
    for spec, body in _TABULAR_RE.findall(raw):
        n_cols = sum(1 for ch in spec if ch in "clr")
        if n_cols != 2:  # item label + exactly one value column
            continue
        if any(kw in body for kw in _DISQUALIFYING):
            continue
        for raw_row in body.split(r"\\"):
            row = _MULTICOL_RE.sub(r"\1", raw_row)
            row = _TAG_RE.sub("", row).replace("\n", " ").strip()
            if not row:
                continue
            cells = [c.strip() for c in row.split("&")]
            text = _DOTS_RE.sub("", cells[0]).strip()
            # Column-title header row (empty label, names the Bill column) — skip.
            if not text and any(kw in row for kw in ("Bill", "Enacted", "Request")):
                continue
            if len(cells) < 2:
                if not text:
                    continue
                val = ""  # label-only / section row
            else:
                text = _DOTS_RE.sub("", " ".join(cells[:-1])).strip()
                val = _clean_value(cells[-1])
                # A non-empty value with no digit is not a Bill amount — it is a stray
                # two-column non-financial row (e.g. a roll-call "Yea | Nay" name pair).
                # Drop it rather than record a bogus recommendation.
                if val and not any(ch.isdigit() for ch in val):
                    continue
            if not text:
                continue
            items.append(
                {
                    "text": text,
                    "indent": 0,
                    "is_subtotal": False,
                    "col1": "",
                    "col2": "",
                    "col3": val,  # committee recommendation (the Bill amount)
                    "col4": "",
                    "col5": "",
                }
            )
    return items


def _clean_value(cell: str) -> str:
    """Normalise a value cell. Leader dashes/dots mean blank (zero / N/A)."""
    cell = _FOOTNOTE_RE.sub("", _TAG_RE.sub("", cell)).strip()
    if cell in {"--", "---", "-", ""} or set(cell) <= {".", " "}:
        return ""
    return cell


def _b64(pil: Image.Image) -> str:
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def _call(image_b64: str, temperature: float, top_k: int) -> tuple[int | None, str]:
    """One server call. Returns (completion_tokens, raw output string)."""
    payload = {
        "model": NEMOTRON_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": NEMOTRON_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            }
        ],
        "max_tokens": _MAX_TOKENS,
        "temperature": temperature,
        "top_k": top_k,
        "repetition_penalty": 1.1,
        "skip_special_tokens": False,
    }
    resp = httpx.post(
        f"{NEMOTRON_BASE_URL}/chat/completions", json=payload, timeout=600.0
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("usage", {}).get("completion_tokens"), data["choices"][0]["message"]["content"]


_TRUNCATED = _MAX_TOKENS - 100  # near the output cap => runaway/degenerate decode


def _has_comparative_table(raw: str) -> bool:
    """True if the raw output contains at least one comparative-statement table."""
    return any(_is_comparative_table(spec, body) for spec, body in _TABULAR_RE.findall(raw))


def extract_with_nemotron(page: pdfplumber.pdf.Page, page_number: int) -> tuple[list[dict], str]:
    """Extract one page's comparative rows, choosing the rendering per page.

    Returns (items, kind) where kind is one of:
      - "rows": comparative rows were parsed.
      - "empty_failed": a comparative table was present but parsed to nothing, OR the
        model produced no output at all (greedy-EOS even after retry) so we can't tell.
        These are the pages worth sending to a Gemini fallback.
      - "non_comparative": the model produced output but no comparative table (a votes
        page, a project-table-only page, etc.). NOT a recall gap — must not be sent to
        Gemini, which would mangle a non-comparative table into the comparative schema.

    Strategy (best digit fidelity first, recall-safe fallback):
      1. Native CROP at temp=0 — sharp digits. Accept if it parsed rows and did not
         run away to the token cap.
      2. Otherwise FULL-PAGE render at temp=0 — in-distribution, stable decode.
      3. If full-page emits an immediate EOS (a known greedy pathology), retry sampling.
    """
    # 1. Native crop — best digit accuracy.
    ct, raw = _call(_b64(render_crop(page)), temperature=0.0, top_k=1)
    items = parse_page(raw)
    truncated = ct is not None and ct >= _TRUNCATED
    if items and not truncated:
        logger.info(f"Page {page_number}: extracted {len(items)} items (crop)")
        return items, "rows"

    # 2. Full-page fallback (recall-safe).
    reason = "crop truncated" if truncated else "crop empty"
    logger.info(f"Page {page_number}: {reason}, falling back to full-page render")
    ct, raw = _call(_b64(render_full(page)), temperature=0.0, top_k=1)
    tries = 0
    while ct is not None and ct <= 1 and tries < 2:
        tries += 1
        logger.info(f"Page {page_number}: empty (immediate EOS), retry {tries} with sampling")
        ct, raw = _call(_b64(render_full(page)), temperature=0.7, top_k=40)
    items = parse_page(raw)
    if items:
        kind = "rows"
    elif not raw.strip() or _has_comparative_table(raw):
        kind = "empty_failed"  # model bailed, or had a comparative table it couldn't parse
    else:
        kind = "non_comparative"  # produced content but no comparative table on this page
    logger.info(f"Page {page_number}: extracted {len(items)} items (full-page, kind={kind})")
    return items, kind


def page_to_fitted_base64(page: pdfplumber.pdf.Page, rotate: bool | None = None) -> str:
    """Render a page (crop strategy) fit-to-cap and return base64-encoded PNG."""
    return _b64(render_crop(page, rotate=rotate))


def extract_house_nemotron(
    pdf_path,
    report_id: str,
    congress: int,
    fiscal_year: int | None = None,
    subcommittee: str | None = None,
    max_pages: int | None = None,
):
    """Extract a House comparative statement with the Nemotron-Parse backend.

    Returns (lines, meta) where lines is a list of ComparativeStatementLine and meta is
    a per-page extraction report. Used by the CLI (VISION_BACKEND=nemotron) and by the
    standalone driver and the hybrid first pass.
    """
    import time

    from approps.extraction.comparative_house import _find_image_pages, _items_to_lines

    pdf = pdfplumber.open(str(pdf_path))
    image_pages = _find_image_pages(pdf)
    if max_pages:
        image_pages = image_pages[:max_pages]

    lines = []
    succeeded: list[int] = []
    empty: list[int] = []  # comparative table present but unparsed, or model bailed
    non_comparative: list[int] = []  # no comparative table on the page (don't flag)
    errored: list[dict] = []
    cur_title = cur_dept = None
    t0 = time.time()

    for page_idx in image_pages:
        page_num = page_idx + 1
        logger.info(f"  page {page_num} ...")
        try:
            items, kind = extract_with_nemotron(pdf.pages[page_idx], page_num)
        except Exception as e:  # noqa: BLE001 - record, don't abort
            logger.error(f"  page {page_num} ERROR: {e}")
            errored.append({"page": page_num, "error": str(e)})
            continue
        if kind == "empty_failed":
            empty.append(page_num)
        elif kind == "non_comparative":
            non_comparative.append(page_num)
        page_lines, cur_title, cur_dept = _items_to_lines(
            items=items, report_id=report_id, congress=congress, fiscal_year=fiscal_year,
            subcommittee=subcommittee, page_number=page_num,
            current_title=cur_title, current_dept=cur_dept,
        )
        lines.extend(page_lines)
        succeeded.append(page_num)

    elapsed = time.time() - t0
    n = len(succeeded) + len(errored)
    meta = {
        "image_pages": len(image_pages),
        "pages_succeeded": len(succeeded),
        "pages_empty": empty,
        "pages_non_comparative": non_comparative,
        "pages_errored": errored,
        "total_lines": len(lines),
        "data_lines": sum(1 for ln in lines if not ln.is_subtotal),
        "subtotal_lines": sum(1 for ln in lines if ln.is_subtotal),
        "elapsed_seconds": round(elapsed, 1),
        "seconds_per_page": round(elapsed / n, 2) if n else None,
    }
    return lines, meta


def extract_house_single_column(
    pdf_path,
    report_id: str,
    congress: int,
    fiscal_year: int | None = None,
    subcommittee: str | None = None,
):
    """Extract a single-column 'Amounts Recommended in the Bill' House statement.

    For reports that carry the single-column Statement of New Budget Authority instead of
    a multi-column comparative statement (e.g. Interior-Environment FY2026). Runs Nemotron
    over the image pages and parses the Bill amount per line into
    ``committee_recommendation`` only. Returns (lines, meta).

    Gated on the statement signature: if no page shows "RECOMMENDED IN THE BILL", the
    report is not this kind of statement and an empty list is returned (so this never
    fabricates recommendation rows from an unrelated two-column table).
    """
    from approps.extraction.comparative_house import _find_image_pages, _items_to_lines

    pdf = pdfplumber.open(str(pdf_path))
    image_pages = _find_image_pages(pdf)
    lines = []
    cur_title = cur_dept = None
    saw_signature = False
    pages_used = 0

    for page_idx in image_pages:
        page_num = page_idx + 1
        try:
            _, raw = _call(_b64(render_crop(pdf.pages[page_idx])), temperature=0.0, top_k=1)
        except Exception as e:  # noqa: BLE001 - record, don't abort
            logger.error(f"  single-col page {page_num} ERROR: {e}")
            continue
        upper = raw.upper()
        # Roll-call vote pages also render as two-column tables (Yea names | Nay names);
        # skip them so member names never leak in as line items.
        if any(kw in upper for kw in ("MEMBERS VOTING", "ROLL CALL", "FULL COMMITTEE VOTE")):
            continue
        # A comparative table here means this is NOT a pure single-column report; skip
        # the page (the caller only reaches this path when the comparative pass was empty).
        if parse_page(raw):
            continue
        if _SINGLE_COL_SIGNATURE in upper:
            saw_signature = True
        items = parse_page_single_column(raw)
        if not items:
            continue
        page_lines, cur_title, cur_dept = _items_to_lines(
            items=items, report_id=report_id, congress=congress, fiscal_year=fiscal_year,
            subcommittee=subcommittee, page_number=page_num,
            current_title=cur_title, current_dept=cur_dept,
        )
        lines.extend(page_lines)
        pages_used += 1

    if not saw_signature:
        return [], {"image_pages": len(image_pages), "single_column": False, "total_lines": 0}
    logger.info(f"Single-column statement: {len(lines)} recommendation rows over {pages_used} pages")
    return lines, {
        "image_pages": len(image_pages),
        "single_column": True,
        "pages_used": pages_used,
        "total_lines": len(lines),
    }
