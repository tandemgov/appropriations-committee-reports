"""CLI entry point for the approps pipeline."""

from __future__ import annotations

import asyncio
import json as json_mod
import logging
import sys
from pathlib import Path

import click

from approps.config import MAX_CONGRESS, MIN_CONGRESS, OUTPUT_DIR

# Intermediate House vision artifacts written alongside the primary <package_id>.json:
# the Nemotron first pass (<id>_nemotron.json) and the hybrid pre-promotion output
# (<id>_hybrid.json). Package IDs are hyphenated (CRPT-118hrpt553), never underscored,
# so any underscore in the stem marks an intermediate. These must NOT be ingested by
# output/crosswalk/verify or the same report is double- or triple-counted.
_INTERMEDIATE_SUFFIXES = ("_nemotron", "_hybrid")


def _primary_json_files(root: Path) -> list[Path]:
    """Extracted primary artifacts only — excludes intermediate vision passes."""
    return [
        p
        for p in root.rglob("*.json")
        if not p.stem.endswith(_INTERMEDIATE_SUFFIXES)
    ]


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def _filter_reports(reports, chamber: str | None, fiscal_year: int | None, stage: str | None = None):
    """Narrow a list of ReportMetadata by chamber, fiscal year, and/or stage.

    Lets the catalog-driven commands target one track (e.g. Senate FY2024, or the enacted
    explanatory-statement prints) without pulling in the whole catalog — notably to avoid
    triggering House vision extraction.
    """
    if chamber:
        reports = [r for r in reports if r.chamber == chamber]
    if fiscal_year is not None:
        reports = [r for r in reports if r.fiscal_year == fiscal_year]
    if stage:
        reports = [r for r in reports if r.stage == stage]
    return reports


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose: bool) -> None:
    """approps: Extract appropriations data from congressional committee reports."""
    _setup_logging(verbose)


@cli.command()
@click.option(
    "--min-congress", default=MIN_CONGRESS, help=f"Earliest congress (default: {MIN_CONGRESS})"
)
@click.option(
    "--max-congress", default=MAX_CONGRESS, help=f"Latest congress (default: {MAX_CONGRESS})"
)
def discover(min_congress: int, max_congress: int) -> None:
    """Discover appropriations committee reports on GovInfo."""
    from approps.discovery.enacted_prints import enacted_report_metadata
    from approps.discovery.govinfo_api import GovInfoClient
    from approps.discovery.report_catalog import discover_reports, save_catalog

    async def _run():
        client = GovInfoClient()
        try:
            reports = await discover_reports(client, min_congress, max_congress)
            # Append curated enacted-stage explanatory-statement prints (CPRT collection);
            # these are omnibus and not found by the per-subcommittee CRPT scan.
            enacted = enacted_report_metadata(min_congress, max_congress)
            reports.extend(enacted)
            save_catalog(reports)
            click.echo(
                f"Discovered {len(reports)} reports "
                f"({len(enacted)} enacted explanatory-statement prints)"
            )
        finally:
            await client.close()

    asyncio.run(_run())


@cli.command()
@click.option("--package-id", "-p", help="Download a specific report by package ID")
@click.option("--all", "fetch_all", is_flag=True, help="Download all reports in the catalog")
@click.option("--chamber", "-c", type=click.Choice(["house", "senate"]), help="Limit to one chamber")
@click.option("--fiscal-year", "--fy", type=int, default=None, help="Limit to one fiscal year")
@click.option(
    "--stage",
    type=click.Choice(["subcommittee", "committee", "conference", "enacted"]),
    help="Limit to one legislative stage",
)
def download(
    package_id: str | None,
    fetch_all: bool,
    chamber: str | None,
    fiscal_year: int | None,
    stage: str | None,
) -> None:
    """Download report HTML/PDF from GovInfo."""
    from approps.discovery.report_catalog import load_catalog
    from approps.download.fetcher import ReportFetcher

    catalog = load_catalog()
    if not catalog:
        click.echo("No reports in catalog. Run 'approps discover' first.", err=True)
        sys.exit(1)

    if package_id:
        reports = [r for r in catalog if r.package_id == package_id]
        if not reports:
            click.echo(f"Report {package_id} not found in catalog.", err=True)
            sys.exit(1)
    elif fetch_all:
        reports = catalog
    else:
        click.echo("Specify --package-id or --all", err=True)
        sys.exit(1)

    reports = _filter_reports(reports, chamber, fiscal_year, stage)
    if not reports:
        click.echo("No reports match the given filters.", err=True)
        sys.exit(1)

    async def _run():
        fetcher = ReportFetcher()
        try:
            results = await fetcher.fetch_all(reports)
            click.echo(f"Downloaded {len(results)} reports")
        finally:
            await fetcher.close()

    asyncio.run(_run())


