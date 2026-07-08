"""In-memory query layer over the extracted line-item dataset.

The canonical queryable dataset is the enriched flat file produced by the output
step, `data/output/comparative_statements.csv` (~85k rows, FY2016-FY2027, both
chambers, committee + enacted stages). It already carries the account crosswalk
(`account_key`, `account_key_title`, `designation`, `real_factor_2024`) that makes
cross-year "follow the money" joins possible, so the API reads it directly.

If the CSV has not been built, we fall back to reading the per-report extracted
JSON tree so the API still returns line items (without the crosswalk enrichment).

All money values are absolute dollars. Negative amounts are real (rescissions and
offsetting collections) and are preserved, never filtered.
"""

from __future__ import annotations

import csv
import json
from functools import lru_cache
from typing import Any

from approps.config import EXTRACTED_DIR, OUTPUT_DIR
from approps.normalization.account_inference import (
    _is_rollup,
    _MEMO_ONLY_RE,
    _rollup_name,
)

COMPARATIVE_CSV = OUTPUT_DIR / "comparative_statements.csv"

# The three money figures a line item can carry, in reporting order.
METRICS = ("prior_year_enacted", "budget_estimate", "committee_recommendation")

# Ordered hierarchy the money flows through. Any contiguous or non-contiguous
# subset of these can be used as the levels of a Sankey flow.
HIERARCHY_LEVELS = (
    "chamber",
    "stage",
    "subcommittee",
    "title_name",
    "department",
    "agency",
    "account",
    "program",
)

# Subcommittee labels drifted across years/chambers (e.g. "Homeland Security"
# vs "Homeland-Security"). Canonicalize so grouping and filtering are stable.
_SUBCOMMITTEE_CANON = {
    "Homeland Security": "Homeland-Security",
    "State-Foreign-Ops": "State-Foreign-Operations",
}

_UNSPECIFIED = "(unspecified)"


def canon_subcommittee(value: str | None) -> str | None:
    if not value:
        return value
    return _SUBCOMMITTEE_CANON.get(value.strip(), value.strip())


