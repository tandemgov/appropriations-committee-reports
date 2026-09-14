"""Repair value columns that were filed into the wrong schema slots, where the rows themselves prove the correct mapping.

Two layouts are handled.

**House allowance (Senate FY2016).**
Five FY2016 Senate statements print seven value columns: `2015 appropriation | Budget estimate | House allowance | Committee recommendation | compared with 2015 | compared with estimate | compared with House`.
The reader keeps the first five in order, so `committee_recommendation` holds the House allowance, `delta_vs_enacted` holds the Senate recommendation, and `delta_vs_estimate` holds the Senate change from 2015.
Those rows satisfy `delta_vs_estimate == delta_vs_enacted - prior_year_enacted` instead of the usual `delta_vs_enacted == committee_recommendation - prior_year_enacted`, which is how the layout is recognized.
The repair moves the recommendation and its delta into place; the House allowance has no slot and is dropped, and the change from the estimate, which the reader never kept, stays empty.

**Three columns (House FY2026–FY2027).**
FY2026 and FY2027 House statements print three value columns, `Enacted | Bill | Bill vs. Enacted`, not the usual five.
On some pages of those reports the vision pass filed them into the first three of the five schema slots: `budget_estimate` holds the bill amount and `committee_recommendation` holds the change from enacted.
Anyone reading those rows gets a delta where the committee's level should be.

The misfiling proves itself: on a shifted page every row with three values satisfies `committee_recommendation == budget_estimate - prior_year_enacted`, which is exactly `delta == bill - enacted`.
A correctly read five-column page essentially never does, because a recommendation is not the request minus the prior year.
The pages that were read correctly in the same reports carry `delta_vs_enacted` values, so a page is repaired only when it carries no delta of either kind.

The repair moves the bill amount to `committee_recommendation` and the delta to `delta_vs_enacted`, and leaves `budget_estimate` empty, as the source prints no request.
It does not mark the rows verified: the identity that justifies the move is the same one a delta check would test, so it cannot also corroborate them.
"""

from __future__ import annotations

from collections import defaultdict

REPAIR = "three_column_shift"
HOUSE_ALLOWANCE = "house_allowance_columns"


def _value(line: dict, key: str) -> int | None:
    amount = line.get(key)
    return amount.get("value") if isinstance(amount, dict) else None


def _shifted_page(rows: list[dict], min_full: int) -> bool:
    if any(_value(r, "delta_vs_enacted") is not None or _value(r, "delta_vs_estimate") is not None for r in rows):
        return False
    full = [
        r for r in rows
        if None not in (_value(r, "prior_year_enacted"), _value(r, "budget_estimate"), _value(r, "committee_recommendation"))
    ]
    if len(full) < min_full:
        return False
    if all(_value(r, "committee_recommendation") == 0 for r in full):
        return False
    return all(
        _value(r, "committee_recommendation") == _value(r, "budget_estimate") - _value(r, "prior_year_enacted")
        for r in full
    )


def repair_three_column_pages(lines: list[dict]) -> int:
    """Remap shifted pages of one report's House vision rows in place. Returns the number of rows changed.

    A page needs at least two rows with all three values to prove the shift on its own.
    Once two pages of the report have, a page with a single such row is enough.
    """
    pages: dict[int, list[dict]] = defaultdict(list)
    for line in lines:
        if line.get("chamber") == "house" and line.get("extraction_method") == "llm":
            pages[(line.get("line_number") or 0) // 100].append(line)

    strong = {p for p, rows in pages.items() if _shifted_page(rows, min_full=2)}
    shifted = set(strong)
    if len(strong) >= 2:
        shifted |= {p for p, rows in pages.items() if _shifted_page(rows, min_full=1)}

    changed = 0
    for page in shifted:
        for line in pages[page]:
            bill, delta = line.get("budget_estimate"), line.get("committee_recommendation")
            if _value(line, "budget_estimate") is None and _value(line, "committee_recommendation") is None:
                continue
            line["committee_recommendation"] = bill
            line["delta_vs_enacted"] = delta
            line["budget_estimate"] = None
            line["column_repair"] = REPAIR
            changed += 1
    return changed


def repair_house_allowance_columns(lines: list[dict], min_rows: int = 20) -> int:
    """Remap one Senate report whose statement carries a House allowance column. Returns the number of rows changed.

    The report qualifies only when the House-allowance identity holds on at least `min_rows` rows and outnumbers the standard identity four to one.
    """
    senate = [ln for ln in lines if ln.get("chamber") == "senate"]
    shifted = standard = 0
    for ln in senate:
        prior, rec, dve, dvs = (_value(ln, k) for k in ("prior_year_enacted", "committee_recommendation", "delta_vs_enacted", "delta_vs_estimate"))
        if prior is None:
            continue
        if dve is not None and dvs is not None and dvs == dve - prior and dvs != dve:
            shifted += 1
        if rec is not None and dve is not None and dve == rec - prior:
            standard += 1
    if shifted < min_rows or shifted < 4 * standard:
        return 0

    changed = 0
    for ln in senate:
        if all(ln.get(k) is None for k in ("committee_recommendation", "delta_vs_enacted", "delta_vs_estimate")):
            continue
        ln["committee_recommendation"], ln["delta_vs_enacted"], ln["delta_vs_estimate"] = (
            ln.get("delta_vs_enacted"), ln.get("delta_vs_estimate"), None,
        )
        ln["column_repair"] = HOUSE_ALLOWANCE
        changed += 1
    return changed
