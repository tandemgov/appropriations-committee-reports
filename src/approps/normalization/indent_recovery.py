"""Recover account groupings for *over-summing* House subtotal blocks via a double gate.

Some House subtotal blocks fail to reconcile because they OVER-sum: a non-add sub-detail
(a transfer, a limitation, an "of which" breakout, a gross figure already inside a net)
is visually indented beneath a parent line but the vision extraction flattened it, so it
gets added into the block sum when it should not be. Nemotron emits one bounding box per
table (LaTeX flattens indentation), so the indent signal is absent from the extracted
data — see [[project_definition_of_done]].

This module recovers it with a DOUBLE GATE that never guesses:

  1. Gemini reads the page image and, for each over-summing block, flags which line items
     are non-add sub-details (the semantic question it answers reliably — unlike a numeric
     indent level, which drifts run to run).
  2. The block is only accepted — its leaves labeled with ``account_inferred`` and the
     flagged lines marked ``is_memo`` — when excluding *exactly* Gemini's flagged
     lines makes the block reconcile to the subtotal on some shared column.

Neither signal is trusted alone: the arithmetic kills Gemini's hallucinations, and Gemini
kills the arithmetic coincidences (a single line coincidentally equal to the excess). This
is the same verified-never-guess discipline as ``account_inference`` — Gemini proposes, the
table's own arithmetic disposes. Additive only; ``account``/``account_inferred`` set by the
base reconciler are never overwritten.

Runs as a post-process over an already-extracted report, re-reading only the pages that
carry an over-summing block (one Gemini call per such page), so its cost is bounded by the
failing-block pages, not the corpus.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re

from approps.config import VISION_MODEL, gemini_client

# The non-add classifier model. Defaults to the corpus vision model but can be pointed at
# another Gemini model via INDENT_MODEL — useful when the primary model's daily quota is
# exhausted (each model has its own quota bucket). The double-gate's arithmetic check keeps
# any capable model honest, so the exact model does not affect correctness, only quality.
_INDENT_MODEL = os.environ.get("INDENT_MODEL", VISION_MODEL)
from approps.normalization.account_inference import (
    _COLS,
    _MEMO_ONLY_RE,
    _col_values,
    _is_rollup,
    _rollup_name,
)

logger = logging.getLogger(__name__)


def _reconciles(segment_values: list[dict[str, int]], target: dict[str, int]) -> bool:
    """Whether the segments sum to the target on any shared value column."""
    for col in _COLS:
        if col not in target:
            continue
        addends = [v[col] for v in segment_values if col in v]
        if addends and sum(addends) == target[col]:
            return True
    return False


def _oversum_blocks(lines: list[dict]) -> list[dict]:
    """Find named subtotal blocks that fail to reconcile because they OVER-sum.

    Mirrors the scan in ``account_inference.infer_block_accounts`` but, instead of
    labeling, records each failing block that over-sums on its primary column:
    ``{page, subtotal_name, subtotal_line, leaves: [line dict], values: [col dict]}``.
    Only real leaf lines (not already-reconciled inner groups) are recorded as candidates.
    """
    blocks: list[dict] = []
    pending: list[dict] = []  # {"values":{col:int}, "line":dict|None (None==group)}

    for line in lines:
        text = (line.get("line_item_text") or "").strip()
        if _is_rollup(line):
            name = _rollup_name(text)
            target = _col_values(line)
            if name and target:
                seg_vals = [s["values"] for s in pending]
                if not _reconciles(seg_vals, target):
                    col = next((c for c in _COLS if c in target), None)
                    if col is not None:
                        addends = [s["values"][col] for s in pending if col in s["values"]]
                        if addends and sum(addends) > target[col]:
                            leaves = [s for s in pending if s["line"] is not None]
                            if leaves:
                                blocks.append({
                                    "page": (line.get("line_number") or 0) // 100,
                                    "subtotal_name": name,
                                    "subtotal_line": line,
                                    "target": target,
                                    "leaves": leaves,  # [{"values":..,"line":..}]
                                })
                    pending = []
                else:
                    pending = [{"values": target, "line": None}]
            else:
                pending = []
        elif not text:
            continue
        else:
            is_memo = bool(_MEMO_ONLY_RE.match(text))
            pending.append({
                "values": {} if is_memo else _col_values(line),
                "line": line,
            })
    return blocks


_NONADD_PROMPT = """You are reading ONE page of a U.S. House appropriations Committee comparative statement (a scanned table). In these tables some line items are NON-ADD sub-details of the line above them: they are indented one level deeper and represent a transfer, a limitation, an "of which"/"including" breakout, or a gross amount already counted in a net total. Non-add lines must NOT be summed into their account/subtotal.

Below are one or more subtotal blocks our OCR extracted from this page. Each block's line items currently over-sum its stated subtotal, which usually means one or more listed lines is actually a non-add sub-detail that was mis-read as a top-level addend.

