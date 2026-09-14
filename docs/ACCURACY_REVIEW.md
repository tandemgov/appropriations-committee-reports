# Accuracy review

A bounded, blind comparison of the release against its source documents, run 2026-09-13 before this release was finalized.
It measures what the pipeline's own checks cannot: whether a figure landed on the right line, in the right column, and whether lines are missing.
It is a sample, not a proof, and it is reported with its limits.

## Design

**Sample.** 24 units drawn at random with a fixed seed (`20260913`), stratified so every extraction track is covered and fiscal years and subcommittees are spread:

| Track | Units | Unit | Fiscal years | Subcommittees |
|---|---:|---|---|---|
| House committee, scanned pages | 8 | one PDF page | 2016, 2017, 2019, 2021, 2022, 2024, 2025, 2027 | Agriculture, SFOPS, Homeland, Interior, THUD, Leg Branch, FSGG, MilCon-VA |
| Senate committee, HTML text | 6 | a 44-line window of the statement | 2016, 2017, 2019, 2022, 2025, 2026 | SFOPS, THUD, CJS, Agriculture, MilCon-VA, Defense |
| Enacted explanatory statements | 6 | one PDF page | 2016, 2017, 2019, 2021, 2022, 2024 | various divisions |
| House committee, typeset text | 4 | one PDF page | 2027 | Defense (the only typeset report) |

Pages were drawn from within each report's statement, not chosen for difficulty, so hard layouts appear at their natural rate.

**Transcription.** Reviewers transcribed every table row on each unit — line items, headings, subtotals, memo lines, rows that failed every check — exactly as printed, from the rendered page image (scans) or the source text checked against a rendering (born-digital), **without access to the extracted data**.

**Comparison.** Each transcript was aligned to the released rows in document order and scored three ways, separately:

- **Completeness** — source rows carrying a figure that have a released counterpart.
- **Transcription** — source figures reproduced as a number on the matched row, in any column.
- **Column placement** — of those, the share in the column the source header gives them.

Every disagreement was adjudicated against the source, because a reviewer can misread too.
Where row arithmetic decided a dispute (for example `114,500 − 78,948 = 35,552`), the arithmetic was taken as the witness.

## Results

| Track | Completeness | Transcription | Column placement |
|---|---:|---:|---:|
| House committee, scanned | 89 / 91 (97.8%) | 333 / 335 (99.4%) | 332 / 333 (99.7%) |
| Senate committee | 139 / 144 (96.5%) | 513 / 513 (100%) | 505 / 513 (98.4%) |
| Enacted | 128 / 131 (97.7%) | 128 / 128 (100%) | 128 / 128 (100%) |
| House committee, typeset | 97 / 97 (100%) | 287 / 289 (99.3%) | 287 / 287 (100%) |

Typeset completeness excludes 42 Defense program-adjustment rows ("Program increase", "Carryover", "Classified adjustment") that print only a change from the request; the parser skips them by design, and they are not line items.
With samples of 90–145 rows per track, a one-row difference moves completeness by about a point: read these as orders of magnitude, not as rates to two decimals.

### What the disagreements were

**House scanned pages.**
Two misread digits the row's own deltas expose (`CRPT-116hrpt448`: 35,532 for 35,552; 718,449 for 716,449); these rows fail their delta check and carry no verification tier.
Two rows with their values lost (`CRPT-118hrpt120`, a spending-reduction line and a title total).
One partial read (`CRPT-115hrpt948`, "Securing the Cities", prior year missing).
Two phantom subtotal rows with values not on the page (`CRPT-115hrpt948`).