@cli.command()
@click.option("--package-id", "-p", help="Extract a specific report")
@click.option("--all", "extract_all", is_flag=True, help="Extract all downloaded reports")
@click.option("--chamber", "-c", type=click.Choice(["house", "senate"]), help="Limit to one chamber")
@click.option("--fiscal-year", "--fy", type=int, default=None, help="Limit to one fiscal year")
@click.option(
    "--stage",
    type=click.Choice(["subcommittee", "committee", "conference", "enacted"]),
    help="Limit to one legislative stage",
)
@click.option(
    "--type",
    "extract_type",
    type=click.Choice(["inline", "comparative", "all"]),
    default="all",
    help="What to extract",
)
def extract(
    package_id: str | None,
    extract_all: bool,
    chamber: str | None,
    fiscal_year: int | None,
    stage: str | None,
    extract_type: str,
) -> None:
    """Extract structured data from downloaded reports."""
    from approps.config import EXTRACTED_DIR, RAW_DIR
    from approps.discovery.report_catalog import load_catalog
    from approps.output.schemas import Chamber

    catalog = load_catalog()
    if not catalog:
        click.echo("No reports in catalog. Run 'approps discover' first.", err=True)
        sys.exit(1)

    if package_id:
        reports = [r for r in catalog if r.package_id == package_id]
        if not reports:
            click.echo(f"Report {package_id} not found in catalog.", err=True)
            sys.exit(1)
    elif extract_all:
        reports = catalog
    else:
        click.echo("Specify --package-id or --all", err=True)
        sys.exit(1)

    reports = _filter_reports(reports, chamber, fiscal_year, stage)
    if not reports:
        click.echo("No reports match the given filters.", err=True)
        sys.exit(1)

    for report in reports:
        _extract_report(report, extract_type, RAW_DIR, EXTRACTED_DIR, Chamber)


