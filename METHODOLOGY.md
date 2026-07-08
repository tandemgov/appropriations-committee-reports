# Methodology

## Data sources

All data is sourced from committee reports published on [GovInfo](https://www.govinfo.gov/) (U.S. Government Publishing Office). Reports are identified by package IDs in the CRPT collection (e.g., `CRPT-118srpt83` for Senate Report 118-83).

### Source formats

**Senate reports** are available as HTML on GovInfo. The HTML contains the full text of the report inside a single `<pre>` block (preformatted text, no semantic HTML elements). Critically, the comparative statement tables at the back of Senate reports are embedded as **text** and are directly parseable.

**House reports** are also available as HTML, but the comparative statement tables are embedded as **TIFF images** (`<GRAPHIC(S) NOT AVAILABLE IN TIFF FORMAT>` appears in the HTML where the tables should be). The corresponding PDFs contain these tables as embedded images. The narrative text and inline funding tables are available as text in the HTML for both chambers.

This structural difference between chambers drives the two-track extraction strategy.

### GovInfo API

The GovInfo API (`api.govinfo.gov`) is used for programmatic discovery of reports. The `/published` endpoint lists reports by collection and congress number. The `/packages/{id}/summary` endpoint provides metadata including title, date, chamber, and document class.

Report URLs follow a predictable pattern:
- HTML: `https://www.govinfo.gov/content/pkg/{package_id}/html/{package_id}.htm`
- PDF: `https://www.govinfo.gov/content/pkg/{package_id}/pdf/{package_id}.pdf`

## Extraction pipeline

### Stage 1: Inline narrative funding tables

**Applicable to:** Both chambers (from HTML text)

The body of each report contains 3-5 line funding summaries for each account:

**Senate format:**
```
Appropriations, 2023....................................  $1,368,969,000
Budget estimate, 2024...................................   1,497,069,000
Committee recommendation................................   1,371,619,000
```

**House format:**
```
Appropriation, fiscal year 2024.......................      $404,695,000
Budget request, fiscal year 2025......................       358,466,000
Recommended in the bill...............................       281,358,000
Bill compared with:
    Appropriation, fiscal year 2024...................      -123,337,000
    Budget request, fiscal year 2025..................       -77,108,000
```

**Method:** Regex-based extraction. The extractor scans for lines matching the pattern `{label}\.{3,}\s*{amount}` (a label, three or more dot-leader dots, then the amount — which is parsed and typed downstream), groups consecutive matching lines into blocks, and parses each block using chamber-specific label patterns. A backward search identifies the nearest heading to provide account context.

**Context detection:** For each funding block, the extractor looks backward for the nearest heading — up to 15 lines for a title-case heading, up to 30 for an all-caps one. It prefers title-case headings (closer, more specific) over all-caps headings (section-level).

### Stage 2: Senate comparative statements

**Applicable to:** Senate reports only (from HTML text)

The comparative statement is a dense, fixed-width table typically spanning 800-1,800 lines at the end of each report. It contains every line item with five numeric columns:
1. Prior year enacted appropriation
2. President's budget estimate
3. Committee recommendation
4. Committee recommendation vs. prior year (delta)
5. Committee recommendation vs. budget estimate (delta)

All values are in thousands of dollars.

**Method:** Deterministic fixed-width positional parsing.

1. **Section detection:** Find the heading "COMPARATIVE STATEMENT OF NEW BUDGET" and verify it's the actual section (not a table-of-contents reference) by checking that "[In thousands of dollars]" appears within 8 lines.

2. **Column parsing:** After the dot leaders connecting item names to numbers, extract all number-like tokens. Numbers include: plain integers with commas (`112,340`), parenthesized amounts (`(34,000)` for mandatory spending), signed deltas (`+2,000`, `-1,437`), and dot patterns (`................` for zero/not applicable).

3. **Hierarchy detection:** The hierarchy (Title → Department → Agency → Account → Program) is inferred from:
   - `TITLE I--` prefixes (title level)
   - ALL CAPS text (department/agency level)
   - Lines ending with `:` (sub-category headers)
   - Indentation depth (program/subprogram level)
   - `Total,` / `Subtotal,` / `Subtotal--` prefixes (aggregation lines)

4. **Dollar parsing:** A centralized parser handles all observed formats including comma-separated integers, parenthesized negatives, signed deltas, dash markers (`---`, `- - -`), and dot markers (`................`). When the `[In thousands of dollars]` context is present, values are multiplied by 1,000.

### Stage 3: House comparative statements

**Applicable to:** House reports only (from PDF images)

**Method:** a hybrid, format-aware extraction.

- Recent *typeset* House prints carry a real text layer and are parsed deterministically (`extraction/comparative_house_text.py`), like the Senate and enacted tracks — no vision model.
- Genuinely scanned reports run the vision pipeline below: a **Nemotron-Parse** bulk pass (self-hosted, free) with **Gemini** (default `gemini-3.1-pro-preview`) re-extracting only the ~⅓ of pages whose arithmetic doesn't close (`VISION_BACKEND=hybrid`). The steps below describe the per-page vision mechanics.

1. **Page identification:** pdfplumber identifies PDF pages containing substantial images (width > 200, height > 200 points). These are the TIFF-based table pages.

2. **Image rendering:** Each page is rendered to a 300 DPI PNG image using pdfplumber's rendering engine.

3. **Vision extraction:** The PNG image is sent to the vision model (Nemotron for the bulk pass, Gemini for the cleanup leg) with a structured prompt requesting JSON output. Each line item is extracted with: item name, indentation level, subtotal flag, and five numeric column values.

4. **Post-processing:** The JSON response is parsed, dot-leader artifacts in item names are stripped, dollar amounts are parsed through the same dollar parser used for Senate extraction, and hierarchy is inferred from indentation and capitalization.

**Model evaluation:** Multiple vision models were tested on page 142 of CRPT-118hrpt553 (DHS FY2025):

| Model | Item names | Column accuracy | Speed |
|-------|-----------|----------------|-------|
| Tesseract OCR (PSM 12) | Poor | Very poor | Fast |
| Qwen2.5-VL-7B (local) | Good | Partial (missed columns) | ~3 min/page |
| Qwen2.5-VL-32B (remote) | Untestable | Untestable | >8 min/page |
| Marker (local OCR tool) | Mixed | Unreliable column alignment | ~50 sec/page |
| Gemini 2.5 Flash | Good | ~95% (emergency sub-row errors) | ~3 sec/page |
| Gemini 3 Pro Preview | Excellent | ~100% (manually verified) | ~5 sec/page |

Gemini 3 Pro Preview was selected for the paid cleanup leg. It correctly handles the complex layout where line items have emergency-funding sub-rows, and it maintains accurate column alignment across all five numeric columns. (The default model is now `gemini-3.1-pro-preview`, and the production House path is the Nemotron-Parse + Gemini **hybrid** described above — Nemotron runs the free bulk pass and Gemini cleans up only the pages whose arithmetic doesn't close. The cost profile and optimization frontier are in `docs/vision-model-eval-brief.md`.)

### Stage 4: Enacted explanatory statements

**Applicable to:** the final enacted stage, FY2016–FY2024 (`stage=enacted`).

**Source:** the enacted program-level detail does not live in "conference reports" (those barely exist for this decade) but in the **House Rules Committee Prints** (GovInfo `CPRT` collection) — the two-book "Consolidated Appropriations Act, {year}" pairs whose Joint Explanatory Statement carries the allocation tables. These are born-digital, text-extractable PDFs, so this is a dot-leader / column regex parse (pdfplumber), **not** a vision problem.

**Method** (`extraction/comparative_enacted.py`): two table shapes are handled — single-column "Program ......... $amount" dot-leader tables (the single amount is the final enacted level → `committee_recommendation`), and two-column "Budget Request | Final Bill" adjustment tables (ALL-CAPS account rows give the absolute levels; the lowercase "Program increase/decrease—…" delta rows are skipped so they cannot pollute absolute amounts). Each line is **self-verified**: its amount must appear verbatim on its source page, so enacted rows ship `verified=true` without a companion HTML document.

**Result:** 11,829 enacted line items across FY2016–FY2024, 100% self-verified. The enacted stage fills the committee track's omnibus-year gaps (FY2021/FY2023 have no Senate committee reports but carry 1,306/1,516 enacted lines). Limitation: prose-only divisions (Energy-Water, Homeland Security) are under-captured because their detail is in narrative sentences rather than tables; FY2025 is a genuine gap (full-year CR, no explanatory statement).

## Normalization and crosswalk

To support longitudinal analysis, extracted accounts are resolved to a stable identity and amounts can be expressed in constant dollars. Design and findings: `docs/crosswalk_scoping.md`.

- **Account crosswalk** (`normalization/crosswalk.py`): each account is anchored to an authoritative **USASpending federal-account code** (`data/reference/federal_accounts.json`, 2,261 Treasury-sourced accounts). Anchoring — rather than fuzzy self-clustering — is essential: naive fuzzy matching conflates distinct accounts (e.g. African vs Asian Development Bank). The matcher is conservative (exact/prefix-unique and agency-scoped matches are trusted; fuzzy hits are flagged `needs_review` and gated out of the key). Coverage is gated by account-extraction quality: ~29% of account-bearing committee rows receive a trusted `account_key`; program-level rows and accounts absent from the reference are left blank with `account_match` recording why. `approps crosswalk` emits the distinct-account crosswalk + review queue.
- **Designation** dimension (`normalization/account_names.py`): base/OCO/emergency/disaster/rescission/CHIMP, parsed only from parentheticals/suffixes so account names are not misread.
- **Inflation** (`normalization/inflation.py`, `data/reference/deflators.csv`): a CPI-U series (BLS CUUR0000SA0) drives the `real_factor_2024` column emitted by the output layer — multiply any nominal amount for FY2024 constant dollars.

### Cross-year account tracing

Once accounts carry a stable `account_key`, an account can be followed through time by that key even as its source label changes — the report-stage analogue of tracing an appropriation across enacted bills by its Treasury/OMB account symbol (the approach in `cgorski/congress-appropriations`). `normalization/account_authority.py` groups every crosswalk-keyed line item by `account_key` and reconstructs three things per account, exposed via `approps trace`, `GET /api/accounts`, and `GET /api/accounts/{account_key}/history`.

1. **Money series** across fiscal years, broken out by chamber and stage. To avoid the account-total-vs-program double-count that comparative statements create (an account lists both its own total and its program breakdown as non-subtotal rows), each `(report, account_key)` is collapsed to its single largest-magnitude leaf — the account total, `>=` any child part — the same rule the flow layer uses. Rollup rows the `is_subtotal` flag missed are dropped.

2. **Label timeline** — every distinct label the source documents gave the account and the years each appeared.

3. **Title changes** between consecutive years, comparing the dominant label (the one carrying the most money) year over year. Each change is classified: `prefix` (one label is a leading token-run of the other — an expansion or contraction) or `reword` (a substantive change). Case- and punctuation-only drift is normalized away and never emitted.

Two honest caveats. Only trusted `account_key` rows participate — the coarser attribution tiers (`account_inferred`, `account_recovered`) have no stable cross-year identity, so they are out of scope by design and cross-year coverage inherits the crosswalk's ~29% ceiling. And a `reword` change is **not** always a real rename: because the crosswalk sometimes folds distinct programs under one code, a `reword` equally flags a crosswalk over-merge — which makes `approps trace` a useful QA lens on the crosswalk (and on extraction artifacts such as amounts bleeding into a title), not only a rename detector.

## Verification

### Three-tier amount verification

Every extracted dollar amount is verified against the source text using three tiers of string matching (methodology adapted from [cgorski/congress-appropriations](https://github.com/cgorski/congress-appropriations)):

1. **Exact:** The raw extracted text appears verbatim in the source document
2. **Normalized:** After collapsing multiple whitespace characters to single spaces
3. **Spaceless:** After removing all whitespace from both strings

If all three tiers fail, the amount is flagged as unverified.

**Results on Senate and inline extractions:** every extracted dollar amount across the 87 Senate committee reports and both chambers' inline funding tables is checked this way. Rows that carry an amount verify at ~100% by exact string match; the corpus-wide `verified` fractions (Senate committee 92.7%, the remainder being structural/no-amount rows) are in [COVERAGE.md](docs/COVERAGE.md). An early 5-report validation run was 8,815 amounts at 100%, zero failures.

### Cross-validation for House PDF extractions

Since House comparative statements are extracted via vision model (non-deterministic), we cross-validate against the inline narrative tables (which are 100% verified from HTML text):

- **Direct match:** Agency-level totals in the comparative statement should match corresponding inline table values
- **Offsetting collections:** Some comparative statement totals are net of offsetting collections. The inline tables show gross appropriations. The difference must equal the offsetting collection amount stated in the comparative statement.

**Cross-validation results (CRPT-118hrpt553, DHS FY2025):**

| Agency | Comparative (PDF) | Inline (HTML) | Status |
|--------|-------------------|---------------|--------|
| U.S. Customs and Border Protection | $18,261,585,000 | $18,261,585,000 | Exact match |
| U.S. Immigration and Customs Enforcement | $10,516,791,000 | $10,516,791,000 | Exact match |
| Transportation Security Administration | $8,173,643,000 | $11,492,643,000 | Offset by $3,319,000,000 (verified) |
| Coast Guard | $14,182,215,000 | $14,182,215,000 | Exact match |
| United States Secret Service | $3,158,110,000 | $3,158,110,000 | Exact match |
| Federal Emergency Management Agency | $28,145,913,000 | $28,145,913,000 | Exact match |

### Subtotal arithmetic

For comparative statement extractions, subtotal lines are checked against the sum of their child line items. Delta columns are verified: `committee_recommendation - prior_year_enacted` should equal `delta_vs_enacted`.

## PDF parsing tools evaluated

| Tool | Result | Notes |
|------|--------|-------|
| **pdfplumber** | Used for page rendering and image detection | Cannot extract text from TIFF image pages in House reports. Word-level extraction only finds page metadata (page numbers, GPO footer). |
| **Tesseract OCR** | Rejected | Multiple PSM modes tested. PSM 12 produced some numbers but with severe noise and garbled item names. |
| **Marker** (VikParuchuri) | Rejected | Produced structured markdown tables but with unreliable column alignment. Better than Tesseract but not accurate enough for financial data. |
| **Tabula / Camelot** | Not applicable | These tools require table grid lines or a text layer. House comparative statements have neither. |
| **Gemini 3 Pro Preview** | Selected | Free tier (15 RPM, daily quota). 100% accuracy on manually verified page. Correct handling of emergency sub-rows and complex table layouts. |

## Known limitations

1. **House PDF extraction is non-deterministic.** Vision model outputs may vary between runs. Cross-validation against inline tables mitigates this.

2. **Vision extraction is rate- and cost-bound.** The hybrid keeps the paid Gemini leg to the ~⅓ of pages the free Nemotron bulk pass can't self-verify; even so, large reports (Defense/THUD run hundreds of image pages) are throughput-limited by per-model quotas. See `docs/vision-model-eval-brief.md` for the measured cost profile.

3. **Heading detection for inline tables is heuristic.** The backward-search algorithm occasionally picks up a nearby heading from a different section, especially in House reports where heading styles vary.

4. **Account crosswalk coverage is partial and gated by extraction quality.** Accounts are anchored to authoritative USASpending codes, but only ~29% of account-bearing committee rows currently receive a trusted `account_key`; program-level lines, OCR/wording drift, and accounts absent from the reference are flagged for review rather than force-matched. Coverage grows as account-level extraction is cleaned up (see `docs/crosswalk_scoping.md`).

5. **Only the comparative statement and PPA detail tables from image pages are extracted.** Vote roll call pages (which are also images in House PDFs) are processed but correctly return 0 items.

## Data dictionary

The full, current field-by-field data dictionary for the combined dataset is **`docs/DATA_DICTIONARY.md`** (every column, stage semantics, the crosswalk/designation/real-dollar fields, verification meaning, and limitations). The canonical types live in the Pydantic schemas in `src/approps/output/schemas.py`. The legacy summary below is retained for reference:

### comparative_statements.csv

| Field | Type | Description |
|-------|------|-------------|
| report_id | string | GovInfo package ID (e.g., CRPT-118srpt83) |
| congress | int | Congress number (114-119) |
| chamber | string | "house" or "senate" |
| fiscal_year | int | Target fiscal year of the bill |
| subcommittee | string | Canonical subcommittee name |
| stage | string | "committee" or "enacted" |
| title_name | string | Title heading (e.g., "TITLE I--DEPARTMENT OF THE INTERIOR") |
| department | string | Department/agency name |
| account | string | Account/bureau name |
| program | string | Program/sub-account (if applicable) |
| line_item_text | string | Full text of the line item |
| prior_year_enacted | float | Prior year enacted amount (dollars) |
| budget_estimate | float | President's budget estimate (dollars) |
| committee_recommendation | float | Committee recommendation (dollars) |
| delta_vs_enacted | float | Committee rec minus prior year (dollars) |
| delta_vs_estimate | float | Committee rec minus budget estimate (dollars) |
| is_subtotal | bool | Whether this is a subtotal/total line |
| hierarchy_depth | int | Depth in hierarchy (0=title, 1=dept, ...) |
| in_thousands | bool | Whether source values were in thousands |
| extraction_method | string | "rule_based" or "llm" |
| verified | bool | Whether amount was verified against source |

### inline_funding_tables.csv

| Field | Type | Description |
|-------|------|-------------|
| report_id | string | GovInfo package ID |
| congress | int | Congress number |
| chamber | string | Chamber |
| fiscal_year | int | Target fiscal year |
| subcommittee | string | Canonical subcommittee name |
| context_heading | string | Nearest heading above the table |
| account_name | string | Inferred account/program name |
| prior_year_amount | float | Prior year appropriation (dollars) |
| budget_estimate | float | Budget estimate (dollars) |
| committee_recommendation | float | Committee recommendation (dollars) |
| raw_text_block | string | Verbatim text of the funding block |
| verified | bool | Amount verification status |
