"""Batch-run the House hybrid extractor over a slice of the corpus, with a metrics ledger.

For each selected House report it: downloads HTML+PDF if missing, extracts the inline
tables to a CSV (so the recall cross-check is active), runs the Nemotron+Gemini hybrid,
writes the canonical extracted JSON, and appends a metrics row to
data/output/hybrid_ledger.csv. Designed to be run incrementally (by FY / congress)
so the hybrid can be inspected and tuned between batches.

Usage:
  # explicit ids
  uv run python scripts/run_corpus.py CRPT-118hrpt555 CRPT-118hrpt556
  # or select from the catalog
  uv run python scripts/run_corpus.py --fy 2025 [--congress 118] [--subcommittee Defense]
  uv run python scripts/run_corpus.py --fy 2025 --skip-existing --limit 3
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx

from approps.config import EXTRACTED_DIR, OUTPUT_DIR, RAW_DIR
from approps.discovery.report_catalog import load_catalog
from approps.download.fetcher import ReportFetcher
from approps.extraction.hybrid import extract_house_hybrid
from approps.extraction.inline_tables import extract_inline_tables
from approps.extraction.nemotron_parse import NEMOTRON_BASE_URL, extract_house_nemotron
from approps.extraction.verify import verify
from approps.output.csv_writer import write_inline_csv
from approps.verification.recall_check import audit_recall, load_inline_accounts

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

LEDGER = OUTPUT_DIR / "hybrid_ledger.csv"
LEDGER_COLS = [
    "report_id", "congress", "fiscal_year", "subcommittee", "image_pages",
    "gemini_calls", "gemini_frac", "nemotron_pass_rate", "hybrid_pass_rate",
    "hybrid_pass", "hybrid_fail", "recall", "total_lines",
]


def _nemotron_up() -> bool:
    """Health-check the Nemotron server so we never churn empty files at a dead server."""
    try:
        return httpx.get(NEMOTRON_BASE_URL.rsplit("/v1", 1)[0] + "/health", timeout=8).status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _chamber(r) -> str:
    return getattr(r.chamber, "value", r.chamber)


def _select(args) -> list:
    cat = load_catalog()
    house = [r for r in cat if _chamber(r) == "house" and r.package_id.startswith("CRPT")]
    if args.package_ids:
        ids = set(args.package_ids)
        return [r for r in house if r.package_id in ids]
    rep = house
    if args.congress:
        rep = [r for r in rep if r.congress == args.congress]
    if args.fy:
        rep = [r for r in rep if r.fiscal_year == args.fy]
    if args.subcommittee:
        rep = [r for r in rep if r.subcommittee == args.subcommittee]
    return rep


def _ensure_files(report) -> tuple[Path, Path]:
    pdf = RAW_DIR / str(report.congress) / "house" / f"{report.package_id}.pdf"
    htm = RAW_DIR / str(report.congress) / "house" / f"{report.package_id}.htm"
    if not pdf.exists() or not htm.exists():
        logger.info(f"  downloading {report.package_id} (pdf/html) ...")

        async def _fetch():
            fetcher = ReportFetcher()
            try:
                await fetcher.fetch_report(report)
            finally:
                await fetcher.close()

        asyncio.run(_fetch())

    # GovInfo sometimes serves an HTML landing/error page at the .pdf URL (the report
    # has no PDF rendition). Detect that so the batch skips it cleanly with a clear
    # message instead of failing deep inside pdfplumber.
    if pdf.exists() and pdf.read_bytes()[:5] != b"%PDF-":
        raise ValueError(f"{pdf.name}: GovInfo served non-PDF content (no PDF rendition?)")
    return pdf, htm


def _append_ledger(row: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS)
        if new:
            w.writeheader()
        w.writerow(row)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("package_ids", nargs="*", help="Explicit report ids (else use filters)")
    ap.add_argument("--congress", type=int, default=None)
    ap.add_argument("--fy", type=int, default=None)
    ap.add_argument("--subcommittee", default=None)
    ap.add_argument("--skip-existing", action="store_true",
                    help="Skip reports whose canonical JSON is already a hybrid run")
    ap.add_argument("--nemotron-only", action="store_true",
                    help="Phase A: run only the Nemotron first pass (+inline CSV), no Gemini. "
                         "Saves <id>_nemotron.json for a later cleanup pass.")
    ap.add_argument("--reuse-nemotron", action="store_true",
                    help="Hybrid phase: reuse an existing <id>_nemotron.json instead of "
                         "re-running Nemotron (run the Gemini cleanup leg only).")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    reports = _select(args)
    if args.limit:
        reports = reports[: args.limit]
    if not reports:
        logger.info("No matching House reports.")
        return
    # Cleanup (--reuse-nemotron) reuses saved passes and never calls the Spark, so it
    # doesn't need the server up. Only gate fresh Nemotron work on server health.
    if not args.reuse_nemotron and not _nemotron_up():
        logger.error(f"Nemotron server unreachable at {NEMOTRON_BASE_URL} — aborting. "
                     "Is the DGX Spark / Tailscale up? (No empty files written.)")
        sys.exit(2)
    logger.info(f"Batch: {len(reports)} House reports")

    summary = []
    for i, report in enumerate(reports, 1):
        rid = report.package_id
        out_path = EXTRACTED_DIR / str(report.congress) / "house" / f"{rid}.json"
        nemo_existing = EXTRACTED_DIR / str(report.congress) / "house" / f"{rid}_nemotron.json"
        if args.skip_existing:
            if args.nemotron_only and nemo_existing.exists():
                logger.info(f"[{i}/{len(reports)}] {rid}: nemotron pass exists, skipping")
                continue
            if not args.nemotron_only and out_path.exists():
                existing = json.loads(out_path.read_text())
                if "hybrid" in str(existing.get("vision_model", "")):
                    logger.info(f"[{i}/{len(reports)}] {rid}: already hybrid, skipping")
                    continue

        logger.info(f"\n[{i}/{len(reports)}] {rid} ({report.subcommittee} FY{report.fiscal_year})")
        house_dir = EXTRACTED_DIR / str(report.congress) / "house"
        try:
            pdf, htm = _ensure_files(report)
            # Inline tables (HTML) -> CSV so the recall cross-check is active.
            tables = extract_inline_tables(
                text=htm.read_text(), report_id=rid, congress=report.congress,
                chamber="house", fiscal_year=report.fiscal_year, subcommittee=report.subcommittee,
            )
            write_inline_csv(tables, EXTRACTED_DIR / f"{rid}_inline.csv")

            if args.nemotron_only:
                # Phase A: Nemotron first pass only; save for a later Gemini cleanup.
                lines, meta = extract_house_nemotron(
                    pdf, rid, report.congress, report.fiscal_year, report.subcommittee
                )
                line_dicts = [ln.model_dump(mode="json") for ln in lines]
                # Don't save an empty pass that came from server/connection errors — it
                # would be wrongly skipped on resume. A genuine 0-row report (no
                # comparative tables, e.g. construction-only) has no errored pages.
                if not line_dicts and meta.get("pages_errored"):
                    logger.error(f"  {rid}: 0 rows with {len(meta['pages_errored'])} errored pages "
                                 "(server issue?) — NOT saving, will retry next run")
                    continue
                house_dir.mkdir(parents=True, exist_ok=True)
                (house_dir / f"{rid}_nemotron.json").write_text(json.dumps({
                    "report_id": rid, "congress": report.congress, "chamber": "house",
                    "fiscal_year": report.fiscal_year, "subcommittee": report.subcommittee,
                    "vision_model": "nemotron", "comparative_lines": line_dicts,
                    "extraction_report": meta,
                }, indent=2))
                v = verify(line_dicts)
                inline_acc = load_inline_accounts(rid)
                rec = audit_recall(line_dicts, inline_acc)["recall"] if inline_acc else None
                row = {
                    "report_id": rid, "congress": report.congress, "fiscal_year": report.fiscal_year,
                    "subcommittee": report.subcommittee, "image_pages": meta["image_pages"],
                    "gemini_calls": 0, "gemini_frac": None,
                    "nemotron_pass_rate": round(v["pass_rate"], 4) if v["pass_rate"] else None,
                    "hybrid_pass_rate": None, "hybrid_pass": v["passed"], "hybrid_fail": v["failed"],
                    "recall": round(rec, 4) if rec is not None else None,
                    "total_lines": len(line_dicts),
                }
                _append_ledger(row)
                summary.append(row)
                logger.info(f"  -> nemotron {v['passed']}/{v['verifiable']} "
                            f"({(v['pass_rate'] or 0):.1%}), recall {rec}, saved _nemotron.json")
                continue

            reuse = (house_dir / f"{rid}_nemotron.json") if args.reuse_nemotron else None
            lines, meta = extract_house_hybrid(
                pdf_path=pdf, report_id=rid, congress=report.congress,
                fiscal_year=report.fiscal_year, subcommittee=report.subcommittee,
                reuse_nemotron_path=reuse,
            )
        except Exception as e:  # noqa: BLE001 - record and continue the batch
            logger.error(f"  FAILED: {e}")
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({
            "report_id": rid, "congress": report.congress, "chamber": "house",
            "fiscal_year": report.fiscal_year, "subcommittee": report.subcommittee,
            "vision_model": "hybrid (nemotron+gemini)",
            "inline_tables": [t.model_dump(mode="json") for t in tables],
            "comparative_lines": [ln.model_dump(mode="json") for ln in lines],
            "extraction_report": meta,
        }, indent=2))

        frac = meta["gemini_calls"] / meta["image_pages"] if meta["image_pages"] else None
        row = {
            "report_id": rid, "congress": report.congress, "fiscal_year": report.fiscal_year,
            "subcommittee": report.subcommittee, "image_pages": meta["image_pages"],
            "gemini_calls": meta["gemini_calls"],
            "gemini_frac": round(frac, 3) if frac is not None else None,
            "nemotron_pass_rate": round(meta["nemotron_pass_rate"], 4) if meta["nemotron_pass_rate"] else None,
            "hybrid_pass_rate": round(meta["hybrid_pass_rate"], 4) if meta["hybrid_pass_rate"] else None,
            "hybrid_pass": meta["hybrid_pass"], "hybrid_fail": meta["hybrid_fail"],
            "recall": round(meta["recall"], 4) if meta["recall"] is not None else None,
            "total_lines": meta["total_lines"],
        }
        _append_ledger(row)
        summary.append(row)
        logger.info(f"  -> hybrid {meta['hybrid_pass']}/{meta['hybrid_verifiable']} "
                    f"({(meta['hybrid_pass_rate'] or 0):.1%}), "
                    f"gemini {meta['gemini_calls']}/{meta['image_pages']} "
                    f"({(frac or 0):.0%}), recall {meta['recall']}")

    if summary:
        gp = sum(r["gemini_calls"] for r in summary)
        ip = sum(r["image_pages"] for r in summary)
        logger.info(f"\n=== batch done: {len(summary)} reports ===")
        logger.info(f"gemini calls: {gp}/{ip} pages ({gp/ip:.0%}) | ledger: {LEDGER}")


if __name__ == "__main__":
    main()
