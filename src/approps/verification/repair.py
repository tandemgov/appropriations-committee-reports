"""Deterministic value recovery from the over-determined comparative columns.

A comparative line carries up to five columns, two of them derived:
    delta_vs_enacted  = committee_recommendation - prior_year_enacted
    delta_vs_estimate = committee_recommendation - budget_estimate

So the committee recommendation is over-determined: it can be reconstructed as
prior+delta_enacted or as budget+delta_estimate. This module uses that redundancy
to, conservatively and only:

  * RECOVER a blank recommendation (often a "$0"/"---" program stored as None, or a
    value the parser dropped) when the available derivation is unambiguous; and
  * CORRECT a present recommendation only when BOTH independent derivations exist
    and AGREE on a value different from the stored one -- two derivations agreeing
    make a compensating multi-misread effectively impossible (the verify_house
    standard), so the repair is safe even on vision-extracted data.

It never overwrites a value on a single derivation, and never touches the source
columns. Each change is flagged (recovered / corrected) and is idempotent.
"""

from __future__ import annotations


def _v(item: dict, field: str) -> int | None:
    return (item.get(field) or {}).get("value")


def _set_rec(item: dict, value: int, kind: str, old: int | None = None) -> None:
    cur = item.get("committee_recommendation") or {}
    in_thousands = cur.get("in_thousands")
    if in_thousands is None:  # derived value inherits source units from a sibling
        for f in ("prior_year_enacted", "budget_estimate", "delta_vs_enacted"):
            sib = item.get(f)
            if sib and sib.get("in_thousands") is not None:
                in_thousands = sib["in_thousands"]
                break
    new = {"value": value, "raw_text": cur.get("raw_text", ""),
           "in_thousands": bool(in_thousands), kind: True}
    if old is not None:
        new["corrected_from"] = old
    item["committee_recommendation"] = new


def repair_recommendation(item: dict) -> str | None:
    """Recover or correct one line's committee recommendation. Returns the action
    ('recovered' / 'corrected') or None if nothing safe to do."""
    pe, de = _v(item, "prior_year_enacted"), _v(item, "delta_vs_enacted")
    be, ds = _v(item, "budget_estimate"), _v(item, "delta_vs_estimate")
    cands = []
    if pe is not None and de is not None:
        cands.append(pe + de)
    if be is not None and ds is not None:
        cands.append(be + ds)
    if not cands:
        return None

    r = _v(item, "committee_recommendation")
    if r is None:
        if len(cands) == 1 or cands[0] == cands[1]:
            _set_rec(item, cands[0], "recovered")
            return "recovered"
        return None  # two derivations disagree -> not safe to recover
    if len(cands) == 2 and cands[0] == cands[1] and cands[0] != r:
        _set_rec(item, cands[0], "corrected", old=r)
        return "corrected"
    return None


def repair_report(data: dict) -> dict:
    """Apply repair_recommendation to every comparative line in an extracted report
    dict (mutated in place). Returns {'recovered': n, 'corrected': m}."""
    counts = {"recovered": 0, "corrected": 0}
    for item in data.get("comparative_lines", []):
        if item.get("is_subtotal"):
            continue
        action = repair_recommendation(item)
        if action:
            counts[action] += 1
    return counts
