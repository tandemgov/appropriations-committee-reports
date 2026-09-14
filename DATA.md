# The dataset

Line-item appropriations data extracted from congressional committee reports and enacted explanatory statements, FY2016–FY2027: **116,393 rows** from **246 reports**, both chambers, committee and enacted stages.

Download it from the [latest release](https://github.com/tandemgov/appropriations-committee-reports/releases/latest). Everything here is CC0 — public domain, no attribution required (though it's appreciated).

## Read this before you use a number

This is extracted data, not an official record.
Most rows are right, some are not, and the columns below tell you which rows have evidence behind them.
Before citing a figure, filter:

```python
import pandas as pd

df = pd.read_parquet("comparative_statements.parquet")

# Rows whose columns mean what they say and whose amount some check stands behind: 85,045 rows (73.1%).
strict = df[(df.column_layout == "standard") & (df.verification_tier != "none")]
```

Then check anything important against the source report; every row names its `report_id`.

What the checks do and do not establish:

- A **verification tier** means a check passed: the figure appears in the source text (`string_match`, `verbatim_page`), the row's own arithmetic closes (`delta_arithmetic`), or a printed subtotal above it reconciles (`block`). The first three compare the row with itself, so they cannot see a correctly transcribed figure placed in the wrong column. A bounded review against the source documents measured what they miss; see [docs/ACCURACY_REVIEW.md](docs/ACCURACY_REVIEW.md).
- **`column_layout` other than `standard`** marks a table shape or parse whose columns cannot be trusted. Those columns are **already empty** in this release, and the extracted values are in `nonstandard_layout_rows` if you need them (3,026 rows).
- **`column_repair`** marks 1,508 rows whose values were moved into the right columns because the rows' own arithmetic proves the source layout. Repair is not verification.

## Measured accuracy

A bounded review transcribed 24 complete source pages or table windows blind, across every extraction track, 11 subcommittees, and FY2016–FY2027, and compared them with the release cell by cell.

| Track | Source rows found | Figures transcribed correctly | In the right column |
|---|---:|---:|---:|
| Senate committee (HTML text) | 96.5% | 100.0% | 98.4% |
| House committee (scanned pages) | 97.8% | 99.4% | 99.7% |
| House committee (typeset text) | 100.0% | 99.3% | 100.0% |
| Enacted (explanatory statements) | 97.7% | 100.0% | 100.0% |

These are small samples (91 to 144 source rows per track), and pages were chosen at random, not for difficulty. Read them as "errors of this kind exist at roughly this rate", not as guarantees. Details, every disagreement, and the multi-year check are in [docs/ACCURACY_REVIEW.md](docs/ACCURACY_REVIEW.md).

## Account totals and change over time

**Do not sum rows.** A statement prints an account's own line and its program breakdown as separate rows.

Use `account_year_totals`: one row per report and account, taken from the line the source presents as the account (`method` = `single_line` or `account_line`), or no total at all (`unresolved`, 2,991 of 9,154). Compare within one `chamber` and one `stage`:

```python
t = pd.read_parquet("account_year_totals.parquet")
series = t[(t.account_key == "080-0126") & (t.chamber == "senate") & (t.stage == "committee") & (t.method != "unresolved")]
```

A House recommendation, a Senate recommendation, and an enacted level for the same year are three different figures.

`account_key` is a federal account symbol, assigned only by a conservative match that passed an additional gate; 7,687 keys that were demonstrably wrong were withheld (`account_key_withheld`). A key is still not proof of identity: see [KNOWN_ISSUES #16](docs/KNOWN_ISSUES.md).

## Amounts are in whole dollars

Every amount is in **whole dollars**; a statement printed `[In thousands of dollars]` showing `6,030` is stored as `6030000`. Do not multiply. `in_thousands` records only how the source printed it.

Amounts may be negative (rescissions, offsets). Parentheses in the source mark a memo line (a limitation, a transfer, an "of which"), stored as a positive amount with `is_memo = true`. About a fifth of memo rows are added in by the printed total above them, so do not drop memos wholesale before summing.

`real_factor_2024` converts nominal dollars to FY2024 dollars (CPI-U). **It is empty for FY2026 and FY2027**, which have no annual deflator yet; treat empty as unavailable, not as 1.

## Coverage

- **Stages:** committee (each chamber's report) and enacted (the joint explanatory statement). There is no subcommittee stage: subcommittee marks are not published as line-item statements.
- **House committee:** FY2016–FY2027, all 12 subcommittees except FY2024 CJS and Labor-HHS (not reported).
- **Senate committee:** FY2016–FY2026 with gaps. No Senate reports for FY2021, FY2023, or FY2027; only 3 for FY2022.
- **Enacted:** FY2016–FY2024. FY2025 was a full-year continuing resolution with no explanatory statement. Energy-Water and Homeland Security statements are mostly prose and thinly represented.

The full stage × chamber × subcommittee × year matrix is in [docs/COVERAGE.md](docs/COVERAGE.md).

## Files

| File | Rows | Description |
|---|---:|---|
| `comparative_statements` | 116,393 | The main table: one row per statement line, in document order. |
| `account_year_totals` | 9,154 | One total per report and account; the table for longitudinal work. |
| `account_title_changes` | 640 | Years in which an account's dominant label changed. |
| `nonstandard_layout_rows` | 3,026 | The values emptied from isolated rows, with their source text. |
| `inline_funding_tables` | 13,853 | Funding summaries from report prose, string-matched against the source. |
| `manifest.json` | — | Code revision, source snapshot hash, counts, every release check, and file hashes. |
| `SHA256SUMS` | — | Checksums. |

Every table ships as `.csv`, `.parquet`, and `.json` (records), written from one frame and verified to agree. Prefer Parquet: CSV cannot carry integer types, so `pd.read_csv` returns `2016.0` for years and amounts unless you pass dtypes.

Every column is defined in [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md).

## Changes in this release that affect existing analyses

- **Values moved.** Rows in FY2026–27 House three-column statements, FY2016 Senate statements with a House allowance column, FY2026 Senate statements, and Senate rows with blank leading columns had values in the wrong columns or overwritten; they are corrected. See KNOWN_ISSUES #11–#13 and #20.
- **Values removed.** 3,026 rows had their untrusted columns emptied (#1, #2, #15).
- **Account keys removed.** 7,687 keys were withheld (#16).
- **Rows added.** 980 enacted rows whose labels contain dashes or apostrophes (#14).
- **API:** `/api/line_items/compare` now requires `account_key`, returns one series per chamber and stage, and returns 422 for real-dollar requests covering FY2026–27 (#18).

Corrections to earlier releases (Senate parentheses, enacted units, dropped House pages) are in [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) and [CHANGELOG.md](CHANGELOG.md).

## Provenance

Extracted from reports published on [GovInfo](https://www.govinfo.gov/). Those reports are works of the United States Government and carry no copyright (17 U.S.C. § 105). This derived dataset is released under [CC0 1.0](LICENSE).

`manifest.json` records the code revision and a hash of the extracted source files the release was built from. To rebuild the release from extracted data, see [docs/DELIVERABLES.md](docs/DELIVERABLES.md#regenerating).

## Corrections

Found a wrong number? Please [open an issue](https://github.com/tandemgov/appropriations-committee-reports/issues) with the `row_id` (or `report_id` and `line_item_text`). Source-document errors and extraction errors are both in scope, and worth distinguishing.
