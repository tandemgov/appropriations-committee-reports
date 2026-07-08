# The dataset

Line-item appropriations data extracted from congressional committee reports, FY2016–FY2027: **109,052 line items** across **246 reports**, both chambers, committee and enacted stages.

Download it from the [latest release](https://github.com/tandemgov/appropriations-committee-reports/releases/latest). Everything here is CC0 — public domain, no attribution required (though it's appreciated).

## Read this before you use a number

**Not every row is verified.** 26% of rows have no independent corroboration, and a few hundred have values sitting in the wrong columns. Both conditions are flagged in the data. If you are going to cite a dollar figure, filter first:

```python
import pandas as pd

df = pd.read_parquet("comparative_statements.parquet")

# The subset with a corroborated amount in a standard column layout: 80,429 rows (73.8%).
strict = df[(df.column_layout == "standard") & (df.verification_tier != "none")]
```

That is the honest default. The other 26% are not junk — they are mostly correct — but nothing in the document independently confirms them, so they should not be quoted without checking the source PDF.

### `verification_tier` — how the amount is corroborated

| Tier | Rows | Meaning |
|---|---:|---|
| `delta` | 74,453 (68.3%) | The row's own delta arithmetic closes. Strongest. |
| `block` | 5,616 (5.1%) | Member of a subtotal block whose amounts sum exactly. |
| `inline` | 491 (0.5%) | Amount + account restated in the report's string-verified prose. |
| `none` | 28,492 (26.1%) | **No second witness in the document.** Treat as unconfirmed. |

The `none` rows are overwhelmingly House. The House comparative statements are *scanned images* in the source PDFs and are read by a vision model; the Senate reports are born-digital HTML and are parsed deterministically. That asymmetry is the single biggest driver of data quality here.

### `column_layout` — whether the columns mean what they're named

| Layout | Rows | Meaning |
|---|---:|---|
| `standard` | 108,570 | Normal shape: prior-year enacted / request / recommendation / two deltas. |
| `category_split` | 297 | **`committee_recommendation` is correct; the other amount columns are mislabeled funding categories.** |
| `procurement_qty` | 185 | Defense procurement tables. The program name was lost and amounts are shifted. |

See [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) for exactly what goes wrong in each and why the fix is deferred.

## Files

| File | Rows | Description |
|---|---:|---|
| `comparative_statements.{csv,parquet}` | 109,052 | The main table. One row per line item. |
| `inline_funding_tables.{csv,parquet}` | 13,853 | Narrative funding tables from report prose. String-verified against source text. |
| `account_authority.{csv,parquet}` | 732 | Federal account reference used by the crosswalk. |
| `SHA256SUMS` | — | Checksums for all of the above. |

### Prefer the Parquet

CSV cannot carry a type. `fiscal_year` is written as `2016`, but `pd.read_csv` sees 495 empty cells in that column and infers `float64` — so you get `2016.0` back, and likewise for every nullable amount. The Parquet copies pin the declared `Int64` and are roughly 10× smaller (3.0 MB vs 31.2 MB).

If you must use CSV, pass the dtype explicitly:

```python
df = pd.read_csv(
    "comparative_statements.csv",
    dtype={"fiscal_year": "Int64", "committee_recommendation": "Int64"},
    low_memory=False,
)
```

## Amounts are in thousands

Every row in this release carries `in_thousands = True` — comparative statements are conventionally published `[In thousands of dollars]`. A `committee_recommendation` of `649` means **$649,000**. Do not skip this. The column is retained per-row rather than assumed, so check it rather than hardcoding the multiplier.

`real_factor_2024` is a CPI-U deflator: multiply a nominal amount by it to get constant FY2024 dollars.

## Coverage

- **Fiscal years:** 2016–2027
- **Chambers:** House 80,179 rows · Senate 28,873 rows
- **Stages:** `committee` 97,223 · `enacted` 11,829
- **Accounts:** `account_key` resolves to a canonical federal account symbol on 27,469 rows (25.2%). It is populated only on conservative matches — fuzzy hits are recorded in `account_match` but deliberately withheld from the key.

Reports per year vary because omnibus years produce fewer standalone committee reports. **FY2021, FY2023, and FY2027 carry no Senate reports at all**, and FY2022 has only 3 — so any House-vs-Senate comparison must be scoped to years where both chambers reported. FY2027 is simply incomplete: the Senate had not marked up when this was built. [`docs/COVERAGE.md`](docs/COVERAGE.md) has the full matrix.

## Column reference

Every column is defined in [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md). Method and verification design are in [`METHODOLOGY.md`](METHODOLOGY.md).

## Provenance

Extracted from committee reports published on [GovInfo](https://www.govinfo.gov/). Those reports are works of the United States Government and carry no copyright (17 U.S.C. § 105). This derived dataset is released under [CC0 1.0](LICENSE).

Regenerate it yourself:

```bash
approps discover && approps download && approps extract && approps output
uv run --with pyarrow python scripts/build_release.py
```

## Corrections

Found a wrong number? Please [open an issue](https://github.com/tandemgov/appropriations-committee-reports/issues) with the `report_id` and `line_item_text`. Source-document errors and extraction errors are both in scope, and worth distinguishing.
