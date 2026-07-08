# approps

Extract line-item appropriations data from Congressional committee reports into structured datasets.

## What this does

Congressional appropriations data is locked inside committee report PDFs and HTML documents. This tool extracts it into structured CSV/JSON, enabling longitudinal analysis of federal spending decisions.

**Extracted data includes:**
- Comparative statements of new budget authority (the dense multi-page tables at the back of each report showing every line item with prior year enacted, budget estimate, and committee recommendation)
- Inline narrative funding tables (the 3-line funding summaries throughout the report body)

**Coverage targets:**
- All 12 appropriations subcommittees in both chambers
- Committee and enactment stages (subcommittee marks are rarely published separately)
- 12 fiscal years (FY2016–FY2027)

**Deliverables:** start with **[docs/DELIVERABLES.md](docs/DELIVERABLES.md)** (what each dataset is and how it was verified), **[docs/COVERAGE.md](docs/COVERAGE.md)** (the stage × chamber × fiscal-year matrix), and **[docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md)** (per-field schema).

## Architecture

```
GovInfo (HTML/PDF) → Discovery → Download → Extraction → Verification → Output (CSV/JSON)
                                                                          ↓
                                                                     FastAPI (/api)
```

### Extraction approaches by data source

| Source | Format | Method | Accuracy |
|--------|--------|--------|----------|
| Senate comparative statements | Text in HTML | Deterministic fixed-width parser | 100% string-match |
| Inline narrative tables (both chambers) | Text in HTML | Regex-based extraction | 100% string-match |
| House comparative statements | TIFF images in PDF | Hybrid: Nemotron-Parse bulk + Gemini cleanup | Delta-arithmetic gate |
| House typeset committee prints | Born-digital PDF text | Deterministic text parser | Reconciles to RECAPITULATION totals |
| Enacted line items | Born-digital PDF text (CPRT) | Regex parser, self-verifying | 100% verbatim-on-page |

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

# Run verification
approps verify --all

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
| `GET /api/line_items/compare` | Longitudinal comparison: one account's money across fiscal years |
| `GET /api/accounts` | Cross-year account authorities; filter to `changed_only`/`kind=reword` for rename candidates |
| `GET /api/accounts/{account_key}/history` | One account followed through time: money series, label timeline, title changes |
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
│   ├── cross_check.py          # Subtotal arithmetic validation
│   └── audit_report.py         # Verification summary statistics
├── normalization/              # Account crosswalk (USASpending-anchored), CPI-U inflation, account-name hygiene
│   └── account_authority.py    # Cross-year account tracing: money series, label timeline, title changes
├── output/
│   ├── schemas.py              # Pydantic models for all data types
│   ├── csv_writer.py           # CSV generation
│   └── metadata.py             # Provenance tracking
└── api/                        # FastAPI application
```

## Verification methodology

Every extracted dollar amount is verified against the source text using three-tier string matching (modeled after [cgorski/congress-appropriations](https://github.com/cgorski/congress-appropriations)):

1. **Exact match**: raw extracted text appears verbatim in source
2. **Normalized match**: after collapsing whitespace
3. **Spaceless match**: after removing all whitespace

Senate and inline extractions verify by string match; House vision extractions verify by a delta-arithmetic gate (the two derived delta columns cross-check all four value columns at once); enacted lines self-verify (each amount must appear verbatim on its source page). See [docs/DELIVERABLES.md](docs/DELIVERABLES.md#what-verified-means) for the full semantics.

## Current results

**246 report-stages, 109,052 comparative line items (74,453 delta-verified), 13,853 inline funding records**, spanning committee (both chambers) and enacted stages, FY2016–FY2027. Full breakdown by stage × chamber × fiscal year in **[docs/COVERAGE.md](docs/COVERAGE.md)**.

| Stage | Reports | Rows | Delta-verified |
|---|---:|---:|---:|
| Senate committee (HTML text) | 87 | 28,873 | 26,792 |
| House committee (vision + typeset text) | 143 | 68,350 | 35,832 |
| Enacted (House CPRT explanatory statements) | 16 | 11,829 | 11,829 |

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
uv run pytest tests/ -v
uv run ruff check src/ tests/
```
