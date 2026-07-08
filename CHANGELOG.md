<!-- markdownlint-disable MD024, MD013 -->
# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

### Changed

### Breaking

### Fixed

- **Senate comparative rows whose dot leader was squeezed out are no longer dropped.** A label long enough to consume the entire dot-leader field left the reader with no `...` to split label from numbers, so the row matched no parse branch and was silently dropped — 682 line items across 72 of 87 Senate reports, 363 of them `Total` rows, whose loss also deleted the block structure the reconciler recovers from document order. A second reader now adjudicates by column geometry (the declared right edges) when the dot-leader reader can't, and stitches a wrapped-label tail back onto its row. Extraction is strictly additive (+169 rows, 0 value-cells removed, every recovered amount string-matches the source); Senate reconcile checkable totals rise 4,833 → 5,198 and overall strict pass rate holds at 75.7%. (refs #2)

### Internal / Infra

## [1.2.0] - 2026-07-08

### Added

- **`approps reconcile` — cross-row reconciliation gate.** Every other check compares a row to itself or to the string it was read from; this one sums the extracted line items against an independent witness, the subtotal the committee set in type, so it is the only gate that can catch a misinterpretation of the source rather than a mistranscription. Reports a `pass` and a `strict` rate per track (strict excludes `overlapping_view` totals, which re-aggregate rows already counted under another view), and `--fail-under` makes it a release gate over the shipped artifact.
- **`approps workbook` — per-report Excel workbooks that prove the arithmetic.** Each printed total is a live `=SUM()` over the exact cells it consumed; nothing is precomputed, so a staffer can select the leaf cells and read the sum off Excel's own status bar. Non-add memo rows are greyed and parked in a column no `SUM` reaches.

### Breaking

- **Two columns renamed; values did not move.** `verification_tier == "delta"` split into `delta_arithmetic` / `string_match` / `verbatim_page` (one label had covered three different checks; 52% of `delta` rows were never delta-checked), with a new `verification_method` carrying the same value. `non_add_inferred` renamed to `is_memo` (the old name asserted "does not add," false for 20% of the rows it flagged; `is_memo` names what the row *is*, and `reconcile`'s `memo_mode` names what the total *did* with it).

### Fixed

- **Senate parenthesis sign defect.** A parenthesized amount like `(24,000)` is a positive non-add memo, not a negative; it had been read as `-24,000`. Invisible to both row-local gates (the raw text still string-matched, and negating every column preserved the delta identity), it surfaced only against the printed subtotals: Senate reconciliation was 65.1% and rose to 78.8% once the signs were corrected.
- **Enacted-stage 1000× scale error**, with a magnitude tripwire added so a units bug can no longer reach a CSV disguised as a verification pass.
- **Schema-declared integer columns serialize as integers, not floats** — nullable ints had been round-tripping through pandas as `2016.0`; the Parquet copy now pins the declared `Int64`.

---

v1.2.0 is the first tagged release; the initial public release and everything before the changelog existed are recorded in git history and the `pre-oss-history` tag.
