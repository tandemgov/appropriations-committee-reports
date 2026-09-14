"""One defensible total per account, per report — the unit of longitudinal analysis.

A comparative statement lists an account's own line and, often, its program breakdown beneath it, all as ordinary rows keyed to the same `account_key`.
Summing every keyed row double-counts; the earlier "largest-magnitude row" rule picked whichever breakdown line happened to be biggest when the account line was missing.
Neither is a total anyone could defend to the committee that printed it.

The rule here selects rows the source itself presents as the account, and refuses otherwise:

1. `single_line` — the report has exactly one eligible row for the account, and its label is the account's own title. That row is the account.
2. `account_line` — several rows share the key, and the rows whose label is the account's own title (the authoritative title starts with the label) number exactly one per designation (base, emergency, OCO, …). Those lines are the account; their designations are summed, and listed.
3. `unresolved` — anything else. No total is reported; `n_lines` says how many keyed rows competed.

Eligible rows carry a trusted key and a level amount, are not subtotals or rollups, are not memo lines (a parenthesized limitation or transfer is not the account's appropriation), and sit in a table whose recommendation column means what it says (`standard` or `category_split` layout).

Totals are kept per report, and a series is only ever built within one chamber and one stage: a House recommendation, a Senate recommendation, and an enacted level for the same account and year are three different numbers, not parts of one.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from approps.normalization.account_inference import _is_rollup
from approps.normalization.account_names import extract_designation, normalize_account

LEVELS = ("prior_year_enacted", "budget_estimate", "committee_recommendation")
_TRUSTED_LAYOUTS = frozenset({"standard", "category_split"})


@dataclass
class AccountTotal:
    account_key: str
    account_key_title: str | None
    report_id: str
    fiscal_year: int | None
    chamber: str | None
    stage: str | None
    subcommittee: str | None
    method: str
    n_lines: int
    row_ids: list[str] = field(default_factory=list)
    designations: list[str] = field(default_factory=list)
    prior_year_enacted: int | None = None
    budget_estimate: int | None = None
    committee_recommendation: int | None = None
    verified_lines: int = 0
    # The selected rows themselves, for callers that need their labels or hierarchy; not serialized.
    chosen: list[dict] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "chosen"}
        d["row_ids"] = ";".join(self.row_ids)
        d["designations"] = ";".join(self.designations)
        return d


def _eligible(r: dict) -> bool:
    if not r.get("account_key") or r.get("is_subtotal") or r.get("is_memo"):
        return False
    if (r.get("column_layout") or "standard") not in _TRUSTED_LAYOUTS:
        return False
    if _is_rollup({"is_subtotal": r.get("is_subtotal"), "line_item_text": r.get("line_item_text")}):
        return False
    return any(r.get(m) is not None for m in LEVELS)


_PAREN = re.compile(r"\(([^)]*)\)")
_CITATION = re.compile(r"(?i)^\s*(sec\.?|section|p\.?\s*l\.?|public law)\b")


def _label_for_title_match(text: str) -> str:
    """Normalize a label, dropping designation and citation parentheticals but keeping any other qualifier.

    "Child Nutrition Programs (Entitlement Commodities)" names a component of the account, not the account; stripping every parenthetical would make it look like the whole.
    """

    def keep(m: re.Match) -> str:
        inner = m.group(1)
        if extract_designation(f"({inner})") != "base" or _CITATION.match(inner):
            return " "
        return f" {inner} "

    return normalize_account(_PAREN.sub(keep, text or ""))


def is_account_line(r: dict) -> bool:
    """Whether the row's label is the account's own title rather than a program or component beneath it."""
    label = _label_for_title_match(r.get("line_item_text") or "")
    title = normalize_account(r.get("account_key_title") or "")
    return bool(label) and (title == label or title.startswith(label + " "))


def _sum(rows: list[dict], metric: str) -> int | None:
    vals = [r[metric] for r in rows if r.get(metric) is not None]
    return sum(vals) if vals else None


def account_totals(rows: list[dict]) -> list[AccountTotal]:
    """Resolve every (report, account_key) group in the dataset. Rows are output-table row dicts."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if _eligible(r):
            groups[(r["report_id"], r["account_key"])].append(r)

    out = []
    for (report_id, key), members in groups.items():
        first = members[0]
        base = dict(
            account_key=key, account_key_title=first.get("account_key_title"), report_id=report_id,
            fiscal_year=first.get("fiscal_year"), chamber=first.get("chamber"), stage=first.get("stage"),
            subcommittee=first.get("subcommittee"), n_lines=len(members),
        )
        chosen: list[dict] | None = None
        if len(members) == 1:
            # A lone keyed row is the account only if it is titled as the account: a keyed program line or component is not a total.
            if is_account_line(members[0]):
                method, chosen = "single_line", members
            else:
                method = "unresolved"
        else:
            lines = [r for r in members if is_account_line(r)]
            by_designation = defaultdict(list)
            for r in lines:
                by_designation[r.get("designation") or "base"].append(r)
            if lines and all(len(v) == 1 for v in by_designation.values()):
                method, chosen = "account_line", lines
            else:
                method = "unresolved"

        total = AccountTotal(method=method, **base)
        if chosen:
            total.chosen = chosen
            total.row_ids = [r.get("row_id") or "" for r in chosen]
            total.designations = sorted({r.get("designation") or "base" for r in chosen})
            for m in LEVELS:
                setattr(total, m, _sum(chosen, m))
            total.verified_lines = sum(1 for r in chosen if (r.get("verification_tier") or "none") != "none")
        out.append(total)
    out.sort(key=lambda t: (t.account_key, t.fiscal_year or 0, t.chamber or "", t.stage or "", t.report_id))
    return out


def account_series(totals: list[AccountTotal], account_key: str, metric: str = "committee_recommendation") -> dict:
    """One account's money through time, as separate series per (chamber, stage).

    A fiscal year that two reports of the same chamber and stage both claim is reported as a conflict with no value, never summed.
    """
    if metric not in LEVELS:
        raise ValueError(f"metric must be one of {LEVELS}")
    series: dict[tuple, dict[int, list[AccountTotal]]] = defaultdict(lambda: defaultdict(list))
    unresolved = []
    for t in totals:
        if t.account_key != account_key:
            continue
        if t.method == "unresolved":
            unresolved.append({"report_id": t.report_id, "fiscal_year": t.fiscal_year, "chamber": t.chamber, "stage": t.stage, "n_lines": t.n_lines})
            continue
        if t.fiscal_year is None or getattr(t, metric) is None:
            continue
        series[(t.chamber, t.stage)][t.fiscal_year].append(t)

    out = []
    for (chamber, stage), years in sorted(series.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
        points = []
        for fy in sorted(years):
            ts = years[fy]
            if len(ts) > 1:
                points.append({"fiscal_year": fy, "value": None, "conflict": [t.report_id for t in ts]})
                continue
            t = ts[0]
            points.append({"fiscal_year": fy, "value": getattr(t, metric), "report_id": t.report_id, "method": t.method,
                           "row_ids": t.row_ids, "designations": t.designations})
        out.append({"chamber": chamber, "stage": stage, "points": points})
    return {"account_key": account_key, "metric": metric, "series": out, "unresolved": unresolved}
