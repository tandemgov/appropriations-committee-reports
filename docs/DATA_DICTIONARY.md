# Data dictionary

Covers every table in the release (`data/release/`, built by `scripts/build_release.py`).
Each table ships as CSV, Parquet, and JSON (an array of records), written from one in-memory frame and checked to agree row for row and value for value; `manifest.json` records the proof.
Prefer Parquet: it keeps the integer types that CSV cannot.

All amounts are integers in **whole dollars**; the source's "[In thousands of dollars]" convention is already applied, so a printed `104,102` is stored as `104102000`.
Amounts may be negative (rescissions, offsets).
An empty cell means the value was not printed, not captured, or deliberately withheld; the columns below say which.

Scope and gaps are in [COVERAGE.md](COVERAGE.md); how rows were produced and checked is in [../METHODOLOGY.md](../METHODOLOGY.md); open defects are in [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## `comparative_statements`

One row per line of a comparative statement (committee stage) or an explanatory-statement table (enacted stage), in document order.
Rows are line items, subtotals, and headings as the source printed them: **do not sum rows to get an account total** — use `account_year_totals`.

### Identity and provenance

| Column | Type | Description |
|---|---|---|
| `row_id` | string | `<report_id>:<ordinal>`, the row's position in its report. Joins this table to `nonstandard_layout_rows` and `account_year_totals.row_ids`. Stable for a given extraction, not across re-extractions. |
| `report_id` | string | GovInfo package ID (`CRPT-118srpt83`, `CPRT-117HPRT50347`). |
| `congress` | int | 114–119. |
| `chamber` | enum | `house` or `senate`. Enacted rows carry `house` because the explanatory-statement prints are House Rules Committee prints; they are the final cross-chamber level. Use `stage` to separate them. |
| `fiscal_year` | int | The fiscal year the bill funds. Always populated: rows merged in by page repair inherit it from the report catalog. |
| `subcommittee` | string | One of the twelve ids in `data/reference/subcommittees.json`. Committee rows take the report's subcommittee; enacted rows take the subcommittee of their omnibus division. Empty only for enacted rows in divisions that are not a regular bill. |
| `stage` | enum | `committee` or `enacted`. There is no subcommittee stage; see COVERAGE.md. |
| `title_name`, `department`, `agency`, `account`, `program` | string | Hierarchy context as the source's headings gave it. Sparse on House vision rows, which carry no extracted hierarchy. Raw text, not normalized. |
| `account_inferred` | string | House vision rows only: the account a row belongs to, taken from a `Total, <name>` row whose block of line items sums to it exactly. Set only when the arithmetic closes. |
| `line_item_text` | string | The line's label as printed. Always populated. |
| `hierarchy_depth` | int | Indentation depth as extracted. Unreliable on House vision and enacted rows. |
| `in_thousands` | bool | Whether the source table was printed in thousands. Provenance only; amounts are already whole dollars. |
| `extraction_method` | enum | `rule_based` (Senate HTML, enacted PDF text, House typeset PDF text) or `llm` (House scanned pages). |

### Amounts

| Column | Type | Description |
|---|---|---|
| `prior_year_enacted` | int $ | Prior-year enacted level. |
| `budget_estimate` | int $ | President's request. Empty where the statement prints no request column (FY2026–27 three-column statements). |
| `committee_recommendation` | int $ | Committee's recommended level. **On enacted rows this is the final enacted level.** |
| `delta_vs_enacted` | int $ | Recommendation minus prior year, as printed. |
| `delta_vs_estimate` | int $ | Recommendation minus request, as printed. |
| `is_subtotal` | bool | A `Total`/`Subtotal` row. |
| `is_memo` | bool | A memo line (limitation, transfer, "of which") — by a parenthesized amount or by the House non-add check. Says what the row is, not whether its printed total adds it: about a fifth of memo rows are added in by their enclosing total. |
| `designation` | enum | `base`, `OCO`, `emergency`, `disaster`, `rescission`, `CHIMP`, read from parentheticals and suffixes only. |
| `real_factor_2024` | float | Converts the row's **report-year** amounts — `budget_estimate` and `committee_recommendation` — to FY2024 dollars (CPI-U). **It does not apply to `prior_year_enacted`**, which is in the previous year's dollars: use the factor for `fiscal_year - 1` (`data/reference/deflators.csv`, or `real_factor_2024` on any row of that year). Do not deflate the delta columns; they mix two years. **Empty for FY2026 and FY2027**, which have no annual CPI-U yet; do not treat empty as 1. |

### Can this row's numbers be trusted?

| Column | Type | Description |
|---|---|---|
| `column_layout` | enum | Whether the amount columns mean what they are named. `standard` for ordinary rows. Every other value marks a table shape whose untrusted columns **have been emptied** (the extracted values are in `nonstandard_layout_rows`), with `verified=false` and `verification_tier=none`: `category_split` (only `committee_recommendation` kept), `procurement_qty`, `text_in_amount`, `amount_in_label`, `signed_level`, `adjustment_detail` (all amounts emptied). Definitions below. |
| `column_repair` | enum | Set when values were moved into the slots the source prints them in, because the rows' own arithmetic proves the mapping: `three_column_shift` (FY2026–27 House pages) or `house_allowance_columns` (FY2016 Senate statements). Repaired rows are not marked verified by the repair. |
| `verified` | bool | The row passed its track's primary gate (below). Structural rows with no amount are `false`. |
| `verification_method` | enum | The gate that set `verified`: `delta_arithmetic`, `string_match`, `verbatim_page`, or `none`. |
| `verification_tier` | enum | The strongest evidence for the row's amount. For verified rows, the gate that passed. Otherwise `block` (a member of a subtotal block that reconciles exactly), `inline` (amount and account restated in the report's string-verified prose tables), or `none`. |

