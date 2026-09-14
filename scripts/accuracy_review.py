"""Compare blind source transcriptions against the extracted rows.

For each unit: align transcript rows to extracted rows in document order, then score
  completeness   — transcribed value rows that have an extracted counterpart (and extracted value rows in the span with no source row)
  transcription  — source amounts reproduced as a number somewhere on the matched extracted row
  column         — of those, the amount sits in the schema slot its source column means
Every disagreement is written out for adjudication, because the transcriber can be wrong too.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from approps.cli import _primary_json_files  # noqa: E402
from approps.config import EXTRACTED_DIR  # noqa: E402
from approps.normalization.summary_rows import drop_summary_rows  # noqa: E402

HERE = ROOT / "docs" / "accuracy_review"
SLOTS = ["prior_year_enacted", "budget_estimate", "committee_recommendation", "delta_vs_enacted", "delta_vs_estimate"]

units = {u["unit_id"]: u for u in json.loads((HERE / "units.json").read_text())}
files = {p.stem: p for p in _primary_json_files(EXTRACTED_DIR)}


def slot_for_header(h: str, idx: int, headers: list[str]) -> str | None:
    s = re.sub(r"\s+", " ", h.lower())
    if "qty" in s or "quantity" in s:
        return None
    is_delta = any(t in s for t in ("vs", "compared", "change", "+ or", "(+/-)", "increase", "difference"))
    if is_delta:
        if any(t in s for t in ("request", "estimate", "budget")):
            return "delta_vs_estimate"
        return "delta_vs_enacted"
    if any(t in s for t in ("request", "estimate")):
        return "budget_estimate"
    if any(t in s for t in ("recommend", "bill", "committee", "final", "conference", "agreement")):
        return "committee_recommendation"
    if any(t in s for t in ("enacted", "appropriation", "enacted")):
        return "prior_year_enacted"
    return None


def parse_cell(c: str) -> int | None:
    t = c.replace("$", "").replace(",", "").replace(" ", "").strip()
    t = t.strip("()")
    if not re.fullmatch(r"[+\-−–]?\d+", t):
        return None
    t = t.replace("−", "-").replace("–", "-")
    return int(t)


def norm_label(s: str) -> str:
    s = re.sub(r"\.{2,}.*$", "", s or "")
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def label_sim(a: str, b: str) -> float:
    """Token similarity, or spaceless similarity when a text layer dropped the spaces ("EducationandResearchCenters")."""
    na, nb = norm_label(a), norm_label(b)
    return max(fuzz.token_set_ratio(na, nb), fuzz.ratio(na.replace(" ", ""), nb.replace(" ", "")))


def ext_values(ln: dict) -> dict[str, int]:
    """The row's released amounts, in the source's printed units."""
    out = {}
    for k in SLOTS:
        v = ln.get(k)
        if v is None or (isinstance(v, float) and v != v):
            continue
        v = int(v)
        if ln.get("in_thousands"):
            v = v // 1000 if v % 1000 == 0 else v / 1000
        out[k] = v
    return out


def score(trow, tvals, ln):
    ev = ext_values(ln)
    evs = [abs(v) for v in ev.values()]
    amt = sum(1 for v in tvals if abs(v) in evs)
    lab = label_sim(trow["label"], ln.get("line_item_text"))
    return amt, lab


report_rows_cache = {}
OUTPUT_CSV = ROOT / "data/output/comparative_statements.csv"
_released = None


def report_rows(rid):
    """The released rows for a report, in document order, with the source page carried over from the extracted JSON.

    The output build keeps every extracted row after dropping summary tables, in order, so the n-th released row is the n-th kept JSON line.
    """
    global _released
    if _released is None:
        import pandas as pd

        _released = {k: g.to_dict("records") for k, g in pd.read_csv(OUTPUT_CSV, low_memory=False).groupby("report_id", sort=False)}
    if rid not in report_rows_cache:
        d = json.loads(files[rid].read_text())
        lines = drop_summary_rows(d.get("comparative_lines", []))
        rel = _released[rid]
        if len(rel) != len(lines):
            raise SystemExit(f"{rid}: {len(rel)} released rows vs {len(lines)} extracted lines")
        for r, ln in zip(rel, lines):
            if r["line_item_text"] != ln["line_item_text"]:
                raise SystemExit(f"{rid}: row order diverged at {r['row_id']}")
            r["line_number"] = ln.get("line_number")
        report_rows_cache[rid] = rel
    return report_rows_cache[rid]


results = []
disagreements = []
for tpath in sorted((HERE / "transcripts").glob("*.json")):
    t = json.loads(tpath.read_text())
    u = units[t["unit_id"]]
    rows = report_rows(u["report_id"])
    headers = t.get("column_headers") or []
    slots = [slot_for_header(h, i, headers) for i, h in enumerate(headers)]
    # An enacted statement's single amount column ("Budget Authority", or unheaded) is the enacted level, which the schema stores as the recommendation.
    if u["track"] == "enacted" and len(slots) == 1 and slots[0] is None:
        slots = ["committee_recommendation"]
    trows = []
    adjustment_rows = 0
    for r in t["rows"]:
        vals = [(slots[i] if i < len(slots) else None, parse_cell(c)) for i, c in enumerate(r.get("cells") or [])]
        vals = [(s, v) for s, v in vals if v is not None]
        # Typeset Defense tables explain each account's change with rows that print a single figure under the account ("Program increase—…", "Carryover", "Classified adjustment").
        # They are not funding lines and the typeset parser omits them by design, so they leave the completeness denominator.
        # Line items carry a line number or an upper-case label and more than one figure; totals are flagged.
        if (u["track"] == "house_typeset" and len(vals) == 1 and not r.get("is_total")
                and not re.match(r"^\d+\s", r["label"]) and r["label"] != r["label"].upper()):
            adjustment_rows += 1
            vals = []
        trows.append((r, vals))

    pool = list(range(len(rows)))
    if u["track"] == "house_vision":
        pool = [i for i, ln in enumerate(rows) if (ln.get("line_number") or 0) // 100 == u["pdf_page"]]

    # Monotonic greedy alignment of value rows.
    matched = {}
    last = -1
    for ti, (r, vals) in enumerate(trows):
        if not vals:
            continue
        tv = [v for _, v in vals]
        best, best_key = None, (0, 0)
        window = [i for i in pool if i > last] if last >= 0 else pool
        if last >= 0:
            window = window[:25]
        for i in window:
            amt, lab = score(r, tv, rows[i])
            ok = (amt >= 2) or (amt >= 1 and lab >= 70) or (lab >= 92 and amt >= 1)
            if ok and (amt, lab) > best_key:
                best, best_key = i, (amt, lab)
        if best is None and last >= 0:  # recover after a gap: search the whole pool
            for i in pool:
                amt, lab = score(r, tv, rows[i])
                if (amt >= 2 or (amt >= 1 and lab >= 85)) and (amt, lab) > best_key:
                    best, best_key = i, (amt, lab)
        if best is not None:
            matched[ti] = best
            last = best

    # The unit's span in the extraction: the matched indices after dropping any that jumped far from the rest.
    span = None
    if matched:
        idx = sorted(matched.values())
        med = idx[len(idx) // 2]
        reach = 3 * max(10, len(trows))
        kept = [i for i in idx if abs(i - med) <= reach]
        span = (min(kept), max(kept))
    ext_value_rows_in_span = [i for i in pool if span and span[0] <= i <= span[1] and ext_values(rows[i])]
    used = set(matched.values())

    n_value_rows = sum(1 for _, v in trows if v)
    cells = cells_ok = col_ok = 0
    for ti, (r, vals) in enumerate(trows):
        if not vals:
            continue
        if ti not in matched:
            disagreements.append(dict(unit=t["unit_id"], kind="omitted_row", label=r["label"], cells=r["cells"]))
            continue
        ln = rows[matched[ti]]
        ev = ext_values(ln)
        for slot, v in vals:
            if slot is None:
                continue
            cells += 1
            hit = [k for k, x in ev.items() if abs(x) == abs(v)]
            if hit:
                cells_ok += 1
                if slot in hit:
                    col_ok += 1
                else:
                    disagreements.append(dict(unit=t["unit_id"], kind="wrong_column", label=r["label"], source_slot=slot, value=v, extracted_slots=hit, extracted=ev))
            else:
                disagreements.append(dict(unit=t["unit_id"], kind="wrong_or_missing_value", label=r["label"], source_slot=slot, value=v, extracted=ev, extracted_label=ln.get("line_item_text")))
    extras = [i for i in ext_value_rows_in_span if i not in used]
    for i in extras:
        disagreements.append(dict(unit=t["unit_id"], kind="extra_row", label=rows[i].get("line_item_text"), extracted=ext_values(rows[i])))

    results.append(dict(unit=t["unit_id"], track=u["track"], sub=u["sub"], fy=u["fy"], headers=list(zip(headers, slots)),
                        source_value_rows=n_value_rows, matched_rows=len(matched), extra_rows=len(extras), adjustment_rows=adjustment_rows,
                        cells=cells, cells_transcribed=cells_ok, cells_in_right_column=col_ok))

(HERE / "diff_results.json").write_text(json.dumps(results, indent=2, default=str))
(HERE / "disagreements.json").write_text(json.dumps(disagreements, indent=2, default=str))

by_track = defaultdict(lambda: defaultdict(int))
for r in results:
    for k in ("source_value_rows", "matched_rows", "extra_rows", "cells", "cells_transcribed", "cells_in_right_column"):
        by_track[r["track"]][k] += r[k]
    print(f"{r['unit']:<32} rows {r['matched_rows']}/{r['source_value_rows']} extra {r['extra_rows']}  cells {r['cells_transcribed']}/{r['cells']} col {r['cells_in_right_column']}/{r['cells_transcribed']}  {r['headers']}")
print()
print()
print(f"{'track':<14} {'completeness':>18} {'transcription':>18} {'column':>18}  out-of-scope rows")
for tr, m in sorted(by_track.items()):
    def rate(a, b):
        return f"{a}/{b} ({a / b:.1%})" if b else "n/a"
    in_scope = m["source_value_rows"]
    adj = sum(r["adjustment_rows"] for r in results if r["track"] == tr)
    print(f"{tr:<14} {rate(m['matched_rows'], in_scope):>18} {rate(m['cells_transcribed'], m['cells']):>18} {rate(m['cells_in_right_column'], m['cells_transcribed']):>18}  {adj}")
print("disagreements:", len(disagreements), dict((k, sum(1 for d in disagreements if d['kind']==k)) for k in {d['kind'] for d in disagreements}))
