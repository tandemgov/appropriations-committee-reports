# Data dictionary — appropriations line-item dataset

Covers the combined outputs in `data/output/`:
- `comparative_statements.csv` — line items from comparative statements (Senate/House committee reports) and enacted explanatory statements.
- `inline_funding_tables.csv` — the inline narrative funding tables found in report bodies.

All dollar amounts are integers in **whole dollars** (the `in_thousands` source convention is already applied — a source table "(In thousands of dollars)" value of `104,102` is stored as `104102000`). Amounts may be negative (rescissions, offsets). Empty cells mean the field was not present or not captured for that row.

Scope: Congresses 114–119, fiscal years FY2016–FY2027. See `COVERAGE.md` for coverage by stage/chamber/year and `crosswalk_scoping.md` for the account-identity design.

## `comparative_statements.csv`

| Column | Type | Description |
|---|---|---|
| `report_id` | string | GovInfo package ID of the source document (e.g. `CRPT-118srpt83`, `CPRT-117HPRT50347`). |
| `congress` | int | Congress number (114–119). |
| `chamber` | enum | `senate` or `house`. Enacted explanatory-statement prints are House-numbered, so they carry `house`; use `stage` to separate them. |
| `fiscal_year` | int | Fiscal year the appropriation is for (FY2016–FY2027). The analytic time key. |
| `subcommittee` | string | One of the 12 appropriations subcommittees (e.g. `Defense`, `State-Foreign-Ops`). Empty for enacted omnibus rows — use `title_name` (division) until the division→subcommittee crosswalk lands. |
| `stage` | enum | Legislative stage: `committee` (chamber committee report) or `enacted` (final, from the Joint Explanatory Statement). `subcommittee`/`conference` are defined but not populated. |
| `title_name` | string | Top hierarchy label. For enacted rows this is the omnibus division (e.g. `DIVISION A—AGRICULTURE…`). |
| `department` | string | Department, where captured (committee rows; ~49%). |
| `agency` | string | Agency/bureau, where captured (committee rows; sparse, ~17%). |
| `account` | string | Appropriations account name **as it appears in the source**. Empty for House committee rows (vision extraction did not capture hierarchy) and ~75% of enacted rows. Raw, un-normalized — see `account_inferred` (House) and `account_key`. |
| `account_inferred` | string | Account grouping **recovered for House vision rows** from a reconciling subtotal block: set only when the block's line amounts sum exactly to the `Subtotal,/Total, <name>` amount, so it is arithmetic-verified, never guessed. Nested — a reconciled inner subtotal rolls up into its parent, so leaves resolve to their account-level name; tolerates one OCR-mangled column, rollup rows the `is_subtotal` flag missed, and parenthesized non-add memo amounts (limitations/transfers) excluded from the block sum. Additive — `account` is left untouched (empty here for Senate/enacted rows, which already carry `account`). Populated on ~19,500 rows (≈31% of value-bearing House line items) — the arithmetic base reconciler plus the Gemini non-add double-gate (see `non_add_inferred`); feeds `account_key` matching as a fallback after `account`. |
| `non_add_inferred` | bool | True when the row's amount is **non-add** — must not be summed into its account total — by either signal: (1) the Gemini non-add double-gate flagged it as a non-add sub-detail (arithmetic-verified — excluding exactly the flagged rows makes the block reconcile), or (2) its `committee_recommendation` is a **parenthesized non-add memo** (a limitation, transfer authority, or "of which"/GWOT breakout) written `(X)` — positive, no inner sign; `(-X)` rescissions are real negatives and are **not** flagged. ~8,300 rows. Filter these (with subtotals) out before summing amounts per account. |
| `column_layout` | enum | `standard` (the usual prior-year / request / recommendation / delta shape) or a nonstandard table whose columns the standard schema mis-maps — filter to `standard` for the strictly-comparable subset. `category_split` (~297; chiefly Energy-Water Reclamation/Corps "Water and Related Resources"): funding split across category columns — the `committee_recommendation` total is correct, but `prior_year_enacted` / `budget_estimate` / the deltas are mislabeled category columns. `procurement_qty` (~185; Defense procurement quantity-column tables): the program name was lost (the label is a bare line-item number like `30`) and amounts are shifted. See `docs/KNOWN_ISSUES.md` for both. |
| `program` | string | Program/project/activity line under the account, where present. |
| `line_item_text` | string | The full line text as it appeared in the source. Always populated; the most reliable label when `account` is empty. |
| `prior_year_enacted` | int $ | Prior-year enacted amount (comparative-statement column). |
| `budget_estimate` | int $ | President's budget request. For enacted 2-column tables, the "Budget Request" column. |
| `committee_recommendation` | int $ | The committee's recommended amount. **For `stage=enacted`, this column holds the final ENACTED amount** ("Final Bill" / agreement). |
| `delta_vs_enacted` | int $ | recommendation − prior_year_enacted (committee comparative rows). |
| `delta_vs_estimate` | int $ | recommendation − budget_estimate (committee comparative rows). |
| `is_subtotal` | bool | True for subtotal/total rows (exclude when summing leaf line items). |
| `hierarchy_depth` | int | Indentation depth in the source hierarchy (0 = top). |
| `in_thousands` | bool | Whether the source table was "(In thousands of dollars)". Informational — `*_amount` values are already in whole dollars. |
| `extraction_method` | enum | `rule_based` (deterministic text/PDF parsing) or `llm` (House vision extraction). |
| `verified` | bool | Amount(s) on the row passed verification. Senate/inline: exact string-match vs source HTML. House comparative: delta-arithmetic. Enacted: the amount appears verbatim on its source PDF page. Empty/structural rows (no amount) are `false`. |
| `verification_tier` | enum | *How* the row's amount is independently supported, strongest first: `delta` (its own delta-column arithmetic closes — equivalent to `verified=true`); `block` (not delta-verified, but a value-bearing member of a subtotal block whose amounts reconcile exactly, so the block sum is a second witness); `inline` (its amount **and** account are restated in the report's string-verified inline funding tables); `none` (no in-document second witness — the source printed no comparison column, or the amount appears nowhere else). Lets you widen "trustworthy" beyond the strict `verified` boolean: for House committee rows, `delta`+`block`+`inline` corroborate ~61% vs the 52% that `verified` alone captures. Block is a hair weaker than delta (an exact block sum could in principle mask two perfectly-compensating errors), which is why it is a separate tier, not folded into `verified`. |
| `account_key` | string | **Authoritative account identity** (federal-account symbol / OMB account code, e.g. `019-0113`) assigned by the crosswalk. Empty when unmatched. The stable key for longitudinal and cross-stage/cross-chamber joins. |
| `account_key_title` | string | Canonical account title for `account_key`. |
| `account_match` | enum | How `account_key` was assigned: `exact` (unique token-prefix match), `agency_scoped`, `ambiguous`, `fuzzy` (suggestion only — gated out of the key), `unmatched`, or — for rows the primary crosswalk left unkeyed — `tango` / `tango_scoped` (matched to Tango's federal-account reference by title containment, resolving to a single account outright or after narrowing to the subcommittee's agency scope; see `docs/DELIVERABLES.md` and `approps.normalization.tango_crosswalk`). |
| `account_key_agency` | string | Reporting agency of the matched federal account (from the Tango crosswalk). Fills the agency hierarchy for House committee rows, which carry no extracted agency. Populated only when `account_match` starts with `tango`. |
| `account_key_bureau` | string | Budget bureau of the matched federal account (from the Tango crosswalk). Same provenance as `account_key_agency`. |
| `designation` | enum | Funding designation parsed as a separate dimension: `base` (default), `OCO`, `emergency`, `disaster`, `rescission`, `CHIMP`. Lets base vs OCO/emergency rows for the same `account_key` be summed or split. |
| `real_factor_2024` | float | Multiply any nominal amount on the row by this factor to get **constant FY2024 dollars** (CPI-U, BLS CUUR0000SA0). Empty if the fiscal year is outside the deflator series. |