The first three tiers compare a row with itself or with the text it was read from.
They prove transcription, not interpretation: a string match passes when a correctly transcribed figure sits in the wrong column, and the delta identity survives a sign flip across a row.
`block` and `approps reconcile` are the only checks that look outside the row.
The bounded review in [ACCURACY_REVIEW.md](ACCURACY_REVIEW.md) measures what the gates miss.

`column_layout` values:

- `category_split` — funding split across category columns that sum to the line total, with the deltas echoing them (chiefly Energy-Water). Only the total is real.
- `procurement_qty` — a Defense quantity-and-amount table read as five columns; the label is a bare line number and the amounts are shifted.
- `text_in_amount` — a value cell held words: a header row, merged multi-line cells, or a project list (Community Project Funding) forced into the comparative columns.
- `amount_in_label` — the label ends in a figure (`Aeronautics..... 935,000`), so the row was split past its first column and the rest are shifted.
- `signed_level` — a level column holds an explicit `+`, which only a change figure prints.
- `adjustment_detail` — an enacted "Program increase—…" line, whose amount is a change from the request, not a level.

### Account identity

| Column | Type | Description |
|---|---|---|
| `account_key` | string | Federal account symbol (e.g. `080-0126`) — the join key across years, chambers, and stages. Empty unless a conservative match passed every check in `normalization.account_gate`. |
| `account_key_title` | string | Authoritative title of `account_key`. |
| `account_key_agency`, `account_key_bureau` | string | Agency and bureau of the key, when it came from the Tango reference. |
| `account_match` | enum | How the key was decided. Assigned: `exact`, `agency_scoped`, `tango`, `tango_scoped`. Not assigned: `unmatched`, `ambiguous`, `fuzzy` (a suggestion, never trusted). **Withheld** (a key was proposed and rejected): `withheld_unmapped_agency` (the account's agency has no jurisdiction entry), `withheld_jurisdiction` (the account's agency is not funded by this subcommittee and the pairing is not a reviewed cross-coded account), `withheld_generic` (a boilerplate label such as "Salaries and expenses" or "Trust Funds" with nothing on the row naming the agency), `withheld_partial_label` (a single word that only begins the account's title, such as "Direct"), `withheld_heading` (a department, title, or division heading), `withheld_ambiguous` (a tie-break among same-titled accounts with no evidence on the row). |
| `account_key_withheld` | string | The key that was proposed and withheld, for review. Never use it as a join key. |

## `nonstandard_layout_rows`

The values the release removed from rows with a nonstandard `column_layout`, so the change is auditable and reversible.
One row per isolated row.

| Column | Type | Description |
|---|---|---|
| `row_id`, `report_id`, `column_layout`, `line_item_text` | | As in `comparative_statements`. |
| `verified`, `verification_method` | | What the primary gate recorded before isolation. |
| `<amount>` / `<amount>_raw_text` | int $ / string | For each of the five amount columns, the extracted value and the source text it was parsed from — as mislabeled as the layout says. |

## `account_year_totals`

One row per (report, `account_key`): the account's total in that report, selected by `normalization.account_totals`.
This is the table for longitudinal analysis.

| Column | Type | Description |
|---|---|---|
| `account_key`, `account_key_title` | string | The account. |
| `report_id`, `fiscal_year`, `chamber`, `stage`, `subcommittee` | | The report the total comes from. **Compare within one `chamber` + `stage`**: a House recommendation, a Senate recommendation, and an enacted level for the same year are different figures, never parts of one. |
| `method` | enum | Several reports can hold a total for the same account, year, chamber, and stage (12 cells: a duplicated FY2019 Homeland report, and NIEHS, which two bills fund). Series built from this table should treat those as conflicts, as `/compare` and account history do, not add them. `single_line` — the report's only eligible keyed row, and its label is the account's own title. `account_line` — several keyed rows, and exactly one per designation is titled as the account; those are summed. `unresolved` — neither; **no total is given**. |
| `n_lines` | int | Eligible keyed rows that competed. |
| `row_ids` | string | `;`-separated rows the total was taken from. |
| `designations` | string | `;`-separated designations summed. |
| `prior_year_enacted`, `budget_estimate`, `committee_recommendation` | int $ | The total. Empty when `unresolved`, or when the source line prints no figure in that column. |
| `verified_lines` | int | How many of the chosen rows carry a verification tier other than `none`. |

Eligible rows carry a trusted key and a level amount, are not subtotals, rollups, or memo lines, and have a `standard` or `category_split` layout.

## `account_title_changes`

Derived from `account_year_totals`: for each account seen in at least two fiscal years, every year in which the label carrying the most money changed.
Years in which two reports of the same chamber and stage both claim the account are conflicts and are left out, so a wrongly keyed report cannot pass for a rename.
A `reword` is a rename candidate or a crosswalk over-merge; a `prefix` is an expansion or contraction.

| Column | Type | Description |
|---|---|---|
| `account_key`, `canonical_title` | string | The account and its authoritative title. |
| `first_fy`, `last_fy`, `n_years` | int | Years observed. |
| `change_fy` | int | First year of the new label. |
| `from_title`, `to_title` | string | Dominant labels before and after. |
| `kind` | enum | `prefix` or `reword`. |

## `inline_funding_tables`

The short funding summaries in report prose (`Appropriations, 2023 … / Budget estimate, 2024 … / Committee recommendation …`), a second, independent extraction.
String-matched against the source text.

| Column | Type | Description |
|---|---|---|
| `report_id`, `congress`, `chamber`, `fiscal_year`, `subcommittee` | | As above. |
| `context_heading` | string | The nearest heading above the block; heuristic. |
| `account_name` | string | The account or program the block describes, where identifiable. |
| `prior_year_amount`, `budget_estimate`, `committee_recommendation`, `delta_vs_enacted`, `delta_vs_estimate` | int $ | As printed. |
| `raw_text_block` | string | The verbatim block. |
| `verified` | bool | Every amount string-matched the source. |

## `manifest.json`

| Key | Contents |
|---|---|
| `version` | Package version. |
| `code` | `git_commit`, `git_dirty` (a dirty build is not a release), Python version. |
| `source_snapshot` | Count and combined SHA-256 of the extracted report files the build read, plus a hash of each reference file. |
| `tables` | Per table: rows, columns, and whether the CSV, Parquet, and JSON copies matched the source frame. |
| `counts` | Rows by stage and chamber, reports, and distributions of `verification_tier`, `column_layout`, `column_repair`, `account_match`, and `account_year_totals.method`. |
| `checks` | Each release check with its value, expectation, and pass/fail. The build refuses to finish if any fails. |
| `files` | SHA-256 and size of every file. `SHA256SUMS` repeats the hashes in `sha256sum` format. |
