"""Cross-row reconciliation: do the line items add up to the totals the report printed?

Every other gate in this package validates a row against *itself* or against the string it
was read from. ``amount_verifier`` proves the digits were transcribed correctly.
``cross_check.check_delta`` proves the row's own delta columns are self-consistent. Neither
can see an error that is uniform across a row's columns, because both compare the row only
to itself.

The printed subtotal is an **independent witness**. It was set in type by the committee, it
is not derived from the columns we parsed, and it constrains the rows above it. Checking the
line items against it is therefore the only gate here that can catch a misinterpretation --
as opposed to a mistranscription -- of the source. It is also the check appropriations staff
actually perform by hand: highlight the account rows, compare the sum to the recap.

Two source conventions make this non-trivial, and both are load-bearing:

* **Parenthesized amounts are positive memos, but whether they are summed is decided by the
  total, not by the parentheses.** ``(35,000)`` is never ``-35,000`` -- real negatives print an
  explicit minus (``-2,000``). But the same parenthesized row can be additive at one level and
  non-add at the next. In CRPT-114srpt68, ``Operating expenses 134,488`` plus
  ``(By transfer from Disaster Relief) (24,000)`` is exactly the printed
  ``Total, Office of Inspector General 158,488`` -- the transfer is *added*. One line further
  down, ``Total, title I`` excludes that same 24,000, because the money was appropriated under
  Disaster Relief and counting it twice would inflate the bill.

  So ``is_memo`` is treated here as a *hypothesis*, not a fact. For each total the
  reconciler sums its children both ways -- memos excluded, then memos included -- and lets the
  printed figure adjudicate, recording which reading it endorsed in ``memo_mode``. Exclusion is
  tried first, since it is the documented convention. This is the same arithmetic double-gate
  the House indent recovery uses: a grouping is accepted only because the sum closes, never
  because the shape looked right.

  Note that this cannot launder a sign error. A row whose ``(35,000)`` was parsed as
  ``-35,000`` is not flagged as a memo at all, so it is a mandatory child in both readings and
  the total still fails.

* **Indentation depth is unreliable.** Total rows are often typeset further right than the
  children they summarize, and the enacted explanatory statements flatten every account to
  depth 0. So nesting is recovered from *document order* instead: each total consumes the
  shortest contiguous run of preceding unconsumed nodes that sums to it, and is then pushed
  back as a single node so that a parent total rolls up its child totals without ever
  consulting a depth label.

When a total fails, its block is still consumed (the run whose sum comes closest is taken).
A total row terminates the lines beneath it whether or not it reconciled, so consuming the
block keeps one bad total from cascading into every ancestor above it -- the failure stays
localized to the row that actually failed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

#: The three columns that carry a funding *level* (as opposed to a delta between levels).
#: Structure is recovered from the primary column, then every level column is checked
#: against that same structure -- a column that ties on a different child set is a signal.
LEVEL_COLUMNS: tuple[str, ...] = (
    "prior_year_enacted",
    "budget_estimate",
    "committee_recommendation",
)

PRIMARY_COLUMN = "committee_recommendation"

#: A total is "off by a rounding hair" when it misses by no more than this fraction.
#: Chosen to separate a single dropped or misread line from a structural mismatch.
SMALL_MISS = 0.02


class Status(StrEnum):
    """Why a printed total did or did not equal the sum of its line items."""

    OK = "ok"
    """The children sum to the printed total, exactly, to the dollar."""

    OFF_BY_SMALL = "off_by_small"
    """Missed by <=2% -- one line dropped or misread. A genuine extraction gap."""

    PARTIAL_READ = "partial_read"
    """A child carries amounts in other columns but not the primary one: a value we lost."""

    OVERLAPPING_VIEW = "overlapping_view"
    """Not a sum of its children *by construction* -- an advance-appropriation or
    forward-funding total re-aggregates the same rows under a different view (appropriated
    in this bill vs available this year vs advance for next). Unmeasurable, not an error."""

    UNRECONCILED = "unreconciled"
    """Children do not sum to the total and none of the above explains it."""

    UNCHECKED = "unchecked"
    """The total row printed no amount in the primary column (a dot leader), so there is
    nothing to check it against."""


#: Labels that mark a total which re-aggregates rows already counted elsewhere. Such totals
#: are not the sum of any contiguous run of children, so a sum check cannot validate them.
_OVERLAPPING_VIEW_MARKERS = (
    "advance",
    "available this fiscal",
    "appropriated in this bill",
    "forward fund",
    "less prior year",
    "prior year appropriation",
    "available in",
    "to remain available",
)

_ROLLUP_TEXT = re.compile(r"(?i)^\s*\(?(sub)?total\b")


@dataclass(frozen=True)
class ColumnCheck:
    """One printed total vs the sum of its children, for a single amount column."""

    column: str
    printed: int | None
    computed: int | None
    complete: bool
    """Every child carried a value in this column. When False, ``computed`` sums only the
    children that had one, so a nonzero ``delta`` may reflect the gap rather than an error."""

    @property
    def delta(self) -> int | None:
        if self.printed is None or self.computed is None:
            return None
        return self.printed - self.computed

    @property
    def ok(self) -> bool:
        return self.complete and self.delta == 0


class MemoMode(StrEnum):
    """Which reading of the parenthesized memo rows the printed total endorsed."""

    EXCLUDED = "excluded"
    """Memos in this block are non-add. The documented convention, and tried first."""

    INCLUDED = "included"
    """The total only closes with its memos summed in -- a transfer that really is
    additional budget authority at this level (see the module docstring)."""


@dataclass(frozen=True)
class TotalCheck:
    """A printed total row, the rows it consumed, and whether they add up."""

    index: int
    """Row position within the report, in document order."""
    label: str
    status: Status
    child_indices: tuple[int, ...]
    columns: dict[str, ColumnCheck]
    memo_mode: MemoMode = MemoMode.EXCLUDED
    """Only meaningful when the block actually contained a memo row."""

    @property
    def primary(self) -> ColumnCheck:
        return self.columns[PRIMARY_COLUMN]

    @property
    def delta(self) -> int | None:
        return self.primary.delta

    @property
    def is_genuine_failure(self) -> bool:
        """A failure attributable to the extraction, not to the shape of the source table."""
        return self.status in (Status.OFF_BY_SMALL, Status.PARTIAL_READ, Status.UNRECONCILED)


@dataclass
class ReportReconciliation:
    """Every printed total in one report, checked."""

    report_id: str
    checks: list[TotalCheck] = field(default_factory=list)
    n_rows: int = 0
    n_memo: int = 0

    @property
    def checkable(self) -> list[TotalCheck]:
        return [c for c in self.checks if c.status is not Status.UNCHECKED]

    @property
    def n_ok(self) -> int:
        return sum(1 for c in self.checks if c.status is Status.OK)

    @property
    def n_genuine_failures(self) -> int:
        return sum(1 for c in self.checks if c.is_genuine_failure)

    @property
    def pass_rate(self) -> float | None:
        """Share of checkable totals that tie exactly. None when nothing is checkable."""
        checkable = self.checkable
        return self.n_ok / len(checkable) if checkable else None

    @property
    def strict_pass_rate(self) -> float | None:
        """Pass rate excluding overlapping-view totals, which no sum check can validate."""
        pool = [c for c in self.checkable if c.status is not Status.OVERLAPPING_VIEW]
        return sum(1 for c in pool if c.status is Status.OK) / len(pool) if pool else None


@dataclass(frozen=True)
class _Node:
    """An unconsumed contributor to some not-yet-seen total: a leaf, or a total that has
    already absorbed its own children and now stands in for the whole block."""

    index: int
    primary: int
    values: dict[str, int | None]
    optional: bool = False
    """A parenthesized memo. Whether it contributes is decided by the enclosing total."""


def _value(row: dict, column: str) -> int | None:
    v = row.get(column)
    return int(v) if v is not None else None


def recover_primary(row: dict) -> int | None:
    """The recommendation, recovering it from the delta identity when the column is blank.

    A program recommended at $0 often prints as a dot leader and parses to None, yet its true
    level is ``prior + delta_enacted`` or ``budget + delta_estimate``. Recovering it lets a
    zeroed-out line contribute 0 to its subtotal instead of being skipped -- and stops it
    being misread as a dropped value. Both derivations must agree, so a single misread column
    cannot invent a level.
    """
    direct = _value(row, PRIMARY_COLUMN)
    if direct is not None:
        return direct

    candidates = []
    prior, d_prior = _value(row, "prior_year_enacted"), _value(row, "delta_vs_enacted")
    budget, d_budget = _value(row, "budget_estimate"), _value(row, "delta_vs_estimate")
    if prior is not None and d_prior is not None:
        candidates.append(prior + d_prior)
    if budget is not None and d_budget is not None:
        candidates.append(budget + d_budget)
    if candidates and all(c == candidates[0] for c in candidates):
        return candidates[0]
    return None


def is_memo(row: dict) -> bool:
    """Whether the dataset flagged this row as a memo line.

    Deliberately reads the published flag rather than re-deriving the parenthesis convention:
    reconciliation is meant to be an *independent* witness to the flag's correctness, and a
    reconciler that re-applied the same rule could never disagree with it.

    A memo is a *candidate* for exclusion, never a decision. ``_best_run`` sums the block both
    ways and lets the printed total settle it.
    """
    return bool(row.get("is_memo"))


def is_total(row: dict) -> bool:
    return bool(row.get("is_subtotal")) or bool(_ROLLUP_TEXT.match(row.get("line_item_text") or ""))


def _has_other_value(row: dict) -> bool:
    """A row that carries some amount, just not one we could read into the primary column."""
    return any(
        _value(row, c) is not None
        for c in ("prior_year_enacted", "budget_estimate", "delta_vs_enacted", "delta_vs_estimate")
    )


def _looks_overlapping(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in _OVERLAPPING_VIEW_MARKERS)


def _classify(rows: list[dict], anchor: int, index: int, printed: int, delta: int) -> Status:
    """Why this total missed. Order matters: an unmeasurable total is not an error."""
    window = rows[anchor + 1 : index]
    if _looks_overlapping(rows[index].get("line_item_text") or "") or any(
        _looks_overlapping(r.get("line_item_text") or "") for r in window
    ):
        return Status.OVERLAPPING_VIEW
    for r in window:
        if not is_total(r) and not is_memo(r) and recover_primary(r) is None and _has_other_value(r):
            return Status.PARTIAL_READ
    if printed and abs(delta) / abs(printed) <= SMALL_MISS:
        return Status.OFF_BY_SMALL
    return Status.UNRECONCILED


def _best_run(nodes: list[_Node], printed: int) -> tuple[int, int, MemoMode]:
    """The trailing run of nodes that best explains ``printed``: ``(length, delta, mode)``.

    Prefers the *shortest* run that hits the total exactly, and at a given length prefers the
    reading that excludes memo rows -- the documented convention. Failing an exact hit, returns
    the run whose sum comes closest, so the reported delta is the smallest honest statement of
    how far off we are and the consumed block is the most plausible child set.

    A reading that would leave the total with no children at all is never chosen: an all-memo
    block summing to a printed zero is not evidence of anything.
    """
    best_k, best_delta, best_mode = 0, printed, MemoMode.EXCLUDED
    running_included = 0
    running_excluded = 0
    mandatory = 0

    for k in range(1, len(nodes) + 1):
        node = nodes[-k]
        running_included += node.primary
        if not node.optional:
            running_excluded += node.primary
            mandatory += 1

        readings = []
        if mandatory:
            readings.append((MemoMode.EXCLUDED, running_excluded))
        readings.append((MemoMode.INCLUDED, running_included))

        for mode, total in readings:
            delta = printed - total
            if delta == 0:
                return k, 0, mode
            if best_k == 0 or abs(delta) < abs(best_delta):
                best_k, best_delta, best_mode = k, delta, mode

    return best_k, best_delta, best_mode


def reconcile_report(report_id: str, rows: list[dict]) -> ReportReconciliation:
    """Check every printed total in one report against the line items above it.

    ``rows`` must be in document order, each a mapping with ``line_item_text``,
    ``is_subtotal``, ``is_memo`` and the five amount columns as ints or None.
    """
    result = ReportReconciliation(report_id=report_id, n_rows=len(rows))
    nodes: list[_Node] = []
    anchor = -1

    for index, row in enumerate(rows):
        memo = is_memo(row)
        primary = recover_primary(row)
        values = {c: _value(row, c) for c in LEVEL_COLUMNS}
        values[PRIMARY_COLUMN] = primary

        if memo:
            result.n_memo += 1

        if not is_total(row):
            # Memos are pushed as optional nodes rather than dropped: the enclosing total,
            # not the parentheses, decides whether they are summed.
            if primary is not None:
                nodes.append(_Node(index=index, primary=primary, values=values, optional=memo))
            continue

        label = row.get("line_item_text") or ""

        if primary is None:
            # A dot-leader total. It witnesses nothing, so leave the stack alone: its children
            # remain available to whatever real total encloses them.
            result.checks.append(
                TotalCheck(
                    index=index,
                    label=label,
                    status=Status.UNCHECKED,
                    child_indices=(),
                    columns={c: ColumnCheck(c, values[c], None, False) for c in LEVEL_COLUMNS},
                )
            )
            continue

        length, delta, mode = _best_run(nodes, primary)
        run = nodes[len(nodes) - length :] if length else []
        if length:
            del nodes[len(nodes) - length :]

        # A memo consumed under EXCLUDED is still consumed -- it belongs to this block, it just
        # does not contribute to it. Leaving it on the stack would corrupt the next total.
        children = run if mode is MemoMode.INCLUDED else [n for n in run if not n.optional]

        status = (
            Status.OK if delta == 0 and children else _classify(rows, anchor, index, primary, delta)
        )

        columns: dict[str, ColumnCheck] = {}
        for column in LEVEL_COLUMNS:
            child_values = [c.values.get(column) for c in children]
            complete = bool(child_values) and all(v is not None for v in child_values)
            computed = sum(v for v in child_values if v is not None) if child_values else None
            columns[column] = ColumnCheck(column, values[column], computed, complete)

        result.checks.append(
            TotalCheck(
                index=index,
                label=label,
                status=status,
                child_indices=tuple(c.index for c in children),
                columns=columns,
                memo_mode=mode,
            )
        )

        nodes.append(_Node(index=index, primary=primary, values=values))
        anchor = index

    return result


def reconcile_corpus(rows_by_report: dict[str, list[dict]]) -> list[ReportReconciliation]:
    return [reconcile_report(rid, rows) for rid, rows in rows_by_report.items()]


def summarize(results: list[ReportReconciliation]) -> dict[str, object]:
    """Corpus-level counts, split into what a sum check can and cannot adjudicate."""
    counts = dict.fromkeys(Status, 0)
    for result in results:
        for check in result.checks:
            counts[check.status] += 1

    checkable = sum(v for k, v in counts.items() if k is not Status.UNCHECKED)
    measurable = checkable - counts[Status.OVERLAPPING_VIEW]
    genuine = counts[Status.OFF_BY_SMALL] + counts[Status.PARTIAL_READ] + counts[Status.UNRECONCILED]
    return {
        "reports": len(results),
        "totals": sum(len(r.checks) for r in results),
        "checkable": checkable,
        "measurable": measurable,
        "ok": counts[Status.OK],
        "genuine_failures": genuine,
        "pass_rate": counts[Status.OK] / checkable if checkable else None,
        "strict_pass_rate": counts[Status.OK] / measurable if measurable else None,
        "by_status": {k.value: v for k, v in counts.items()},
    }
