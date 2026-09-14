# Known issues

Tracked data-quality issues: what is wrong, how it was found, what was done, and what remains.
Fixed and repaired issues stay listed because releases before the fix carry the defect.
Open issues are isolated in the release where a signature exists, and documented where one does not (#3, #19).

---

## 1. Category-split tables mis-mapped into the standard column schema

**Status:** isolated (`column_layout = category_split`; the four mislabeled columns are emptied in the release and kept in `nonstandard_layout_rows`), proper fix deferred.
**Scope:** 301 rows across ~13 reports — chiefly **Energy-Water** (Bureau of Reclamation /
Corps of Engineers "Water and Related Resources" tables); a handful in Labor-HHS, Interior,
Agriculture, State-Foreign-Ops, THUD.

### What's wrong
These tables do **not** use the standard comparative-statement shape (prior-year enacted /
budget request / committee recommendation / two deltas). Instead each line's appropriation is
**split across two or more funding-category columns that sum to the line total** — there is no
prior-year column. Example (CRPT-114hrpt532, p66, Bureau of Reclamation):

```
SALT RIVER PROJECT     cat1=649   cat2=250   total=899
```

The vision/parser force-fit that into the standard schema, producing:
`prior_year_enacted = 649` (really category 1), `budget_estimate = 250` (really category 2),
`committee_recommendation = 899` (correct total), and delta columns that merely **echo** the
two categories. The verification gate correctly marks these `verified = false` (the delta
identity can't hold), but three columns still carry confidently-wrong labels.

### Detection (already shipped)
`approps.output.csv_writer._column_layout` flags a row `category_split` when
`prior + budget_estimate == committee_recommendation` **and** the deltas echo those two
columns (`delta_vs_enacted == prior_year_enacted`, `delta_vs_estimate == budget_estimate`).
A genuine comparative row essentially never satisfies all of these, so the flag is precise.
**Today:** `committee_recommendation` on these rows is trustworthy; `prior_year_enacted`,
`budget_estimate`, and both deltas are not — filter with `column_layout = 'standard'` for the
strictly-comparable subset.

### Proper fix (this issue)
Re-extract the category-split tables with layout-aware column semantics rather than assuming
the five-column comparative shape:
- Detect the layout at extraction time (from the source table header / column count), not just
  post-hoc from the values.
- Represent N funding categories faithfully — the current comparative schema has no slot for
  "category 1 / category 2 …", so this needs either a small schema extension (e.g. a
  `categories` sub-structure or a long-format companion table keyed by `report_id` + line) or a
  dedicated output for these tables.
- Preserve the category breakdown (it is real data, just unschema-able today) and stop
  populating `prior_year_enacted` / `budget_estimate` / deltas with category values.
- Backfill the flagged ~297 rows and re-verify.

---

## 2. Defense procurement quantity-column tables mis-mapped

**Status:** partially isolated (`column_layout = procurement_qty` on the clearest instances, all amounts emptied in the release), proper fix deferred.
**Scope:** Defense procurement tables (`CRPT-116hrpt453` and other Defense reports). 197 rows
carry the unmistakable signature; the true extent is larger (named rows with scattered
columns are not yet flagged).

### What's wrong
Defense procurement statements are *wide*: each line has **quantity + amount pairs** (prior
qty, prior $, request qty, request $, recommended qty, recommended $) plus an item number.
The five-column comparative parser can't map that shape, so it (a) **drops the program name**
— the row's label becomes the bare procurement **line-item number** (`29`, `30`, `31`) — and
(b) scatters the amounts into the wrong columns. Example (CRPT-116hrpt453, p164):

```
30    request=12,938   delta_vs_enacted=12,338     (name gone; rec column empty; values shifted)
```

### Detection (partial, shipped)
A row whose `line_item_text` is a bare 1–3 digit number is flagged `column_layout =
procurement_qty` — a real appropriations line is never labelled just "30". This catches the
name-lost rows precisely (~185); rows that kept their name but have shifted columns are not
yet caught.

### Proper fix (this issue)
Detect the quantity-column layout at extraction time (from the table header / an odd column
count) and parse the quantity+amount pairs into their own fields, keeping the program names.
Needs quantity-aware extraction + a schema slot for procurement quantities.

---

## 3. Supplemental / emergency tables — inconsistent amount column

**Status:** not flagged (would over-flag; emergency rows are already findable via
`designation = emergency`). Proper fix deferred.
**Scope:** the CARES-Act / emergency / disaster-relief supplemental blocks in several bills
(Defense, THUD, Homeland, Energy-Water). ~1,000+ emergency rows; the drifted subset is smaller.

### What's wrong
In supplemental/emergency blocks the amount lands **inconsistently** — in
`committee_recommendation` for some rows and `delta_vs_enacted` for others *within the same
table*. Example (CRPT-116hrpt453, p447):

```
Operation and Maintenance, Army (emergency)     committee_recommendation = -160,300
Operation and Maintenance, Marine (emergency)   delta_vs_enacted        = -90,000   <- wrong column
```

### Why it isn't flagged today
The obvious signature — `(emergency)` in the label — matches ~1,161 rows across many bills,
but most are correctly extracted emergency-*designated* lines, not drifted ones (and
`designation = emergency` already identifies them). Flagging all of them would over-claim a
column bug. A precise flag needs section-aware detection (identify the supplemental block,
then check for the column inconsistency).

### Proper fix (this issue)
Detect supplemental/emergency blocks as a section and normalize the amount into a single
consistent column, or extract them with a layout-aware parser; then re-verify.

---

## 4. Enacted-stage amounts were 1000x too large — FIXED

**Status:** **fixed.** The 16 CPRT prints were re-extracted; the row set is unchanged (11,829).
**Scope (was):** **4,922 of the 11,829 `stage = enacted` rows (41.6%)** across 16 CPRT prints. The
other 6,907 sat on pages that genuinely *were* in thousands, where the x1000 happened to be right.

The original diagnosis said "every enacted row", inferred from finding no unit header in the first
40 pages of four prints. That was wrong: headers do exist, deep in the documents (pages 258+, 407+,
1022+) and in spellings the regex did not recognize. The defect was real; its scope was 41.6%, not
100%. The lesson is the obvious one — a scope claim from a first-40-pages sample is a guess, and
should have been labelled one.

### What's wrong
`comparative_enacted.py` sets `in_thousands = True` as a per-page default and only corrects it
when a `[In thousands of dollars]`-style marker line is matched:

```python
in_thousands = True                            # per-page default
...
if _THOUSANDS.search(s) and len(s) < 45:
    in_thousands = "thousand" in s.lower()     # only runs when a marker is found
```

Note the second line can only ever assign `True` — `_THOUSANDS` matches "in thousands of dollars",
so `"thousand" in s.lower()` is necessarily true when it is reached. `in_thousands` had **no path to
`False` at all**.

These prints mix both conventions. 7,065 of their 11,987 extracted amounts (59%) sit on pages
carrying a unit header and genuinely are in thousands; the remaining 4,922 (41%) sit on unmarked
pages and are whole dollars. With the default at `True`, that 41% was multiplied by 1,000.

| Source `raw_text` | Stored `value` | Should be |
|---|---|---|
| `$5,250,000` | `5,250,000,000` | `5,250,000` |
| `$615,847,000` | `615,847,000,000` | `615,847,000` |
| `32,386,831,000` (division total) | `32,386,831,000,000` | `32,386,831,000` |

The last implies a $32.4 *trillion* division total — roughly 5x the entire federal budget.

### Why verification didn't catch it
**Delta arithmetic is scale-invariant.** Multiply `prior`, `estimate`, and `recommendation` by
the same constant and `recommendation - prior == delta_vs_enacted` still holds. So every one of
these rows is `verified = True` at `verification_tier = delta` — the *strongest* tier — and
passes the `column_layout = 'standard'` filter. This is a structural gap, not a one-off: the
delta gate cannot detect a uniform scale error, and needs pairing with a magnitude sanity check
(no single line item should exceed total discretionary budget authority for its year).

### Not affected
The committee track is correct. Senate comparative statements do carry the `[In thousands]`
marker, and a raw `6,030` correctly becomes `6030000` (780 sampled amounts scaled, 0 unscaled).

### What was done
- `in_thousands` now defaults to `False` per page. Scaling requires positive evidence — a unit
  header on the page. The failure mode of the old default was silent and 1000x; the failure mode
  of this one is a visibly-too-small number.
- **The unit header is spelled fourteen different ways** across these prints — `[In thousands of
  dollars]`, `(Dollars in thousands)`, `[$ in thousands]`, `(Amounts in thousands)`,
  `[Budget authority in thousands of dollars]`, … The old regex recognized only the "in thousands
  of dollars" family. Defaulting to `True` had hidden that gap; flipping the default exposed it,
  and unfixed it would have under-scaled the USDA and NRC tables by 1000x in the other direction.
  `_THOUSANDS` now matches a bracketed span containing "thousand", anchored on the opening bracket
  so `(6) Budget year dollars in thousands` and a bare `thousands);` cannot masquerade as headers.
- Re-extracted all 16 CPRT prints. **Row set identical (11,829); every `raw_text` identical;
  4,922 amounts divided by 1,000; 7,065 correctly left alone; zero other changes.**
- Regression tests in `tests/test_enacted.py` pin every real header spelling, the lookalikes that
  must not match, and `$5,051 -> 5_051_000` / `32,386,831,000 -> 32_386_831_000`.
- Added `approps.verification.magnitude`, run by `approps output`: no line item may exceed a $3T
  plausibility ceiling. It found 11 rows on the broken data and finds 0 now. It is a coarse
  backstop — blind to a 1000x rescale of a small line — and the module documents two smarter
  checks that were tried and rejected for being confounded.

---

## 5. Two-column table detection is keyed to one header spelling (latent)

**Status:** latent hazard, not a live defect. Documented so it is not "fixed" by accident.
**Scope:** `comparative_enacted.py`, the Defense "Budget Request | Final Bill" adjustment tables.

Issue #4 broadened the *units* regex (`_THOUSANDS`) to recognize all fourteen header spellings.
The *table-shape* logic — two-column detection and account-heading context — was deliberately left
keyed to the original narrow phrase, `_THOUSANDS_TABLE_SHAPE`, so that the units fix provably
changed units and nothing else.

Broadening the shape detection is not a one-line change. Both the Defense adjustment tables and the
NRC tables announce a "Final Bill" column, but:

- Defense rows carry **two** amounts (budget request, final bill) and ALL-CAPS labels. The
  two-column path uses a `_caps_fraction >= 0.7` gate to skip the lowercase
  `Program increase—…` rows, which are *deltas* and must not pollute absolute amounts.
- NRC rows (`(Dollars in thousands)` / `Account Final Bill`) carry **one** amount and mixed-case
  labels. Routed down the two-column path, the caps gate silently drops all of them.

The column name cannot distinguish them: pdfplumber renders Defense's stacked two-line
`Budget`/`Request` header as interleaved characters — literally `R B e u q d u g e e s t t Final
Bill`. Structural discrimination (does a nearby data row carry two amounts?) also fails, because
some Defense tables have ALL-CAPS single-amount rows. Every variant tried lost a different set of
16-38 rows.

If this is revisited, the acceptance criterion is the one issue #4 used: re-extract all 16 prints
and assert the **row set is unchanged** and every `raw_text` is unchanged, so only the intended
field moves.

---

## 6. Senate parentheses were read as negatives — FIXED

**Status:** **fixed.** The 88 Senate reports were re-extracted; the row set was unchanged by this fix
(28,873 at the time; 29,042 after the later dot-leader recovery — see the CHANGELOG),
and every `raw_text` is unchanged — only the parsed sign moved.
**Scope (was):** **9,629 amounts across 3,970 rows**, all `chamber = senate`. Senate rows with a
negative `committee_recommendation` fell from 5,128 to 1,787; the remainder are genuine negatives.

### What was wrong
`parse_dollar` defaulted to `paren_negative=True` — the accounting convention, where `(35,000)`
means −35,000. Appropriations comparative statements do not use that convention: parentheses mark a
**non-add memo** (a limitation, a transfer authority, an "of which" breakout), and real negatives
print an explicit minus (`-2,000`). `comparative_house.py` passed `paren_negative=False` for exactly
this reason. `comparative_senate.py` took the default.

So `(By transfer from Disaster Relief)` shipped as −$24,000,000, and a bureau's gross
`Appropriations` line shipped as −$8,776,051,000.

### Why every gate missed it
All 5,128 affected rows were `verified = true` at what was then tier `delta`, the strongest tier — though on the Senate track that label named a check that had never run (fixed; the tier now reports the gate that actually passed, `string_match` here):

* Senate `verified` is a **string match** of `raw_text` against the source HTML. The raw text
  `(24,000)` is transcribed perfectly. Only the interpretation is wrong, and a string match cannot
  see an interpretation.
* The **delta identity** is invariant to a sign flip applied across a row's columns: negate
  `recommendation`, `prior`, and `estimate` together and `rec − prior == delta_vs_enacted` still
  holds.

Both gates compare a row to itself. Neither can witness a misread convention.

Two tests actively concealed it. `test_parenthesized_amounts` asserted
`prior_year_enacted.value == -34_000_000` under the docstring *"Parenthesized amounts like (34,000)
should parse as negative"* — the bug, written down as the specification. And
`test_full_report_subtotal_arithmetic`, the one test named for the check that would have caught it,
read its input from `/tmp/CRPT-118srpt83.htm`, returned silently when the file was absent (it always
was), and asserted only row *counts* even when it ran.

### How it was found, and what now prevents it
`verification.reconcile` checks the line items against the subtotals the committee printed — an
independent witness, outside the row. The Senate track is parsed deterministically and string-matches
at ~100%, yet only 65.1% of its printed subtotals reconciled. Transcription-perfect digits whose sums
do not close means the *interpretation* is wrong. Correcting the sign took Senate to 78.8%.

Three things guard it now:

1. `paren_negative` is a **required keyword** on `parse_dollar`. The convention is a property of the
   source table, never of the token, and no caller may take it by default.
2. `test_full_report_subtotal_arithmetic` reconciles the committed fixture and asserts a 100% strict
   pass rate.
3. `approps reconcile --fail-under` is a release gate over the shipped artifact.

### Residual
`is_memo` remains a *hypothesis*, not a fact: 2,350 flagged rows (20.3%) are added in by the
printed total that encloses them. `reconcile` resolves this per total and reports `memo_mode`; the
column itself is still named for the common case. See `DATA.md`.

---

## 7. House vision pages dropped whole — Defense titles missing from the shipped data

**Status:** FIXED — cause fixed in the extractor (`table_unreadable` + `_statement_gap_pages`) and the affected pages re-extracted (2026-09-11).
**Scope:** House vision track. 307 dropped pages across 73 of 149 House reports; worst in Defense, where whole titles were absent.

### What's wrong
`_is_comparative_table` identifies a comparative statement by its header names. When a scan's header does not survive OCR, the table is classified `non_comparative` and discarded, and that class is deliberately never sent to the Gemini fallback. Nothing is flagged, so the page leaves no trace.

CRPT-118hrpt557 (Defense FY2025) is the clearest case. Its Title III Procurement block is printed plainly on page 288 — Aircraft Procurement Army, Missile Procurement Army, Weapons Procurement Navy and 16 more — and none of it is in the dataset. Titles II and IV are missing the same way. 149 rows survive, about two thirds of them from the supplementals and the recapitulation. Two pages of 169 reached the fallback.

**Recovered 2026-09-11:** `scripts/repair_dropped_pages.py` re-read all 307 pages and merged 5,160 rows back in (the merge is additive — a gap page holds no rows to overwrite). CRPT-118hrpt557 went from 18 of 21 printed totals reconciling to 23 of 27, and `Total, title III, Procurement` now reconciles exactly against the 19 accounts beneath it. Corpus totals moved from 109,221 rows to 114,344, and the House strict reconcile rate from 74.8% to 76.1%.

### Why no gate caught it
Every suspect signal was a failure a page reports about itself, and a page dropped whole reports nothing. Reconciliation could not see it either: a missing block takes its own printed subtotal with it, so the rows and the witness that would convict them disappear together. `approps reconcile -p CRPT-118hrpt557` scores 18 of 21 totals OK.

### The fix
Two signals that do not require the page to report its own failure: `_money_dense_tabular` treats a headerless money table as ambiguous rather than ignorable, and `_statement_gap_pages` escalates an image page that produced nothing while sitting inside a run of pages that did.

### Remaining
A report-level completeness check — comparing each report's extracted title totals against the titles its own recapitulation names — would catch the class directly rather than page by page, and is not built.


---

## 8. Senate value columns were placed by position, not by name — FIXED

**Status:** FIXED (2026-09-12). Six FY2026 reports re-extracted.
**Scope:** Senate committee track, FY2026: `CRPT-119srpt37`, `srpt38`, `srpt43`, `srpt44`, `srpt46`, `srpt47`. 862 value-bearing rows.

### What was wrong
FY2026 Senate statements print **three** value columns, not the five earlier years printed:

```
Item | 2025 appropriation | Committee recommendation | recommendation compared with (+ or -) 2025 appropriation
```

`_find_column_positions` reads column *geometry* and never looked at the header names, so the three columns were filed into the first three of five fixed slots. Every value landed one place to the left: `budget_estimate` held the committee recommendation, and `committee_recommendation` held a delta. Anyone charting an FY2026 Senate level got a change figure instead.

### Why no gate caught it
The same blindness as #6 and #7. String matching passes, because every digit is genuinely on the page. Reconciliation passes too: **deltas are additive**, so a column of deltas sums to a subtotal of deltas exactly as amounts do. `CRPT-119srpt46` reconciled at 53% before the fix and nothing looked wrong.

It was found by an arithmetic tripwire over the shipped data — `committee_recommendation == budget_estimate - prior_year_enacted` held for **100%** of value-bearing rows in six reports, which no correctly-parsed statement does.

### The fix
`_column_slots` reads each column's stacked header text and maps it to its schema slot by name, the way the House/Nemotron path already did. Three guards keep it from making things worse: an identity mapping returns None so five-column reports take the untouched positional path; a mapping with duplicate or missing slots is refused; and `_arithmetic_agrees` checks the reading against the table's own deltas before trusting it, because the header is a claim and the rows are the evidence.

Acceptance, per the discipline in #5: re-extract all 87 Senate reports and diff against the previous parser. **81 of 87 byte-identical, 0 row-set changes, and exactly the 6 intended reports changed.**

### Remaining
The delta column itself is still not captured on these three-column statements (`delta_vs_enacted` is null), because the value reader's geometry helper insists on five columns. The figure is derivable as recommendation minus prior-year. Correcting the geometry was tried and reverted: it changed 28 unrelated reports for no gain.


---

## 9. Senate statements lost the rows above their first subtotal — FIXED

**Status:** FIXED (2026-09-12). 23 reports re-extracted, 63 rows recovered.
**Scope:** Senate committee track, every fiscal year. 18 reports opened mid-table; 23 gained rows once fixed.

### What was wrong
The reader found the data by counting rules: "after the third separator, data begins". A statement has two rules in its header, one under the title and one under the column names, so the third rule is somewhere in the table itself. Where a statement prints a rule above its opening subtotal — Corps of Engineers, Diplomatic Programs, Active Components and NRC tables all do — every row above that rule was stepped over.

`CRPT-118srpt72` began at `Subtotal, Investigations` with `Investigations` and `Rescission` missing above it. `CRPT-114srpt236` began at `SUBTOTAL, OPERATING REACTORS`, missing `OPERATING REACTORS` and `CORPORATE SUPPORT`.

### Why no gate caught it
Same shape as #7. The rows and the subtotal they belong to were both absent, so nothing could be compared against anything. The detector that found it was structural rather than arithmetic: **a statement whose first row is a subtotal has lost its head**, since no table opens with a total of nothing.

### The fix
Data begins after the second rule, the one closing the column headers. Acceptance: all 87 Senate reports re-extracted and diffed — 64 byte-identical, 23 gained rows, **zero other changes**, so the edit is purely additive.

Senate strict reconciliation moved 81.3% to 81.7% and genuine failures fell from 941 to 922.


---

## 10. House deltas were written over the enacted and request amounts — FIXED

**Status:** FIXED (2026-09-13). `CRPT-119hrpt696` re-read with Gemini.
**Scope:** House vision track. The signature — an explicit `+` on an enacted or request amount — appears in 2 of 148 House reports: `CRPT-119hrpt696` (Labor-HHS FY2027, 223 of 1,058 rows) and a single page of `CRPT-117hrpt392`.

### What was wrong
`CRPT-119hrpt696` sets "Committee vs." on the header line above a second `Enacted | Request` pair, so its two delta columns carry no "vs" of their own. `_header_to_slot` mapped them to the enacted and request slots, and `parse_page` lets a later cell overwrite an earlier one: each row's enacted and request amounts were replaced by its deltas, or blanked where the delta read `---`.

A page-by-page audit against the scans found 298 of 1,023 table rows matching exactly. `Total, Title I, Department of Labor` carried a request of `+169,485` against 11,733,555 on the page, and Pell Grants carried −10,298,000 against 33,023,352. The statement's first page and its Grand Total page produced no rows at all.

### Why no gate caught it
A row missing a level cannot express either delta identity, so `row_status` calls it `unverifiable`, not `fail`. The hybrid pipeline escalates fail pages to Gemini, and not one page in the report had a failing row. `delta_arithmetic` still tagged 354 of its rows verified, and a string match would have passed them all, because every misplaced number is genuinely on the page.

The independent witness was the report's own text-layer summary table: its department request totals (Labor 10,206,762, HHS 98,602,461) disagreed with the dataset (169,485, and the HHS committee-vs-request delta). The two dropped pages sat at the edges of the statement, where `_statement_gap_pages`, which only looks inside a run, cannot see them.

### The fix
`_promote_repeated_to_deltas` maps a repeated Enacted or Request header name to its delta slot, leaving every layout without a repeat untouched. Two escalation signals were added to the hybrid pipeline: `_shifted_column_pages` flags a page whose enacted or request cell carries an explicit `+`, which a level never does, and `_statement_edge_pages` flags an image page directly before or after a statement's run that produced no rows. On this report the sign signal flagged 44 of the 58 bad pages and none of the 13 good ones.

The other bad pages held row offsets and merged rows with no clean signal, so every image page was re-read with Gemini rather than only the flagged ones. Page 401 came back with its last rows shifted one line; two further reads were both exact, and the hand transcription chose between them. Against that transcription, whose 1,168 delta identities all close, all 933 value rows now match: 932 as read, plus one misread digit that `auto_repair` corrected from the row's own deltas. `auto_repair` also filled four `---` recommendations as zero. Strict reconciliation moved from 69.9% to 87.2%, and genuine failures fell from 46 to 23.

### Edge pages across the corpus
`scripts/repair_dropped_pages.py` re-read the 107 candidate pages the gap and edge signals name across 69 House reports. Its first pass merged whatever came back, and 16 of those pages were not statement pages at all: full-committee vote rosters, military construction project lists, unauthorized-appropriations tables and a 302(b) allocation table, whose cells Gemini had mapped into the five columns anyway. `_looks_like_statement` now keeps a re-read page only when one of its rows closes a delta identity, which a comparative table does and those tables cannot; the hybrid pipeline applies the same test to edge pages.

With the gate in place, 46 pages were recovered (885 rows, 479 verified, none with a plus-signed level), 21 were turned away, and 40 came back empty. No existing row changed. House strict reconciliation moved from 76.4% to 76.5%, with 58 more printed totals reconciling.

### Remaining
The Nemotron server was not reachable for this fix, so the header mapping and all three signals are covered by unit tests but have not run end to end through `extract_house_hybrid`. Row-offset and merged-row errors of the kind the sign signal missed are not measured outside `CRPT-119hrpt696`. Some recovered edge pages are Defense procurement detail tables whose quantity columns only partly align (#2): enough rows close a delta to pass the gate, and the rest join the mis-mapped rows #2 already describes.


---

## 11. FY2026–27 House three-column pages were filed one slot to the left — REPAIRED

**Status:** repaired at output (`column_repair = three_column_shift`), 2026-09-13.
**Scope:** 647 rows on pages of eight FY2026–27 House reports, among them `CRPT-119hrpt622` (MilCon-VA), `119hrpt697` (Homeland), `119hrpt236` (Financial Services), and `119hrpt686` (THUD).

These statements print `Enacted | Bill | Bill vs. Enacted`.
On some pages the vision pass filled the first three schema slots in order, so `budget_estimate` held the bill and `committee_recommendation` held the change from enacted.
The accuracy review found it on its FY2027 MilCon-VA page: 28 of 43 cells in the wrong column.

Every full row on a shifted page satisfies `committee_recommendation == budget_estimate - prior_year_enacted`, which is `delta == bill - enacted`, and correctly read pages of the same reports carry a delta column instead.
`normalization.column_shift` remaps a page only when every full row satisfies the identity and the page carries no delta of either kind.
The repaired rows are not marked verified, because the identity that justifies the move is the one a delta check would test.

**Remaining:** pages where the enacted amount stayed in the label (`Aeronautics..... 935,000`, CJS FY2027) are shifted two slots and cannot be remapped; they are isolated as `amount_in_label` (#15).

## 12. Senate rows with blank leading columns slid one column left — FIXED

**Status:** fixed in the parser, 2026-09-13. All 88 Senate reports re-extracted and re-verified.
**Scope:** 370 rows regained values they had lost, and rows like `Contributions for International Peacekeeping Activities  ....  ....  505,000  +505,000  +505,000` no longer read as request 505,000 / recommendation 505,000 / delta 505,000.

A label long enough to reach the value columns prints no dot leader, so the first dot run on the line is a blank column's placeholder.
The reader split at the first dot run, swallowed that column, and moved every value one slot left; where the amounts sat on a wrapped continuation line they were dropped.
A dot run that ends on a column edge is now treated as a placeholder and the row is read by column position.
Every value on the rows involved string-matched the source, so no gate objected.

Acceptance, per #5: re-parse all 88 reports and diff. 49 byte-identical, no row-count change in any report, 370 rows gained values, none lost one, and each other change was checked against its source line.

**Remaining:** a few rows in `CRPT-114srpt243` (THUD FY2016) still shift, where the column geometry of that statement is irregular. The accuracy review counts them.

## 13. FY2016 Senate statements with a House allowance column — REPAIRED

**Status:** repaired at output (`column_repair = house_allowance_columns`), 2026-09-13.
**Scope:** 861 rows in `CRPT-114srpt54`, `114srpt57`, `114srpt64`, `114srpt66`, `114srpt75`.

These print seven value columns, with the House allowance and its delta interleaved.
The reader keeps five in order, so `committee_recommendation` held the House allowance and `delta_vs_enacted` held the Senate recommendation.
The rows prove it: `delta_vs_estimate == delta_vs_enacted - prior_year_enacted` holds where the standard identity fails.
The repair moves the recommendation and its delta into place when that identity holds on at least 20 rows and outnumbers the standard one four to one.

**Remaining:** `delta_vs_estimate` is empty on these rows (the reader never kept it), and squeezed rows whose columns were read by geometry keep the wrong values — `Pacific coastal salmon recovery` in `CRPT-114srpt66` shows 7,000 as the prior year. Teaching the reader seven columns was tried and reverted, as in #8.

## 14. Enacted rows with dashes or typographic apostrophes in the label were dropped — FIXED

**Status:** fixed, 2026-09-13. All 16 prints re-extracted.
**Scope:** 980 rows recovered (`F–22`, `AH–64 Mods`, `Johanna’s Law`, `Garrett Lee Smith—Youth Suicide Prevention`).

The dot-leader pattern's label class stopped at ASCII, so a line whose label contained an en dash, em dash, or curly apostrophe never matched.
The review found 14 of 54 lines missing from one Defense page.
Acceptance: every existing row survives, in order, with label, raw text, and value unchanged.

**Remaining:** labels with other characters (`Items Less Than $5 Million`) are still missed.
Enacted "Program increase—…" lines state a change from the request, not a level; 38 are isolated as `adjustment_detail`.

## 15. Rows whose columns are shifted by an unrepairable parse — ISOLATED

**Status:** isolated, 2026-09-13. The untrusted amounts are emptied, `verification_tier` is `none`, and the extracted values are kept in `nonstandard_layout_rows`.

| Layout | Rows | Signature |
|---|---:|---|
| `text_in_amount` | 1,857 | A value cell carried words: header rows read as data, merged multi-line cells, and Community Project Funding tables (project, state, and member names) forced into the comparative columns. `CRPT-118hrpt581` had a village water project at $2.25 billion. |
| `amount_in_label` | 459 | The label ends in a figure, so the row was split past its first value column. 396 of them had passed a string match. |
| `signed_level` | 174 | A level column holds an explicit `+`, which only a change figure prints: the delta was read into a level's place. |

None of these can be put right from the extracted values: the figure that belongs in the empty slot was never read.
Fixing them means re-reading the pages.

## 16. Account keys that were demonstrably wrong — WITHHELD

**Status:** withheld, 2026-09-13 (`normalization.account_gate`).
**Scope:** 5,716 rows lost a key: 3,110 for jurisdiction, 1,639 generic labels, 872 tie-breaks, 95 headings. 22,852 rows keep one.

The crosswalk and the Tango matcher match on the label alone, so labels that name no particular account resolved to one: "Offsetting collections" became a Treasury refunds account on Interior, Homeland, and Energy-Water rows; "Mission Support" on Homeland rows became NASA; "Trust Funds" on Labor-HHS rows became a State Department account; every Financial Services "Salaries and expenses" became FinCEN because the subcommittee's name contains "Financial".
A key is now withheld when its agency is not funded by the row's subcommittee (unless Senate rows attest the pairing in two reports), when every label on the row is boilerplate and nothing else names the agency, when the row is a heading, or when a tie-break rested only on the subcommittee's name.
The rejected key is kept in `account_key_withheld`.

**Remaining:** the gate removes keys it can prove wrong; it does not prove the rest right.
A short label can still match the right agency's wrong account: NOAA's "Pacific Salmon" program line in the enacted statements carries the Pacific Coastal Salmon Recovery key.
`account_year_totals` does not take such rows as totals, because the label is not the account's title, but the key stays on the row.

## 17. Report metadata missing on repaired rows — FIXED

**Status:** fixed at output, 2026-09-13.
**Scope:** 857 House rows had no `fiscal_year` and 362 no `subcommittee` (nine reports, chiefly `CRPT-115hrpt230` and `CRPT-119hrpt215`); all 12,809 enacted rows had no `subcommittee`.

Rows merged in by `scripts/repair_dropped_pages.py` were written without their report's metadata, so they were in the data but invisible to any per-year query.
Report-level fields are now filled from the catalog, never overwriting a value a row already carries, and enacted rows take the subcommittee of their omnibus division.
The release build fails if any row lacks a fiscal year or any committee row lacks a subcommittee.

## 18. API longitudinal views double-counted and mixed real with nominal dollars — FIXED

**Status:** fixed, 2026-09-13.

`/api/line_items/compare` summed every non-subtotal row matching an account name per fiscal year — the account line and its program breakdown together, and House, Senate, and enacted figures for the same year into one number.
Flow and account history picked each account's largest-magnitude row as its total, which promoted a program line whenever the account line was missing.
`real=true` silently returned nominal dollars for FY2026–27, which have no deflator.

All three now use `normalization.account_totals`: the account's own titled line, or no total.
`/compare` requires `account_key`, returns one series per chamber and stage, lists unresolved reports, and fails with 422 when a requested real-dollar series has a year without a deflator.
`inflation.real_dollars` raises for a year outside the series instead of returning nothing.

## 19. Printed totals that do not reconcile — DOCUMENTED, NOT PURSUED

**Status:** documented. Eliminating these is out of scope for this release.

`approps reconcile` on the release:

| Track | Checkable totals | OK | Off by ≤2% | Partial read | Unreconciled | Strict pass rate |
|---|---:|---:|---:|---:|---:|---:|
| House committee | 10,532 | 7,873 | 484 | 99 | 1,829 | 76.5% |
| Senate committee | 5,286 | 4,210 | 280 | 32 | 569 | 82.7% |
| Enacted | 1,178 | 886 | 84 | 0 | 199 | 75.8% |
| **All** | **16,996** | **12,969** | **848** | **131** | **2,597** | **78.4%** |

The strict rate excludes the 451 `overlapping_view` totals (advance-appropriation and forward-funding lines that are not a contiguous sum by construction).
928 totals printed no figure and are unchecked.

A total that does not reconcile is not proof its rows are wrong: the reconciler recovers nesting from document order, and unusual table shapes defeat it.
It is a review item.
The reports with the most genuine failures are `CRPT-116hrpt9` (82 of 503 totals, the FY2019 Homeland continuing-appropriations report), `CRPT-118srpt207` (61), `CRPT-117hrpt403` (55), `CRPT-117hrpt96` (53), and `CPRT-118HPRT56550` (51).
The failure classes found in the accuracy review — misread digits, lost values, phantom subtotals on vision pages, and cross-page blocks — account for the House residual; enacted statements flatten hierarchy, which defeats the nesting inference.
`approps reconcile -p <report_id>` and `approps workbook -p <report_id>` show every failing total.

## 20. FY2026 Senate recommendations overwritten by the delta — FIXED

**Status:** fixed in the parser, 2026-09-13. The six FY2026 Senate reports with comparative statements were re-extracted and re-verified.
**Scope:** 1,859 rows changed in `CRPT-119srpt37`, `119srpt38`, `119srpt43`, `119srpt44`, `119srpt46`, `119srpt47`: recommendations restored where a dot placeholder or the delta had replaced them, and deltas captured where they had been dropped. No other report changed.

Found by the multi-year check: High Energy Cost Grants in `CRPT-119srpt37` prints `8,000 | 8,000 | ....` and was released with no recommendation.
These statements print three columns, but the delta column is mostly dot runs, so the header reading counted two columns and mapped them to prior year and recommendation.
The row's third token then fell back to its position — the recommendation's slot — and overwrote it: with a dot run (the recommendation vanished) or with the delta (`Child nutrition programs` released a recommendation of 3,019,176 for a printed 36,269,402).
A token that the header reading does not name no longer overwrites a slot already filled.
KNOWN_ISSUES #8's fix had covered the reading of the names; this was the placement after it.

**Remaining:** 16 rows in these reports still show a `+` in a level column and are isolated as `signed_level` (#15).
