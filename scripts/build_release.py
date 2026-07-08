"""Assemble the published data release from data/output/.

Emits, into data/release/, for each table: the CSV as-built plus a Parquet copy, and a
SHA256SUMS manifest over the lot.

Parquet is not a nicety here. CSV cannot carry a dtype, so a consumer reading
comparative_statements.csv gets float64 for every nullable integer column and is back to
`2016.0`. The Parquet copy pins the schema's declared Int64, and is ~10x smaller.

    uv run --with pyarrow python scripts/build_release.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from approps.config import OUTPUT_DIR
from approps.output.csv_writer import _coerce_int_columns
from approps.output.schemas import ComparativeStatementRow, InlineFundingRow

RELEASE_DIR = OUTPUT_DIR.parent / "release"

# table stem -> the schema whose int fields must survive the CSV round-trip (None = no
# nullable ints, so pandas' inference is already faithful).
TABLES: dict[str, type | None] = {
    "comparative_statements": ComparativeStatementRow,
    "inline_funding_tables": InlineFundingRow,
    "account_authority": None,
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for stem, schema in TABLES.items():
        src = OUTPUT_DIR / f"{stem}.csv"
        if not src.exists():
            raise SystemExit(f"missing {src} — run `approps output` first")

        df = pd.read_csv(src, low_memory=False)
        if schema is not None:
            df = _coerce_int_columns(df, schema)

        csv_out = RELEASE_DIR / f"{stem}.csv"
        pq_out = RELEASE_DIR / f"{stem}.parquet"
        csv_out.write_bytes(src.read_bytes())
        df.to_parquet(pq_out, compression="zstd", index=False)
        written += [csv_out, pq_out]

        print(f"{stem:<24} {len(df):>7,} rows   csv {csv_out.stat().st_size/1e6:>6.1f} MB"
              f"   parquet {pq_out.stat().st_size/1e6:>5.1f} MB")

    manifest = RELEASE_DIR / "SHA256SUMS"
    manifest.write_text("".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(written)))
    print(f"\nwrote {manifest} ({len(written)} files)")


if __name__ == "__main__":
    main()
