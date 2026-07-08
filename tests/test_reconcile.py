"""Line items must add up to the totals the report printed."""

from __future__ import annotations

from approps.verification.reconcile import (
    PRIMARY_COLUMN,
    MemoMode,
    Status,
    reconcile_report,
    recover_primary,
    summarize,
)


def _leaf(text, rec=None, prior=None, budget=None, d_prior=None, d_budget=None, non_add=False):
    return {
        "line_item_text": text,
        "is_subtotal": False,
        "is_memo": non_add,
        "committee_recommendation": rec,
        "prior_year_enacted": prior,
        "budget_estimate": budget,
        "delta_vs_enacted": d_prior,
        "delta_vs_estimate": d_budget,
    }


def _total(text, rec=None, prior=None, budget=None):
    row = _leaf(text, rec=rec, prior=prior, budget=budget)
    row["is_subtotal"] = True
    return row


def _statuses(result):
    return [c.status for c in result.checks]


def test_a_block_of_leaves_sums_to_its_printed_subtotal():
    rows = [_leaf("Rangeland", 112_340), _leaf("Forestry", 10_814), _total("Subtotal", 123_154)]
    result = reconcile_report("R", rows)
    (check,) = result.checks
    assert check.status is Status.OK
    assert check.delta == 0
    assert check.child_indices == (0, 1)
    assert result.pass_rate == 1.0


def test_flagged_non_add_memo_is_excluded_from_the_sum():
    """CRPT-118srpt83: 149,938 + 59,247 = 209,185. The (35,000) memo sits between them."""
    rows = [
        _leaf("Wildlife habitat management", 149_938),
        _leaf("Threatened and endangered species", 35_000, non_add=True),
        _leaf("Aquatic habitat management", 59_247),
        _total("Subtotal", 209_185),
    ]
    result = reconcile_report("CRPT-118srpt83", rows)
    (check,) = result.checks
    assert check.status is Status.OK
    assert check.child_indices == (0, 2)
    assert result.n_memo == 1


def test_an_unflagged_non_add_memo_breaks_the_block():
    """The regression this module exists to catch. A parenthesized memo parsed as a negative
    and left unflagged is arithmetically invisible to every row-local check, and shows up
    only here -- as a subtotal that does not add up."""
    rows = [
        _leaf("Wildlife habitat management", 149_938),
        _leaf("Threatened and endangered species", -35_000),  # (35,000) read as a negative
        _leaf("Aquatic habitat management", 59_247),
        _total("Subtotal", 209_185),
    ]
    (check,) = reconcile_report("R", rows).checks
    assert check.status is not Status.OK
    assert check.delta == 35_000


def test_the_printed_total_decides_whether_a_memo_is_summed():
    """CRPT-114srpt68: 134,488 + 24,000 = 158,488. Here the transfer IS additive, and the
    total says so. Excluding it would leave the total 24,000 short."""
    rows = [
        _leaf("Operating expenses", 134_488),
        _leaf("(By transfer from Disaster Relief)", 24_000, non_add=True),
        _total("Total, Office of Inspector General", 158_488),
    ]
    (check,) = reconcile_report("CRPT-114srpt68", rows).checks
    assert check.status is Status.OK
    assert check.memo_mode is MemoMode.INCLUDED
    assert check.child_indices == (0, 1)


def test_exclusion_is_preferred_when_both_readings_would_close():
    """Ambiguity resolves to the documented convention, not to whichever is tried last."""
    rows = [_leaf("A", 100), _leaf("memo", 0, non_add=True), _total("Subtotal", 100)]
    (check,) = reconcile_report("R", rows).checks
    assert check.status is Status.OK
    assert check.memo_mode is MemoMode.EXCLUDED
    assert check.child_indices == (0,)


def test_a_memo_excluded_from_its_block_is_still_consumed_by_it():
    """Otherwise the memo would drift down and corrupt the next total."""
    rows = [
        _leaf("A", 100),
        _leaf("memo", 35, non_add=True),
        _total("Subtotal", 100),
        _leaf("B", 5),
        _total("Total", 105),
    ]
    result = reconcile_report("R", rows)
    assert _statuses(result) == [Status.OK, Status.OK]
    assert result.checks[1].child_indices == (2, 3)


def test_a_block_of_only_memos_never_reconciles_to_a_printed_zero():
    rows = [_leaf("memo", 1_000, non_add=True), _total("Subtotal", 0)]
    (check,) = reconcile_report("R", rows).checks
    assert check.status is not Status.OK


def test_a_total_rolls_up_child_subtotals_without_double_counting_their_leaves():
    rows = [
        _leaf("Oil and gas management", 114_873),
        _leaf("Oil and gas inspection", 50_402),
        _total("Subtotal, Oil and gas", 165_275),
        _leaf("Coal management", 16_609),
        _leaf("Other mineral resources", 13_466),
        _leaf("Renewable energy", 40_983),
        _total("Subtotal, Energy and Minerals", 236_333),
    ]
    result = reconcile_report("R", rows)
    assert _statuses(result) == [Status.OK, Status.OK]
    # The parent consumed the child subtotal as a single node, plus the three loose leaves.
    assert result.checks[1].child_indices == (2, 3, 4, 5)


