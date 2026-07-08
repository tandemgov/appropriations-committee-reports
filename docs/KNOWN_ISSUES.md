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
