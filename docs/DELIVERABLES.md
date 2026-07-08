# Deliverables handoff

This is the front door to the appropriations extraction deliverables — what each file is, how it was produced and verified, and where the boundaries are. It maps directly to the seven SOW items.

## The datasets

| Deliverable | File | Size | What it is |
|---|---|---|---|
| **Comparative statements** | `data/output/comparative_statements.csv` | 109,052 rows / 246 report-stages | Every line item in the back-of-report comparative ledgers: department → agency → account → program, with prior-year enacted, budget estimate, and committee/enacted recommendation, plus normalization columns. The primary deliverable. |
| **Inline funding tables** | `data/output/inline_funding_tables.csv` | 13,853 records | The 3-line narrative funding summaries in the report body (a second, independent extraction). |
| **Combined JSON** | `data/output/all_data.json` | — | Both of the above as nested JSON. |
| **FY2027 House Defense** | `data/output/fy2027-house-defense/` | 2,327 line items + 1,354 marks | Standalone deliverable from the born-digital Defense committee print; see its own README. |
| **Account crosswalk** | `data/reference/account_crosswalk.csv` | — | Distinct extracted accounts mapped to authoritative USASpending federal-account codes, plus a human-review queue. Regenerate with `approps crosswalk`. |

Coverage across stage × chamber × fiscal year is in **[COVERAGE.md](COVERAGE.md)**. The per-field schema — every column, its meaning, units, and null semantics — is in **[DATA_DICTIONARY.md](DATA_DICTIONARY.md)**.

## What each row carries

Beyond the raw amounts, every comparative row is enriched with (see the data dictionary for exact semantics):

- `verified` — whether the row's dollar amounts passed verification (see below).
- `account_key` / `account_key_title` / `account_match` — the authoritative federal-account code, when the account name matched conservatively (exact/agency-scoped; fuzzy hits are recorded but gated out of the key). Rows the primary crosswalk leaves unkeyed get a second pass against **Tango's federal-account reference** (`data/reference/tango_accounts.csv`, refreshed by `scripts/fetch_tango_accounts.py` from the Tango budget lake), matched by title containment and resolved to a single account (`account_match` = `tango`/`tango_scoped`). Populated on ~27,470 rows.
- `account_key_agency` / `account_key_bureau` — agency + bureau of the matched federal account, from the Tango crosswalk. Fills the agency hierarchy for House committee rows (which carry no extracted agency); populated on the Tango-matched rows.
- `real_factor_2024` — CPI-U inflation factor; multiply any nominal amount by it for FY2024 constant dollars. Populated on ~94,700 rows.
- `designation` — base / OCO / emergency / disaster / rescission / CHIMP, read only from parentheticals/suffixes.

## How the data was produced

Three extraction tracks, chosen by how the source encodes its tables:

1. **Senate committee (deterministic, HTML text).** Senate reports embed the comparative tables as fixed-width text in HTML — parsed deterministically, no model. 100% exact string-match on every dollar amount.
2. **House committee (vision, scanned images).** House reports embed the tables as scanned TIFF images. Extracted by a hybrid pipeline: **Nemotron-Parse** (self-hosted, free) does the bulk pass; **Gemini** re-extracts only the ~⅓ of pages whose arithmetic doesn't close. Recent *typeset* House prints (e.g. FY2027 Defense) have a real text layer and are parsed deterministically instead.
3. **Enacted (deterministic, PDF text).** Final enacted levels come from the House Rules Committee explanatory-statement prints (GovInfo CPRT), which are born-digital PDFs parsed by regex. Each line self-verifies (its amount must appear verbatim on its source page).

Full rationale, model selection, and methodological decisions are in [../METHODOLOGY.md](../METHODOLOGY.md); the vision-cost optimization brief is in [vision-model-eval-brief.md](vision-model-eval-brief.md).

## What "verified" means

Verification is per-amount and first-class, not a spot check:

- **Senate + inline (string match):** the extracted text appears verbatim in the source HTML (three-tier: exact → whitespace-normalized → spaceless).
- **House comparative (delta arithmetic):** each row carries five columns where two are derived — `recommended − prior_year_enacted == delta_enacted` and `recommended − budget_estimate == delta_estimate`. These identities hold in the source table, so checking them cross-validates all four value columns at once. A single misread digit breaks the arithmetic.
- **Enacted (self-verifying):** each amount must appear verbatim on its source PDF page.

A row is `verified = True` only when its applicable check passes. Filter on `verified` for the trustworthy value-bearing dataset. **Unverified is not the same as wrong** — most unverified rows are structural/label rows (headings, subtotals) that carry no independently-checkable amount. See [COVERAGE.md](COVERAGE.md) for why the House verified fraction is lower than Senate's.

## Boundaries (read before analysis)

- **Subcommittee stage is out of scope by nature.** Subcommittee marks are rarely published as separate line-item documents; the committee report is the first public artifact. The corpus therefore covers the **committee** and **enacted** stages.
- **House account hierarchy is partial.** In the vision track, `account` is often null and the label lands in `program`; this caps the account-crosswalk coverage (not the dollar amounts). See [crosswalk_scoping.md](crosswalk_scoping.md).
- **The `chamber` on enacted rows is `house`** because the enacted detail is sourced from House Rules Committee prints — it represents the final *cross-chamber* enacted level, not a House-only figure.
- **Back-of-report summary tables are excluded — line items only.** A few reports print a 302(b) allocation-compliance table and an outlay-projection-by-year table between the summary and detailed comparative statements; the vision pass reads them as rows, but their columns are budget authority / allocation / outlays (not recommendation / prior / delta), so a `Discretionary` or bare-year (`2027`) row is *not* an appropriations line item. These are dropped from the dataset (`approps.normalization.summary_rows`); ~36 rows across 4 reports.
- **Gaps are documented, not silent:** Senate FY2021/FY2023 (omnibus years, no Senate markup — filled by the enacted stage) and enacted FY2025 (full-year CR, no explanatory statement). See [COVERAGE.md](COVERAGE.md). (Two earlier "gaps" were resolved: Senate Labor-HHS FY2026 — `srpt55`, GovInfo published no HTML — is now recovered from its born-digital PDF (146 inline funding tables); and an "THUD FY2025 House — no report filed" note was **wrong** — the report exists (`CRPT-118hrpt584`) but a title-hyphenation bug hid it from discovery. FY2025 House is 12/12, Senate FY2026 is 8/8. Both fixed 2026-07-03.)

## Regenerating everything

```bash
uv sync
approps discover                 # rebuild the GovInfo catalog (needs GOVINFO_API_KEY)
approps download --all           # fetch HTML/PDF
approps extract --all            # extract (House vision needs a backend; see below)
approps verify --all             # persist string-match verified flags (Senate/inline)
approps crosswalk                # rebuild the account crosswalk
approps output                   # write the combined CSV/JSON deliverables
```

House comparative extraction needs a vision backend (`VISION_BACKEND` = `hybrid` with a Nemotron server, or `gemini` with `GEMINI_API_KEY`); the delta-arithmetic gate for House vision runs via `scripts/verify_house.py`. `approps output` counts each report exactly once — it ignores the intermediate `<id>_nemotron.json` / `<id>_hybrid.json` passes left on disk. 176 tests pass; `uv run pytest tests/`.
