"""Arithmetic cross-checks for extracted data.

Validates that subtotals sum correctly and deltas are computed correctly.
"""

from __future__ import annotations

from approps.output.schemas import ComparativeStatementLine, CrossCheckResult


def check_subtotal(
    subtotal_line: ComparativeStatementLine,
    children: list[ComparativeStatementLine],
    column: str = "committee_recommendation",
) -> CrossCheckResult:
    """Check that a subtotal line equals the sum of its children for a given column.

    Args:
        subtotal_line: The subtotal/total line
        children: The child line items that should sum to the subtotal
        column: Which dollar column to check

    Returns:
        CrossCheckResult indicating pass/fail
    """
    def _get_value(line: ComparativeStatementLine, col: str) -> int:
        amount = getattr(line, col, None)
        if amount is None:
            return 0
        return amount.value or 0

    expected = _get_value(subtotal_line, column)
    computed = sum(_get_value(child, column) for child in children)
    difference = expected - computed

    return CrossCheckResult(
        line_item_text=subtotal_line.line_item_text,
        expected_total=expected,
        computed_total=computed,
        difference=difference,
        passed=(difference == 0),
        children=[c.line_item_text for c in children],
    )


def check_delta(line: ComparativeStatementLine) -> list[CrossCheckResult]:
    """Check that delta columns equal recommendation minus base.

    Checks:
    - delta_vs_enacted = committee_recommendation - prior_year_enacted
    - delta_vs_estimate = committee_recommendation - budget_estimate
    """
    results = []

    rec = line.committee_recommendation
    prior = line.prior_year_enacted
    est = line.budget_estimate
    d_enacted = line.delta_vs_enacted
    d_estimate = line.delta_vs_estimate

    if rec and prior and d_enacted and rec.value is not None and prior.value is not None:
        expected = d_enacted.value or 0
        computed = (rec.value or 0) - (prior.value or 0)
        results.append(CrossCheckResult(
            line_item_text=f"{line.line_item_text} (delta_vs_enacted)",
            expected_total=expected,
            computed_total=computed,
            difference=expected - computed,
            passed=(expected == computed),
        ))

    if rec and est and d_estimate and rec.value is not None and est.value is not None:
        expected = d_estimate.value or 0
        computed = (rec.value or 0) - (est.value or 0)
        results.append(CrossCheckResult(
            line_item_text=f"{line.line_item_text} (delta_vs_estimate)",
            expected_total=expected,
            computed_total=computed,
            difference=expected - computed,
            passed=(expected == computed),
        ))

    return results