### Stage semantics for the amount columns

- **committee** rows: the three amount columns are prior-year enacted, the President's request, and the chamber committee's recommendation — i.e. a *proposal* with its comparison baseline.
- **enacted** rows: `committee_recommendation` = the final enacted amount; `budget_estimate` = the request (only when the source used a 2-column Request/Final-Bill table); `prior_year_enacted` and the deltas are usually empty.

## `inline_funding_tables.csv`

Inline narrative funding tables (the short prior-year / estimate / recommendation blocks embedded in report prose).

| Column | Type | Description |
|---|---|---|
| `report_id` | string | Source GovInfo package ID. |
| `congress` | int | Congress number. |
| `chamber` | enum | `senate` or `house`. |
| `fiscal_year` | int | Fiscal year. |
| `subcommittee` | string | Subcommittee. |
| `context_heading` | string | The narrative heading the table appeared under. |
| `account_name` | string | Account/program the table describes, where identifiable. |
| `prior_year_amount` | int $ | Prior-year enacted amount. |
| `budget_estimate` | int $ | Budget request. |
| `committee_recommendation` | int $ | Committee recommendation. |
| `delta_vs_enacted` | int $ | recommendation − prior_year_amount. |
| `delta_vs_estimate` | int $ | recommendation − budget_estimate. |
| `raw_text_block` | string | The verbatim source text block (provenance; may contain embedded newlines). |
| `verified` | bool | Amounts string-matched against the source HTML. |