def _to_int(raw: str | None) -> int | None:
    """Parse a dollar cell to an int, preserving sign. Empty/None -> None."""
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "" or raw == "None":
        return None
    try:
        return int(round(float(raw)))
    except ValueError:
        return None


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    raw = raw.strip()
    if raw in ("", "None"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _norm(value: Any) -> str | None:
    """Empty strings -> None; everything else stripped."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


@lru_cache
def load_line_items() -> list[dict]:
    """Load and normalize every line item once (cached).

    Returns a list of plain dicts with parsed numeric metrics, canonical
    subcommittee names, and a coalesced `account_effective` (falls back to the
    arithmetic-verified `account_inferred` when `account` is blank).
    """
    if COMPARATIVE_CSV.exists():
        rows = _load_from_csv()
    else:
        rows = _load_from_json_tree()
    _recover_house_accounts(rows)
    return rows


def _finalize(row: dict) -> dict:
    row["subcommittee"] = canon_subcommittee(row.get("subcommittee"))
    # Coalesce account: House vision rows leave `account` blank but carry an
    # arithmetic-verified `account_inferred`.
    row["account_effective"] = row.get("account") or row.get("account_inferred")
    row["account_recovered"] = None
    # A row whose *text* is a rollup ("Total. Joint Items") the extractor failed to
    # flag is_subtotal — must not be summed as a leaf. Computed once here.
    row["is_rollup_row"] = _is_rollup(
        {"is_subtotal": row.get("is_subtotal"), "line_item_text": row.get("line_item_text")}
    )
    return row


def _recover_house_accounts(rows: list[dict]) -> None:
    """Assign a heuristic `account_recovered` to unlabeled leaves in source order.

    Third, lowest-confidence tier below `account`/`account_key` (extracted) and
    `account_inferred` (arithmetic-verified): each unlabeled leaf inherits the name
    of the next naming subtotal (`Subtotal,/Total, <name>`) that closes its block —
    the report's own structure — *without* requiring the block to reconcile. This
    recovers ~80% of House dollars that otherwise carry no account, at the cost of
    not being arithmetic-verified, so it is kept in a separate field and surfaced as
    a distinct coverage tier. `account`/`account_inferred` are never overwritten.

    Mutates rows in place. Rows must be grouped by report in source (line) order,
    which the CSV and JSON-tree loaders both preserve.
    """
    pending: list[dict] = []
    current_report: str | None = None

    def is_labeled(r: dict) -> bool:
        return bool(r.get("account_effective") or r.get("account_key"))

    for r in rows:
        if r.get("report_id") != current_report:
            pending = []
            current_report = r.get("report_id")
        text = (r.get("line_item_text") or "").strip()
        if not text:
            continue
        if r["is_rollup_row"]:
            name = _rollup_name(text)
            if name:
                for leaf in pending:
                    if not is_labeled(leaf) and not leaf.get("account_recovered"):
                        leaf["account_recovered"] = name
            pending = []
        elif _MEMO_ONLY_RE.match(text):
            continue  # non-add memo line — never a countable leaf
        else:
            pending.append(r)


def _load_from_csv() -> list[dict]:
    out: list[dict] = []
    with COMPARATIVE_CSV.open(newline="") as fh:
        for r in csv.DictReader(fh):
            row = {
                "report_id": _norm(r.get("report_id")),
                "congress": _to_int(r.get("congress")),
                "chamber": _norm(r.get("chamber")),
                "fiscal_year": _to_int(r.get("fiscal_year")),
                "subcommittee": _norm(r.get("subcommittee")),
                "stage": _norm(r.get("stage")),
                "title_name": _norm(r.get("title_name")),
                "department": _norm(r.get("department")),
                "agency": _norm(r.get("agency")),
                "account": _norm(r.get("account")),
                "account_inferred": _norm(r.get("account_inferred")),
                "non_add_inferred": str(r.get("non_add_inferred")).strip().lower() == "true",
                "program": _norm(r.get("program")),
                "line_item_text": _norm(r.get("line_item_text")),
                "prior_year_enacted": _to_int(r.get("prior_year_enacted")),
                "budget_estimate": _to_int(r.get("budget_estimate")),
                "committee_recommendation": _to_int(r.get("committee_recommendation")),
                "delta_vs_enacted": _to_int(r.get("delta_vs_enacted")),
                "delta_vs_estimate": _to_int(r.get("delta_vs_estimate")),
                "is_subtotal": str(r.get("is_subtotal")).strip().lower() == "true",
                "hierarchy_depth": _to_int(r.get("hierarchy_depth")) or 0,
                "verified": str(r.get("verified")).strip().lower() == "true",
                "verification_tier": _norm(r.get("verification_tier")) or "none",
                "column_layout": _norm(r.get("column_layout")) or "standard",
                "extraction_method": _norm(r.get("extraction_method")),
                # Account crosswalk enrichment
                "account_key": _norm(r.get("account_key")),
                "account_key_title": _norm(r.get("account_key_title")),
                "account_key_agency": _norm(r.get("account_key_agency")),
                "account_key_bureau": _norm(r.get("account_key_bureau")),
                "designation": _norm(r.get("designation")),
                "real_factor_2024": _to_float(r.get("real_factor_2024")),
            }
            out.append(_finalize(row))
    return out


def _load_from_json_tree() -> list[dict]:
    """Fallback: read the per-report extracted JSON when the CSV isn't built.

    Crosswalk fields (account_key, designation, real_factor_2024) are absent here.
    """
    out: list[dict] = []
    if not EXTRACTED_DIR.exists():
        return out
    for path in EXTRACTED_DIR.rglob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for ln in data.get("comparative_lines", []):
            def amt(key: str) -> int | None:
                d = ln.get(key)
                return d.get("value") if isinstance(d, dict) else None

            row = {
                "report_id": ln.get("report_id"),
                "congress": ln.get("congress"),
                "chamber": ln.get("chamber"),
                "fiscal_year": ln.get("fiscal_year"),
                "subcommittee": ln.get("subcommittee"),
                "stage": ln.get("stage"),
                "title_name": ln.get("title_name"),
                "department": ln.get("department"),
                "agency": ln.get("agency"),
                "account": ln.get("account"),
                "account_inferred": ln.get("account_inferred"),
                "non_add_inferred": bool(ln.get("non_add_inferred")),
                "program": ln.get("program"),
                "line_item_text": ln.get("line_item_text"),
                "prior_year_enacted": amt("prior_year_enacted"),
                "budget_estimate": amt("budget_estimate"),
                "committee_recommendation": amt("committee_recommendation"),
                "delta_vs_enacted": amt("delta_vs_enacted"),
                "delta_vs_estimate": amt("delta_vs_estimate"),
                "is_subtotal": bool(ln.get("is_subtotal")),
                "hierarchy_depth": ln.get("hierarchy_depth") or 0,
                "verified": bool(ln.get("verified")),
                # Fallback tier without the CSV build: inline corroboration is unavailable
                # here, so only delta/block/none are distinguishable from the raw JSON.
                "verification_tier": (
                    "delta" if ln.get("verified")
                    else "block" if (ln.get("account_inferred") or "").strip()
                    else "none"
                ),
                "extraction_method": ln.get("extraction_method"),
                "account_key": None,
                "account_key_title": None,
                "designation": None,
                "real_factor_2024": None,
            }
            out.append(_finalize(row))
    return out


# --- Query helpers -------------------------------------------------------


def filter_items(
    rows: list[dict] | None = None,
    *,
    congress: int | None = None,
    chamber: str | None = None,
    subcommittee: str | None = None,
    stage: str | None = None,
    fiscal_year: int | None = None,
    fiscal_year_min: int | None = None,
    fiscal_year_max: int | None = None,
    account: str | None = None,
    account_key: str | None = None,
    designation: str | None = None,
    include_subtotals: bool = False,
) -> list[dict]:
    """Filter the dataset. `account` is a case-insensitive substring match."""
    rows = load_line_items() if rows is None else rows
    acct_needle = account.lower() if account else None
    sub = canon_subcommittee(subcommittee)
    out = []
    for r in rows:
        if not include_subtotals and r["is_subtotal"]:
            continue
        if congress is not None and r["congress"] != congress:
            continue
        if chamber is not None and (r["chamber"] or "") != chamber.lower():
            continue
        if sub is not None and r["subcommittee"] != sub:
            continue
        if stage is not None and (r["stage"] or "") != stage.lower():
            continue
        if fiscal_year is not None and r["fiscal_year"] != fiscal_year:
            continue
        if fiscal_year_min is not None and (r["fiscal_year"] or 0) < fiscal_year_min:
            continue
        if fiscal_year_max is not None and (r["fiscal_year"] or 9999) > fiscal_year_max:
            continue
        if account_key is not None and r["account_key"] != account_key:
            continue
        if designation is not None and r["designation"] != designation:
            continue
        if acct_needle is not None:
            hay = " ".join(
                filter(None, [r["account_effective"], r["line_item_text"], r["account_key_title"]])
            ).lower()
            if acct_needle not in hay:
                continue
        out.append(r)
    return out


@lru_cache
def facets() -> dict[str, list]:
    """Distinct filter values for populating UI controls."""
    rows = load_line_items()
    chambers, stages, subs, fys = set(), set(), set(), set()
    congresses = set()
    for r in rows:
        if r["chamber"]:
            chambers.add(r["chamber"])
        if r["stage"]:
            stages.add(r["stage"])
        if r["subcommittee"]:
            subs.add(r["subcommittee"])
        if r["fiscal_year"]:
            fys.add(r["fiscal_year"])
        if r["congress"]:
            congresses.add(r["congress"])
    return {
        "chambers": sorted(chambers),
        "stages": sorted(stages),
        "subcommittees": sorted(subs),
        "fiscal_years": sorted(fys),
        "congresses": sorted(congresses),
        "metrics": list(METRICS),
        "levels": list(FLOW_LEVELS),
    }


# The account is the finest grain the money reconciles at. Below it the source
# tables fragment (program breakdowns that don't cleanly sum), so `account` is
# the deepest level the flow diagram aggregates to.
FLOW_LEVELS = (
    "chamber",
    "stage",
    "subcommittee",
    "title_name",
    "department",
    "agency",
    "account",
)


def _account_identity(r: dict) -> str | None:
    """Stable identity for an account within a report, or None if unlabeled.

    Uses only the *trusted* tiers: crosswalk key and extracted/arithmetic-verified
    account name. The heuristic `account_recovered` is deliberately NOT used here —
    it names non-reconciling blocks whose amounts don't sum correctly, so folding
    them into the flow money would re-inflate the totals. Recovery is reported as a
    coverage diagnostic instead (see `dedupe_to_account_grain`).
    """
    return r["account_key"] or r["account_effective"]


def account_tier(r: dict) -> str:
    """Confidence tier of a row's account attribution.

    `named` — extracted or crosswalk-keyed, or arithmetic-verified inference.
    `recovered` — heuristic nearest-subtotal label (House recovery).
    `unlabeled` — no account at all.
    """
    if r["account_key"] or r["account_effective"]:
        return "named"
    if r.get("account_recovered"):
        return "recovered"
    return "unlabeled"


def dedupe_to_account_grain(rows: list[dict], metric: str) -> tuple[list[dict], dict]:
    """Collapse each labeled account within a report to one representative row.

    Two problems make raw summation wrong:

    1. Comparative statements list an account's total *and* its program breakdown,
       both as non-subtotal rows — summing both double-counts. We keep, per
       (report_id, account identity), the single largest-magnitude row, which is
       the account's own total (>= any child part). Rows whose *text* is a rollup
       the extractor didn't flag (`is_rollup_row`) are dropped for the same reason.
    2. Rows with no account label at any tier can't be placed in the flow, so they
       are excluded and counted for the coverage indicator.

    Only the trusted (named) tier enters the flow money. Excluded rows are split
    for the coverage indicator into `recovered` (structurally attributable to a
    section by the House recovery pass, but with amounts that don't reconcile — so
    not summed) and `unlabeled` (no account at any tier).

    Returns (deduped named-tier rows, coverage dict).
    """
    best: dict[tuple, dict] = {}
    recovered_rows = unlabeled_rows = 0
    for r in rows:
        val = r.get(metric)
        if val is None or r.get("is_rollup_row"):
            continue
        ident = _account_identity(r)
        if ident is None:
            if r.get("account_recovered"):
                recovered_rows += 1
            else:
                unlabeled_rows += 1
            continue
        key = (r["report_id"], ident)
        cur = best.get(key)
        if cur is None or abs(val) > abs(cur.get(metric) or 0):
            best[key] = r
    deduped = list(best.values())
    coverage = {
        "accounts": len(deduped),
        "recovered_attributable_rows": recovered_rows,
        "unlabeled_rows": unlabeled_rows,
    }
    return deduped, coverage


def build_flow(
    *,
    metric: str = "committee_recommendation",
    levels: list[str] | None = None,
    chamber: str | None = None,
    subcommittee: str | None = None,
    stage: str | None = None,
    fiscal_year: int | None = None,
    top: int = 12,
) -> dict:
    """Aggregate one money metric into Sankey `{nodes, links}`.

    Rows are first de-duplicated to account grain (see `dedupe_to_account_grain`)
    so account totals and their program sub-rows are not double-counted. The
    resulting per-account amounts then flow along the path defined by `levels`.
    Blank level values coalesce to "(unspecified)". Negative amounts
    (rescissions/offsets) are preserved.

    `top` caps the number of distinct values kept per level (by absolute total);
    the remainder is folded into a single "(other)" node so the graph stays legible.
    """
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {METRICS}")
    levels = levels or ["subcommittee", "title_name", "account"]
    for lv in levels:
        if lv not in FLOW_LEVELS:
            raise ValueError(f"unknown flow level {lv!r}; choose from {FLOW_LEVELS}")

    rows, coverage = dedupe_to_account_grain(
        filter_items(
            chamber=chamber,
            subcommittee=subcommittee,
            stage=stage,
            fiscal_year=fiscal_year,
            include_subtotals=False,
        ),
        metric,
    )

    def level_value(r: dict, lv: str) -> str:
        if lv == "account":
            v = r["account_effective"] or r["account_key"]
        else:
            v = r.get(lv)
        return v if v else _UNSPECIFIED

    # Drop levels that are mostly blank for this selection (e.g. department/agency
    # are sparse for Labor-HHS but populated for Defense). Otherwise they collapse
    # into a single giant "(unspecified)" column and muddy the flow. Always keep at
    # least two levels; prefer the least-sparse when everything is thin.
    def unspec_fraction(lv: str) -> float:
        tot = uns = 0.0
        for r in rows:
            v = r.get(metric)
            if v is None:
                continue
            tot += abs(v)
            if level_value(r, lv) == _UNSPECIFIED:
                uns += abs(v)
        return uns / tot if tot else 1.0

    fractions = {lv: unspec_fraction(lv) for lv in levels}
    kept = [lv for lv in levels if fractions[lv] < 0.6]
    if len(kept) < 2:
        kept = sorted(levels, key=lambda lv: fractions[lv])[:2]
        kept = [lv for lv in levels if lv in kept]  # restore original order
    levels = kept

    # First pass: rank values per level by absolute magnitude so we can keep the
    # biggest `top` and bucket the rest into "(other)".
    per_level_totals: list[dict[str, float]] = [{} for _ in levels]
    for r in rows:
        val = r.get(metric)
        if val is None:
            continue
        for i, lv in enumerate(levels):
            key = level_value(r, lv)
            per_level_totals[i][key] = per_level_totals[i].get(key, 0) + abs(val)

    keep: list[set[str]] = []
    for totals in per_level_totals:
        ranked = sorted(totals, key=lambda k: totals[k], reverse=True)
        keep.append(set(ranked[:top]))

    def bucket(value: str, i: int) -> str:
        return value if value in keep[i] else "(other)"

    node_index: dict[tuple[int, str], int] = {}
    nodes: list[dict] = []

    def node_id(level_idx: int, name: str) -> int:
        k = (level_idx, name)
        if k not in node_index:
            node_index[k] = len(nodes)
            nodes.append({"id": len(nodes), "name": name, "level": level_idx, "total": 0.0})
        return node_index[k]

    links: dict[tuple[int, int], float] = {}
    for r in rows:
        val = r.get(metric)
        if val is None:
            continue
        path = [node_id(i, bucket(level_value(r, lv), i)) for i, lv in enumerate(levels)]
        for nid in path:
            nodes[nid]["total"] += val
        for a, b in zip(path, path[1:]):
            links[(a, b)] = links.get((a, b), 0.0) + val

    coverage["total_flowed"] = sum(r[metric] for r in rows)
    return {
        "metric": metric,
        "levels": levels,
        "nodes": nodes,
        "links": [
            {"source": a, "target": b, "value": v}
            for (a, b), v in links.items()
        ],
        "coverage": coverage,
    }
