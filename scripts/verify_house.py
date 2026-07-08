"""Repair signs and verify a House comparative extraction — the full gate.

Two independent checks, neither dependent on the noisy hierarchy:

1. SIGN REPAIR. Re-parse every amount from its stored ``raw_text`` with
   ``paren_negative=False`` (parentheses are non-add memo markers in these tables,
   not negatives). Because raw_text is the verbatim model output, re-parsing is
   exactly equivalent to re-running extraction with the fixed parser — no API call.

2. DELTA ARITHMETIC. Each row carries five columns where two are derived:
   ``delta_vs_enacted = recommended - prior_year_enacted`` and
   ``delta_vs_estimate = recommended - budget_estimate``. These identities hold for
   every row in the source table, so checking them validates all four value columns
   at once: a single misread digit breaks the arithmetic. This covers ALL rows that
   carry the values, not just the ~52 account totals the HTML can corroborate.

A row passes (``verified=True``) when every delta identity it can express holds
exactly. The residual is the human review queue. The fixed JSON is written back.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from approps.extraction.dollar_parser import parse_dollar  # noqa: E402

TARGET = Path("data/extracted/118/house/CRPT-118hrpt553.json")
COLS = [
    "prior_year_enacted",
    "budget_estimate",
    "committee_recommendation",
    "delta_vs_enacted",
    "delta_vs_estimate",
]


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else TARGET
    d = json.loads(path.read_text())
    L = d["comparative_lines"]

    # 1. Sign repair from raw_text -------------------------------------------------
    changed = 0
    for x in L:
        for c in COLS:
            amt = x.get(c) or {}
            raw = amt.get("raw_text", "")
            fixed = parse_dollar(raw, in_thousands=True, paren_negative=False)
            if fixed.value != amt.get("value"):
                changed += 1
            x[c] = {"value": fixed.value, "raw_text": raw, "in_thousands": True}

    def v(x, c):
        return (x.get(c) or {}).get("value")

    # 2. Auto-repair: fix the recommendation only when the redundant columns
    # over-determine it — i.e. enacted+delta_enacted and budget+delta_estimate
    # both exist and AGREE on a single value that differs from the stored rec.
    # Two independent derivations agreeing makes a compensating multi-misread
    # effectively impossible, so the repair is safe and auditable.
    repaired = []
    for x in L:
        e, b, r = v(x, "prior_year_enacted"), v(x, "budget_estimate"), v(x, "committee_recommendation")
        d1, d2 = v(x, "delta_vs_enacted"), v(x, "delta_vs_estimate")
        if None in (e, b, d1, d2):
            continue
        cand1, cand2 = e + d1, b + d2
        if cand1 == cand2 and cand1 != r:
            x["committee_recommendation"] = {
                "value": cand1,
                "raw_text": (x.get("committee_recommendation") or {}).get("raw_text", ""),
                "in_thousands": True,
                "corrected_from": r,
                "correction_basis": "enacted+delta_enacted == budget+delta_estimate",
            }
            repaired.append((x.get("line_item_text", "")[:40], x.get("line_number", 0) // 100, r, cand1))

    # 3. Delta-arithmetic verification --------------------------------------------
    passed = failed = unverifiable = 0
    residual = []
    for x in L:
        e, b, r = v(x, "prior_year_enacted"), v(x, "budget_estimate"), v(x, "committee_recommendation")
        d1, d2 = v(x, "delta_vs_enacted"), v(x, "delta_vs_estimate")
        checks = []
        if None not in (e, r, d1):
            checks.append(r - e == d1)
        if None not in (b, r, d2):
            checks.append(r - b == d2)
        if not checks:
            unverifiable += 1
            x["verified"] = False
            continue
        ok = all(checks)
        x["verified"] = ok
        if ok:
            passed += 1
        else:
            failed += 1
            residual.append(
                {
                    "text": x.get("line_item_text", "")[:48],
                    "page": x.get("line_number", 0) // 100,
                    "enacted": e, "budget": b, "rec": r,
                    "delta_enacted": d1, "rec_minus_enacted": (r - e) if None not in (e, r) else None,
                    "delta_estimate": d2, "rec_minus_budget": (r - b) if None not in (b, r) else None,
                }
            )

    path.write_text(json.dumps(d, indent=2))

    total = len(L)
    verifiable = passed + failed
    print(f"file: {path}")
    print(f"sign repair: {changed} amount values corrected")
    print(f"auto-repair (over-determined recommendation): {len(repaired)} rows")
    for t, pg, was, now in repaired:
        print(f"    [p{pg}] {t!r}: {was} -> {now}")
    print(f"rows: {total}")
    print(f"  verifiable by delta arithmetic: {verifiable}")
    pass_pct = f"{passed / verifiable:.1%}" if verifiable else "n/a — single-column statement"
    print(f"    PASS: {passed}  ({pass_pct} of verifiable)")
    print(f"    FAIL: {failed}")
    print(f"  unverifiable (header/blank rows): {unverifiable}")
    print()
    print(f"=== review queue: {len(residual)} rows where the table arithmetic does not hold ===")
    for r in residual:
        print(f"[p{r['page']}] {r['text']!r}")
        print(f"    enacted={r['enacted']} budget={r['budget']} rec={r['rec']}")
        print(f"    delta_enacted={r['delta_enacted']} (rec-enacted={r['rec_minus_enacted']})  "
              f"delta_estimate={r['delta_estimate']} (rec-budget={r['rec_minus_budget']})")


if __name__ == "__main__":
    main()
