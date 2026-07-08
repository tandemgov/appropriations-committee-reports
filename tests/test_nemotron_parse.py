"""The Nemotron LaTeX parser must handle both House comparative-statement layouts.

Regression for the FY2026 discovery: the classic layout has six columns (item + five
value columns — Enacted / Request / Bill / Bill-vs-Enacted / Bill-vs-Request), but some
FY2026 bills omit the President's Budget Request, yielding a four-column table (item +
Enacted / Bill / Bill-vs-Enacted). The parser identifies the value columns by their
header NAMES and maps them to the fixed col1..col5 slots, so either layout parses and a
column-count assumption can't silently drop a whole report (CRPT-119hrpt272 extracted 0
lines before this fix).
"""

from __future__ import annotations

from approps.extraction.nemotron_parse import parse_page, parse_page_single_column

SIX_COL = (
    r"<x_0.20><y_0.0>\begin{tabular}{cccccc}"
    "\n & **FY 2025 Enacted** & **FY 2026 Request** & **Bill** & "
    r"**Bill vs. Enacted** & **Bill vs. Request**\\"
    "\nTITLE I - LEGISLATIVE BRANCH & & & & & \\\\"
    "\nSalaries and Expenses..... & 10,499 & 10,300 & 10,499 & --- & +199\\\\"
    r"\end{tabular}"
)

FOUR_COL = (
    r"<x_0.21><y_0.0>\begin{tabular}{cccc}"
    "\n & **FY 2025 Enacted** & **Bill** & **Bill vs. Enacted**\\\\"
    "\nTITLE I - DEPARTMENT OF COMMERCE & & & \\\\"
    "\nOperations and administration..... & 573,000 & 440,000 & -133,000\\\\"
    r"\end{tabular}"
)

# A three-column outlay/financial-assistance table is NOT a comparative statement.
NON_COMPARATIVE = (
    r"<x_0.20><y_0.0>\begin{tabular}{ccc}"
    "\n & **2026** & **2027**\\\\"
    "\nProjection of outlays..... & 1,000 & 2,000\\\\"
    r"\end{tabular}"
)


def _row(items, label_prefix):
    return next(it for it in items if it["text"].startswith(label_prefix))


def test_six_column_layout_maps_all_value_columns():
    row = _row(parse_page(SIX_COL), "Salaries and Expenses")
    assert row["col1"] == "10,499"  # enacted
    assert row["col2"] == "10,300"  # request
    assert row["col3"] == "10,499"  # bill
    assert row["col4"] == ""        # bill vs enacted ("---" -> blank)
    assert row["col5"] == "+199"    # bill vs request


def test_four_column_layout_maps_to_enacted_bill_and_delta():
    row = _row(parse_page(FOUR_COL), "Operations and administration")
    assert row["col1"] == "573,000"   # enacted
    assert row["col2"] == ""          # request column absent in this layout
    assert row["col3"] == "440,000"   # bill
    assert row["col4"] == "-133,000"  # bill vs enacted
    assert row["col5"] == ""          # bill-vs-request column absent


def test_three_column_table_is_not_comparative():
    # A non-comparative table (no Enacted+Bill header pair) yields no line items.
    assert parse_page(NON_COMPARATIVE) == []


# A single-column "Statement of New Budget Authority — Amounts Recommended in the Bill"
# page: item label + one value (the committee recommendation), no comparison columns.
SINGLE_COL = (
    r"<x_0.15><y_0.09>\begin{tabular}{cc}"
    "\nTransportation and Facilities Maintenance: & \\\\"
    "\nAnnual maintenance..... & 31,697\\\\"
    "\nDeferred maintenance..... & 17,500\\\\"
    "\nSubtotal..... & 49,197\\\\"
    r"\end{tabular}"
)


def test_single_column_maps_value_to_recommendation_only():
    rows = parse_page_single_column(SINGLE_COL)
    annual = next(r for r in rows if r["text"].startswith("Annual maintenance"))
    assert annual["col3"] == "31,697"  # committee recommendation (the Bill amount)
    assert annual["col1"] == annual["col2"] == annual["col4"] == annual["col5"] == ""


# A roll-call votes page also renders as a two-column table (Yea names | Nay names).
VOTES_TWO_COL = (
    r"<x_0.20><y_0.0>\begin{tabular}{cc}"
    "\n**Members Voting Yea** & **Members Voting Nay**\\\\"
    "\nMr. Aguilar & Mr. Aderholt\\\\"
    "\nMs. DeLauro & Mr. Alford\\\\"
    r"\end{tabular}"
)


def test_single_column_parser_drops_non_numeric_vote_rows():
    # Member names are not dollar amounts; no line items should come out of a votes table.
    assert parse_page_single_column(VOTES_TWO_COL) == []


def test_single_column_parser_ignores_multi_column_comparative():
    # The comparative layouts are 4/6 columns, not 2 — the single-column parser skips them
    # so it can only ever fire on a genuine single-value table.
    assert parse_page_single_column(SIX_COL) == []
    assert parse_page_single_column(FOUR_COL) == []
