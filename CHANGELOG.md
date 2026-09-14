<!-- markdownlint-disable MD024, MD013 -->
# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [2.0.0] - 2026-09-14

### Added

- `account_year_totals`: one total per report and account, taken only from the line the source presents as the account; 2,991 of 9,154 are left unresolved rather than guessed.
- `nonstandard_layout_rows`: the values emptied from rows whose columns cannot be trusted, keyed by the new `row_id`.
- Release `manifest.json` recording the code revision, a hash of the extracted snapshot, counts, every release check, and file hashes. The build fails if a check fails.
- JSON copies of every release table, verified row for row against the CSV and Parquet.
- `docs/ACCURACY_REVIEW.md`: a blind cell-by-cell comparison of 24 source pages with the release, and a multi-year check of three accounts.
- Columns `row_id`, `column_repair`, and `account_key_withheld`.

### Changed

- Rows from nonstandard layouts (`category_split`, `procurement_qty`, `text_in_amount`, `amount_in_label`, `signed_level`, `adjustment_detail`) have their untrusted columns emptied and no verification tier. 3,026 rows.
- 7,687 account keys that failed a jurisdiction, generic-label, heading, or tie-break check are withheld; 20,881 rows keep one.
- Docs rewritten against the release; claims of complete verification removed.

### Breaking

- `/api/line_items/compare` requires `account_key` (the `account` substring filter is gone), returns one series per chamber and stage, and returns 422 for real-dollar years without a deflator.
- `inflation.real_dollars` raises for a year outside the deflator series instead of returning None.
- `/api/accounts/{account_key}/history` reports a year that two reports of the same chamber and stage both claim as a `conflict` with no amount, instead of their sum; such years no longer produce title changes.
- The release's `account_authority` table is renamed `account_title_changes` and built from account totals.

### Fixed

- FY2026–27 House three-column pages had the bill in `budget_estimate` and the delta in `committee_recommendation`. 647 rows repaired where the rows' own arithmetic proves the layout (KNOWN_ISSUES #11).
- Senate rows whose leading columns print blank placeholders slid one column left or lost their amounts. 370 rows regained values (#12).
- Five FY2016 Senate statements carried the House allowance in `committee_recommendation`. 861 rows repaired (#13).
- Enacted rows whose labels contain dashes or typographic apostrophes were dropped. 980 rows recovered (#14).
- FY2026 Senate statements had recommendations overwritten by the delta or a blank placeholder when the header reading counted fewer columns than the rows print. 1,859 rows corrected in six reports (#20).
- 857 rows lacked a fiscal year and 13,171 a subcommittee; both are filled from the report catalog or the enacted division (#17).
- `/compare` double-counted account lines with their breakdowns and mixed chambers and stages; flow and account history promoted the largest program line to an account total (#18).
- The account gate no longer admits a cross-jurisdiction key because two Senate reports repeat the same label-only match; every agency has a jurisdiction entry and the only exceptions are two reviewed accounts (#16).

- House vision pages whose header sets "Committee vs." on its own line had their delta columns written over the enacted and request amounts. The rows turned unverifiable rather than failing, so no gate escalated them, and only 29% of CRPT-119hrpt696's rows (Labor-HHS FY2027) matched the page. A repeated Enacted/Request header now maps to its delta slot, two new signals escalate a delta read into a level column and a page dropped at a statement's edge, and the report was re-read with Gemini: all 933 value rows now match a hand transcription, and its strict reconciliation rose from 69.9% to 87.2% (KNOWN_ISSUES #10).
- Twelve Labor-HHS rows lost a false account match: "Inspector General Federal Funds" had been keyed to a Treasury advances account, and "User Fees" to National Park Service filming fees. The Tango crosswalk learns each subcommittee's agency scope from the corpus, and the corrected FY2027 rows widened Labor-HHS's scope enough to leave those matches ambiguous.
- House statements that lost their first or last page to the vision pass get it back. 107 candidate pages across 69 reports were re-read, and a page is now kept only when one of its rows closes a delta identity: 46 pages came back (885 line items), and 21 vote rosters, project lists and authorization tables that an ungated first pass had merged in were turned away (KNOWN_ISSUES #10).
- Senate statements no longer lose the rows above their first subtotal. Data start was found by counting to the third rule, which falls inside the table whenever a statement rules off its opening subtotal (KNOWN_ISSUES #9).
- Senate value columns are now placed by their header names rather than their order. FY2026 statements print three columns, and a positional read filed the recommendation as the budget estimate and a delta as the recommendation across 862 rows in six reports (KNOWN_ISSUES #8).
- House vision pages whose table header failed OCR were dropped unflagged, costing Defense FY2025 its whole Title III Procurement block. Two new signals now escalate them, and re-extracting the 307 affected pages recovered 5,160 line items across 73 reports (KNOWN_ISSUES #7).

### Internal / Infra

- `scripts/repair_dropped_pages.py` closes each PDF before opening the next. It held every parsed page open, and a corpus run was killed for memory.

## [1.3.0] - 2026-09-02

### Added

- **`approps output` warns when a track's verified coverage collapses.** Per-row gates cannot see a gate that never *ran* — every row in a skipped-verify build is truthfully unverified.

### Changed

- **Corpus figures refreshed against a fully regenerated artifact.** `approps output` had run before `verify` was re-run, so all 29,042 Senate rows shipped unverified; re-running the pipeline restores them (94.6%) and settles the corpus at **109,221 rows / 75,133 passing a primary gate**.

### Fixed

- **The data dictionary documented a `verification_tier` enum v1.2.0 had already renamed.** It described a single `delta` tier and warned the name was a misnomer, the exact defect the split into `delta_arithmetic` / `string_match` / `verbatim_page` had removed.

- **Senate comparative rows whose dot leader was squeezed out are no longer dropped.** A label long enough to consume the entire dot-leader field left the reader with no `...` to split label from numbers, so the row matched no parse branch and was silently dropped — 682 line items across 72 of 87 Senate reports, 363 of them `Total` rows, whose loss also deleted the block structure the reconciler recovers from document order. A second reader now adjudicates by column geometry (the declared right edges) when the dot-leader reader can't, and stitches a wrapped-label tail back onto its row. Extraction is strictly additive (+169 rows, 0 value-cells removed, every recovered amount string-matches the source); Senate reconcile checkable totals rise 4,833 → 5,198 and overall strict pass rate holds at 75.7%. (refs #2)

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