For EACH block, look at the page image and return the numbers of the line items that are NON-ADD sub-details (indented beneath a sibling / marked as of-which / transfer / limitation) and should be EXCLUDED from the subtotal.

{blocks}

Return ONLY a JSON object mapping each block letter to an array of line numbers to exclude, e.g. {{"A": [3], "B": []}}. Use [] for a block with no non-add lines. No other text."""


def _block_prompt(blocks_on_page: list[dict]) -> str:
    """Render the per-page block list for the prompt (block letter -> numbered leaves)."""
    parts = []
    for bi, blk in enumerate(blocks_on_page):
        letter = chr(ord("A") + bi)
        col = next((c for c in _COLS if c in blk["target"]), None)
        lines_txt = []
        for li, leaf in enumerate(blk["leaves"], 1):
            amt = leaf["values"].get(col)
            label = (leaf["line"].get("line_item_text") or "").strip()[:60]
            lines_txt.append(f"    {li}. {label} — {amt}")
        head = f'Block {letter} — subtotal "{blk["subtotal_name"]}" = {blk["target"].get(col)}:'
        parts.append(head + "\n" + "\n".join(lines_txt))
    return "\n\n".join(parts)


def _render_page_b64(pdf, page_number: int) -> str:
    """Render a 1-indexed PDF page to a base64 PNG (full page, fit for the vision model)."""
    from approps.extraction.nemotron_parse import render_full

    pil = render_full(pdf.pages[page_number - 1])
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def _gemini_nonadd(image_b64: str, blocks_on_page: list[dict]) -> dict[str, list[int]]:
    """Ask Gemini which line items per block are non-add. Returns {block_letter: [idx]}."""
    import time

    from google import genai

    client = gemini_client()
    prompt = _NONADD_PROMPT.format(blocks=_block_prompt(blocks_on_page))
    contents = [
        genai.types.Part.from_bytes(
            data=base64.standard_b64decode(image_b64), mime_type="image/png"
        ),
        prompt,
    ]
    # Bounded backoff on transient rate limits (429/RESOURCE_EXHAUSTED) so a momentary
    # quota blip doesn't fail the page and drop the whole report from the marker.
    resp = None
    for attempt in range(5):
        try:
            resp = client.models.generate_content(model=_INDENT_MODEL, contents=contents)
            break
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) and attempt < 4:
                time.sleep(min(4.0 + 4.0 * attempt, 30.0))
                continue
            raise
    text = resp.text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        logger.warning("Gemini non-add response was not valid JSON: %s", text[:200])
        return {}


def recover_indent(pdf_path, lines: list[dict]) -> dict:
    """Recover account groupings for over-summing blocks via the Gemini double gate.

    Mutates ``lines`` in place: on a block that reconciles once Gemini's flagged lines are
    excluded, sets ``account_inferred`` on the surviving leaves (never overwriting an
    existing ``account``/``account_inferred``) and marks each excluded line
    ``is_memo = True``. Returns stats.
    """
    import pdfplumber

    blocks = _oversum_blocks(lines)
    by_page: dict[int, list[dict]] = {}
    for blk in blocks:
        by_page.setdefault(blk["page"], []).append(blk)

    stats = {
        "oversum_blocks": len(blocks),
        "pages_reread": 0,
        "pages_failed": 0,
        "blocks_recovered": 0,
        "rows_labeled": 0,
        "lines_marked_nonadd": 0,
        "gemini_calls": 0,
    }
    if not blocks:
        return stats

    pdf = pdfplumber.open(str(pdf_path))
    for page, page_blocks in sorted(by_page.items()):
        if page <= 0 or page > len(pdf.pages):
            continue
        try:
            image_b64 = _render_page_b64(pdf, page)
            flagged = _gemini_nonadd(image_b64, page_blocks)
        except Exception as e:  # noqa: BLE001 - one bad page must not abort the report
            logger.warning("page %d non-add re-read failed: %s", page, e)
            stats["pages_failed"] += 1
            continue
        stats["pages_reread"] += 1
        stats["gemini_calls"] += 1

        for bi, blk in enumerate(page_blocks):
            letter = chr(ord("A") + bi)
            excl_idx = {int(i) for i in flagged.get(letter, []) if isinstance(i, (int, float))}
            if not excl_idx:
                continue
            # Double gate: exclude exactly Gemini's flagged leaves, require exact reconcile.
            kept = [leaf for li, leaf in enumerate(blk["leaves"], 1) if li not in excl_idx]
            dropped = [leaf for li, leaf in enumerate(blk["leaves"], 1) if li in excl_idx]
            if not kept or not _reconciles([k["values"] for k in kept], blk["target"]):
                continue
            stats["blocks_recovered"] += 1
            for leaf in kept:
                ln = leaf["line"]
                if not (ln.get("account") or "").strip() and not ln.get("account_inferred"):
                    ln["account_inferred"] = blk["subtotal_name"]
                    stats["rows_labeled"] += 1
            for leaf in dropped:
                leaf["line"]["is_memo"] = True
                stats["lines_marked_nonadd"] += 1
    return stats
