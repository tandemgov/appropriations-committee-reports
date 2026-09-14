# approps

Extract line-item appropriations data from Congressional committee reports into structured datasets.

## What this does

Congressional appropriations data is locked inside committee report PDFs and HTML documents. This tool extracts it into structured CSV/JSON, enabling longitudinal analysis of federal spending decisions.

> **Just want the data?** Download it from the [latest release](https://github.com/tandemgov/appropriations-committee-reports/releases/latest) — 116,393 rows, FY2016–FY2027, CC0. **Read [DATA.md](DATA.md) first:** 27% of rows have no check behind their amount, some table shapes are isolated, and the measured error rates are in [docs/ACCURACY_REVIEW.md](docs/ACCURACY_REVIEW.md). Filter before you cite a number.

**Extracted data includes:**
- Comparative statements of new budget authority (the dense multi-page tables at the back of each report showing every line item with prior year enacted, budget estimate, and committee recommendation)
- Inline narrative funding tables (the 3-line funding summaries throughout the report body)

**Coverage targets:**
- All 12 appropriations subcommittees in both chambers, in the years each chamber reported them
- Committee and enacted stages (subcommittee marks are not published as line-item statements)
- House committee FY2016–FY2027, Senate committee FY2016–FY2026 with gaps, enacted FY2016–FY2024

**Deliverables:** start with **[docs/DELIVERABLES.md](docs/DELIVERABLES.md)** (what was delivered and how to rebuild it), **[docs/COVERAGE.md](docs/COVERAGE.md)** (stage × chamber × subcommittee × fiscal year), **[docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md)** (every column), **[docs/ACCURACY_REVIEW.md](docs/ACCURACY_REVIEW.md)** (measured accuracy), and **[docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)**.

## Architecture

```
GovInfo (HTML/PDF) → Discovery → Download → Extraction → Verification → Output (CSV/JSON)
                                                                          ↓
                                                                     FastAPI (/api)
```

### Extraction approaches by data source

| Source | Format | Method | Primary gate |
|--------|--------|--------|----------|
| Senate comparative statements | Text in HTML | Deterministic fixed-width parser | String match |
| Inline narrative tables (both chambers) | Text in HTML | Regex-based extraction | String match |
| House comparative statements | TIFF images in PDF | Hybrid: Nemotron-Parse bulk + Gemini cleanup | Delta-arithmetic gate |
| House typeset committee prints | Born-digital PDF text | Deterministic text parser | Reconciles to RECAPITULATION totals |
| Enacted line items | Born-digital PDF text (CPRT) | Regex parser | Verbatim on page |

The gate is not the accuracy. A string match proves an amount was *transcribed*; it says nothing about whether it landed in the right column, and every defect in [KNOWN_ISSUES](docs/KNOWN_ISSUES.md) passed its gate. Measured accuracy is in [docs/ACCURACY_REVIEW.md](docs/ACCURACY_REVIEW.md). Only [reconciliation](#reconciliation--the-gate-that-checks-the-others) checks a row against something other than itself.

### Key finding

Senate reports embed comparative statement tables as **text** in the HTML. House reports embed them as **images** (TIFF graphics). This architectural difference drives the two-track extraction strategy.

## Quick start

```bash
# Install
uv sync

# Extract a local Senate report (no API keys needed)
approps extract-file report.htm -c senate --fy 2024 --csv

# Extract a House report (needs Gemini API key for comparative statements)
approps extract-file report.htm -c house --fy 2025 --csv

# Rebuild the release from extracted data (see docs/DELIVERABLES.md)
approps output
python scripts/build_release.py

# Start the API server
approps serve
```

## Configuration

Copy `.env.example` to `.env` and set:

```bash
# Required for House PDF extraction (free: https://aistudio.google.com/apikey)
GEMINI_API_KEY=your-key

# Optional: for GovInfo discovery at scale (free: https://api.data.gov/signup/)
GOVINFO_API_KEY=your-key
```

## CLI commands

| Command | Description |
|---------|-------------|
| `approps discover` | Find appropriations reports on GovInfo |
| `approps download` | Download report HTML/PDF |
| `approps extract` | Extract data from downloaded reports |
| `approps extract-file <path>` | Extract from a local file (no catalog needed) |
| `approps extract-house-pdf <path>` | Extract House comparative tables from a local PDF (vision) |
| `approps verify` | Run verification checks |
| `approps reconcile` | Check that line items sum to the totals the reports printed |
| `approps workbook` | Write per-report Excel workbooks that prove the sums, with live formulas |
| `approps crosswalk` | Build the authoritative account crosswalk + human-review queue |
| `approps trace` | Follow crosswalk-keyed accounts across fiscal years; report title changes |
| `approps output` | Generate combined CSV/JSON datasets |
| `approps serve` | Start the FastAPI server |
| `approps status` | Show pipeline status |

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/reports` | List reports (filterable by congress, chamber, subcommittee, fiscal year) |
| `GET /api/reports/{id}` | Report metadata |
| `GET /api/reports/{id}/line_items` | Extracted line items for a report |
| `GET /api/line_items` | Query line items across all reports |
| `GET /api/line_items/compare` | One account's totals across fiscal years, one series per chamber and stage (`account_key` required; `real=true` deflates each point from its price year and fails for years without a deflator) |
| `GET /api/accounts` | Cross-year account authorities; filter to `changed_only`/`kind=reword` for rename candidates |
| `GET /api/accounts/{account_key}/history` | One account followed through time: money series (a year two reports both claim is a `conflict` with no amount), label timeline, title changes |
| `POST /api/parse_report` | On-demand extraction (stub) |

## Project structure

```
src/approps/
├── cli.py                      # Click CLI
├── config.py                   # Settings
├── discovery/                  # GovInfo API client, report catalog, subcommittee classifier
├── download/                   # HTML/PDF fetcher with caching
├── extraction/
│   ├── dollar_parser.py        # Parse all dollar amount formats
│   ├── inline_tables.py        # Regex extraction of narrative funding tables
│   ├── comparative_senate.py   # Fixed-width text parser for Senate tables
│   ├── comparative_house.py    # Vision extraction for House PDF tables
│   ├── comparative_house_text.py # Deterministic parser for born-digital House prints
│   ├── comparative_enacted.py  # Enacted-stage parser (CPRT explanatory statements)
│   ├── nemotron_parse.py       # Nemotron-Parse client (self-hosted vision bulk pass)
│   ├── hybrid.py               # Nemotron bulk + Gemini cleanup on suspect pages
│   └── hierarchy.py            # Hierarchy detection (Title/Dept/Agency/Account)
├── verification/
│   ├── amount_verifier.py      # Three-tier string matching (exact/normalized/spaceless)
│   ├── reconcile.py            # Line items vs the totals the committee printed
│   ├── reconcile_source.py     # Loads the shipped release into the reconciler
│   ├── cross_check.py          # Per-row delta identities
│   └── audit_report.py         # Verification summary statistics
├── normalization/              # Account crosswalk (USASpending-anchored), CPI-U inflation, account-name hygiene
│   ├── account_gate.py         # Withholds account keys that fail jurisdiction/label checks
│   ├── account_totals.py       # One total per report and account: the titled account line, or none
│   ├── column_shift.py         # Repairs column layouts the rows' own arithmetic proves
│   ├── report_metadata.py      # Fills fiscal year / subcommittee from the report catalog
│   └── account_authority.py    # Cross-year account tracing: money series, label timeline, title changes
├── output/
│   ├── schemas.py              # Pydantic models for all data types
│   ├── csv_writer.py           # Output table: enrichment, layout isolation, sidecar
│   ├── xlsx_writer.py          # Per-report Excel workbooks with live =SUM() proofs
│   └── metadata.py             # Provenance tracking
└── api/                        # FastAPI application
```

## Verification methodology

Amounts on text-based tracks are checked against the source text using three-tier string matching (modeled after [cgorski/congress-appropriations](https://github.com/cgorski/congress-appropriations)):

1. **Exact match**: raw extracted text appears verbatim in source
2. **Normalized match**: after collapsing whitespace
3. **Spaceless match**: after removing all whitespace

Each track has one primary gate, and `verification_tier` names it per row: Senate and inline extractions verify by `string_match`; House vision extractions by `delta_arithmetic` (the two derived delta columns cross-check all four value columns at once); enacted statements and House typeset prints by `verbatim_page`. See [docs/DELIVERABLES.md](docs/DELIVERABLES.md#what-verified-means) for the full semantics.

### Reconciliation — the gate that checks the others

Every check above compares a row to *itself* or to the string it came from, so none of them can catch a misreading of the source's conventions. A string match still passes when `(24,000)` is transcribed perfectly and then interpreted as −24,000. The delta identity still closes when a row's columns are all negated together.

The printed subtotal is an independent witness. `approps reconcile` checks the line items against it, which is also the check appropriations staff perform by hand:

```bash
approps reconcile                       # corpus report + review queue
approps reconcile -p CRPT-118srpt83     # every printed total in one report
approps reconcile --fail-under 0.75     # release gate; exits non-zero below the bar
approps workbook -p CRPT-118srpt83      # an .xlsx a staffer can audit in Excel
```

This gate found a sign defect that had shipped in every prior release, on 9,629 Senate amounts that were all marked `verified` at the strongest tier. See [DATA.md](DATA.md#correction--senate-parentheses).

## Current results

**246 reports, 116,393 comparative-statement rows (85,045 with a verification tier), 13,853 inline funding records**, committee (both chambers) and enacted stages, FY2016–FY2027. Full matrix in **[docs/COVERAGE.md](docs/COVERAGE.md)**.

| Track | Reports | Rows | Primary gate | Rows passing it | Printed totals that reconcile¹ | Accuracy review² |
|---|---:|---:|---|---:|---:|---|
| Senate committee (HTML text) | 87 | 29,105 | `string_match` | 27,163 | 82.7% | 96.5% rows found · 98.4% right column |
| House committee (scanned + typeset) | 143 | 74,479 | `delta_arithmetic` / `verbatim_page` | 38,736 | 76.5% | 97.8% rows found · 99.7% right column |
| Enacted (explanatory statements) | 16 | 12,809 | `verbatim_page` | 12,761 | 75.8% | 97.7% rows found · 100% right column |

¹ `approps reconcile`, strict rate — the share of printed subtotals whose line items sum to them exactly, excluding advance-appropriation views. Unreconciled totals are documented in KNOWN_ISSUES #19.
² Blind transcription of sampled source pages compared cell by cell; small samples, see [docs/ACCURACY_REVIEW.md](docs/ACCURACY_REVIEW.md).

## Related work

This project extracts what the committee **reports** and explanatory statements say. That is a different document, at a finer granularity, than what the enacted **bill** says — which is the axis that separates it from the nearest comparable efforts.

**[cgorski/congress-appropriations](https://github.com/cgorski/congress-appropriations)** is the closest neighbor, and a natural complement rather than a competitor. It extracts spending provisions from enrolled-bill XML (Congress.gov) at the enacted stage using an LLM, and it resolves provisions to Treasury Account Symbols with cross-year tracing. Because it reads born-structured bill XML, it never touches PDFs or images — and the program/project/activity (PPA) allocations that live only in committee comparative statements and joint explanatory statements are outside its source set. This project covers exactly that: the committee stage in both chambers, plus the enacted explanatory statements, including the House comparative-statement tables that are published as **images** rather than text. (The three-tier amount verification here is modeled after cgorski's approach — see [Verification methodology](#verification-methodology).) His cross-year account tracing (grouping by the account symbol so a rename is visible as a label change under a stable code) has an analogue here in `approps trace` / `GET /api/accounts`, keyed on the authoritative crosswalk code.

The broader landscape sits at coarser granularity or a different source:

- **[USASpending](https://api.usaspending.gov/) / Treasury** — authoritative *execution-side* data (Treasury accounts, object class, agency-reported program activity), derived from agency accounting submissions, not appropriations documents. This project anchors its account crosswalk to USASpending federal-account codes.
- **[unitedstates/congress](https://github.com/unitedstates/congress), GovTrack, GPO bulk data** — bill, vote, and status metadata; no dollar-figure extraction.
- **[CRS Appropriations Status Table](https://www.congress.gov/crs-appropriations-status-table)** — a navigation index to the documents by stage; extracts no figures.
- **[Policy Agendas / Comparative Agendas](https://www.comparativeagendas.net/project/us/datasets)** — an academic budget-authority series at OMB budget-function level, far coarser than account or line item.

No released, open dataset was found that extracts program/line-item detail from the House and Senate comparative statements and explanatory statements — specifically, nothing that handles the House image-based tables. That combination appears to be rare-to-unique among public efforts. (Absence of evidence is not proof: unpublished or non-indexed efforts may exist.)

## Development

```bash
uv sync --all-extras
uv run pytest tests/
uv run ruff check src/ tests/
```
