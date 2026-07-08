"""Hybrid House extraction: Nemotron bulk first pass, Gemini only on suspect pages.

Thin driver over approps.extraction.hybrid.extract_house_hybrid. Writes
``<report_id>_hybrid.json``. Pass --reuse-nemotron to load an existing
``<report_id>_nemotron.json`` first pass instead of re-running Nemotron.

Usage:
    GEMINI_API_KEY=... uv run python scripts/extract_house_hybrid.py \
        data/raw/118/house/CRPT-118hrpt553.pdf CRPT-118hrpt553 \
        --fy 2025 --subcommittee "Homeland Security" [--reuse-nemotron]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from approps.config import EXTRACTED_DIR, VISION_MODEL
from approps.extraction.hybrid import extract_house_hybrid
from approps.extraction.nemotron_parse import NEMOTRON_MODEL

logging.basicConfig(level=logging.INFO, format="%(message)s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_path")
    ap.add_argument("report_id")
    ap.add_argument("--congress", type=int, default=118)
    ap.add_argument("--fy", type=int, default=None)
    ap.add_argument("--subcommittee", default=None)
    ap.add_argument("--reuse-nemotron", action="store_true",
                    help="Load existing <report_id>_nemotron.json instead of re-running Nemotron")
    args = ap.parse_args()

    out_dir = EXTRACTED_DIR / str(args.congress) / "house"
    reuse = out_dir / f"{args.report_id}_nemotron.json" if args.reuse_nemotron else None

    lines, meta = extract_house_hybrid(
        args.pdf_path, args.report_id, args.congress, args.fy, args.subcommittee,
        reuse_nemotron_path=reuse,
    )

    report = {
        "report_id": args.report_id,
        "congress": args.congress,
        "chamber": "house",
        "fiscal_year": args.fy,
        "subcommittee": args.subcommittee,
        "vision_model": f"hybrid: {NEMOTRON_MODEL} + {VISION_MODEL}",
        "comparative_lines": [ln.model_dump(mode="json") for ln in lines],
        "extraction_report": meta,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.report_id}_hybrid.json"
    out_path.write_text(json.dumps(report, indent=2))

    logging.info("=" * 60)
    logging.info(f"Nemotron-only : {meta['nemotron_pass_rate']:.1%}")
    logging.info(f"Hybrid        : {meta['hybrid_pass']}/{meta['hybrid_verifiable']} "
                 f"({meta['hybrid_pass_rate']:.1%})")
    logging.info(f"Gemini calls  : {meta['gemini_calls']} of {meta['image_pages']} pages "
                 f"— saved {meta['gemini_calls_saved_vs_pure']}")
    logging.info(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