@cli.command("extract-file")
@click.argument("html_path", type=click.Path(exists=True))
@click.option("--chamber", "-c", type=click.Choice(["house", "senate"]), required=True)
@click.option("--congress", type=int, default=118)
@click.option("--fiscal-year", "--fy", type=int, default=None)
@click.option("--subcommittee", "-s", default=None)
@click.option("--output-dir", "-o", type=click.Path(), default=None)
@click.option("--csv", "write_csv", is_flag=True, help="Also write CSV output")
def extract_file(
    html_path: str,
    chamber: str,
    congress: int,
    fiscal_year: int | None,
    subcommittee: str | None,
    output_dir: str | None,
    write_csv: bool,
) -> None:
    """Extract from a local HTML file (no catalog needed).

    Example: approps extract-file /tmp/CRPT-118srpt83.htm -c senate --fy 2024
    """
    from approps.extraction.comparative_senate import extract_senate_comparative
    from approps.extraction.inline_tables import extract_inline_tables
    from approps.output.csv_writer import write_comparative_csv, write_inline_csv

    path = Path(html_path)
    report_id = path.stem
    text = path.read_text()

    click.echo(f"Extracting: {report_id} ({chamber})")

    # Inline tables
    tables = extract_inline_tables(
        text=text,
        report_id=report_id,
        congress=congress,
        chamber=chamber,
        fiscal_year=fiscal_year,
        subcommittee=subcommittee,
    )
    click.echo(f"  Inline tables: {len(tables)}")

    # Comparative statement (Senate only for now)
    comp_lines = []
    if chamber == "senate":
        comp_lines = extract_senate_comparative(
            text=text,
            report_id=report_id,
            congress=congress,
            fiscal_year=fiscal_year,
            subcommittee=subcommittee,
        )
        data_count = sum(1 for ln in comp_lines if not ln.is_subtotal)
        sub_count = sum(1 for ln in comp_lines if ln.is_subtotal)
        click.echo(f"  Comparative: {len(comp_lines)} lines ({data_count} data, {sub_count} subtotals)")
    else:
        click.echo("  Comparative: skipped (House PDF extraction requires vision model)")

    # Save JSON
    out_dir = Path(output_dir) if output_dir else Path("data/extracted")
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "report_id": report_id,
        "congress": congress,
        "chamber": chamber,
        "fiscal_year": fiscal_year,
        "subcommittee": subcommittee,
        "inline_tables": [t.model_dump(mode="json") for t in tables],
        "comparative_lines": [ln.model_dump(mode="json") for ln in comp_lines],
    }
    json_path = out_dir / f"{report_id}.json"
    json_path.write_text(json_mod.dumps(result, indent=2))
    click.echo(f"  JSON: {json_path}")

    # Optionally write CSV
    if write_csv:
        if comp_lines:
            csv_path = write_comparative_csv(comp_lines, out_dir / f"{report_id}_comparative.csv")
            click.echo(f"  CSV: {csv_path}")
        if tables:
            csv_path = write_inline_csv(tables, out_dir / f"{report_id}_inline.csv")
            click.echo(f"  CSV: {csv_path}")


@cli.command("extract-house-pdf")
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--report-id", "-r", default=None, help="Report id (default: PDF filename stem)")
@click.option("--congress", type=int, required=True)
@click.option("--fiscal-year", "--fy", type=int, default=None)
@click.option("--subcommittee", "-s", default=None)
def extract_house_pdf(
    pdf_path: str,
    report_id: str | None,
    congress: int,
    fiscal_year: int | None,
    subcommittee: str | None,
) -> None:
    """Extract a House committee-print PDF that is not in the catalog.

    Auto-routes: born-digital typeset prints are parsed from the text layer; image
    -based reports fall through to the vision pipeline. Writes the comparative JSON
    to data/extracted/<congress>/house/ in the standard schema.

    Example:
        approps extract-house-pdf report.pdf --congress 119 --fy 2027 -s Defense
    """
    from approps.config import EXTRACTED_DIR
    from approps.extraction.comparative_house_text import (
        extract_house_text,
        is_born_digital_house_pdf,
    )

    path = Path(pdf_path)
    rid = report_id or path.stem

    if is_born_digital_house_pdf(path):
        lines = extract_house_text(
            pdf_path=path, report_id=rid, congress=congress,
            fiscal_year=fiscal_year, subcommittee=subcommittee,
        )
        click.echo(f"Born-digital text print: {len(lines)} comparative lines")
    else:
        from approps.extraction.comparative_house import extract_house_comparative

        lines = extract_house_comparative(
            pdf_path=path, report_id=rid, congress=congress,
            fiscal_year=fiscal_year, subcommittee=subcommittee,
        )
        click.echo(f"Image-based print (vision): {len(lines)} comparative lines")

    data = sum(1 for ln in lines if not ln.is_subtotal)
    verified = sum(1 for ln in lines if ln.verified)
    click.echo(f"  {data} line items, {len(lines) - data} subtotals, {verified} self-verified")

    result = {
        "report_id": rid,
        "congress": congress,
        "chamber": "house",
        "fiscal_year": fiscal_year,
        "subcommittee": subcommittee,
        "inline_tables": [],
        "comparative_lines": [ln.model_dump(mode="json") for ln in lines],
    }
    out_dir = EXTRACTED_DIR / str(congress) / "house"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{rid}.json"
    out_path.write_text(json_mod.dumps(result, indent=2))
    click.echo(f"  Saved: {out_path}")