## `account_authority.csv`

A derived analytical artifact produced by `approps trace` (not part of the core dataset): it follows each crosswalk-keyed account across fiscal years and emits **one row per title change** — a year in which the account's dominant source label changed under an unchanged `account_key`. Its purpose is twofold: surfacing genuine account renames, and flagging crosswalk over-merges (a `reword` change is equally a signal that two distinct programs were folded under one key). Only rows carrying a trusted `account_key` participate; the coarser attribution tiers have no stable cross-year identity. See `METHODOLOGY.md` (Cross-year account tracing) for the method.

| Column | Type | Description |
|---|---|---|
| `account_key` | string | Authoritative account identity (as in `comparative_statements.csv`) — the stable key the account is followed by. |
| `canonical_title` | string | Canonical crosswalk title for `account_key` (constant across years; the anchor the drifting labels are compared against). |
| `first_fy` | int | Earliest fiscal year the account was observed. |
| `last_fy` | int | Latest fiscal year the account was observed. |
| `n_years` | int | Number of distinct fiscal years the account appears in. |
| `change_fy` | int | Fiscal year in which this title change took effect (the first year the new dominant label appears). |
| `from_title` | string | The dominant source label in the year before the change. |
| `to_title` | string | The dominant source label from `change_fy` onward. |
| `kind` | enum | Change class: `prefix` (one label is a leading token-run of the other — an expansion/contraction) or `reword` (a substantive change — a rename candidate, or a crosswalk over-merge). Case/punctuation-only drift is suppressed and never emitted. |

## Known limitations

See `COVERAGE.md` for the authoritative, up-to-date coverage list. In brief:
- **Coverage:** committee stage Senate FY2016–FY2026 (complete) + House FY2016–FY2027 (vision); enacted FY2016–FY2024. FY2021/FY2023 have no Senate committee reports (omnibus years). FY2025 enacted does not exist (full-year CR).
- **Hierarchy:** `account`/`agency` are sparse on House (vision) and enacted rows. For House rows, `account_inferred` recovers the account grouping where a subtotal block reconciles (arithmetic-verified). Join on `account_key` once populated, else fall back to `account_inferred` / `line_item_text`.
- **Enacted prose divisions:** Energy-Water and Homeland Security are under-captured (their detail is in prose, not tables).
- **Account identity:** `account_key` is assigned by an authoritative-anchored crosswalk; rows marked `account_match=needs_review`/`unmatched` are not yet resolved.
