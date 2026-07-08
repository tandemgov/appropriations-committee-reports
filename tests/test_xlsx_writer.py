"""The workbook must hand a staffer live arithmetic, not a claim about arithmetic."""

from __future__ import annotations

import pytest

from approps.output.xlsx_writer import _compress, _sum_formula, write_report_workbook
from approps.verification.reconcile import reconcile_report

openpyxl = pytest.importorskip("openpyxl")


def _leaf(text, rec, non_add=False):
    return {
        "line_item_text": text,
        "is_subtotal": False,
        "is_memo": non_add,
        "committee_recommendation": rec,
        "prior_year_enacted": None,
        "budget_estimate": None,
        "delta_vs_enacted": None,
        "delta_vs_estimate": None,
    }


def _total(text, rec):
    row = _leaf(text, rec)
    row["is_subtotal"] = True
    return row


@pytest.fixture
def rows():
    """Two leaves, a memo, a subtotal; then a nested rollup over that subtotal."""
    return [
        _leaf("Wildlife habitat management", 149_938),
        _leaf("Threatened and endangered species", 35_000, non_add=True),
        _leaf("Aquatic habitat management", 59_247),
        _total("Subtotal", 209_185),
        _leaf("Wilderness management", 19_216),
        _total("Total, Account", 228_401),
    ]


def test_contiguous_rows_compress_into_ranges():
    assert _compress([5, 6, 7, 9]) == "5:7,9"
    assert _compress([3]) == "3"
    assert _compress([]) == ""
    assert _compress([2, 4, 6]) == "2,4,6"


def test_leaves_sum_from_the_leaf_column_and_rollups_from_the_rollup_column():
    assert _sum_formula([2, 3, 4], []) == "=SUM(C2:C4)"
    assert _sum_formula([], [5]) == "=SUM(D5)"
    assert _sum_formula([7], [5]) == "=SUM(C7,D5)"
    assert _sum_formula([], []) == "=0"


def test_computed_cells_are_live_formulas_over_the_exact_children(tmp_path, rows):
    result = reconcile_report("R", rows)
    path = write_report_workbook(tmp_path / "r.xlsx", rows, result)
    sheet = openpyxl.load_workbook(path)["Line items"]

    # Row 5 is the Subtotal (row 1 is the header). Its children are the two leaves at
    # sheet rows 2 and 4 -- NOT the memo at row 3, which lies between them.
    assert sheet["E5"].value == "=SUM(C2,C4)"
    assert sheet["F5"].value == "=B5-E5"

    # The parent rolls up the subtotal (D5) plus the loose leaf (C6). Summing C2:C6 would
    # double-count the leaves the subtotal already absorbed.
    assert sheet["E7"].value == "=SUM(C6,D5)"


def test_a_non_add_memo_sits_in_no_summable_column(tmp_path, rows):
    result = reconcile_report("R", rows)
    path = write_report_workbook(tmp_path / "r.xlsx", rows, result)
    sheet = openpyxl.load_workbook(path)["Line items"]

    assert sheet["A3"].value == "Threatened and endangered species"
    assert sheet["B3"].value == 35_000  # printed, so a reader can see it
    assert sheet["C3"].value is None  # but unreachable by any SUM
    assert sheet["D3"].value is None
    assert sheet["H3"].value == "non-add memo — no SUM reaches it"


def test_a_memo_the_total_endorsed_is_reachable_by_that_totals_sum(tmp_path):
    """CRPT-114srpt68: the transfer is added, so the SUM must be able to see it."""
    memo_rows = [
        _leaf("Operating expenses", 134_488),
        _leaf("(By transfer from Disaster Relief)", 24_000, non_add=True),
        _total("Total, Office of Inspector General", 158_488),
    ]
    result = reconcile_report("CRPT-114srpt68", memo_rows)
    path = write_report_workbook(tmp_path / "r.xlsx", memo_rows, result)
    sheet = openpyxl.load_workbook(path)["Line items"]

    assert sheet["C3"].value == 24_000  # in the leaf column, so SUM reaches it
    assert sheet["H3"].value == "memo — the printed total adds it"
    assert sheet["E4"].value == "=SUM(C2:C3)"


def test_leaves_and_totals_land_in_different_columns(tmp_path, rows):
    result = reconcile_report("R", rows)
    path = write_report_workbook(tmp_path / "r.xlsx", rows, result)
    sheet = openpyxl.load_workbook(path)["Line items"]

    assert sheet["C2"].value == 149_938 and sheet["D2"].value is None  # leaf
    assert sheet["D5"].value == 209_185 and sheet["C5"].value is None  # rollup


def test_the_workbook_carries_a_reconciliation_sheet_linked_to_the_line_items(tmp_path, rows):
    result = reconcile_report("R", rows)
    path = write_report_workbook(tmp_path / "r.xlsx", rows, result)
    book = openpyxl.load_workbook(path)
    assert book.sheetnames == ["Read me", "Line items", "Reconciliation"]

    recon = book["Reconciliation"]
    assert recon["A2"].value == "Subtotal"
    assert recon["C2"].value == "='Line items'!B5"
    assert recon["D2"].value == "='Line items'!E5"
    assert recon["F2"].value == 2  # two children


def test_a_row_that_is_both_a_memo_and_a_subtotal_lands_in_the_rollup_column(tmp_path):
    """CRPT-118hrpt553: `Subtotal, Immigration Examinations Fee Account` is a subtotal printed
    in parentheses. It is a mandatory rollup child, so its parent's SUM addresses it as D --
    putting its amount in the leaf column would make the parent evaluate to the wrong number.
    """
    memo_subtotal = _total("Subtotal, Fee Account", 40)
    memo_subtotal["is_memo"] = True
    rows = [_leaf("Fee A", 40), memo_subtotal, _leaf("Loose leaf", 5), _total("Subtotal, Fees", 45)]

    result = reconcile_report("CRPT-118hrpt553", rows)
    path = write_report_workbook(tmp_path / "r.xlsx", rows, result)
    sheet = openpyxl.load_workbook(path)["Line items"]

    assert sheet["D3"].value == 40  # rollup column, because it is a subtotal
    assert sheet["C3"].value is None
    assert sheet["E5"].value == "=SUM(C4,D3)"

    # And the parent's formula must actually evaluate to the printed amount.
    assert sheet["B5"].value == (sheet["C4"].value or 0) + (sheet["D3"].value or 0)


def test_a_dot_leader_amount_shows_the_value_the_arithmetic_uses(tmp_path):
    """Otherwise a total that reconciles would render with a blank amount and a red check."""
    rows = [
        _leaf("B", 100),
        _leaf("Defunded", None) | {"prior_year_enacted": 500, "delta_vs_enacted": -500},
        _total("Subtotal", 100),
    ]
    result = reconcile_report("R", rows)
    path = write_report_workbook(tmp_path / "r.xlsx", rows, result)
    sheet = openpyxl.load_workbook(path)["Line items"]

    assert sheet["B3"].value == 0  # not blank: recovered from 500 + (-500)
    assert sheet["C3"].value == 0
    assert sheet["H3"].value == "recovered from this row's deltas"
    assert sheet["E4"].value == "=SUM(C2:C3)"


def test_an_unchecked_total_gets_no_formula(tmp_path):
    rows = [_leaf("A", 100), _total("Total, dot leader", None)]
    result = reconcile_report("R", rows)
    path = write_report_workbook(tmp_path / "r.xlsx", rows, result)
    sheet = openpyxl.load_workbook(path)["Line items"]
    assert sheet["E3"].value is None
    assert sheet["G3"].value == "unchecked"
