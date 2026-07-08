"""Run the Gemini non-add double-gate indentation recovery over House reports.

Post-process: for each report's canonical extracted JSON, re-read only the pages carrying
an over-summing subtotal block, ask Gemini which lines are non-add sub-details, and label a
block only when excluding exactly those lines makes it reconcile (see
approps.normalization.indent_recovery). Reports a per-report and aggregate recovery rate.

Dry-run by default (does not persist). Pass --write to save the additive
``account_inferred`` / ``non_add_inferred`` fields back into the canonical JSON.

Usage:
  uv run python scripts/recover_indent.py CRPT-114hrpt129 CRPT-114hrpt195
  uv run python scripts/recover_indent.py --all-house           # every House report, small-first
  uv run python scripts/recover_indent.py --all-house --write --resume
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from approps.config import EXTRACTED_DIR, RAW_DIR
from approps.normalization.indent_recovery import recover_indent

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _canonical_path(rid: str) -> Path | None:
    for congress_dir in (EXTRACTED_DIR).glob("*/house"):
        p = congress_dir / f"{rid}.json"
        if p.exists():
            return p
    return None


def _pdf_path(rid: str, congress: int) -> Path:
    return RAW_DIR / str(congress) / "house" / f"{rid}.pdf"


def _all_house_ids_small_first() -> list[str]:
    """Every House canonical report id, ordered by over-sum page count ascending, so a
    resumable per-report run banks the cheap reports first (survives short awake windows)."""
    import glob

    from approps.normalization.indent_recovery import _oversum_blocks

    rows = []
    for f in glob.glob(str(EXTRACTED_DIR / "*/house/*.json")):
        if f.endswith("_nemotron.json") or f.endswith("_hybrid.json"):
            continue
        d = json.loads(Path(f).read_text())
        cl = d.get("comparative_lines") or []
        pages = len({b["page"] for b in _oversum_blocks(cl)}) if cl else 0
        rows.append((pages, d.get("report_id")))
    rows.sort()
    return [rid for _, rid in rows if rid]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("report_ids", nargs="*")
    ap.add_argument("--all-house", action="store_true",
                    help="every House canonical report, ordered by over-sum page count (small first)")
    ap.add_argument("--write", action="store_true", help="persist labels back to canonical JSON")
    ap.add_argument("--resume", action="store_true",
                    help="skip reports already carrying a post_process.indent_recovery marker")
    args = ap.parse_args()

    ids: list[str] = list(args.report_ids)
    if args.all_house:
        ids += _all_house_ids_small_first()
    ids = list(dict.fromkeys(ids))  # de-dup, preserve order
    if not ids:
        logger.info("No report ids given.")
        return

    agg = {"reports": 0, "oversum_blocks": 0, "pages_reread": 0,
           "blocks_recovered": 0, "rows_labeled": 0, "gemini_calls": 0}
    for rid in ids:
        path = _canonical_path(rid)
        if not path:
            logger.info(f"{rid}: no canonical JSON, skipping")
            continue
        data = json.loads(path.read_text())
        if args.resume and "indent_recovery" in data.get("post_process", {}):
            logger.info(f"{rid}: already indent-processed, skipping")
            continue
        lines = data.get("comparative_lines") or []
        if not lines:
            logger.info(f"{rid}: 0 comparative lines, skipping")
            continue
        # The canonical path always encodes the congress (.../<congress>/house/<rid>.json);
        # the top-level `congress` field is null on ~18% of files, so trust the path first.
        congress = data.get("congress") or path.parent.parent.name
        pdf = _pdf_path(rid, congress)
        if not pdf.exists():
            logger.info(f"{rid}: PDF missing at {pdf}, skipping")
            continue

        stats = recover_indent(pdf, lines)
        agg["reports"] += 1
        for k in ("oversum_blocks", "pages_reread", "blocks_recovered", "rows_labeled", "gemini_calls"):
            agg[k] += stats[k]
        logger.info(
            f"{rid}: oversum={stats['oversum_blocks']} pages_reread={stats['pages_reread']} "
            f"recovered={stats['blocks_recovered']} rows_labeled={stats['rows_labeled']}"
        )
        if args.write:
            # Bank any labels immediately (they're safe and additive). Only stamp the
            # resume marker when EVERY over-sum page actually re-read — if a page errored
            # (e.g. the API credits ran dry mid-report), leave the report unmarked so a
            # later --resume retries it instead of silently skipping unfinished work.
            if stats["rows_labeled"]:
                data["comparative_lines"] = lines
            if stats["pages_failed"]:
                if stats["rows_labeled"]:
                    path.write_text(json.dumps(data, indent=2))
                logger.info(
                    f"  {rid}: {stats['pages_failed']} page(s) failed — banked "
                    f"{stats['rows_labeled']} labels but NOT marking done (retryable)"
                )
            else:
                data.setdefault("post_process", {})["indent_recovery"] = stats
                path.write_text(json.dumps(data, indent=2))
                logger.info(f"  wrote {stats['rows_labeled']} labels + marker to {path.name}")

    rec = agg["blocks_recovered"]
    ob = agg["oversum_blocks"]
    logger.info("=" * 60)
    logger.info(
        f"AGGREGATE over {agg['reports']} reports: "
        f"recovered {rec}/{ob} over-sum blocks ({(100*rec/ob) if ob else 0:.0f}%), "
        f"{agg['rows_labeled']} rows labeled, {agg['gemini_calls']} Gemini calls "
        f"over {agg['pages_reread']} pages"
    )


if __name__ == "__main__":
    main()
