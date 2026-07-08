"""Extract a House comparative statement end-to-end and persist the result.

Unlike the production `extract_house_comparative`, this driver does NOT abort the
whole run on a single page failure. It processes every image page, records which
pages succeeded / returned zero items / errored, and writes both the extracted
lines and a per-page failure report. That failure report is the input to scoping
a verification harness for vision-extracted House data.

Usage:
    uv run python scripts/extract_house.py <pdf_path> <report_id> \
        --fy 2025 --subcommittee "Homeland Security"
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pdfplumber

from approps.config import EXTRACTED_DIR, VISION_BACKEND, VISION_MODEL
from approps.extraction.comparative_house import (
    _extract_page,
    _find_image_pages,
    _items_to_lines,
    _page_to_base64_png,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_path")
    ap.add_argument("report_id")
    ap.add_argument("--congress", type=int, default=118)
    ap.add_argument("--fy", type=int, default=None)
    ap.add_argument("--subcommittee", default=None)
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--resolution", type=int, default=300)
    args = ap.parse_args()

    logger.info(f"Vision backend: {VISION_BACKEND} ({VISION_MODEL})")

    pdf = pdfplumber.open(args.pdf_path)
    image_pages = _find_image_pages(pdf)
    if args.max_pages:
        image_pages = image_pages[: args.max_pages]
    logger.info(f"{args.report_id}: {len(image_pages)} image pages to process")

    all_lines = []
    succeeded: list[int] = []
    empty: list[int] = []
    errored: list[dict] = []
    current_title = current_dept = None

    import re as _re
    import time as _time

    def _extract_with_retry(b64, page_num, max_tries=6):
        """Extract one page, backing off on 429 rate-limit / quota errors.

        The free-tier quota is per-minute (the 429 carries a retryDelay ~13s), so a
        bounded backoff lets large reports complete instead of cascading failures
        once the limit is first tripped.
        """
        for attempt in range(max_tries):
            try:
                return _extract_page(b64, page_num)
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    m = _re.search(r"retry in ([\d.]+)s|retryDelay['\": ]+([\d.]+)s", msg)
                    delay = float(next((g for g in (m.groups() if m else []) if g), 0)) or 15.0
                    delay = min(delay + 2.0 * attempt, 90.0)
                    logger.info(f"  page {page_num}: 429, backing off {delay:.0f}s (attempt {attempt+1}/{max_tries})")
                    _time.sleep(delay)
                    continue
                raise
        raise RuntimeError(f"page {page_num}: still rate-limited after {max_tries} attempts")

    for page_idx in image_pages:
        page_num = page_idx + 1
        logger.info(f"  page {page_num} ...")
        try:
            b64 = _page_to_base64_png(pdf.pages[page_idx], resolution=args.resolution)
            items = _extract_with_retry(b64, page_num)
        except Exception as e:  # noqa: BLE001 - we want to record, not abort
            logger.error(f"  page {page_num} ERROR: {e}")
            errored.append({"page": page_num, "error": str(e)})
            continue

        if not items:
            empty.append(page_num)

        lines, current_title, current_dept = _items_to_lines(
            items=items,
            report_id=args.report_id,
            congress=args.congress,
            fiscal_year=args.fy,
            subcommittee=args.subcommittee,
            page_number=page_num,
            current_title=current_title,
            current_dept=current_dept,
        )
        all_lines.extend(lines)
        succeeded.append(page_num)

    report = {
        "report_id": args.report_id,
        "congress": args.congress,
        "chamber": "house",
        "fiscal_year": args.fy,
        "subcommittee": args.subcommittee,
        "vision_model": VISION_MODEL,
        "comparative_lines": [ln.model_dump(mode="json") for ln in all_lines],
        "extraction_report": {
            "image_pages": len(image_pages),
            "pages_succeeded": len(succeeded),
            "pages_empty": empty,
            "pages_errored": errored,
            "total_lines": len(all_lines),
            "data_lines": sum(1 for ln in all_lines if not ln.is_subtotal),
            "subtotal_lines": sum(1 for ln in all_lines if ln.is_subtotal),
        },
    }

    out_dir = EXTRACTED_DIR / str(args.congress) / "house"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.report_id}.json"
    out_path.write_text(json.dumps(report, indent=2))

    logger.info("=" * 60)
    logger.info(json.dumps(report["extraction_report"], indent=2))
    logger.info(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
