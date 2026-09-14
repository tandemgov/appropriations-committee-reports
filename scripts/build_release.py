"""Assemble the canonical data release from one snapshot of data/output/.

For every table this writes CSV, Parquet, and JSON from the same in-memory frame, reads each back, and refuses to finish unless all three agree row for row and value for value.
The derived account tables are computed from that same frame, not from an older file.
It then runs the release checks and writes `manifest.json` — code revision, source snapshot, counts, check results, and a hash of every file — plus `SHA256SUMS`.

    uv run approps output
    uv run python scripts/build_release.py

Run it from a clean git tree: the manifest records the revision and whether the tree was dirty, and a dirty build is not a release.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pandas as pd

from approps.cli import _primary_json_files
from approps.config import EXTRACTED_DIR, OUTPUT_DIR, REFERENCE_DIR
from approps.normalization.account_authority import trace_accounts
from approps.normalization.account_gate import CROSS_CODED, JURISDICTION, in_jurisdiction
from approps.normalization.account_totals import account_totals
from approps.output.csv_writer import UNTRUSTED_COLUMNS, _coerce_int_columns
from approps.output.schemas import ComparativeStatementRow, InlineFundingRow
from approps.verification.coverage import COVERAGE_FLOORS
from approps.verification.magnitude import LINE_ITEM_CEILING

ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = OUTPUT_DIR.parent / "release"
RECONCILE_FLOOR = 0.75

_LEVELS = ("prior_year_enacted", "budget_estimate", "committee_recommendation")
_AMOUNTS = _LEVELS + ("delta_vs_enacted", "delta_vs_estimate")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _records(df: pd.DataFrame) -> list[dict]:
    """Plain-Python rows (None for missing) for the pure-Python derivations."""
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _source_snapshot() -> dict:
    """A fingerprint of everything the output build read: the extracted JSON and the reference files."""
    h = hashlib.sha256()
    files = sorted(_primary_json_files(EXTRACTED_DIR))
    for p in files:
        h.update(str(p.relative_to(EXTRACTED_DIR)).encode())
        h.update(_sha256(p).encode())
    # Only tracked reference files: the gitignored review queue is not an input and would make a clean checkout's snapshot differ.
    tracked = _git("ls-files", str(REFERENCE_DIR.relative_to(ROOT))).splitlines()
    refs = {Path(p).name: _sha256(ROOT / p) for p in sorted(tracked)}
    return {"extracted_reports": len(files), "extracted_sha256": h.hexdigest(), "reference_files": refs}


def _load_tables() -> dict[str, pd.DataFrame]:
    tables = {}
    for stem, schema in (("comparative_statements", ComparativeStatementRow), ("inline_funding_tables", InlineFundingRow)):
        src = OUTPUT_DIR / f"{stem}.csv"
        if not src.exists():
            raise SystemExit(f"missing {src} — run `approps output` first")
        tables[stem] = _coerce_int_columns(pd.read_csv(src, low_memory=False), schema)
    sidecar = OUTPUT_DIR / "nonstandard_layout_rows.csv"
    if not sidecar.exists():
        raise SystemExit(f"missing {sidecar} — run `approps output` first")
    side = pd.read_csv(sidecar, low_memory=False)
    tables["nonstandard_layout_rows"] = side.astype({c: "Int64" for c in _AMOUNTS if c in side.columns})
    return tables


def _derive(comp: pd.DataFrame) -> dict[str, pd.DataFrame]:
    rows = _records(comp)
    totals = pd.DataFrame([t.to_dict() for t in account_totals(rows)])
    totals = totals.astype({c: "Int64" for c in ("fiscal_year", "n_lines", "verified_lines", *_LEVELS)})
    changes = []
    for a in trace_accounts(rows, metric="committee_recommendation", min_years=2):
        for c in a.title_changes:
            changes.append({
                "account_key": a.account_key, "canonical_title": a.canonical_title, "first_fy": a.first_fiscal_year,
                "last_fy": a.last_fiscal_year, "n_years": len(a.fiscal_years), "change_fy": c.fiscal_year,
                "from_title": c.from_title, "to_title": c.to_title, "kind": c.kind,
            })
    return {"account_year_totals": totals, "account_title_changes": pd.DataFrame(changes)}


def _write_and_verify(stem: str, df: pd.DataFrame) -> tuple[list[Path], dict]:
    """Write one table three ways and prove the copies agree."""
    csv_path, pq_path, js_path = (RELEASE_DIR / f"{stem}.{ext}" for ext in ("csv", "parquet", "json"))
    df.to_csv(csv_path, index=False)
    df.to_parquet(pq_path, compression="zstd", index=False)
    df.to_json(js_path, orient="records", force_ascii=False, indent=None)

    dtypes = {c: str(t) for c, t in df.dtypes.items()}
    back_csv = pd.read_csv(csv_path, low_memory=False, dtype={c: t for c, t in dtypes.items() if t in ("Int64", "object", "bool")})
    back_pq = pd.read_parquet(pq_path)
    back_js = pd.read_json(js_path, orient="records", dtype=False)
    if back_js.empty and not df.empty:
        raise SystemExit(f"{stem}: JSON read back empty")

    def canon(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.reindex(columns=df.columns)
        out = pd.DataFrame(index=frame.index)
        for c in df.columns:
            if dtypes[c] in ("Int64", "int64"):
                out[c] = pd.to_numeric(frame[c], errors="raise").astype("Int64")
            elif dtypes[c] == "float64":
                out[c] = pd.to_numeric(frame[c], errors="raise").round(6)
            elif dtypes[c] == "bool":
                out[c] = frame[c].map(lambda v: None if pd.isna(v) else str(v).lower() == "true")
            else:
                out[c] = frame[c].map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) or v == "" else str(v))
        return out.reset_index(drop=True)

    ref = canon(df)
    result = {"rows": len(df), "columns": len(df.columns)}
    for name, back in (("csv", back_csv), ("parquet", back_pq), ("json", back_js)):
        if len(back) != len(df):
            raise SystemExit(f"{stem}: {name} has {len(back)} rows, expected {len(df)}")
        other = canon(back)
        diff = [c for c in df.columns if not ref[c].equals(other[c])]
        if diff:
            raise SystemExit(f"{stem}: {name} disagrees with the source frame in columns {diff[:5]}")
        result[f"{name}_matches"] = True
    return [csv_path, pq_path, js_path], result


def _checks(comp: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> list[dict]:
    checks = []

    def add(name: str, passed: bool, value, expectation: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "value": value, "expectation": expectation})

    add("fiscal_year_present", comp.fiscal_year.isna().sum() == 0, int(comp.fiscal_year.isna().sum()), "no row without a fiscal year")
    add("row_id_unique", comp.row_id.is_unique, int(comp.row_id.duplicated().sum()), "row_id unique")

    sub_missing = comp[(comp.stage == "committee") & comp.subcommittee.isna()]
    add("committee_subcommittee_present", sub_missing.empty, len(sub_missing), "every committee row has a subcommittee")

    # Stated against the jurisdiction table and the reviewed exceptions directly, not by re-running the gate: this asserts the policy, it does not prove any key right.
    keyed = comp[comp.account_key.notna()]
    unmapped = int((~keyed.account_key.str[:3].isin(JURISDICTION)).sum())
    add("account_keys_mapped_agency", unmapped == 0, unmapped, "every released key's agency has a jurisdiction entry")
    triples = list(zip(keyed.account_key, keyed.subcommittee, keyed.account_key_title))
    outside = [(k, s) for k, s, _ in triples if isinstance(s, str) and k[:3] in JURISDICTION and s not in JURISDICTION[k[:3]]]
    unreviewed = [p for p in outside if p not in CROSS_CODED]
    unreviewed += [(k, s) for k, s, title in triples if isinstance(s, str) and in_jurisdiction(k, s, title) is False and (k, s) not in outside]
    add("account_keys_in_jurisdiction", not unreviewed, len(unreviewed), "every out-of-jurisdiction key is a reviewed CROSS_CODED account")
    used = {f"{k} in {s}": outside.count((k, s)) for k, s in sorted(set(outside))}
    add("account_keys_cross_coded", True, used, "recorded: reviewed exceptions in use")

    totals = tables["account_year_totals"]
    resolved = totals[totals.method != "unresolved"]
    multi = int((resolved.groupby(["account_key", "fiscal_year", "chamber", "stage"]).report_id.nunique() > 1).sum())
    add("account_year_conflicts", True, multi, "recorded: (account, year, chamber, stage) cells claimed by more than one report; series report them as conflicts")

    leaked = 0
    for layout, cols in UNTRUSTED_COLUMNS.items():
        sub = comp[comp.column_layout == layout]
        leaked += int(sub[list(cols)].notna().sum().sum()) + int((sub.verification_tier != "none").sum())
    add("nonstandard_columns_isolated", leaked == 0, leaked, "no value or verification tier left on an untrusted column")
    side = tables["nonstandard_layout_rows"]
    add("sidecar_covers_isolated_rows", set(side.row_id) == set(comp[comp.column_layout.isin(UNTRUSTED_COLUMNS)].row_id),
        len(side), "sidecar row_ids equal the isolated rows")

    over = int((comp[list(_AMOUNTS)].abs() > LINE_ITEM_CEILING).any(axis=1).sum())
    add("magnitude_ceiling", over == 0, over, f"no amount above ${LINE_ITEM_CEILING:,}")

    for (stage, chamber), floor in COVERAGE_FLOORS.items():
        sub = comp[(comp.stage == stage) & (comp.chamber == chamber)]
        frac = float(sub.verified.mean()) if len(sub) else 0.0
        add(f"verified_floor_{stage}_{chamber}", frac >= floor, round(frac, 4), f">= {floor}")

    from approps.verification.reconcile import reconcile_corpus, summarize
    from approps.verification.reconcile_source import load_release

    by_report, tracks = load_release(RELEASE_DIR / "comparative_statements.parquet")
    results = reconcile_corpus(by_report)
    for track in sorted(set(tracks.values())):
        s = summarize([r for r in results if tracks.get(r.report_id) == track])
        add(f"reconcile_strict_{track}", True, {k: s[k] for k in ("checkable", "strict_pass_rate") if k in s}, "recorded, not gated per track")
    overall = summarize(results)
    add("reconcile_strict_all", (overall.get("strict_pass_rate") or 0) >= RECONCILE_FLOOR,
        {k: overall[k] for k in ("checkable", "strict_pass_rate") if k in overall}, f"strict rate >= {RECONCILE_FLOOR}")
    return checks


def main() -> None:
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    for stale in RELEASE_DIR.iterdir():
        if stale.is_file():
            stale.unlink()

    tables = _load_tables()
    comp = tables["comparative_statements"]
    tables.update(_derive(comp))

    written: list[Path] = []
    table_info = {}
    for stem, df in tables.items():
        paths, info = _write_and_verify(stem, df)
        written += paths
        table_info[stem] = info
        print(f"{stem:<26} {len(df):>7,} rows  csv/parquet/json agree")

    checks = _checks(comp, tables)
    counts = {
        "by_stage_chamber": {f"{s}/{c}": int(n) for (s, c), n in comp.groupby(["stage", "chamber"]).size().items()},
        "reports": int(comp.report_id.nunique()),
        "verification_tier": {k: int(v) for k, v in comp.verification_tier.value_counts().items()},
        "column_layout": {k: int(v) for k, v in comp.column_layout.value_counts().items()},
        "column_repair": {k: int(v) for k, v in comp.column_repair.value_counts().items()},
        "account_match": {k: int(v) for k, v in comp.account_match.value_counts().items()},
        "account_key_rows": int(comp.account_key.notna().sum()),
        "account_year_totals_by_method": {k: int(v) for k, v in tables["account_year_totals"].method.value_counts().items()},
    }
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    manifest = {
        "version": version,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "code": {"git_commit": _git("rev-parse", "HEAD"), "git_dirty": dirty, "python": sys.version.split()[0]},
        "source_snapshot": _source_snapshot(),
        "tables": table_info,
        "counts": counts,
        "checks": checks,
        "files": {p.name: {"sha256": _sha256(p), "bytes": p.stat().st_size} for p in sorted(written)},
    }
    (RELEASE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    written.append(RELEASE_DIR / "manifest.json")
    (RELEASE_DIR / "SHA256SUMS").write_text("".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(written)))

    failed = [c for c in checks if not c["passed"]]
    for c in checks:
        print(f"  {'PASS' if c['passed'] else 'FAIL'}  {c['name']}: {c['value']}")
    if dirty:
        print("\nWARNING: built from a dirty git tree; the manifest says so. Commit and rebuild for a release.")
    if failed:
        raise SystemExit(f"\n{len(failed)} release check(s) failed")
    print(f"\nwrote {RELEASE_DIR} ({len(written)} files, manifest.json, SHA256SUMS)")


if __name__ == "__main__":
    main()
