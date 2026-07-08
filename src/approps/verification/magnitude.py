"""Absolute-magnitude sanity check — the error class arithmetic verification cannot see.

Every other gate in this pipeline checks *internal consistency*: the delta identity closes, a
subtotal block sums, an amount is restated in prose. All of them are **scale-invariant**.
Multiply `prior_year_enacted`, `budget_estimate`, and `committee_recommendation` by the same
constant and

    committee_recommendation - prior_year_enacted == delta_vs_enacted

still holds exactly. A units bug therefore sails through verification wearing the strongest
corroboration tier the pipeline can award. That is not hypothetical: the enacted extractor
multiplied 11,829 rows by 1,000 and every single one came out `verified=True, tier=verbatim_page`
(docs/KNOWN_ISSUES.md #4).

Catching a uniform rescale requires comparing against something *outside* the row. The only
such anchor available here without a second data source is absolute plausibility: no
appropriation is larger than the federal budget.

Scope, honestly: this is a coarse tripwire. It catches a rescale of an already-large line
($32B -> $32T) and is blind to a rescale of a small one ($5M -> $5B). It is a backstop, not a
guarantee. The primary defense is upstream — an extractor must require *positive evidence*
before scaling units, never assume a scale by default. See `comparative_enacted`.

Things that were tried and rejected:

- **Cross-stage peak ratios** (is the enacted peak wildly larger than the committee peak for
  the same year?). Confounded by document granularity: committee reports carry bill-wide
  "Grand Total" rows near $1.5T, while enacted prints top out at division totals near $32B.
  On *corrected* data the ratio runs 45-1379x, larger than the 19-22x seen on the buggy data.
  The check fires harder on correct input than on broken input.
- **"A thousands table never prints a `$` sign"**. True for 348 of 350 sampled thousands-page
  amounts, but not the 2 exceptions — a ~99.4% heuristic, not an invariant, and noisy enough
  that its warnings would be tuned out.
"""

from __future__ import annotations

from dataclasses import dataclass

from approps.output.schemas import ComparativeStatementLine

# No single appropriations line item plausibly exceeds this. Total annual federal budget
# authority is roughly $7T; the largest *legitimate* line in this corpus is a $1.7T
# "Grand Total" row in a House committee report. $3T clears the real data with headroom
# while still catching an order-of-magnitude rescale.
LINE_ITEM_CEILING = 3_000_000_000_000


@dataclass(frozen=True)
class MagnitudeFinding:
    report_id: str
    fiscal_year: int | None
    line_item_text: str
    amount: int
    reason: str

    def __str__(self) -> str:
        return f"{self.report_id} FY{self.fiscal_year}: ${self.amount:,} — {self.reason} — {self.line_item_text!r}"


def _amounts(line: ComparativeStatementLine) -> list[int]:
    values = []
    for field in ("prior_year_enacted", "budget_estimate", "committee_recommendation"):
        amount = getattr(line, field, None)
        if amount is not None and amount.value is not None:
            values.append(amount.value)
    return values


def oversized_line_items(
    lines: list[ComparativeStatementLine],
    ceiling: int = LINE_ITEM_CEILING,
) -> list[MagnitudeFinding]:
    """Line items carrying an amount larger than any plausible appropriation.

    One finding per offending line, keyed on its first offending amount.
    """
    findings: list[MagnitudeFinding] = []
    for line in lines:
        for value in _amounts(line):
            if abs(value) > ceiling:
                findings.append(
                    MagnitudeFinding(
                        report_id=line.report_id,
                        fiscal_year=line.fiscal_year,
                        line_item_text=line.line_item_text[:60],
                        amount=value,
                        reason=f"exceeds ${ceiling:,} plausibility ceiling",
                    )
                )
                break
    return findings
