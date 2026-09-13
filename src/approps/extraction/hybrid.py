"""Hybrid House extraction: Nemotron bulk first pass, Gemini only on suspect pages.

Pipeline:
  1. Nemotron-Parse first pass over every image page (free, local, ~97% precise).
  2. Verify (delta arithmetic) + recall cross-check (vs verified inline tables).
  3. Suspect pages = FAIL ∪ empty ∪ recall-gap pages.
  4. Re-extract ONLY suspect pages with Gemini and replace those pages wholesale.
  5. Re-verify and return.

Keeps Gemini's ~99.5% accuracy while sending only ~1/3 of pages to Gemini, which
removes the per-minute quota wall on large corpora. Returns ComparativeStatementLine
objects so it slots into the CLI exactly like the other backends.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import pdfplumber

from approps.extraction.comparative_house import (
    _extract_with_gemini,
    _find_image_pages,
    _items_to_lines,
    _page_to_base64_png,
)
from approps.extraction.nemotron_parse import extract_house_nemotron
from approps.extraction.verify import page_of, verify
from approps.output.schemas import ComparativeStatementLine
from approps.verification.recall_check import (
    audit_recall,
    load_inline_accounts,
    suspect_pages_from_missing,
)

logger = logging.getLogger(__name__)

# Two row-producing pages this close belong to the same statement.
# Tuned on the corpus: 4 misses CRPT-118hrpt557's Title III block, 5 recovers it.
_STATEMENT_MAX_GAP = 5


def _statement_gap_pages(lines: list[dict], image_pages: list[int]) -> set[int]:
    """Image pages inside a statement's own run that produced no rows at all.

    Every other suspect signal is a failure a page reports about itself, and a page dropped whole reports nothing, so it shows up only as absence.
    """
    produced = sorted({page_of(ln) for ln in lines if page_of(ln)})
    candidates = {idx + 1 for idx in image_pages}
    gaps: set[int] = set()
    for run in _statement_runs(produced):
        if len(run) < 3:  # too short to assert a statement runs through it
            continue
        seen = set(run)
        gaps |= {p for p in range(run[0] + 1, run[-1]) if p not in seen and p in candidates}
    return gaps


def _statement_edge_pages(lines: list[dict], image_pages: list[int]) -> set[int]:
    """Image pages directly before or after a statement's run that produced no rows.

    A dropped first or last page leaves no hole inside the run, so `_statement_gap_pages` cannot see it; CRPT-119hrpt696 lost its opening page and its Grand Total this way.
    """
    produced = sorted({page_of(ln) for ln in lines if page_of(ln)})
    candidates = {idx + 1 for idx in image_pages}
    seen = set(produced)
    edges: set[int] = set()
    for run in _statement_runs(produced):
        if len(run) < 3:
            continue
        edges |= {p for p in (run[0] - 1, run[-1] + 1) if p in candidates and p not in seen}
    return edges


def _statement_runs(produced: list[int]) -> list[list[int]]:
    """Group sorted row-producing pages into runs no more than `_STATEMENT_MAX_GAP` apart."""
    if not produced:
        return []
    runs: list[list[int]] = [[produced[0]]]
    for page in produced[1:]:
        if page - runs[-1][-1] <= _STATEMENT_MAX_GAP:
            runs[-1].append(page)
        else:
            runs.append([page])
    return runs


# Enacted and request are levels, never changes, so an explicit plus sign there is a delta read into the wrong column.
_LEVEL_COLS = ("prior_year_enacted", "budget_estimate")


def _shifted_column_pages(lines: list[dict]) -> set[int]:
    """Pages where a delta landed in a level column.

    Such a row reads as unverifiable rather than failing the delta arithmetic, so the fail-page gate never escalates it.
    """
    return {
        page_of(ln)
        for ln in lines
        if any(((ln.get(c) or {}).get("raw_text") or "").lstrip().startswith("+") for c in _LEVEL_COLS)
    }


class PerDayQuotaError(Exception):
    """Gemini per-model-per-day quota is exhausted — backoff won't help (resets at midnight PT)."""


def _is_per_day(msg: str) -> bool:
    return "per_day" in msg.lower() or "perday" in msg.lower() or "requests_per_model_per_day" in msg


