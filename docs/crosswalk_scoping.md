# Account-name crosswalk — scoping

**Status:** design rationale. The crosswalk scoped here has since been built (`src/approps/normalization/crosswalk.py`, anchored to USASpending federal-account codes); this document records the original scoping analysis and its keystone finding — that naive normalization/fuzzy-matching is *unsafe* because it conflates distinct accounts, so identity must be anchored to authoritative codes. Grounded in the FY2016–FY2025 combined dataset (`data/output/comparative_statements.csv`, 41,943 rows) as of 2026-06-18.

## Why this is the keystone

Everything extracted so far is keyed to its own report. The same appropriations account appears with different text across fiscal years, chambers, and stages, so there is no stable identity to track it by. Until that identity exists, the dataset is a stack of independent tables — you cannot answer "how did funding for account X move FY2016→FY2025?" or "House proposed vs Senate proposed vs enacted for account X?". The crosswalk is what converts "we extracted everything" into "you can analyze federal spending longitudinally." It is SOW deliverable #5 and the prerequisite for cross-stage/cross-chamber comparison (#2 in the gap analysis).

## What the data actually looks like

Tracing real accounts across years/stages (e.g. *International Disaster Assistance*, *NIST Manufacturing Extension Partnership*, the multilateral development banks) shows the matcher's adversaries, in rough order of difficulty:

1. **Case / punctuation / whitespace drift** — `International disaster assistance` ↔ `International Disaster Assistance`. Trivial.
2. **Designation suffixes** — `[OCO]`, `(OCO)`, `(emergency)`, `, Base`, `, Emergency`. These are *semantically meaningful* sub-splits (base vs Overseas Contingency Operations vs emergency vs disaster), not noise. They need a deliberate decision, not blind stripping.
3. **Inconsistent hierarchy across stages** — committee rows carry `agency`/`account`/`program`; enacted rows carry `division`/`account`/`program` with **no agency** (department/agency 0% filled on enacted). House committee rows have **blank `account`** (the vision extraction did not capture hierarchy), so House can only be matched on `line_item_text`.
4. **Extraction-quality pollution** (the part that makes naive matching dangerous):
   - **Number leakage** — dollar columns bleeding into the label: `international narcotics control and law enforcement 300 000`, `international chancery center ... 1 320 743 743 577`.
   - **Line-wrap fragments** — multi-line account names split into junk rows: `operations)`, `relief, and mitigation)`, `appropriation)`. ~3.9% of Senate committee account rows.

### Quantification

| Measure | Value |
|---|---|
| Senate committee distinct `account` strings | 4,432 |
| …after deterministic normalization (lowercase, strip parentheticals + designations) | 3,288 (**26% collapse**) |
| …further greedy fuzzy clustering, one subcommittee (State-Foreign-Ops) | only 16% additional collapse |
| Fragment-like account rows (line-wrap artifacts) | 3.9% |
| Enacted distinct programs | ~4,500 |

## Why the naive approaches fail

- **Deterministic normalization alone** collapses only ~26%. The same account still differs after lowercasing/punctuation because of wording drift, OCR, and fragments. Insufficient for clean identity.
- **Fuzzy string clustering over-merges genuinely distinct accounts.** A 0.88-similarity pass merged *African Development Bank*, *Asian Development Bank*, *African Development Fund*, and *Asian Development Fund* into one cluster, and the four `... paid in capital` bank accounts likewise. These are textually near-identical but are four different Treasury accounts. Number leakage corrupts the strings further. **A fuzzy-match script would silently conflate distinct accounts and quietly corrupt the longitudinal series** — the opposite of what the project values (verified correctness).

**Conclusion:** the right key is not a synthetic string cluster — it is an *authoritative account identity*.

## Recommended design — layered, anchored to authoritative account codes

A pipeline, conservative by default, with the authoritative anchor as the source of truth:

