# Known issues

Tracked data-quality issues with a known cause and a deferred proper fix. Each is *flagged*
in the dataset so it can be filtered today; this file is the backlog for correcting it.

---

## 1. Category-split tables mis-mapped into the standard column schema

**Status:** flagged (`column_layout = category_split`), proper fix deferred.
**Scope:** ~297 rows across ~13 reports — chiefly **Energy-Water** (Bureau of Reclamation /
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

**Status:** partially flagged (`column_layout = procurement_qty` on the clearest instances),
proper fix deferred.
**Scope:** Defense procurement tables (`CRPT-116hrpt453` and other Defense reports). ~185 rows
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