def _extract_report(report, extract_type, raw_dir, extracted_dir, chamber_cls):
    """Extract a single report (used by the extract command)."""
    from approps.config import VISION_BACKEND
    from approps.extraction.comparative_house import extract_house_comparative
    from approps.extraction.comparative_senate import extract_senate_comparative
    from approps.extraction.inline_tables import extract_inline_tables
    from approps.output.schemas import Stage

    # Enacted explanatory-statement prints (CPRT): PDF-only, parsed by the enacted module.
    if report.stage == Stage.ENACTED:
        _extract_enacted_report(report, raw_dir, extracted_dir)
        return

    click.echo(f"\nExtracting: {report.package_id} ({report.subcommittee})")

    html_path = raw_dir / str(report.congress) / report.chamber.value / f"{report.package_id}.htm"
    if not html_path.exists():
        click.echo(
            f"  HTML not downloaded. Run 'approps download -p {report.package_id}' first.",
            err=True,
        )
        return

    text = html_path.read_text()
    result: dict = {"report_id": report.package_id, "inline_tables": [], "comparative_lines": []}

    # Inline tables (both chambers, from HTML)
    if extract_type in ("inline", "all"):
        try:
            tables = extract_inline_tables(
                text=text,
                report_id=report.package_id,
                congress=report.congress,
                chamber=report.chamber.value,
                fiscal_year=report.fiscal_year,
                subcommittee=report.subcommittee,
            )
            # Senate reports published only as a born-digital PDF carry their figures in
            # per-account prose mini-tables inside the PDF text layer; GovInfo serves a
            # cover-page stub for the HTML (e.g. CRPT-119srpt55). When the HTML yields
            # nothing, fall back to the PDF and parse the same inline-table shape. Self-
            # guarding: an image-only PDF extracts no text and returns 0, as before.
            if not tables and report.chamber == chamber_cls.SENATE:
                pdf_path = (
                    raw_dir / str(report.congress) / report.chamber.value
                    / f"{report.package_id}.pdf"
                )
                if pdf_path.exists():
                    from approps.extraction.inline_tables import (
                        extract_inline_tables_from_pdf,
                    )
                    tables = extract_inline_tables_from_pdf(
                        pdf_path=pdf_path,
                        report_id=report.package_id,
                        congress=report.congress,
                        chamber=report.chamber.value,
                        fiscal_year=report.fiscal_year,
                        subcommittee=report.subcommittee,
                    )
                    if tables:
                        click.echo("  (Senate HTML was a stub; parsed born-digital PDF text)")
            result["inline_tables"] = [t.model_dump(mode="json") for t in tables]
            click.echo(f"  Inline tables: {len(tables)}")
        except Exception as e:
            click.echo(f"  Inline extraction failed: {e}", err=True)

    # Comparative statements
    if extract_type in ("comparative", "all"):
        if report.chamber == chamber_cls.SENATE:
            try:
                lines = extract_senate_comparative(
                    text=text,
                    report_id=report.package_id,
                    congress=report.congress,
                    fiscal_year=report.fiscal_year,
                    subcommittee=report.subcommittee,
                )
                result["comparative_lines"] = [ln.model_dump(mode="json") for ln in lines]
                click.echo(f"  Comparative lines (Senate HTML): {len(lines)}")
            except Exception as e:
                click.echo(f"  Senate comparative extraction failed: {e}", err=True)
        else:
            pdf_path = (
                raw_dir
                / str(report.congress)
                / report.chamber.value
                / f"{report.package_id}.pdf"
            )
            if pdf_path.exists():
                try:
                    # Born-digital, typeset House prints (e.g. modern full-committee
                    # markups) have a real text layer -> parse it directly, skipping the
                    # vision pipeline entirely. The detector falls through to vision for
                    # the image-based reports.
                    from approps.extraction.comparative_house_text import (
                        extract_house_text,
                        is_born_digital_house_pdf,
                    )
                    if is_born_digital_house_pdf(pdf_path):
                        lines = extract_house_text(
                            pdf_path=pdf_path, report_id=report.package_id,
                            congress=report.congress, fiscal_year=report.fiscal_year,
                            subcommittee=report.subcommittee,
                        )
                        label = "House PDF/Text"
                    # VISION_BACKEND selects the House engine: the local Nemotron-Parse
                    # server ("nemotron"), the Nemotron+Gemini hybrid ("hybrid"), or the
                    # single-model vision path (gemini/anthropic/openai-compat).
                    elif VISION_BACKEND == "hybrid":
                        from approps.extraction.hybrid import extract_house_hybrid
                        lines, _ = extract_house_hybrid(
                            pdf_path=pdf_path, report_id=report.package_id,
                            congress=report.congress, fiscal_year=report.fiscal_year,
                            subcommittee=report.subcommittee,
                        )
                        label = "House PDF/Hybrid"
                    elif VISION_BACKEND == "nemotron":
                        from approps.extraction.nemotron_parse import extract_house_nemotron
                        lines, _ = extract_house_nemotron(
                            pdf_path=pdf_path, report_id=report.package_id,
                            congress=report.congress, fiscal_year=report.fiscal_year,
                            subcommittee=report.subcommittee,
                        )
                        label = "House PDF/Nemotron"
                    else:
                        lines = extract_house_comparative(
                            pdf_path=pdf_path,
                            report_id=report.package_id,
                            congress=report.congress,
                            fiscal_year=report.fiscal_year,
                            subcommittee=report.subcommittee,
                        )
                        label = "House PDF/Vision"
                    result["comparative_lines"] = [ln.model_dump(mode="json") for ln in lines]
                    click.echo(f"  Comparative lines ({label}): {len(lines)}")
                except Exception as e:
                    click.echo(f"  House PDF extraction failed: {e}", err=True)
            else:
                click.echo(
                    f"  PDF not downloaded. Run 'approps download -p {report.package_id}'."
                )

    # Save extracted data
    out_dir = extracted_dir / str(report.congress) / report.chamber.value
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report.package_id}.json"
    out_path.write_text(json_mod.dumps(result, indent=2))
    click.echo(f"  Saved: {out_path}")


