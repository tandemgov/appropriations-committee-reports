"""Reusable verification gate for House comparative lines (importable).

Mirrors the logic in scripts/verify_house.py so other code (e.g. the hybrid
extractor) can find FAIL rows in memory without shelling out:

  1. SIGN REPAIR  — re-parse each amount from its raw_text with paren_negative=False.
  2. DELTA ARITHMETIC — a row passes when every delta identity it can express holds:
        delta_vs_enacted  == committee_recommendation - prior_year_enacted
        delta_vs_estimate == committee_recommendation - budget_estimate

Operates on the JSON dict shape produced by the extractors (a row is a dict with
the five column keys, each {"value", "raw_text", "in_thousands"}).
"""

from __future__ import annotations

from approps.extraction.dollar_parser import parse_dollar

COLS = [
    "prior_year_enacted",
    "budget_estimate",
    "committee_recommendation",
    "delta_vs_enacted",
    "delta_vs_estimate",
]


def reparse_signs(line: dict) -> None:
    """Re-parse every amount from its raw_text in place (paren = non-add memo)."""
    for c in COLS:
        amt = line.get(c) or {}
        raw = amt.get("raw_text", "")
        fixed = parse_dollar(raw, in_thousands=True, paren_negative=False)
        line[c] = {"value": fixed.value, "raw_text": raw, "in_thousands": True}


def _v(line: dict, c: str):
    return (line.get(c) or {}).get("value")


def row_status(line: dict) -> str:
    """Return 'pass' | 'fail' | 'unverifiable' for one row's delta arithmetic."""
    e, b, r = _v(line, "prior_year_enacted"), _v(line, "budget_estimate"), _v(line, "committee_recommendation")
    d1, d2 = _v(line, "delta_vs_enacted"), _v(line, "delta_vs_estimate")
    checks = []
    if None not in (e, r, d1):
        checks.append(r - e == d1)
    if None not in (b, r, d2):
        checks.append(r - b == d2)
    if not checks:
        return "unverifiable"
    return "pass" if all(checks) else "fail"


def page_of(line: dict) -> int:
    """Recover the 1-based page number from the approximate line_number."""
    return line.get("line_number", 0) // 100


def auto_repair(line: dict) -> bool:
    """Fix the recommendation when the redundant columns over-determine it.

    When enacted+delta_enacted and budget+delta_estimate both exist and AGREE on a
    single value that differs from the stored recommendation, two independent
    derivations agreeing makes a compensating multi-misread effectively impossible,
    so the repair is safe and auditable. Returns True if it changed the row.
    """
    e, b, r = _v(line, "prior_year_enacted"), _v(line, "budget_estimate"), _v(line, "committee_recommendation")
    d1, d2 = _v(line, "delta_vs_enacted"), _v(line, "delta_vs_estimate")
    if None in (e, b, d1, d2):
        return False
    cand1, cand2 = e + d1, b + d2
    if cand1 == cand2 and cand1 != r:
        line["committee_recommendation"] = {
            "value": cand1,
            "raw_text": (line.get("committee_recommendation") or {}).get("raw_text", ""),
            "in_thousands": True,
            "corrected_from": r,
            "correction_basis": "enacted+delta_enacted == budget+delta_estimate",
        }
        return True
    return False


def verify(lines: list[dict]) -> dict:
    """Sign-repair + auto-repair (in place) and verify a list of rows."""
    for ln in lines:
        reparse_signs(ln)
    repaired = sum(auto_repair(ln) for ln in lines)
    passed = failed = unverifiable = 0
    fail_pages: set[int] = set()
    for ln in lines:
        st = row_status(ln)
        ln["verified"] = st == "pass"
        ln["verification_method"] = "delta_arithmetic" if st == "pass" else "none"
        if st == "pass":
            passed += 1
        elif st == "fail":
            failed += 1
            fail_pages.add(page_of(ln))
        else:
            unverifiable += 1
    verifiable = passed + failed
    return {
        "passed": passed,
        "failed": failed,
        "unverifiable": unverifiable,
        "verifiable": verifiable,
        "pass_rate": (passed / verifiable) if verifiable else None,
        "fail_pages": sorted(fail_pages),
        "auto_repaired": repaired,
    }
