"""Cluster the unverified value-bearing House rows into candidate anomaly categories.

The `verified = false` bucket is not monolithic: it splits by *which amount columns are
present and how they relate arithmetically*, and each large cluster is a candidate category
(a nonstandard table type, a formatting artifact, or a genuine extraction fault). This tool
surfaces those clusters with counts and source-page links so categories can be adjudicated
against the PDFs and then flagged or fixed. Read-only; writes nothing.

    uv run python scripts/profile_unverified.py            # summary histogram
    uv run python scripts/profile_unverified.py --category advance_approp   # drill into one

Categories are heuristic — a signature *finds* a candidate; confirm benign-vs-bug at source.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

_ADV = re.compile(
    r"available from prior year|advance appropriation|less prior year|current year appropriation",
    re.IGNORECASE,
)


def _v(row: dict, key: str):
    a = row.get(key)
    return a.get("value") if isinstance(a, dict) else None


def _raw(row: dict, key: str) -> str:
    a = row.get(key)
    return a.get("raw_text") if isinstance(a, dict) and a.get("value") is not None else "·"


def _category(r: dict) -> str:
    """Best-guess category for one unverified, value-bearing, non-subtotal row."""
    pe, be, cr = _v(r, "prior_year_enacted"), _v(r, "budget_estimate"), _v(r, "committee_recommendation")
    de, dt = _v(r, "delta_vs_enacted"), _v(r, "delta_vs_estimate")
    text = (r.get("line_item_text") or "").strip()

    if _ADV.search(text):
        return "advance_approp"                                  # Labor-HHS availability/advance breakouts
    if text.startswith("(") or _raw(r, "committee_recommendation").startswith("("):
        return "parenthetical_memo"                              # non-add memo (transfer/limitation)
    if None not in (pe, be, cr, de, dt) and pe and be and pe + be == cr and de == pe and dt == be:
        return "category_split"                                  # already flagged as column_layout
    if cr is None and pe is not None and de is not None and de == -pe:
        return "elimination"                                     # rec=0 rendered blank, delta=-prior
    if pe is not None and be is not None and cr is not None and pe == be == cr:
        return "all_three_equal"                                 # prior==request==rec (mostly advance-approp)
    if cr is not None and pe is not None and cr == pe:
        return "rec_equals_prior"
    if cr is not None and be is not None and cr == be:
        return "rec_equals_request"
    # otherwise bucket by which columns are present
    present = "".join(c for c, p in zip("PRCde", (pe, be, cr, de, dt)) if p is not None)
    return f"presence:{present or 'none'}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", help="drill into one category: list its reports/pages + samples")
    ap.add_argument("--chamber", default="house")
    args = ap.parse_args()

    from approps.normalization.summary_rows import summary_flags

    counts: Counter = Counter()
    reports: dict[str, Counter] = defaultdict(Counter)
    samples: dict[str, list] = defaultdict(list)
    total = 0
    for f in glob.glob(f"data/extracted/*/{args.chamber}/*.json"):
        if f.endswith(("_nemotron.json", "_hybrid.json")):
            continue
        rid = Path(f).stem
        items = json.loads(Path(f).read_text()).get("comparative_lines") or []
        for it, summ in zip(items, summary_flags(items)):
            if summ or it.get("is_subtotal") or it.get("verified"):
                continue
            if not any(_v(it, k) is not None for k in (
                "prior_year_enacted", "budget_estimate", "committee_recommendation",
                "delta_vs_enacted", "delta_vs_estimate")):
                continue
            total += 1
            cat = _category(it)
            counts[cat] += 1
            reports[cat][rid] += 1
            if len(samples[cat]) < 4:
                page = (it.get("line_number") or 0) // 100
                samples[cat].append((rid, page, (it.get("line_item_text") or "")[:32]))

    if args.category:
        cat = args.category
        print(f"=== {cat}: {counts[cat]:,} rows ===")
        print("top reports:")
        for rid, n in reports[cat].most_common(8):
            print(f"  {rid}: {n}  https://www.govinfo.gov/content/pkg/{rid}/pdf/{rid}.pdf")
        return

    print(f"unverified value-bearing {args.chamber} rows: {total:,}\n")
    print(f"{'category':22} {'rows':>7}   example")
    for cat, n in counts.most_common(20):
        rid, pg, t = samples[cat][0]
        print(f"  {cat:20} {n:>7,}   {rid} p{pg} \"{t}\"")


if __name__ == "__main__":
    main()
