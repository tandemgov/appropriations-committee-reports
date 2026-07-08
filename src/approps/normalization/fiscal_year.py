"""Map congress numbers and sessions to fiscal years."""

from __future__ import annotations

# Each congress spans two calendar years and typically handles two fiscal years.
# First session (odd year): FY for the next calendar year
# Second session (even year): FY for the next calendar year
#
# Examples:
#   114th Congress (2015-2016): FY2016, FY2017
#   115th Congress (2017-2018): FY2018, FY2019
#   118th Congress (2023-2024): FY2024, FY2025

CONGRESS_TO_FY: dict[int, list[int]] = {
    114: [2016, 2017],
    115: [2018, 2019],
    116: [2020, 2021],
    117: [2022, 2023],
    118: [2024, 2025],
    119: [2026, 2027],
}


def congress_to_fiscal_years(congress: int) -> list[int]:
    """Return the fiscal years associated with a congress."""
    if congress in CONGRESS_TO_FY:
        return CONGRESS_TO_FY[congress]
    # Compute for unknown congress numbers
    first_fy = 2016 + (congress - 114) * 2
    return [first_fy, first_fy + 1]


def fiscal_year_to_congress(fy: int) -> int:
    """Return the congress number for a given fiscal year."""
    return 114 + (fy - 2016) // 2