def test_every_level_column_is_checked_against_the_same_child_set():
    rows = [
        _leaf("A", rec=10, prior=7, budget=9),
        _leaf("B", rec=5, prior=3, budget=4),
        _total("Subtotal", rec=15, prior=10, budget=13),
    ]
    (check,) = reconcile_report("R", rows).checks
    assert check.status is Status.OK
    assert check.columns["prior_year_enacted"].ok
    assert check.columns["budget_estimate"].ok
    assert check.columns[PRIMARY_COLUMN].ok


def test_a_level_column_that_misses_is_reported_even_when_the_primary_ties():
    rows = [
        _leaf("A", rec=10, prior=7),
        _leaf("B", rec=5, prior=3),
        _total("Subtotal", rec=15, prior=99),
    ]
    (check,) = reconcile_report("R", rows).checks
    assert check.status is Status.OK  # structure is set by the primary column
    assert check.columns["prior_year_enacted"].delta == 89
    assert not check.columns["prior_year_enacted"].ok


def test_a_dot_leader_total_is_unchecked_and_leaves_its_children_for_the_parent():
    """CRPT-118srpt83: 'Total, Service Charges' prints as dots, but its 10,000 still
    rolls into the bureau total above it."""
    rows = [
        _leaf("Current appropriations", 10_000),
        _leaf("Service charges", 30_000),
        _leaf("Offsetting fees", -30_000),
        _total("Total, Service Charges", None),
        _total("TOTAL, BUREAU", 10_000),
    ]
    result = reconcile_report("R", rows)
    assert _statuses(result) == [Status.UNCHECKED, Status.OK]
    assert result.checks[1].child_indices == (0, 1, 2)


def test_a_failed_total_does_not_cascade_into_its_parent():
    """The failed subtotal consumes its block anyway, so the parent sees one node, not four."""
    rows = [
        _leaf("A", 100),
        _leaf("B", 200),
        _total("Subtotal (wrong)", 999),
        _leaf("C", 1),
        _total("Total", 1_000),
    ]
    result = reconcile_report("R", rows)
    assert result.checks[0].status is not Status.OK
    assert result.checks[1].status is Status.OK
    assert result.checks[1].child_indices == (2, 3)


def test_overlapping_view_totals_are_not_counted_as_errors():
    rows = [
        _leaf("Program", 500),
        _leaf("Advance appropriation for next year", 300),
        _total("Total available this fiscal year", 12_345),
    ]
    (check,) = reconcile_report("R", rows).checks
    assert check.status is Status.OVERLAPPING_VIEW
    assert not check.is_genuine_failure


def test_a_child_missing_only_the_primary_column_is_a_partial_read():
    rows = [
        _leaf("A", rec=100),
        _leaf("B", rec=None, prior=50),  # a value we dropped
        _total("Subtotal", 150),
    ]
    (check,) = reconcile_report("R", rows).checks
    assert check.status is Status.PARTIAL_READ
    assert check.is_genuine_failure


def test_a_near_miss_is_distinguished_from_a_structural_mismatch():
    rows = [_leaf("A", 100_000), _leaf("B", 99_000), _total("Subtotal", 200_000)]
    (check,) = reconcile_report("R", rows).checks
    assert check.status is Status.OFF_BY_SMALL

    rows = [_leaf("A", 100_000), _total("Subtotal", 900_000)]
    (check,) = reconcile_report("R", rows).checks
    assert check.status is Status.UNRECONCILED


def test_a_zeroed_out_line_is_recovered_from_the_delta_identity():
    row = _leaf("Defunded", rec=None, prior=500, budget=0, d_prior=-500, d_budget=0)
    assert recover_primary(row) == 0

    # Only one derivation available, and it is unambiguous.
    assert recover_primary(_leaf("x", rec=None, prior=500, d_prior=-100)) == 400
    # Two derivations that disagree invent nothing.
    assert recover_primary(_leaf("x", rec=None, prior=500, d_prior=-100, budget=1, d_budget=1)) is None


def test_a_recovered_zero_contributes_to_its_subtotal():
    rows = [
        _leaf("A", 100),
        _leaf("Defunded", rec=None, prior=500, d_prior=-500),
        _total("Subtotal", 100),
    ]
    (check,) = reconcile_report("R", rows).checks
    assert check.status is Status.OK
    assert check.child_indices == (0, 1)


def test_summarize_separates_measurable_totals_from_overlapping_views():
    rows = [
        _leaf("A", 100),
        _total("Subtotal", 100),
        _leaf("B", 50),
        _total("Total available this fiscal year", 999),
    ]
    stats = summarize([reconcile_report("R", rows)])
    assert stats["checkable"] == 2
    assert stats["measurable"] == 1
    assert stats["ok"] == 1
    assert stats["pass_rate"] == 0.5
    assert stats["strict_pass_rate"] == 1.0
    assert stats["genuine_failures"] == 0
