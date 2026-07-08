# The dataset

Line-item appropriations data extracted from congressional committee reports, FY2016–FY2027: **109,052 line items** across **246 reports**, both chambers, committee and enacted stages.

Download it from the [latest release](https://github.com/tandemgov/appropriations-committee-reports/releases/latest). Everything here is CC0 — public domain, no attribution required (though it's appreciated).

## Read this before you use a number

**Not every row is verified.** 26% of rows have no independent corroboration, and a few hundred have values sitting in the wrong columns. Both conditions are flagged in the data. If you are going to cite a dollar figure, filter first:

```python
import pandas as pd

df = pd.read_parquet("comparative_statements.parquet")

# The subset with a corroborated amount in a standard column layout: 80,435 rows (73.8%).
strict = df[(df.column_layout == "standard") & (df.verification_tier != "none")]
```

That is the honest default. The other 26% are not junk — they are mostly correct — but nothing in the document independently confirms them, so they should not be quoted without checking the source PDF.

### `verification_tier` — what the amount rests on

Each row names the gate that actually checked it. `verification_method` carries the same value for verified rows; the tier column exists so a single field answers "how do I know this number?", including for rows no primary gate reached.

| Tier | Rows | What was checked | Can it see a misread convention? |
|---|---:|---|---|
| `delta_arithmetic` | 33,391 (30.6%) | House vision rows: `recommendation − prior = delta_vs_enacted`, and likewise for the estimate. | **No** — invariant to a sign flip across the row's columns. |
| `string_match` | 26,792 (24.6%) | Senate rows: the amount's *raw text* appears in the source HTML. | **No** — proves transcription, says nothing about parsing. |
| `verbatim_page` | 14,270 (13.1%) | Enacted statements and House typeset prints: the amount appears verbatim on its source PDF page. | **No** — same reason. |
| `block` | 5,616 (5.1%) | Member of a subtotal block whose amounts sum exactly. | **Yes** — a witness outside the row. |
| `inline` | 491 (0.5%) | Amount + account restated in the report's string-verified prose. | Partly. |
| `none` | 28,492 (26.1%) | **No witness at all.** Treat as unconfirmed. | — |

The `none` rows are overwhelmingly House. The House comparative statements are *scanned images* in the source PDFs and are read by a vision model; the Senate reports are born-digital HTML and are parsed deterministically. That asymmetry is the single biggest driver of data quality here.

#### Why the first three tiers cannot protect you alone

`delta_arithmetic`, `string_match`, and `verbatim_page` all compare a row to *itself*, or to the string it was read from. None can detect a **misinterpretation** of the source as opposed to a **mistranscription** of it:

- A string match compares the *raw text* to the document. If `(24,000)` is transcribed perfectly and then interpreted as −24,000, the raw text still matches.
- The delta identity is invariant to a sign flip applied across a row's columns: negate `recommendation`, `prior`, and `estimate` together and `rec − prior` still equals the printed delta.

This is not hypothetical — it shipped, on 9,629 amounts, every one of them `verified`. See [Correction — Senate parentheses](#correction--senate-parentheses).

Until this release, all 74,453 of those rows were labelled `delta`, on every track. The label asserted an arithmetic check that had never run on 52% of them. It has been split into the three names above, because a column that describes three different claims with one word is not a corroboration column, it is a reassurance.

The check that *can* see a misread convention compares the line items to a witness outside the row — the total the committee printed. That is `approps reconcile`, and you should weigh a row's reconciliation standing at least as heavily as its tier.

### Does it add up?

Run `approps reconcile` to check every printed subtotal against the line items above it.

| Track | Checkable totals | Tie exactly | Strict¹ |
|---|---:|---:|---:|
| house | 9,871 | 73.0% | 74.8% |
| senate | 5,198 | 77.7% | 80.7% |
| enacted | 1,138 | 59.1% | 60.3% |
| **all** | **16,207** | **73.5%** | **75.7%** |

¹ Excludes `overlapping_view` totals — advance-appropriation and forward-funding lines that re-aggregate rows already counted under another view, and so are not the sum of any contiguous block by construction.

The Senate checkable count rose (from 4,833) when the reader was taught to recover rows whose dot leader was squeezed out by a long label — 682 line items across 72 of 87 reports, 363 of them `Total` rows the reconciler had been blind to. The strict rate dipped slightly (from 81.4%) because those newly-visible totals are disproportionately cross-block rollups, the hardest kind to reconcile: the corpus now *measures* structure it previously dropped.

Roughly a quarter of printed totals do not currently reconcile. Most of that is House vision noise and the enacted explanatory statements' flattened hierarchy. **A total that does not reconcile is not proof its line items are wrong** — the reconciler recovers nesting from document order, and unusual table shapes defeat it. But a total that *does* reconcile is a strong, independent corroboration of every line item beneath it.

### Correction — Senate parentheses

Releases before this one stored **9,629 Senate amounts with the wrong sign**, across 3,970 rows.

In a comparative statement, parentheses mark a **non-add memo** — a limitation, a transfer authority, an "of which" breakout. They are not the accounting convention for a negative; real negatives print an explicit minus (`-2,000`). The Senate parser applied the accounting reading, so `(By transfer from Disaster Relief)` shipped as −$24,000,000 and a bureau's gross `Appropriations` line shipped as −$8,776,051,000.

Every one of those rows was marked `verified = true`, at what was then labelled tier `delta` — a label that, on the Senate track, meant only that the raw text `(24,000)` had been found in the HTML. Both gates were structurally blind to the defect, for the reasons above. It surfaced only when the line items were checked against the printed subtotals: Senate reconciliation was 65.1%, and rose to 78.8% once the signs were corrected.

If you have a copy of an earlier release, re-download it, or filter `chamber == "senate" & committee_recommendation < 0` and re-check those rows against the source.

### Breaking schema changes in this release

Two columns were renamed, both because the old name asserted something that was not true of every row it covered. Values did not move.

| Was | Now | Why |
|---|---|---|
| `verification_tier == "delta"` | `delta_arithmetic` / `string_match` / `verbatim_page` | One label for three different checks. 52% of `delta` rows were never delta-checked. Also added: `verification_method`, carrying the same value. |
| `non_add_inferred` | `is_memo` | It named a conclusion about arithmetic ("does not add") that is false for 20% of the rows it flags. `is_memo` names what the row *is*; `approps reconcile`'s `memo_mode` names what the total *did* with it. |

### `column_layout` — whether the columns mean what they're named

| Layout | Rows | Meaning |
|---|---:|---|
| `standard` | 108,576 | Normal shape: prior-year enacted / request / recommendation / two deltas. |
| `category_split` | 291 | **`committee_recommendation` is correct; the other amount columns are mislabeled funding categories.** |
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

## Parentheses, and when a memo is actually added

`(35,000)` in a comparative statement is **positive**. It is a memo — a limitation, a transfer authority, an "of which" breakout. Negatives print a minus sign.

`is_memo` flags 11,562 such rows — parenthesized amounts, plus 3,166 House rows the vision non-add double-gate identified without any parentheses. It says what the row **is**, not whether it sums, because **whether a memo is summed is decided by the printed total, not by the parentheses.** In `CRPT-114srpt68`:

```
Operating expenses ...............................  134,488
    (By transfer from Disaster Relief) ...........  (24,000)
  Total, Office of Inspector General .............  158,488     <- 134,488 + 24,000
```

The transfer is added here. One line further down, `Total, title I` excludes that same 24,000 — the money was appropriated under Disaster Relief, and counting it twice would inflate the bill.

Across the corpus, **1,099 printed totals close only when their memo is added in**, covering 2,350 flagged rows (20.3%). So blanket-filtering `is_memo` before summing will understate those account totals. `approps reconcile` resolves the question per total, by arithmetic, and records the answer as `memo_mode`.

## Amounts are in whole dollars

Every amount is stored in **whole dollars**. The source convention is already applied: a comparative statement printed `[In thousands of dollars]` showing `6,030` is stored as `6030000`. Do not multiply.

`in_thousands` is a provenance flag recording how the *source table* was presented. It does not describe the stored value. Ignore it unless you are auditing extraction.

Amounts may be negative (rescissions, offsets).

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