def _extract_enacted_report(report, raw_dir, extracted_dir) -> None:
    """Extract enacted line items from a CPRT explanatory-statement PDF (self-verifying)."""
    from approps.extraction.comparative_enacted import extract_enacted_pdf

    click.echo(f"\nExtracting (enacted): {report.package_id} (FY{report.fiscal_year})")
    pdf_path = raw_dir / str(report.congress) / "cprt" / f"{report.package_id}.pdf"
    if not pdf_path.exists():
        click.echo(
            f"  PDF not downloaded. Run 'approps download -p {report.package_id} "
            f"--stage enacted' first.",
            err=True,
        )
        return

    lines = extract_enacted_pdf(
        pdf_path=pdf_path,
        report_id=report.package_id,
        congress=report.congress,
        fiscal_year=report.fiscal_year,
    )
    verified = sum(1 for ln in lines if ln.verified)
    result = {
        "report_id": report.package_id,
        "inline_tables": [],
        "comparative_lines": [ln.model_dump(mode="json") for ln in lines],
    }
    out_dir = extracted_dir / str(report.congress) / "enacted"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report.package_id}.json"
    out_path.write_text(json_mod.dumps(result, indent=2))
    click.echo(f"  Enacted lines: {len(lines)} ({verified} self-verified)")
    click.echo(f"  Saved: {out_path}")