def _gemini_extract_retry(b64, page_num, max_tries=6):
    """Gemini extract with bounded backoff on per-minute 429s.

    Raises PerDayQuotaError immediately on a daily-cap 429 (backoff is futile — the
    caller must stop rather than degrade the report by keeping Nemotron rows).
    """
    for attempt in range(max_tries):
        try:
            return _extract_with_gemini(b64, page_num)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if _is_per_day(msg):
                raise PerDayQuotaError(msg) from e
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                m = re.search(r"retry in ([\d.]+)s|retryDelay['\": ]+([\d.]+)s", msg)
                delay = float(next((g for g in (m.groups() if m else []) if g), 0)) or 15.0
                delay = min(delay + 2.0 * attempt, 90.0)
                logger.info(f"  page {page_num}: 429, backing off {delay:.0f}s "
                            f"(attempt {attempt + 1}/{max_tries})")
                time.sleep(delay)
                continue
            raise
    raise RuntimeError(f"page {page_num}: still rate-limited after {max_tries} attempts")


def _gemini_page(pdf, page_num, report_id, congress, fiscal_year, subcommittee) -> list[dict]:
    """Re-extract a single page with Gemini (300 DPI), as JSON dicts."""
    b64 = _page_to_base64_png(pdf.pages[page_num - 1], resolution=300)
    items = _gemini_extract_retry(b64, page_num)
    page_lines, _, _ = _items_to_lines(
        items=items, report_id=report_id, congress=congress,
        fiscal_year=fiscal_year, subcommittee=subcommittee, page_number=page_num,
    )
    return [ln.model_dump(mode="json") for ln in page_lines]


