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

The source tables print these columns in thousands of dollars. The extracted `value` is normalized to **whole dollars** (the parser applies the ×1,000 itself), and `in_thousands` records only how the source presented it. See `docs/DATA_DICTIONARY.md`.

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

**Result:** 12,809 enacted rows across FY2016–FY2024; 12,761 pass the verbatim-on-page gate (the rest are isolated layouts). Verbatim-on-page proves a figure is on the page, not that it was read into the right line: the accuracy review found 3 of 131 source lines missing on its six sampled pages. The enacted stage fills the committee track's omnibus-year gaps. Limitations: divisions whose detail is prose (Energy-Water, Homeland Security) are under-captured; FY2025 is a genuine gap (full-year CR, no explanatory statement). See [docs/COVERAGE.md](docs/COVERAGE.md).

## Normalization and crosswalk

To support longitudinal analysis, extracted accounts are resolved to a stable identity and amounts can be expressed in constant dollars. Design and findings: `docs/crosswalk_scoping.md`.

- **Account crosswalk** (`normalization/crosswalk.py`, `normalization/tango_crosswalk.py`): each account is anchored to an authoritative **federal account symbol** (`data/reference/federal_accounts.json`, and Tango's account reference for rows the first pass leaves unkeyed). Anchoring — rather than fuzzy self-clustering — keeps distinct accounts apart (African vs Asian Development Bank). Exact, prefix-unique, and agency-scoped matches are proposed; fuzzy hits are recorded and never trusted. `approps crosswalk` emits the distinct-account crosswalk and review queue.
- **Account gate** (`normalization/account_gate.py`): both matchers match on the label alone, so boilerplate labels resolved to arbitrary accounts. After matching, a key is withheld when its agency has no entry in the jurisdiction table (every agency in the corpus has one, keyed by CGAC prefix), when that agency is not funded by the row's subcommittee — or is funded there only through particular bureaus (Forest Service in Interior, FDA in Agriculture, Reclamation in Energy-Water, military construction in MilCon-VA) and the account is not one of them — and the pairing is not one of the reviewed cross-coded accounts (Legal Services Corporation in CJS, Council on Environmental Quality in Interior), when every label on the row is boilerplate or a single word that only begins the account's title and nothing else on the row names the agency, when the row is a heading, or when an agency tie-break had no evidence. There is no data-driven exception: the same label-only match repeated across reports is not evidence. 20,881 rows keep a key; 7,687 had one withheld (`account_key_withheld`). See [KNOWN_ISSUES #16](docs/KNOWN_ISSUES.md).
- **Designation** dimension (`normalization/account_names.py`): base/OCO/emergency/disaster/rescission/CHIMP, parsed only from parentheticals/suffixes so account names are not misread.
- **Inflation** (`normalization/inflation.py`, `data/reference/deflators.csv`): a CPI-U series (BLS CUUR0000SA0, calendar-year averages as an approximation for fiscal years) drives `real_factor_2024`. The series ends at 2025 (provisional), so FY2026–27 rows have no factor. Nothing substitutes a default: `real_dollars` raises and `/api/line_items/compare?real=true` returns 422 for a year without a deflator.

## Report metadata and column repairs

The output build (`approps output`) corrects two things before any row is written, each from evidence in the data rather than a guess.

- **Report metadata** (`normalization/report_metadata.py`): `fiscal_year`, `subcommittee`, `congress`, `chamber`, and `stage` are properties of the report. Rows missing them (those merged in by page repair) take the catalog's values; enacted rows take the subcommittee of their omnibus division. A row's existing value is never overwritten, and contradictions are reported.
- **Column repairs** (`normalization/column_shift.py`): two layouts file values into the wrong slots in a way the rows' own arithmetic proves — FY2026–27 House three-column pages (`committee_recommendation == budget_estimate - prior_year_enacted` on every full row of a page with no delta column) and FY2016 Senate statements with a House allowance column. Values are moved into place and the row records `column_repair`. The repair is not counted as verification. See KNOWN_ISSUES #11 and #13.

## Isolating nonstandard layouts

Some rows come from tables whose columns do not mean what the schema names them, or from parses that shifted a row's values: category-split tables, Defense quantity tables, cells holding words, labels holding a figure, level columns holding a `+`, and enacted program-increase lines.
`output.csv_writer._column_layout` recognizes each from the row's own text, and the build **empties the untrusted columns**, sets `verified = false` and `verification_tier = none`, and writes the extracted values to `nonstandard_layout_rows` keyed by `row_id`.
Flagging alone was not enough: a mislabeled figure with a verification tier looks trustworthy to anyone who does not filter.
3,026 rows are isolated; see [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) for each layout and KNOWN_ISSUES #1, #2, and #15.

## Account totals

A comparative statement prints an account's own line and, often, its program breakdown beneath it, all as ordinary rows sharing one `account_key`.
Summing them double-counts; taking the largest (the earlier rule) promotes a program line to a total whenever the account line is missing or keyed elsewhere.

`normalization/account_totals.py` selects, per report and account, only lines the source presents as the account:

1. `single_line` — the report's only eligible keyed row, and its label is the account's own title (the authoritative title starts with it, ignoring designation and citation parentheticals but not other qualifiers, so `Child Nutrition Programs (Entitlement Commodities)` is not the whole account);
2. `account_line` — several keyed rows, and exactly one per designation is titled as the account; those are summed;
3. `unresolved` — otherwise, and no total is given.

Eligible rows carry a trusted key and a level amount and are not subtotals, rollups, memo lines, or isolated layouts.
Totals are per report and are never combined across chambers or stages: a House recommendation, a Senate recommendation, and an enacted level are different figures.
The release's `account_year_totals` resolves 6,163 of 9,154 report-account pairs.
The same function drives `/api/line_items/compare`, the flow view, and account history, so the API and the file cannot disagree.

The rule is conservative, not complete: it declines where the source's structure is ambiguous, and it trusts the key. The multi-year check in [docs/ACCURACY_REVIEW.md](docs/ACCURACY_REVIEW.md) tests it against the source documents.

### Cross-year account tracing

Once accounts carry a stable `account_key`, an account can be followed through time by that key even as its source label changes — the report-stage analogue of tracing an appropriation across enacted bills by its Treasury/OMB account symbol (the approach in `cgorski/congress-appropriations`). `normalization/account_authority.py` groups every crosswalk-keyed line item by `account_key` and reconstructs three things per account, exposed via `approps trace`, `GET /api/accounts`, and `GET /api/accounts/{account_key}/history`.

1. **Money series** across fiscal years, broken out by chamber and stage, from the account totals above. Reports whose total is unresolved contribute no point.

2. **Label timeline** — every distinct label the source documents gave the account and the years each appeared.

3. **Title changes** between consecutive years, comparing the dominant label (the one carrying the most money) year over year. Each change is classified: `prefix` (one label is a leading token-run of the other — an expansion or contraction) or `reword` (a substantive change). Case- and punctuation-only drift is normalized away and never emitted.

Two honest caveats. Only trusted `account_key` rows participate — the coarser attribution tiers (`account_inferred`, `account_recovered`) have no stable cross-year identity, so they are out of scope by design and cross-year coverage inherits the crosswalk's ceiling (20,881 keyed rows, about a fifth of the corpus). And a `reword` change is **not** always a real rename: because the crosswalk sometimes folds distinct programs under one code, a `reword` equally flags a crosswalk over-merge — which makes `approps trace` a useful QA lens on the crosswalk (and on extraction artifacts such as amounts bleeding into a title), not only a rename detector.

## Verification

### Three-tier amount verification

Every extracted dollar amount is verified against the source text using three tiers of string matching (methodology adapted from [cgorski/congress-appropriations](https://github.com/cgorski/congress-appropriations)):

1. **Exact:** The raw extracted text appears verbatim in the source document
2. **Normalized:** After collapsing multiple whitespace characters to single spaces
3. **Spaceless:** After removing all whitespace from both strings

If all three tiers fail, the amount is flagged as unverified.

**Results:** every amount on the Senate comparative rows and both chambers' inline funding tables is checked this way. 27,163 of 29,105 Senate rows pass (the rest carry no amount or are isolated layouts), and 13,707 of 13,853 inline records. A pass proves the figure is in the source text. It does not prove the figure is in the right column or on the right line: the accuracy review found 8 of 513 Senate cells in the wrong column, every one of them string-matched.

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

### Reconciliation — the only gate that looks outside the row

The two gates above share a blind spot, and it is structural rather than incidental. Both compare a row to *itself*: string matching compares an amount to the text it was read from, and the delta identity compares a row's columns to each other. Neither can detect a **misinterpretation** of the source, as opposed to a **mistranscription** of it.

Concretely: if `(24,000)` is transcribed perfectly and then read as −24,000, the string match still passes, because the raw text really does say `(24,000)`. And the delta identity is invariant to a sign flip applied across a row's columns — negate `recommendation`, `prior`, and `estimate` together and `rec − prior == delta_vs_enacted` still holds exactly. This is not a hypothetical; it shipped in every release before this one (see [KNOWN_ISSUES #6](docs/KNOWN_ISSUES.md)).

The subtotal a committee sets in type is an **independent witness**. It is not derived from the columns we parsed, and it constrains the rows above it. Checking the line items against it is therefore the only gate here that can catch a wrong reading of the document — and it is also, not coincidentally, the check appropriations staff perform by hand: highlight the account rows, compare the sum to the recap.

`approps reconcile` (`verification.reconcile`) does this over the shipped release. Two design decisions carry it:

**Nesting is recovered from document order, not indentation.** Total rows are frequently typeset further right than the children they summarize, and the enacted explanatory statements flatten every account to depth 0. So each total consumes the shortest contiguous run of preceding unconsumed nodes that sums to it, and is then pushed back as a single node — letting a parent total roll up its child totals without ever consulting a depth label. A total that fails still consumes its block (the closest-summing run), so one bad total cannot cascade into every ancestor above it.

**Whether a memo is summed is decided by the total, not by the parentheses.** `is_memo` is treated as a hypothesis. For each total the reconciler sums the children both ways — memos excluded, then included — and lets the printed figure adjudicate, recording the verdict as `memo_mode`. Exclusion is tried first, as the documented convention. This is the same arithmetic double-gate the House indent recovery uses: a grouping is accepted because the sum closes, never because the shape looked right. It is necessary because the same parenthesized row can be additive at one level and non-add at the next — in `CRPT-114srpt68`, `Operating expenses 134,488` plus `(By transfer from Disaster Relief) (24,000)` is exactly the printed `Total, Office of Inspector General 158,488`, while `Total, title I` one line below excludes that same 24,000.

Crucially, this cannot launder a sign error: a row whose `(35,000)` was parsed as −35,000 is not flagged as a memo at all, so it is a mandatory child under both readings and the total still fails.

Totals are classified rather than merely passed or failed:

| Status | Meaning |
|---|---|
| `ok` | The children sum to the printed total, exactly, to the dollar |
| `off_by_small` | Missed by ≤2% — one line dropped or misread. Genuine |
| `partial_read` | A child carries amounts in other columns but not the primary one. Genuine |
| `overlapping_view` | An advance-appropriation or forward-funding total, which re-aggregates rows already counted under another view. **Not the sum of any contiguous block by construction** — unmeasurable, not an error |
| `unreconciled` | Children do not sum, and none of the above explains it |
| `unchecked` | The total printed a dot leader, so there is nothing to check against |

The **strict pass rate** excludes `overlapping_view`, and is the honest denominator: the share of totals a sum check can actually adjudicate.

| Track | Checkable | Tie exactly | Strict |
|---|---:|---:|---:|
| house | 10,532 | 74.8% | 76.5% |
| senate | 5,286 | 79.6% | 82.7% |
| enacted | 1,178 | 75.2% | 75.8% |
| **all** | **16,996** | **76.3%** | **78.4%** |

The unreconciled residual is documented in [KNOWN_ISSUES #19](docs/KNOWN_ISSUES.md).

A total that reconciles corroborates every line item beneath it. A total that does *not* reconcile is a review item, not a proven error — the reconciler infers nesting, and unusual table shapes defeat it.

### Handing the check to the reader

`approps workbook` writes one Excel file per report in which every total's `computed` cell is a live `=SUM()` over the exact cells that total consumed. Nothing is precomputed; Excel does the adding. Leaves and rollups occupy separate columns so a parent can sum its child subtotals without double-counting the leaves they already absorbed, and a memo the printed total did *not* endorse sits in no summable column at all — its exclusion is visible on the page rather than hidden in a filter. A staffer who distrusts the `check` column can select the leaf cells and read the sum off Excel's own status bar.

This is the point of the whole exercise. A parsed dataset earns adoption not by asserting that it verified itself, but by making its arithmetic cheap to re-perform with the tool already on the reader's desk.

## PDF parsing tools evaluated

| Tool | Result | Notes |
|------|--------|-------|
| **pdfplumber** | Used for page rendering and image detection | Cannot extract text from TIFF image pages in House reports. Word-level extraction only finds page metadata (page numbers, GPO footer). |
| **Tesseract OCR** | Rejected | Multiple PSM modes tested. PSM 12 produced some numbers but with severe noise and garbled item names. |
| **Marker** (VikParuchuri) | Rejected | Produced structured markdown tables but with unreliable column alignment. Better than Tesseract but not accurate enough for financial data. |
| **Tabula / Camelot** | Not applicable | These tools require table grid lines or a text layer. House comparative statements have neither. |
| **Gemini 3 Pro Preview** | Selected | Free tier (15 RPM, daily quota). 100% accuracy on manually verified page. Correct handling of emergency sub-rows and complex table layouts. |

## Known limitations

The authoritative, current list is [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md); the measured error rates are in [docs/ACCURACY_REVIEW.md](docs/ACCURACY_REVIEW.md).

1. **House PDF extraction is non-deterministic.** Vision model outputs may vary between runs. Cross-validation against inline tables mitigates this.

2. **Vision extraction is rate- and cost-bound.** The hybrid keeps the paid Gemini leg to the ~⅓ of pages the free Nemotron bulk pass can't self-verify; even so, large reports (Defense/THUD run hundreds of image pages) are throughput-limited by per-model quotas. See `docs/vision-model-eval-brief.md` for the measured cost profile.

3. **Heading detection for inline tables is heuristic.** The backward-search algorithm occasionally picks up a nearby heading from a different section, especially in House reports where heading styles vary.

4. **Account crosswalk coverage is partial, and a key is not proof of identity.** 20,881 rows carry a trusted `account_key`; the gate withholds keys it can show are wrong but cannot prove the rest right. See KNOWN_ISSUES #16.

5. **Only the comparative statement and PPA detail tables from image pages are extracted.** Vote roll call pages (which are also images in House PDFs) are processed but correctly return 0 items.

## Data dictionary

Every column of every release table is defined in [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md); the canonical types are the Pydantic schemas in `src/approps/output/schemas.py`.