@cli.command()
@click.option("--package-id", "-p", help="Verify a specific report's extraction")
@click.option("--all", "verify_all", is_flag=True, help="Verify all extracted reports")
@click.option("--chamber", "-c", type=click.Choice(["house", "senate"]), help="Limit to one chamber")
@click.option("--fiscal-year", "--fy", type=int, default=None, help="Limit to one fiscal year")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the audit report without writing verified flags back to the JSON",
)
def verify(
    package_id: str | None,
    verify_all: bool,
    chamber: str | None,
    fiscal_year: int | None,
    dry_run: bool,
) -> None:
    """Run verification checks on extracted data and persist verified flags.

    Each line item is marked verified=true when every dollar amount it carries matches
    the source HTML (three-tier string match). Results are written back into the
    extracted JSON unless --dry-run is given. The string-match check applies to the text
    tracks (Senate comparative, inline tables); House comparative tables extracted from
    images are verified separately (scripts/verify_house.py) and are skipped here when no
    source HTML exists, so their verification is never clobbered.
    """
    from approps.config import EXTRACTED_DIR, RAW_DIR
    from approps.output.schemas import DollarAmount
    from approps.verification.amount_verifier import verify_amount
    from approps.verification.audit_report import build_audit_report, format_audit_report

    json_files = []
    if package_id:
        for path in EXTRACTED_DIR.rglob(f"{package_id}.json"):
            json_files.append(path)
    elif verify_all:
        json_files = _primary_json_files(EXTRACTED_DIR)
    else:
        click.echo("Specify --package-id or --all", err=True)
        sys.exit(1)

    if not json_files:
        click.echo("No extracted data found. Run 'approps extract' first.", err=True)
        sys.exit(1)

    def _verify_item(item: dict, fields: list[str], results: list) -> bool | None:
        """Verify one line item's amounts; return whether all matched (None if no amounts)."""
        item_results = []
        for field in fields:
            amt_data = item.get(field)
            if amt_data and amt_data.get("raw_text"):
                amt = DollarAmount(**amt_data)
                r = verify_amount(amt, source_text)
                item_results.append(r)
                results.append(r)
        if not item_results:
            return None
        return all(r.matched for r in item_results)

    def _report_field(data: dict, key: str):
        """Read a report-level field that may live only on the nested line items."""
        if data.get(key) is not None:
            return data[key]
        for coll in ("comparative_lines", "inline_tables"):
            for item in data.get(coll, []):
                if item.get(key) is not None:
                    return item[key]
        return None

    total_changed = 0
    for json_path in sorted(json_files):
        data = json_mod.loads(json_path.read_text())
        report_id = data["report_id"]

        if chamber and _report_field(data, "chamber") != chamber:
            continue
        if fiscal_year is not None and _report_field(data, "fiscal_year") != fiscal_year:
            continue

        # Find source HTML for verification
        source_text = ""
        for htm_path in RAW_DIR.rglob(f"{report_id}.htm"):
            source_text = htm_path.read_text()
            break

        if not source_text:
            click.echo(f"{report_id}: no source HTML for verification (skipped)")
            continue

        # Verify each line item and update its verified flag
        results: list = []
        changed = 0
        for item in data.get("inline_tables", []):
            ok = _verify_item(
                item, ["prior_year", "budget_estimate", "committee_recommendation"], results
            )
            if ok is not None and item.get("verified") != ok:
                item["verified"] = ok
                changed += 1

        for item in data.get("comparative_lines", []):
            ok = _verify_item(
                item,
                ["prior_year_enacted", "budget_estimate", "committee_recommendation"],
                results,
            )
            if ok is not None and item.get("verified") != ok:
                item["verified"] = ok
                changed += 1

        report = build_audit_report(report_id, results)
        click.echo(format_audit_report(report))
        if not dry_run:
            json_path.write_text(json_mod.dumps(data, indent=2))
            click.echo(f"  Persisted verified flags ({changed} rows updated): {json_path}")
        total_changed += changed
        click.echo()

    if not dry_run:
        click.echo(f"Total rows updated: {total_changed}")


