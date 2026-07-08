"""Corpus-wide reconciliation audit.

The extraction gates (verify_house delta arithmetic, the verify CLI string match,
recall_check account presence) test transcription and account-level presence, but
NOT whether the line items actually sum to their printed subtotals. That
completeness/structure axis is where dropped, duplicated, or misattributed rows
hide -- and it is unmeasured.

This audit reconstructs the hierarchical sum check (the same idea as the wired-but
-never-called verification.cross_check.check_subtotal) for every extracted report:
each is_subtotal line must equal either the sum of the line items since the last
subtotal (a leaf) or a rollup of recent subtotals (+ any items since). Reconciled
on committee_recommendation, the primary column.

Reports two honest numbers per report and per track x congress:
  * pass_rate  -- of the subtotals we could check, how many the line items add up to
  * coverage   -- whether the report is reconcilable at all (has checkable subtotals)

Usage: uv run python scripts/reconcile_audit.py [--worst N]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

EXTRACTED = Path("data/extracted")


def _v(line: dict, field: str) -> int | None:
    return (line.get(field) or {}).get("value")


def _rec(line: dict) -> int | None:
    """Committee recommendation, recovering it from the delta identity when the
    column is blank.

    A program recommended at $0 (or any readable level) often prints as '---' and
    is stored as None; its true level is prior+delta_enacted or budget+delta_estimate.
    Recovering it (a) lets $0-defunded rows contribute 0 instead of being skipped and
    (b) stops them being miscounted as dropped values.
    """
    r = _v(line, "committee_recommendation")
    if r is not None:
        return r
    cands = []
    pe, de = _v(line, "prior_year_enacted"), _v(line, "delta_vs_enacted")
    be, ds = _v(line, "budget_estimate"), _v(line, "delta_vs_estimate")
    if pe is not None and de is not None:
        cands.append(pe + de)
    if be is not None and ds is not None:
        cands.append(be + ds)
    if cands and all(c == cands[0] for c in cands):
        return cands[0]
    return None


def _has_other_value(line: dict) -> bool:
    """A non-subtotal row that carries SOME amount (prior-year/budget/delta)."""
    return any(_v(line, f) is not None for f in
               ("prior_year_enacted", "budget_estimate", "delta_vs_enacted", "delta_vs_estimate"))


# Overlapping-view / forward-funding subtotals (Labor-HHS especially) are NOT the
# sum of contiguous children -- they re-aggregate the same rows under different
# views (appropriated this bill vs available this year vs advance for next). A
# sum-of-children check cannot validate them, so they are structural, not errors.
_ADVANCE = ("advance", "available this fiscal", "appropriated in this bill",
            "forward fund", "less prior year", "prior year appropriation",
            "available in", "to remain available")


def _classify(lines, anchor, i, val, node_vals) -> str:
    """Why did this subtotal fail to reconcile?

    partial_read  -- a candidate child has NO recommendation but DOES carry other
                     columns: a value we dropped. A real error, reconciler-independent.
    off_by_small  -- the closest contiguous trailing run is within 2% of the subtotal:
                     one dropped/misread row. Real.
    structural    -- can't-check: deep/non-contiguous nesting, a cascade, or an
                     overlapping-view/advance-appropriation subtotal.
    """
    label = (lines[i].get("line_item_text", "") or "").lower()
    window = lines[anchor + 1:i]
    if any(k in label for k in _ADVANCE) or any(
            k in (y.get("line_item_text", "") or "").lower() for y in window for k in _ADVANCE):
        return "structural"
    for y in window:
        if not y.get("is_subtotal") and _rec(y) is None and _has_other_value(y):
            return "partial_read"
    best, s = None, 0
    for k in range(1, len(node_vals) + 1):
        s += node_vals[-k]
        d = abs(s - val)
        best = d if best is None else min(best, d)
    if val and best is not None and best / abs(val) <= 0.02:
        return "off_by_small"
    return "structural"


def reconcile_lines(lines: list[dict]) -> dict:
    """Nesting-robust subtotal reconciliation, with each failure classified.

    Depth is unreliable (enacted JES flattens accounts to depth 0), so for each
    subtotal we find the shortest contiguous TRAILING run of unconsumed preceding
    nodes that sums to it; the run is consumed and the subtotal pushed as a node, so
    parents roll up their child subtotals without depth labels. Failures are then
    classified into real (partial_read / off_by_small) vs structural (see _classify).
    """
    nodes: list[tuple[int, int]] = []   # (value, line index)
    anchor = -1                         # line index of the last consume/anchor
    ok = bad = 0
    kinds = {"partial_read": 0, "off_by_small": 0, "structural": 0}
    mismatches: list[dict] = []

    for i, x in enumerate(lines):
        val = _rec(x)
        if x.get("is_subtotal"):
            if val is None:
                continue
            s, hit = 0, 0
            for k in range(1, len(nodes) + 1):
                s += nodes[-k][0]
                if s == val:
                    hit = k
                    break
            if hit:
                del nodes[len(nodes) - hit:]
                nodes.append((val, i))
                ok += 1
            else:
                kind = _classify(lines, anchor, i, val, [v for v, _ in nodes])
                kinds[kind] += 1
                bad += 1
                mismatches.append({"label": x.get("line_item_text", "")[:50],
                                   "subtotal": val, "kind": kind})
                nodes.append((val, i))
            anchor = i
        elif val is not None:
            nodes.append((val, i))

    checked = ok + bad
    real = kinds["partial_read"] + kinds["off_by_small"]
    return {"checked": checked, "ok": ok, "bad": bad,
            "pass_rate": ok / checked if checked else None,
            "real_err": real, "structural": kinds["structural"], "kinds": kinds,
            "mismatches": mismatches}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worst", type=int, default=15, help="show N worst reconciling reports")
    args = ap.parse_args()

    rows = []
    for path in sorted(EXTRACTED.rglob("*.json")):
        parts = path.relative_to(EXTRACTED).parts
        if len(parts) < 3:
            continue
        congress, track = parts[0], parts[1]
        # The vision corpus stores each report twice (gemini + _nemotron copy); count once.
        if path.stem.endswith("_nemotron"):
            continue
        data = json.loads(path.read_text())
        lines = data.get("comparative_lines", [])
        n_items = sum(1 for x in lines if not x.get("is_subtotal"))
        r = reconcile_lines(lines)
        rows.append({"report": path.stem, "congress": congress, "track": track,
                     "lines": len(lines), "items": n_items, **r})

    def line(track, label, rs):
        recon = [r for r in rs if r["checked"]]
        sub = sum(r["checked"] for r in rs)
        ok = sum(r["ok"] for r in rs)
        real = sum(r["real_err"] for r in rs)
        struc = sum(r["structural"] for r in rs)
        print(f"{track:8} {label:5} {len(rs):>4} {len(recon):>4} {sub:>8} "
              f"{ok/sub if sub else 0:>6.0%} {real:>9} ({real/sub if sub else 0:>3.0%}) {struc:>10}")

    agg: dict[tuple, list] = defaultdict(list)
    for r in rows:
        agg[(r["track"], r["congress"])].append(r)

    print("=" * 80)
    print("RECONCILIATION AUDIT  (committee recommendation; subtotal = sum of children)")
    print(f"{'track':8} {'cong':5} {'rpts':>4} {'recon':>4} {'subtot':>8} "
          f"{'clean':>6} {'real-err':>11} {'structural':>10}")
    print("-" * 80)
    track_tot: dict[str, list] = defaultdict(list)
    for (track, cong), rs in sorted(agg.items()):
        line(track, cong, rs)
        track_tot[track].extend(rs)
    print("-" * 80)
    for track, rs in sorted(track_tot.items()):
        line(track.upper(), "ALL", rs)
    print("\nclean = subtotals whose children sum exactly | real-err = partial-read or "
          "off-by-<=2% (genuine) | structural = nesting/cascade (lower confidence)")

    # Review queue: reports ranked by count of REAL (not structural) errors.
    queue = sorted([r for r in rows if r["real_err"] > 0],
                   key=lambda r: -r["real_err"])[: args.worst]
    print("\n" + "=" * 80)
    print(f"REVIEW QUEUE — top {args.worst} reports by genuine (non-structural) gaps")
    print(f"{'report':20} {'track':7} {'items':>5} {'subtot':>6} {'real':>5} "
          f"{'partial':>7} {'small':>6}")
    for r in queue:
        print(f"{r['report']:20} {r['track']:7} {r['items']:>5} {r['checked']:>6} "
              f"{r['real_err']:>5} {r['kinds']['partial_read']:>7} {r['kinds']['off_by_small']:>6}")

    blind = [r for r in rows if r["checked"] == 0]
    by_track: dict[str, int] = defaultdict(int)
    for r in blind:
        by_track[r["track"]] += 1
    print("\n" + "=" * 80)
    print(f"UNRECONCILABLE: {len(blind)} of {len(rows)} reports have 0 checkable subtotals "
          f"(unmeasured): {dict(by_track)}")


if __name__ == "__main__":
    main()
