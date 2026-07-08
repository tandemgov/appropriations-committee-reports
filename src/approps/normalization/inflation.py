"""Inflation adjustment for dollar amounts.

Converts nominal appropriations dollars to constant (real) dollars using an annual
deflator series loaded from data/reference/deflators.csv (CPI-U, BLS CUUR0000SA0). This
satisfies the SOW's "unadjusted and inflation-adjustable" requirement: nominal amounts are
kept as-is, and this module produces the real-dollar view on demand.

Caveat: appropriations are fiscal-year (Oct–Sep) while CPI-U is calendar-year, so this is
a standard, transparent approximation. The series lives in a swappable CSV, so an OMB
fiscal-year GDP price index could replace CPI-U without code changes.
"""

from __future__ import annotations

import csv
import functools

from approps.config import RAW_DIR

_DEFLATORS_PATH = RAW_DIR.parent / "reference" / "deflators.csv"


@functools.lru_cache(maxsize=1)
def load_deflators(column: str = "cpi_u") -> dict[int, float]:
    """Load the {year: index} deflator series from data/reference/deflators.csv."""
    series: dict[int, float] = {}
    with open(_DEFLATORS_PATH, newline="") as fh:
        for row in csv.DictReader(fh):
            series[int(row["year"])] = float(row[column])
    return series


def adjust_for_inflation(
    amount: float,
    from_year: int,
    to_year: int,
    method: str = "cpi",
) -> float:
    """Convert a nominal amount in from_year dollars to to_year (constant) dollars.

    real = nominal * deflator[to_year] / deflator[from_year]

    Raises KeyError if either year is missing from the deflator series.
    """
    if method != "cpi":
        raise ValueError(f"Unsupported inflation method: {method!r}")
    series = load_deflators()
    if from_year not in series or to_year not in series:
        missing = {from_year, to_year} - series.keys()
        raise KeyError(f"No deflator for year(s): {sorted(missing)}")
    return amount * series[to_year] / series[from_year]


def real_dollars(amount: float | None, from_year: int | None, base_year: int) -> float | None:
    """Convenience wrapper: amount in from_year nominal dollars -> base_year real dollars.

    Returns None if the amount or year is missing, or the year is outside the series."""
    if amount is None or from_year is None:
        return None
    try:
        return round(adjust_for_inflation(amount, from_year, base_year))
    except KeyError:
        return None