@cli.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"]),
    default="csv",
    help="Output format",
)
def output(output_format: str) -> None:
    """Generate combined output datasets from all extracted data."""
    from approps.config import EXTRACTED_DIR
    from approps.normalization.account_inference import infer_block_accounts
    from approps.normalization.summary_rows import drop_summary_rows
    from approps.output.csv_writer import write_comparative_csv, write_inline_csv
    from approps.output.schemas import (
        ComparativeStatementLine,
        InlineFundingTable,
    )

    json_files = _primary_json_files(EXTRACTED_DIR)
    if not json_files:
        click.echo("No extracted data found. Run 'approps extract' first.", err=True)
        sys.exit(1)

    all_comp: list[ComparativeStatementLine] = []
    all_inline: list[InlineFundingTable] = []
    inferred_total = 0

    for path in json_files:
        data = json_mod.loads(path.read_text())
        # Drop 302(b) compliance / outlay-projection back-matter tables — not line items.
        comp_items = drop_summary_rows(data.get("comparative_lines", []))
        # Recover account groupings for House vision rows from reconciling subtotal
        # blocks (arithmetic-verified; `account` untouched). Per report, in order.
        inferred_total += infer_block_accounts(comp_items)
        for item in comp_items:
            all_comp.append(ComparativeStatementLine(**item))
        for item in data.get("inline_tables", []):
            all_inline.append(InlineFundingTable(**item))

    click.echo(f"Loaded {len(all_comp)} comparative lines, {len(all_inline)} inline tables")
    if inferred_total:
        click.echo(f"  account_inferred set on {inferred_total} rows (arithmetic-verified subtotal blocks)")

    if output_format == "csv":
        if all_comp:
            write_comparative_csv(all_comp, inline_tables=all_inline)
        if all_inline:
            write_inline_csv(all_inline)
        click.echo(f"CSV output written to {OUTPUT_DIR}/")
    else:
        out_path = OUTPUT_DIR / "all_data.json"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_mod.dumps({
            "comparative_lines": [ln.model_dump(mode="json") for ln in all_comp],
            "inline_tables": [t.model_dump(mode="json") for t in all_inline],
        }, indent=2))
        click.echo(f"JSON output written to {out_path}")


@cli.command()
def crosswalk() -> None:
    """Build the authoritative account crosswalk + a human-review queue from extracted data."""
    from collections import Counter

    from approps.config import EXTRACTED_DIR
    from approps.normalization.account_inference import infer_block_accounts
    from approps.normalization.summary_rows import drop_summary_rows
    from approps.normalization.account_names import clean_account_label
    from approps.normalization.crosswalk import match_account, write_crosswalk
    from approps.output.schemas import ComparativeStatementLine

    json_files = _primary_json_files(EXTRACTED_DIR)
    if not json_files:
        click.echo("No extracted data found. Run 'approps extract' first.", err=True)
        sys.exit(1)

    table: dict[tuple[str, str], object] = {}
    for path in json_files:
        data = json_mod.loads(path.read_text())
        comp_items = drop_summary_rows(data.get("comparative_lines", []))
        infer_block_accounts(comp_items)
        for item in comp_items:
            ln = ComparativeStatementLine(**item)
            if ln.is_subtotal:
                continue
            cleaned = clean_account_label(
                (ln.account or ln.account_inferred or ln.line_item_text or "").strip()
            )
            if cleaned.is_fragment or not cleaned.normalized:
                continue
            key = (ln.subcommittee or "", cleaned.normalized)
            if key not in table:
                context = " ".join(
                    filter(None, [ln.subcommittee, ln.department, ln.agency, ln.title_name, ln.program])
                )
                table[key] = match_account(cleaned.normalized, context)

    out_path = EXTRACTED_DIR.parent / "reference" / "account_crosswalk.csv"
    write_crosswalk(table, out_path)

    methods = Counter(m.method for m in table.values())
    trusted = sum(1 for m in table.values() if m.account_key and not m.needs_review)
    click.echo(f"Distinct account entities: {len(table)}")
    for meth, n in methods.most_common():
        click.echo(f"  {meth:13}: {n} ({100 * n / len(table):.0f}%)")
    click.echo(f"Trusted account_key (exact + agency-scoped): {trusted} ({100 * trusted / len(table):.0f}%)")
    click.echo(f"Crosswalk + review queue written to {out_path}")


