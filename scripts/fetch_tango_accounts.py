"""Refresh the federal-account reference used by the account crosswalk.

Pulls an authoritative TAS (Treasury Account Symbol) dimension and projects it to a lean,
de-duplicated reference of distinct federal accounts — the crosswalk *target* the House
appropriations line items are matched against (see approps.normalization.tango_crosswalk).
The result is committed as CSV, so the output build never needs to run this; re-run it only
to refresh the reference against newer source data.

    TAS_DIM_URI=s3://your-bucket/path/dim.parquet \
        uv run --with pyarrow --with pandas python scripts/fetch_tango_accounts.py

TAS_DIM_URI is fetched with `aws s3 cp`, so it must be an S3 URI. The source parquet must
carry these columns: federal_account_symbol, account_title, reporting_agency_name,
budget_bureau_name. The committed CSV was built from the TAS dimension maintained in
MakeGov's Tango budget lake, itself derived from public USASpending/Treasury/OMB data.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

TAS_DIM_URI = os.getenv("TAS_DIM_URI", "")
OUT = Path(__file__).resolve().parent.parent / "data" / "reference" / "tango_accounts.csv"


def main() -> None:
    if not TAS_DIM_URI:
        sys.exit("TAS_DIM_URI is unset — point it at a parquet TAS dimension (see docstring).")
    with tempfile.TemporaryDirectory() as td:
        local = Path(td) / "dim.parquet"
        subprocess.run(["aws", "s3", "cp", TAS_DIM_URI, str(local)], check=True)
        df = pd.read_parquet(local)

    cols = {
        "federal_account_symbol": "federal_account_symbol",
        "account_title": "account_title",
        "reporting_agency_name": "agency",
        "budget_bureau_name": "bureau",
    }
    ref = (
        df[list(cols)]
        .rename(columns=cols)
        .dropna(subset=["federal_account_symbol", "account_title"])
        .drop_duplicates(subset=["federal_account_symbol", "account_title"])
        .sort_values(["federal_account_symbol", "account_title"])
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ref.to_csv(OUT, index=False)
    print(f"wrote {len(ref):,} distinct federal accounts to {OUT}")


if __name__ == "__main__":
    main()