- **Layer 0 — hygiene.** Quarantine/flag fragment and number-leaked rows; exclude subtotals from the entity set. (Better: fix line-wrap + number-leakage in extraction first — see Dependencies.)
- **Layer 1 — canonicalize.** Lowercase, strip punctuation, normalize known abbreviations; split designations (`base`/`OCO`/`emergency`/`disaster`/`CHIMP`) into a separate `designation` field rather than into the key. Scope candidates within `(subcommittee, agency)` where available.
- **Layer 2 — cluster as *candidates only*.** Within `(subcommittee[, agency])`, propose variant clusters across years — but treat them as review candidates, never auto-merged, given the Dev-Bank over-merge risk.
- **Layer 3 — authoritative anchor (the source of truth).** Map each account to an external **OMB / Treasury account identity** — the Budget Appendix "Account Identification Code" / Treasury Account Symbol (TAS), available via OMB's Public Budget Database, the President's Budget Appendix, or USASpending. This gives a real, unambiguous, externally-joinable longitudinal key (and resolves African vs Asian Development Bank correctly). Mapping our ~1,000–1,500 distinct accounts to codes is semi-automatable (text match to the official account list) + LLM-assisted for the long tail + human review. This is the bulk of the effort and the bulk of the value.

The deliverable is a `crosswalk` table: `account_key` (authoritative code) ← every `(report_id, line)` occurrence, plus `designation`, plus a confidence/method column and a `needs_review` flag for the long tail.

## Dependencies / prerequisites

1. **Extraction cleanup** — number leakage and line-wrap fragments (~4%+) pollute the account strings. The crosswalk should flag these, but fixing them upstream (Senate comparative + House vision hierarchy) materially improves match rates. This is a real prerequisite, not optional polish.
2. **House hierarchy** — House committee `account` is blank; either back-fill account from the vision extraction or match House on `line_item_text` only (lower confidence).
3. **An authoritative account reference** must be sourced and loaded (OMB Public Budget Database / Budget Appendix / USASpending TAS list). Feasibility check is the first task of any build.

## Decisions needed before building

- **A. Key granularity** — anchor at the **Treasury/OMB account** level (recommended: the stable longitudinal unit) vs the noisier program/PPA level. Program stays as a secondary attribute.
- **B. Designations** — base/OCO/emergency/disaster as a **separate dimension** on a shared `account_key` (recommended) vs distinct accounts.
- **C. Authoritative anchor vs self-contained clusters** — anchoring to OMB/TAS codes is far more valuable (external joins, unambiguous identity, correct on the Dev-Bank case) but is the larger effort. Self-contained clustering is faster but gives synthetic keys meaningful only inside this dataset *and* carries the over-merge risk. **Recommend anchoring.**
- **D. Extraction cleanup first?** — whether to fix number-leakage/line-wrap in extraction before the crosswalk, or quarantine and proceed.
- **E. Subcommittee stage (SOW #3)** — separate gap; decide build vs descope (subcommittee marks rarely produce table-bearing documents).

## Phased plan (recommended)

1. **Feasibility spike (small).** Source the authoritative account list (OMB Public Budget DB / TAS); confirm we can match our account text to it; measure auto-match rate on one subcommittee. Decide go/no-go on anchoring.
2. **Extraction cleanup (small–medium).** Strip number leakage; repair line-wrap fragments in the Senate comparative + enacted parsers. Re-run, re-verify.
3. **Crosswalk build (medium–large).** Layers 0–3 over all subcommittees; produce the crosswalk table + a human-review queue for the long tail and all auto-merged candidates.
4. **Wire in (small).** Add `account_key`/`designation` columns to the combined output; enable cross-stage/cross-chamber joins and (with the deflator) inflation-adjusted longitudinal series.

**Bottom line:** this is the largest single remaining piece, and it is a data-engineering + reference-data effort, not a quick script. The non-obvious finding from scoping is that naive normalization/fuzzy-matching is *unsafe* here (it conflates distinct accounts), so the defensible path is anchoring to authoritative account codes with human review — preceded by a feasibility spike and a round of extraction cleanup.
