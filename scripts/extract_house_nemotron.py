"""Extract a House comparative statement with the Nemotron-Parse backend.

Thin driver over approps.extraction.nemotron_parse.extract_house_nemotron. Writes to
``<report_id>_nemotron.json`` so it never clobbers the Gemini-extracted ground truth,
enabling a side-by-side bake-off via scripts/verify_house.py.

Usage:
    uv run python scripts/extract_house_nemotron.py data/raw/118/house/CRPT-118hrpt553.pdf \
        CRPT-118hrpt553 --fy 2025 --subcommittee "Homeland Security" [--max-pages N]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from approps.config import EXTRACTED_DIR
from approps.extraction.nemotron_parse import NEMOTRON_MODEL, extract_house_nemotron

logging.basicConfig(level=logging.INFO, format="%(message)s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_path")
    ap.add_argument("report_id")
    ap.add_argument("--congress", type=int, default=118)
    ap.add_argument("--fy", type=int, default=None)
    ap.add_argument("--subcommittee", default=None)
    ap.add_argument("--max-pages", type=int, default=None)
    args = ap.parse_args()

    logging.info(f"Vision backend: nemotron ({NEMOTRON_MODEL})")
    lines, meta = extract_house_nemotron(
        args.pdf_path, args.report_id, args.congress, args.fy, args.subcommittee, args.max_pages
    )

    report = {
        "report_id": args.report_id,
        "congress": args.congress,
        "chamber": "house",
        "fiscal_year": args.fy,
        "subcommittee": args.subcommittee,
        "vision_model": NEMOTRON_MODEL,
        "comparative_lines": [ln.model_dump(mode="json") for ln in lines],
        "extraction_report": meta,
    }
    out_dir = EXTRACTED_DIR / str(args.congress) / "house"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.report_id}_nemotron.json"
    out_path.write_text(json.dumps(report, indent=2))

    logging.info("=" * 60)
    logging.info(json.dumps(meta, indent=2))
    logging.info(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
