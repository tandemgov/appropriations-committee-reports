"""Tests for inflation adjustment (CPI-U real-dollar conversion)."""

import pytest

from approps.normalization.inflation import (
    adjust_for_inflation,
    load_deflators,
    real_dollars,
)


def test_series_loads():
    s = load_deflators()
    assert s[2016] == 240.007
    assert s[2024] == 313.689


def test_same_year_is_identity():
    assert adjust_for_inflation(1_000_000, 2020, 2020) == pytest.approx(1_000_000)


def test_older_dollars_are_worth_more_in_later_dollars():
    # $100M in FY2016 expressed in FY2024 dollars should be larger (inflation).
    out = adjust_for_inflation(100_000_000, 2016, 2024)
    assert out == pytest.approx(100_000_000 * 313.689 / 240.007)
    assert out > 100_000_000


def test_real_dollars_handles_missing():
    assert real_dollars(None, 2020, 2024) is None
    assert real_dollars(1_000_000, None, 2024) is None
    assert real_dollars(1_000_000, 1990, 2024) is None  # year outside the series


def test_unsupported_method():
    with pytest.raises(ValueError):
        adjust_for_inflation(1, 2020, 2024, method="gdp")
