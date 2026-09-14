# Deliverables

The front door for the appropriations extraction handoff: what was delivered, how it was produced and checked, where its limits are, and how to rebuild it.

## The release

The canonical deliverable is the release directory built by `scripts/build_release.py` (`data/release/`, published as a GitHub release).
Everything in it comes from one snapshot of the extracted data, and `manifest.json` says which.

| Table | Rows | What it is |
|---|---:|---|
| `comparative_statements` | 116,393 | Every line of the committee reports' comparative statements and the enacted explanatory statements' tables, with normalization and trust columns. |
| `account_year_totals` | 9,974 | One total per report and account, for longitudinal analysis. |
| `account_title_changes` | 701 | Account relabelings across years. |
| `nonstandard_layout_rows` | 3,026 | Values emptied from rows whose columns cannot be trusted. |
| `inline_funding_tables` | 13,853 | Funding summaries from report prose (a second, independent extraction). |
| `manifest.json`, `SHA256SUMS` | — | Revision, source snapshot, counts, release checks, file hashes. |

Each table is CSV, Parquet, and JSON.
The per-column schema is [DATA_DICTIONARY.md](DATA_DICTIONARY.md); coverage is [COVERAGE.md](COVERAGE.md); measured accuracy is [ACCURACY_REVIEW.md](ACCURACY_REVIEW.md); defects are [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

`data/output/fy2027-house-defense/` is a separate earlier deliverable from the FY2027 Defense full-committee print, superseded in the release by the committee report `CRPT-119hrpt715`.
`data/reference/account_crosswalk.csv` (from `approps crosswalk`) is the account-matching review queue, not a release table.

## How it was produced

| Track | Source | Method | Primary check |
|---|---|---|---|
| Senate committee | Fixed-width text in the report HTML | Deterministic parser | Every amount string-matched in the source |
| House committee, scanned | Table images in the report PDF | Nemotron-Parse bulk pass; Gemini re-reads pages whose arithmetic fails | Row delta identities close |
| House committee, typeset | PDF text layer | Deterministic parser | Amount verbatim on its page |
| Enacted | Explanatory-statement PDF text (House Rules Committee prints) | Deterministic parser | Amount verbatim on its page |

`approps output` then fills report metadata, repairs column layouts the rows prove, withholds wrong account keys, isolates nonstandard layouts, and writes the tables; `scripts/build_release.py` derives the account tables, writes the three formats, and runs the release checks.
Method detail and rationale are in [../METHODOLOGY.md](../METHODOLOGY.md).

## What the checks establish

The primary checks prove **transcription**: a figure is in the source, or a row's arithmetic is consistent.
They do not prove **interpretation** — that a figure sits in the right column, on the right line, with the right sign.
Every defect fixed in this project's history passed its primary check.

Two further witnesses look outside the row: `approps reconcile` checks rows against the subtotals the committee printed (78.4% of checkable totals reconcile strictly), and the bounded accuracy review compares complete source pages with the release cell by cell.
Report both kinds of number, and do not describe the data as verified without saying which check.

## Boundaries

- **Stages:** committee and enacted only; there is no separately published subcommittee line-item stage. Enacted covers FY2016–FY2024.
- **Gaps:** see [COVERAGE.md](COVERAGE.md) for every missing report and why.
- **Completeness:** the review found 2–3.5% of source rows missing per track on its sampled pages; some table shapes are skipped by design (Defense program-adjustment explanations, 302(b) and outlay tables).
- **Account identity:** 22,852 rows carry a key. It is conservative, not guaranteed.
- **Account totals:** 3,307 of 9,974 are unresolved and carry no figure.
- **Not reconciled:** 3,576 printed totals do not reconcile ([KNOWN_ISSUES #19](KNOWN_ISSUES.md)); they were documented, not pursued.
- **Real dollars:** no deflator for FY2026–27.

## Regenerating

### Rebuild the release from extracted data

This is the reproducible path, and the one tested in a clean checkout.
It needs the extracted report files (`data/extracted/`, not in git; hash recorded in the manifest), no API keys, and a few minutes.

```bash
uv sync --all-extras
uv run pytest
uv run approps output
uv run python scripts/build_release.py      # fails if any release check fails
uv run approps reconcile --fail-under 0.75
```

Run the build from a clean git tree; the manifest records the revision and flags a dirty one.

### Re-extract from source documents

```bash
uv run approps discover                           # GovInfo catalog (GOVINFO_API_KEY)
uv run approps download --all                     # report HTML and PDF
uv run approps download --all --stage enacted     # explanatory-statement prints
uv run approps extract --all --chamber senate     # deterministic
uv run approps extract --all --stage enacted      # deterministic
uv run approps extract --all --chamber house      # scanned pages need a vision backend
uv run approps verify --all                       # re-run after ANY re-extraction: it restores string-match flags
uv run python scripts/repair_corpus.py            # re-run after any re-extraction
```

House scanned pages need `VISION_BACKEND=hybrid` with a Nemotron-Parse server and `GEMINI_API_KEY` (or `GEMINI_VERTEX=1`), and the House delta gate and page repairs run through `scripts/verify_house.py` and `scripts/repair_dropped_pages.py`.
Vision output is not deterministic, so a House re-extraction will not reproduce this release exactly; that is why the manifest hashes the extracted snapshot.
Re-extraction resets verification flags that `verify` persists; `approps output` warns when a track's verified share collapses, and the release build refuses it.
