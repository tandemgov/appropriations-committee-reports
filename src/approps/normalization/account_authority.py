"""Cross-year account authority — follow one account through time.

Groups every crosswalk-keyed line item by its authoritative account code
(`account_key`) — the stable identity that survives a title change — and
reconstructs, per account:

  * the **money series** across fiscal years (chamber/stage aware),
  * the **label timeline**: how the source documents *named* that account each year,
  * the **title changes** between consecutive years, classified case/prefix/reword.

This is the report-stage analogue of tracing an appropriation across bills by its
Treasury/OMB account symbol (the approach cgorski/congress-appropriations takes on
enacted-bill text): the code is the identity, the visible name is just a label that
drifts. Because `account_key` is an authoritative federal-account code (see
normalization.crosswalk), two reports that spell an account differently still line
up, and a genuine rename shows up as a label change under an unchanged key.

Two honest caveats about the "title changes" this surfaces:
  * Only rows carrying a trusted `account_key` participate — the coarser tiers
    (`account_effective`, `account_recovered`) have no stable cross-year identity,
    so unkeyed rows are out of scope by design.
  * A label change is not always a real rename. Because the crosswalk sometimes
    folds several distinct programs under one account code, a `reword` change can
    equally flag a crosswalk over-merge — which makes this a useful QA lens on the
    crosswalk itself, not only a rename detector.

Pure over the enriched output-row dicts produced by the output step /
`api.data.load_line_items` (it reads their precomputed `account_effective` /
`is_rollup_row` when present, and falls back to computing them). No I/O.
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass

from approps.normalization.account_inference import _is_rollup

# The three money figures a line item can carry; any is a valid series metric.
METRICS = ("prior_year_enacted", "budget_estimate", "committee_recommendation")


# --- row field access (tolerant of both parsed and raw-CSV row dicts) ----


def _num(v: object) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s in ("", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _observed_title(r: dict) -> str:
    """The label the source document gave this row, best trusted tier first."""
    return (
        r.get("account_effective")
        or r.get("account")
        or r.get("account_inferred")
        or ""
    ).strip()


def _is_rollup_row(r: dict) -> bool:
    v = r.get("is_rollup_row")
    if v is not None:
        return bool(v)
    return _is_rollup(
        {"is_subtotal": r.get("is_subtotal"), "line_item_text": r.get("line_item_text")}
    )


def _fiscal_year(r: dict) -> int | None:
    fy = r.get("fiscal_year")
    if fy in (None, ""):
        return None
    try:
        return int(fy)
    except (TypeError, ValueError):
        return None


# --- title-change classification -----------------------------------------


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def classify_title_change(prev: str, cur: str) -> str:
    """Classify a transition between two observed labels.

    `case`   — identical apart from case/punctuation/whitespace.
    `prefix` — one label's tokens are a leading run of the other's (an expansion or
               contraction, e.g. "office of the secretary" ->
               "office of the secretary and executive management").
    `reword` — a substantive change (the interesting, rename-like case).
    """
    a, b = _norm_title(prev), _norm_title(cur)
    if a == b:
        return "case"
    at, bt = a.split(), b.split()
    if at[: len(bt)] == bt or bt[: len(at)] == at:
        return "prefix"
    return "reword"


# --- data model ----------------------------------------------------------


@dataclass(frozen=True)
class MoneyPoint:
    fiscal_year: int
    chamber: str | None
    stage: str | None
    amount: float | None
    # Reports that each claim this account for the same year, chamber, and stage; `amount` is then None, never their sum.
    conflict: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        d = {
            "fiscal_year": self.fiscal_year,
            "chamber": self.chamber,
            "stage": self.stage,
            "amount": self.amount,
        }
        if self.conflict:
            d["conflict"] = list(self.conflict)
        return d


@dataclass(frozen=True)
class LabelSpan:
    """One observed label and the fiscal years it appeared in."""

    title: str
    fiscal_years: tuple[int, ...]

    def to_dict(self) -> dict:
        return {"title": self.title, "fiscal_years": list(self.fiscal_years)}


@dataclass(frozen=True)
class TitleChange:
    fiscal_year: int  # first year the new dominant label takes over
    from_title: str
    to_title: str
    kind: str  # case | prefix | reword

    def to_dict(self) -> dict:
        return {
            "fiscal_year": self.fiscal_year,
            "from_title": self.from_title,
            "to_title": self.to_title,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class AccountAuthority:
    account_key: str
    canonical_title: str | None  # the authoritative crosswalk title (stable)
    first_fiscal_year: int
    last_fiscal_year: int
    fiscal_years: tuple[int, ...]
    labels: tuple[LabelSpan, ...]
    title_changes: tuple[TitleChange, ...]
    series: tuple[MoneyPoint, ...]
    report_count: int
    metric: str

    def to_dict(self) -> dict:
        return {
            "account_key": self.account_key,
            "canonical_title": self.canonical_title,
            "first_fiscal_year": self.first_fiscal_year,
            "last_fiscal_year": self.last_fiscal_year,
            "fiscal_years": list(self.fiscal_years),
            "labels": [x.to_dict() for x in self.labels],
            "title_changes": [x.to_dict() for x in self.title_changes],
            "series": [x.to_dict() for x in self.series],
            "report_count": self.report_count,
            "metric": self.metric,
        }


# --- construction --------------------------------------------------------


def _representatives(rows: list[dict], metric: str) -> list[dict]:
    """One row per (report, account_key), carrying the account's total for `metric`.

    Comparative statements list an account's own line *and* its program breakdown, both as ordinary rows; summing both double-counts.
    The total is chosen by `normalization.account_totals` — the account's own line, or nothing — the same rule the flow layer and `/compare` use.
    Accounts it cannot resolve, and rows lacking the metric or a fiscal year, are skipped.
    """
    from approps.normalization.account_totals import account_totals

    reps = []
    for t in account_totals([r for r in rows if not _is_rollup_row(r)]):
        value = getattr(t, metric)
        if t.method == "unresolved" or value is None or t.fiscal_year is None:
            continue
        rep = dict(t.chosen[0])
        rep[metric] = value
        reps.append(rep)
    return reps


def _dominant_label_by_year(group: list[dict], metric: str) -> dict[int, str]:
    """The label carrying the most money in each fiscal year (deterministic ties)."""
    weight: dict[int, dict[str, list]] = collections.defaultdict(
        lambda: collections.defaultdict(lambda: [0.0, 0])
    )
    for r in group:
        title = _observed_title(r)
        fy = _fiscal_year(r)
        if not title or fy is None:
            continue
        cell = weight[fy][title]
        cell[0] += abs(_num(r.get(metric)) or 0.0)
        cell[1] += 1
    dominant: dict[int, str] = {}
    for fy, titles in weight.items():
        # magnitude desc, then frequency desc, then title asc for stability.
        dominant[fy] = sorted(
            titles.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0])
        )[0][0]
    return dominant


def trace_accounts(
    rows: list[dict], *, metric: str = "committee_recommendation", min_years: int = 1
) -> list[AccountAuthority]:
    """Group crosswalk-keyed rows into cross-year account authorities.

    `min_years` keeps only accounts observed in at least that many distinct fiscal
    years (use 2 to focus on genuinely longitudinal accounts). Results are sorted
    by account_key.
    """
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {METRICS}")

    reps = _representatives(rows, metric)
    by_key: dict[str, list[dict]] = collections.defaultdict(list)
    for r in reps:
        by_key[r["account_key"]].append(r)

    out: list[AccountAuthority] = []
    for key, group in by_key.items():
        years = sorted({_fiscal_year(r) for r in group if _fiscal_year(r) is not None})
        if len(years) < min_years:
            continue

        canonical = next(
            (r.get("account_key_title") for r in group if r.get("account_key_title")),
            None,
        )

        # Money series: one representative per (fiscal_year, chamber, stage).
        # Two reports claiming the same cell are a conflict, as in account_totals.account_series: usually one of them is keyed wrongly, and their sum is nobody's figure.
        cells: dict[tuple, list[dict]] = collections.defaultdict(list)
        for r in group:
            cells[(_fiscal_year(r), r.get("chamber"), r.get("stage"))].append(r)
        series = tuple(
            MoneyPoint(fy, ch, st, round(_num(rs[0].get(metric)) or 0.0))
            if len(rs) == 1
            else MoneyPoint(fy, ch, st, None, tuple(sorted(str(r.get("report_id")) for r in rs)))
            for (fy, ch, st), rs in sorted(cells.items(), key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2] or ""))
        )
        conflicted = {id(r) for rs in cells.values() if len(rs) > 1 for r in rs}
        # Labels and title changes come only from uncontested cells, so a wrongly keyed report cannot look like a rename.
        group = [r for r in group if id(r) not in conflicted]

        # Label timeline: each observed label and the years it appeared.
        label_years: dict[str, set] = collections.defaultdict(set)
        for r in group:
            title = _observed_title(r)
            fy = _fiscal_year(r)
            if title and fy is not None:
                label_years[title].add(fy)
        labels = tuple(
            LabelSpan(title, tuple(sorted(ys)))
            for title, ys in sorted(
                label_years.items(), key=lambda kv: (min(kv[1]), kv[0])
            )
        )

        # Title changes: walk the dominant label year over year.
        dominant = _dominant_label_by_year(group, metric)
        changes: list[TitleChange] = []
        prev: str | None = None
        for fy in years:
            cur = dominant.get(fy)
            if cur is None:
                continue
            if prev is not None and _norm_title(prev) != _norm_title(cur):
                changes.append(
                    TitleChange(fy, prev, cur, classify_title_change(prev, cur))
                )
            prev = cur

        out.append(
            AccountAuthority(
                account_key=key,
                canonical_title=canonical,
                first_fiscal_year=years[0],
                last_fiscal_year=years[-1],
                fiscal_years=tuple(years),
                labels=labels,
                title_changes=tuple(changes),
                series=series,
                report_count=len({r.get("report_id") for r in group}),
                metric=metric,
            )
        )

    out.sort(key=lambda a: a.account_key)
    return out


def trace_account(
    rows: list[dict], account_key: str, *, metric: str = "committee_recommendation"
) -> AccountAuthority | None:
    """Trace a single account by its crosswalk key, or None if it has no keyed rows."""
    keyed = [r for r in rows if r.get("account_key") == account_key]
    result = trace_accounts(keyed, metric=metric, min_years=1)
    return result[0] if result else None