@cli.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, type=int, help="Port to bind to")
@click.option("--reload", "use_reload", is_flag=True, help="Auto-reload on code changes")
def serve(host: str, port: int, use_reload: bool) -> None:
    """Start the FastAPI server."""
    import uvicorn

    uvicorn.run(
        "approps.api.app:app",
        host=host,
        port=port,
        reload=use_reload,
    )


@cli.command()
def status() -> None:
    """Show pipeline status: catalog size, downloaded, extracted."""
    from approps.config import EXTRACTED_DIR, RAW_DIR
    from approps.discovery.report_catalog import load_catalog

    catalog = load_catalog()
    click.echo(f"Reports in catalog: {len(catalog)}")

    html_count = sum(1 for _ in RAW_DIR.rglob("*.htm")) if RAW_DIR.exists() else 0
    pdf_count = sum(1 for _ in RAW_DIR.rglob("*.pdf")) if RAW_DIR.exists() else 0
    click.echo(f"Downloaded: {html_count} HTML, {pdf_count} PDF")

    json_count = len(_primary_json_files(EXTRACTED_DIR)) if EXTRACTED_DIR.exists() else 0
    click.echo(f"Extracted: {json_count} reports")

    if catalog:
        subcommittees = set(r.subcommittee for r in catalog if r.subcommittee)
        congresses = sorted(set(r.congress for r in catalog))
        click.echo(f"Subcommittees: {len(subcommittees)}")
        click.echo(f"Congresses: {congresses}")


@cli.command()
@click.option("--metric", default="committee_recommendation", help="Money metric for the series")
@click.option("--min-years", default=2, type=int, help="Only accounts seen in >= this many fiscal years")
@click.option("--reword-only", is_flag=True, help="Only report substantive (reword) title changes")
def trace(metric: str, min_years: int, reword_only: bool) -> None:
    """Follow crosswalk-keyed accounts across fiscal years and report title changes.

    Groups the enriched dataset by authoritative account_key (the identity that
    survives a rename), then writes one CSV row per title change. A `reword` change
    is a genuine rename candidate — or a crosswalk over-merge, so this doubles as a
    QA lens on the crosswalk. Build the dataset first with `approps output`.
    """
    from collections import Counter

    from approps.api.data import load_line_items
    from approps.normalization.account_authority import trace_accounts

    auths = trace_accounts(load_line_items(), metric=metric, min_years=min_years)
    if not auths:
        click.echo("No crosswalk-keyed accounts found. Run 'approps output' first.", err=True)
        sys.exit(1)

    out_path = OUTPUT_DIR / "account_authority.csv"
    kinds: Counter = Counter()
    rows_written = 0
    with open(out_path, "w", newline="") as fh:
        import csv as _csv

        w = _csv.writer(fh)
        w.writerow(
            ["account_key", "canonical_title", "first_fy", "last_fy", "n_years",
             "change_fy", "from_title", "to_title", "kind"]
        )
        for a in sorted(auths, key=lambda x: x.account_key):
            for c in a.title_changes:
                kinds[c.kind] += 1
                if reword_only and c.kind != "reword":
                    continue
                w.writerow([a.account_key, a.canonical_title, a.first_fiscal_year,
                            a.last_fiscal_year, len(a.fiscal_years), c.fiscal_year,
                            c.from_title, c.to_title, c.kind])
                rows_written += 1

    changed = sum(1 for a in auths if a.title_changes)
    click.echo(f"Crosswalk-keyed accounts (>= {min_years} fiscal years): {len(auths)}")
    click.echo(f"Accounts with a title change: {changed}")
    for kind, n in kinds.most_common():
        click.echo(f"  {kind:7}: {n}")
    click.echo(f"Title-change rows written: {rows_written} -> {out_path}")