**Senate.**
Eight cells in the wrong column, all in `CRPT-114srpt243` (THUD FY2016), where blank leading columns in an irregular table still shift a few rows (KNOWN_ISSUES #12).
Four total rows whose label swallowed a figure (`CRPT-118srpt191`), now isolated as `amount_in_label` with their values emptied, so they count as missing.
One parenthesized memo row not extracted.
Every misplaced Senate figure had passed its string match.

**Enacted.**
One label containing `$` not matched ("Items Less Than $5 Million"), and two lines with the same labels as lines above them on the page not extracted (`CPRT-116HPRT35160`).

**Typeset.**
Two cells on a title-total row the alignment could not pair.

### Defects the review found, and what was done

The review was run against the data as it stood, before the fixes below; the table above scores the data after them.
The first pass disagreed with the source on 332 cells and rows; the final pass on 73, of which 42 are the out-of-scope adjustment rows.

| Found in the sample | Corpus scope | Action | KNOWN_ISSUES |
|---|---|---|---|
| FY2027 House MilCon-VA page: 28 of 43 cells in the wrong column | 647 rows on three-column House pages | Repaired | #11 |
| Senate blank leading columns slid values left | 370 rows regained values | Parser fixed, re-extracted | #12 |
| Enacted Defense page: 14 of 54 lines missing | 980 rows with dashes or apostrophes | Parser fixed, re-extracted | #14 |
| FY2016 Senate House-allowance columns (seen via a multi-year point) | 861 rows | Repaired | #13 |
| Labels holding a figure, level columns holding a `+` | 633 rows | Isolated | #15 |
| FY2026 Senate recommendation overwritten by the delta (seen via a multi-year point) | 1,859 rows in six reports | Parser fixed, re-extracted | #20 |

## Multi-year check

Three accounts were followed through `account_year_totals` and every sampled point was checked against its source, blind, by a separate reviewer:
NASA Aeronautics (`080-0126`), NASA Space Technology (`080-0131`), and USDA High Energy Cost Grants (`012-2042`), four House committee, four Senate committee, and three enacted points each — 33 points from 24 reports spanning FY2016–FY2026.

**32 of 33 released totals matched the source exactly**, including both FY2016 Senate points from House-allowance statements and both FY2026 House points from three-column pages, after their repairs.
The miss was High Energy Cost Grants in the FY2026 Senate Agriculture report (`CRPT-119srpt37`): the source prints 8,000 for both years and the release had no recommendation. That was the defect in KNOWN_ISSUES #20, fixed afterward.

The check also tested the totals rule itself:

- For NASA accounts, every chosen line was the account's own line, in all three stages.
- High Energy Cost Grants is a federal account in its own right, but the committees and the explanatory statements print it as a line within the Rural Water and Waste Disposal program account's grants. The released figure is the right amount for the account, but a reader looking for it in the source will find it one level down. Accounts whose funding is carried inside another account's table behave this way.
- Where the source prints `---` (no funding), the release has an empty cell on some rows and 0 on others. Read both as zero funding in the source.
- A House FY2020 Space Technology request printed on a differently named line ("Exploration Technology") is not attached to the account; label changes within one year are not reconciled.

## Limits

- 24 units and 33 points cannot bound rare errors. A defect class affecting 0.5% of rows may well not appear.
- Only one report uses the typeset House track, so its figures describe that report.
- The sample was drawn once. The pipeline changed afterward to fix what it found, and the scores are for the final data, so the fixed defect classes are no longer represented at their original rate; the classes the review did not see are exactly as common as before.
- Completeness is measured within sampled pages. Whole pages or statements missing from a report are measured separately by reconciliation (KNOWN_ISSUES #7, #19).

## Reproducing

Everything the rates depend on is in the repository:

| Path | Contents |
|---|---|
| `docs/accuracy_review/units.json` | The 24 sampled units: report, track, fiscal year, subcommittee, source file, and PDF page or HTML line range. |
| `docs/accuracy_review/transcripts/` | One blind transcription per unit: column headers, units line, and every row's cells as printed. |
| `docs/accuracy_review/multiyear/` | The 33 multi-year checks as given to reviewers (locators only) and the reviewers' readings of each source line. |
| `scripts/accuracy_review_sample.py` | Draws the sample from the extracted reports (seed `20260913`). Re-running it after re-extraction can select different pages. |
| `scripts/accuracy_review.py` | Aligns each transcript with the released rows and writes `diff_results.json` (scores per unit) and `disagreements.json` (every disagreement) next to the transcripts. |

```bash
uv run approps output
uv run python scripts/accuracy_review.py
```

The script scores `data/output/comparative_statements.csv`, so it needs the extracted reports the release was built from (hashed in the release manifest).
Its per-track totals are the table above before adjudication; the adjudication — which disagreements were the transcriber's, which were out of scope — is written out in this document, unit by unit.
A House scanned-page unit is the set of rows whose extracted `line_number // 100` is the page.