def extract_house_hybrid(
    pdf_path,
    report_id: str,
    congress: int,
    fiscal_year: int | None = None,
    subcommittee: str | None = None,
    reuse_nemotron_path: str | Path | None = None,
):
    """Run the hybrid pipeline. Returns (lines, meta).

    If ``reuse_nemotron_path`` points at an existing ``*_nemotron.json``, its first pass
    is loaded instead of re-running Nemotron (useful for iterating on the Gemini leg).
    """
    pdf = pdfplumber.open(str(pdf_path))
    image_pages = _find_image_pages(pdf)

    # 1. Nemotron first pass -------------------------------------------------------
    if reuse_nemotron_path and Path(reuse_nemotron_path).exists():
        logger.info(f"Reusing {reuse_nemotron_path}")
        nemo = json.loads(Path(reuse_nemotron_path).read_text())
        lines = nemo["comparative_lines"]
        report = nemo.get("extraction_report", {})
        empty = report.get("pages_empty", [])
        unreadable = report.get("pages_table_unreadable", [])
    else:
        logger.info(f"Nemotron first pass over {len(image_pages)} image pages ...")
        nemo_lines, nemo_meta = extract_house_nemotron(
            pdf_path, report_id, congress, fiscal_year, subcommittee
        )
        lines = [ln.model_dump(mode="json") for ln in nemo_lines]
        empty = nemo_meta["pages_empty"]
        unreadable = nemo_meta.get("pages_table_unreadable", [])

    # 1b. Born-digital text fallback -----------------------------------------------
    # A few reports embed non-comparative scanned pages (roll-call votes, charts) but
    # typeset the comparative statement itself as real text, so the image-based router
    # sends them to vision where the comparative pass finds nothing (e.g. Defense FY2027,
    # CRPT-119hrpt715). Parse the text-layer comparative statement directly; accept it only
    # when it yields a substantial number of value rows, so a stray match can't win.
    if not lines and image_pages:
        from approps.extraction.comparative_house_text import extract_house_text

        text_lines = extract_house_text(pdf_path, report_id, congress, fiscal_year, subcommittee)
        value_rows = [
            ln for ln in text_lines
            if ln.committee_recommendation and ln.committee_recommendation.value is not None
        ]
        if len(value_rows) >= 20:
            logger.info(f"Born-digital text statement: {len(text_lines)} lines "
                        f"({len(value_rows)} with values) — comparative statement is typeset text")
            return text_lines, {
                "image_pages": len(image_pages),
                "born_digital_text": True,
                "total_lines": len(text_lines),
                "gemini_calls": 0,
            }

    # 1c. Single-column fallback ---------------------------------------------------
    # Some reports carry a single-column "Amounts Recommended in the Bill" statement
    # instead of a multi-column comparative statement, so the comparative pass finds
    # nothing. Capture the Bill amounts (committee recommendation only); this path is
    # self-gating on the statement signature and returns [] for a genuinely empty report.
    if not lines and image_pages:
        from approps.extraction.nemotron_parse import extract_house_single_column

        sc_lines, sc_meta = extract_house_single_column(
            pdf_path, report_id, congress, fiscal_year, subcommittee
        )
        if sc_lines:
            logger.info(f"Single-column statement: {len(sc_lines)} recommendation rows "
                        "(no comparative statement in this report)")
            return sc_lines, {
                "image_pages": len(image_pages),
                "single_column": True,
                "total_lines": len(sc_lines),
                "gemini_calls": 0,
            }

    # 2. Verify (values) -----------------------------------------------------------
    before = verify(lines)
    logger.info(f"Nemotron pass: {before['passed']}/{before['verifiable']} "
                f"({(before['pass_rate'] or 0):.1%}) PASS, {before['failed']} FAIL")

    # 2b. Recall cross-check (account presence) ------------------------------------
    recall_pages: set[int] = set()
    inline = load_inline_accounts(report_id)
    recall = None
    if inline:
        recall = audit_recall(lines, inline)
        recall_pages, unmappable = suspect_pages_from_missing(recall["missing"], lines)
        logger.info(f"Recall: {recall['recall']:.1%} of {recall['inline_accounts']} accounts; "
                    f"{len(recall['missing'])} missing -> {len(recall_pages)} extra pages, "
                    f"{len(unmappable)} unmappable")
    else:
        logger.info(f"No inline CSV for {report_id}; recall cross-check skipped")

    # 3. Suspect pages -------------------------------------------------------------
    gap_pages = _statement_gap_pages(lines, image_pages) | _statement_edge_pages(lines, image_pages)
    if gap_pages:
        logger.info(f"Statement gaps (produced no rows inside or at the edge of a run): {sorted(gap_pages)}")
    shifted_pages = _shifted_column_pages(lines)
    if shifted_pages:
        logger.info(f"Deltas read into level columns: {sorted(shifted_pages)}")
    suspect = sorted(
        set(before["fail_pages"]) | set(empty) | set(unreadable) | recall_pages | gap_pages | shifted_pages
    )
    logger.info(f"Suspect pages -> Gemini ({len(suspect)} of {len(image_pages)}): {suspect}")

    # 4-5. Gemini re-extract suspect pages, replace wholesale ----------------------
    gemini_lines: dict[int, list[dict]] = {}
    gemini_calls = 0
    for page_num in suspect:
        logger.info(f"  gemini re-extract page {page_num} ...")
        try:
            gemini_lines[page_num] = _gemini_page(
                pdf, page_num, report_id, congress, fiscal_year, subcommittee
            )
            gemini_calls += 1
        except PerDayQuotaError:
            # Daily cap hit — abort the whole report rather than write a half-cleaned
            # (degraded) canonical output. The caller skips saving; resume after reset.
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"  gemini page {page_num} ERROR: {e} (keeping Nemotron rows)")

    suspect_set = set(gemini_lines)
    merged = [ln for ln in lines if page_of(ln) not in suspect_set]
    for page_lines in gemini_lines.values():
        merged.extend(page_lines)
    merged.sort(key=page_of)

    # 6. Re-verify -----------------------------------------------------------------
    after = verify(merged)
    meta = {
        "image_pages": len(image_pages),
        "suspect_pages_to_gemini": suspect,
        "pages_table_unreadable": sorted(unreadable),
        "statement_gap_pages": sorted(gap_pages),
        "shifted_column_pages": sorted(shifted_pages),
        "gemini_calls": gemini_calls,
        "gemini_calls_saved_vs_pure": len(image_pages) - gemini_calls,
        "nemotron_pass_rate": before["pass_rate"],
        "hybrid_pass_rate": after["pass_rate"],
        "hybrid_pass": after["passed"],
        "hybrid_fail": after["failed"],
        "hybrid_verifiable": after["verifiable"],
        "recall": recall["recall"] if recall else None,
        "total_lines": len(merged),
    }
    out_lines = [ComparativeStatementLine(**d) for d in merged]
    return out_lines, meta
