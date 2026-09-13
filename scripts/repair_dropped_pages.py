"""Recover comparative rows from pages the vision pass dropped whole.

The extractor now escalates these pages, but the shipped extractions predate the fix, so this replays the missing leg over them.
A gap page holds no rows by definition, so the merge is additive and overwrites nothing.

    uv run python scripts/repair_dropped_pages.py --dry-run
    GEMINI_VERTEX=1 GEMINI_VERTEX_PROJECT=gwscli-tandem uv run python scripts/repair_dropped_pages.py
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pdfplumber

from approps.extraction.comparative_house import _find_image_pages, _items_to_lines, _page_to_base64_png
from approps.extraction.hybrid import _gemini_extract_retry, _statement_gap_pages
from approps.extraction.verify import page_of, verify

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("repair")


def _congress_of(report_id: str) -> int | None:
    # Some extractions carry congress=None, which the row model rejects.
    m = re.search(r"CRPT-(\d+)", report_id)
    return int(m.group(1)) if m else None


def _pdf_path(report_id: str, congress) -> Path:
    return Path(f"data/raw/{congress}/house/{report_id}.pdf")


def _repair_one(path: Path, workers: int, dry_run: bool) -> dict | None:
    doc = json.loads(path.read_text())
    report_id = doc.get("report_id") or path.stem
    lines = doc.get("comparative_lines") or []
    if not lines:
        return None
    congress = doc.get("congress") or _congress_of(report_id)
    pdf_path = _pdf_path(report_id, congress)
    if not pdf_path.exists():
        return None

    pdf = pdfplumber.open(str(pdf_path))
    gaps = sorted(_statement_gap_pages(lines, _find_image_pages(pdf)))
    if not gaps:
        return None
    if dry_run:
        return {"report_id": report_id, "gap_pages": gaps, "recovered": 0, "rows_before": len(lines)}

    # Render here, not in the pool: pdfium shares mutable state per document and corrupts under threads.
    rendered: list[tuple[int, str]] = []
    failed: list[int] = []
    for page_num in gaps:
        try:
            rendered.append((page_num, _page_to_base64_png(pdf.pages[page_num - 1], resolution=300)))
        except Exception as exc:  # noqa: BLE001 - record and keep the rest
            logger.error("  %s page %s render failed: %s", report_id, page_num, exc)
            failed.append(page_num)

    def read(job: tuple[int, str]) -> tuple[int, list[dict], str | None]:
        # Catch inside the worker: pool.map re-raises at iteration, losing the whole report.
        page_num, b64 = job
        try:
            items = _gemini_extract_retry(b64, page_num)
            page_lines, _, _ = _items_to_lines(
                items=items, report_id=report_id, congress=congress,
                fiscal_year=doc.get("fiscal_year"), subcommittee=doc.get("subcommittee"),
                page_number=page_num,
            )
            return page_num, [ln.model_dump(mode="json") for ln in page_lines], None
        except Exception as exc:  # noqa: BLE001 - record and keep the rest
            return page_num, [], str(exc)

    recovered: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for page_num, page_rows, error in pool.map(read, rendered):
            if error:
                logger.error("  %s page %s failed: %s", report_id, page_num, error)
                failed.append(page_num)
            recovered.extend(page_rows)

    if not recovered:
        return {"report_id": report_id, "gap_pages": gaps, "recovered": 0, "rows_before": len(lines)}

    merged = lines + recovered
    merged.sort(key=page_of)
    doc["comparative_lines"] = merged
    report = doc.setdefault("extraction_report", {})
    report["repaired_gap_pages"] = gaps
    report["repaired_rows_added"] = len(recovered)
    report["repaired_pages_failed"] = failed
    report["total_lines"] = len(merged)
    after = verify(merged)
    report["hybrid_pass_rate"] = after["pass_rate"]
    report["hybrid_pass"] = after["passed"]
    report["hybrid_fail"] = after["failed"]
    path.write_text(json.dumps(doc))
    return {"report_id": report_id, "gap_pages": gaps, "recovered": len(recovered), "rows_before": len(lines)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report the work without calling Gemini")
    ap.add_argument("--workers", type=int, default=4, help="parallel page reads (Vertex 429s when pushed)")
    ap.add_argument("--only", help="restrict to one report id")
    args = ap.parse_args()

    paths = sorted(Path("data/extracted").glob("*/house/*.json"))
    paths = [p for p in paths if not p.name.endswith("_nemotron.json")]
    if args.only:
        paths = [p for p in paths if args.only in p.name]

    results = []
    for path in paths:
        out = _repair_one(path, args.workers, args.dry_run)
        if out:
            results.append(out)
            logger.info("%-20s %2d gap pages -> +%d rows", out["report_id"], len(out["gap_pages"]), out["recovered"])

    pages = sum(len(r["gap_pages"]) for r in results)
    rows = sum(r["recovered"] for r in results)
    logger.info("")
    logger.info("DONE %d reports, %d gap pages, %d rows recovered", len(results), pages, rows)


if __name__ == "__main__":
    main()
