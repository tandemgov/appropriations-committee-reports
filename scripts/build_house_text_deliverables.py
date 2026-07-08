"""Build the human-facing deliverables for a born-digital House print from the
canonical text extractor (one source of truth -> no stale-file drift).

Writes into <outdir>:
  full.json        nested accounts -> rows(+marks), values in $thousands
  line_items.csv   flat line items
  marks.csv        the congressional adjustments

Usage: uv run python scripts/build_house_text_deliverables.py <pdf> <outdir>
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from approps.extraction.comparative_house_text import _parse, _to_int, reconcile


def build(pdf_path: str, outdir: str) -> None:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    parsed = _parse(pdf_path)

    # Unify line-item accounts and the inline (Title VII) accounts; all values in
    # $thousands (line-item tables are already thousands; inline blocks print whole
    # dollars, so divide by 1000).
    accounts = []
    for a in parsed["accounts"]:
        rows = [{
            "code": r["code"], "item": r["item"], "row_type": r["row_type"],
            "budget_request_k": _to_int(r["req"]) if r["req"] else None,
            "committee_recommended_k": _to_int(r["rec"]),
            "change_k": _to_int(r["chg"]) if r["chg"] else None,
            "marks": [{"description": m["description"], "amount_k": m["amount"]}
                      for m in r["adjustments"]],
        } for r in a["rows"]]
        accounts.append({"title": a["title"], "account": a["account"], "rows": rows})
    for b in parsed["inline"]:
        accounts.append({"title": b["title"], "account": b["account"], "rows": [{
            "code": None, "item": b["account"], "row_type": "inline",
            "budget_request_k": _to_int(b["req"]) // 1000,
            "committee_recommended_k": _to_int(b["rec"]) // 1000,
            "change_k": (_to_int(b["chg"]) // 1000) if b["chg"] else None,
            "marks": [],
        }]})

    # RECAPITULATION: title-level totals (incl. Title VIII) + bill grand total.
    recap = [{"name": r["name"], "kind": r["kind"],
              "budget_request_k": r["req"], "committee_recommended_k": r["rec"]}
             for r in parsed["recap"]]

    rec = reconcile(parsed["ledger"])
    (out / "full.json").write_text(json.dumps(
        {"reconciliation": {k: rec[k] for k in ("nodes", "leaf", "rollup", "bad")},
         "recapitulation": recap, "accounts": accounts}, indent=2, ensure_ascii=False))

    with (out / "line_items.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["title", "account", "code", "row_type", "item",
                    "budget_request_k", "committee_recommended_k", "change_k", "n_marks"])
        for a in accounts:
            for r in a["rows"]:
                w.writerow([a["title"], a["account"], r["code"], r["row_type"], r["item"],
                            r["budget_request_k"], r["committee_recommended_k"], r["change_k"],
                            len(r["marks"])])

    with (out / "marks.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["title", "account", "code", "item", "mark_description", "amount_k"])
        for a in accounts:
            for r in a["rows"]:
                for m in r["marks"]:
                    w.writerow([a["title"], a["account"], r["code"], r["item"],
                                m["description"], m["amount_k"]])

    n_items = sum(len(a["rows"]) for a in accounts)
    n_marks = sum(len(r["marks"]) for a in accounts for r in a["rows"])
    print(f"accounts {len(accounts)} | rows {n_items} | marks {n_marks} | "
          f"reconcile {rec['leaf'] + rec['rollup']}/{rec['nodes']} (bad {rec['bad']})")
    print(f"wrote full.json, line_items.csv, marks.csv to {out}")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
