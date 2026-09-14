"""Three-column House pages filed one slot to the left are remapped; correctly read pages are not."""

from approps.normalization.column_shift import repair_three_column_pages


def _amt(v):
    return None if v is None else {"value": v, "raw_text": f"{v:,}", "in_thousands": True}


def _row(page, prior=None, est=None, rec=None, dve=None, dvs=None, text="Line"):
    return {
        "chamber": "house", "extraction_method": "llm", "line_number": page * 100, "line_item_text": text,
        "prior_year_enacted": _amt(prior), "budget_estimate": _amt(est), "committee_recommendation": _amt(rec),
        "delta_vs_enacted": _amt(dve), "delta_vs_estimate": _amt(dvs),
    }


def _v(row, key):
    return row[key]["value"] if row[key] else None


def test_shifted_page_is_remapped():
    # Printed: Enacted 3,881,000 | Bill 3,744,000 | Bill vs. Enacted -137,000.
    rows = [_row(103, prior=3_881_000, est=3_744_000, rec=-137_000), _row(103, prior=45, est=35, rec=-10)]
    assert repair_three_column_pages(rows) == 2
    assert (_v(rows[0], "committee_recommendation"), _v(rows[0], "delta_vs_enacted"), _v(rows[0], "budget_estimate")) == (3_744_000, -137_000, None)
    assert rows[0]["column_repair"] == "three_column_shift"


def test_rows_without_a_prior_year_move_with_their_page():
    rows = [_row(103, prior=45, est=35, rec=-10), _row(103, prior=10, est=12, rec=2), _row(103, est=500, rec=500, text="New program")]
    repair_three_column_pages(rows)
    assert (_v(rows[2], "committee_recommendation"), _v(rows[2], "delta_vs_enacted")) == (500, 500)


def test_correctly_read_five_column_page_is_untouched():
    rows = [_row(50, prior=100, est=150, rec=120, dve=20, dvs=-30), _row(50, prior=10, est=20, rec=10, dve=0, dvs=-10)]
    assert repair_three_column_pages(rows) == 0
    assert _v(rows[0], "budget_estimate") == 150


def test_page_with_deltas_is_not_repaired_even_if_one_row_fits():
    rows = [_row(7, prior=45, est=35, rec=-10), _row(7, prior=20, est=30, rec=25, dve=5)]
    assert repair_three_column_pages(rows) == 0


def test_one_coincidental_row_is_not_enough():
    rows = [_row(9, prior=45, est=35, rec=-10), _row(9, prior=20, est=30)]
    assert repair_three_column_pages(rows) == 0


def test_a_single_row_page_is_repaired_once_the_report_is_proven_shifted():
    rows = [
        _row(1, prior=45, est=35, rec=-10), _row(1, prior=10, est=12, rec=2),
        _row(2, prior=5, est=9, rec=4), _row(2, prior=7, est=7, rec=0),
        _row(3, prior=100, est=90, rec=-10),
    ]
    assert repair_three_column_pages(rows) == 5


def test_senate_and_rule_based_rows_are_ignored():
    rows = [dict(_row(1, prior=45, est=35, rec=-10), chamber="senate"), dict(_row(1, prior=10, est=12, rec=2), extraction_method="rule_based")]
    assert repair_three_column_pages(rows) == 0


from approps.normalization.column_shift import repair_house_allowance_columns  # noqa: E402


def _senate(prior, est, house, rec, dprior, text="Line"):
    row = _row(0, prior=prior, est=est, rec=house, dve=rec, dvs=dprior, text=text)
    row.update(chamber="senate", extraction_method="rule_based")
    return row


def test_house_allowance_report_is_remapped():
    # Printed: 2015 105,000 | estimate 113,657 | House 93,500 | Committee 110,738 | +5,738 (vs 2015)
    rows = [_senate(105_000 + i, 113_657, 93_500, 110_738 + i * 2, 5_738 + i) for i in range(25)]
    assert repair_house_allowance_columns(rows) == 25
    r = rows[0]
    assert (_v(r, "committee_recommendation"), _v(r, "delta_vs_enacted"), r["delta_vs_estimate"]) == (110_738, 5_738, None)
    assert r["column_repair"] == "house_allowance_columns"


def test_standard_senate_report_is_untouched():
    rows = []
    for i in range(25):
        row = _row(0, prior=100 + i, est=150, rec=120 + i, dve=20, dvs=-30 + i)
        row.update(chamber="senate", extraction_method="rule_based")
        rows.append(row)
    assert repair_house_allowance_columns(rows) == 0


def test_too_little_evidence_is_not_enough():
    rows = [_senate(105_000, 113_657, 93_500, 110_738, 5_738) for _ in range(5)]
    assert repair_house_allowance_columns(rows) == 0
