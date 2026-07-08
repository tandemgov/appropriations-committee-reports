"""Schema-declared integer columns must serialize as integers, not floats.

A nullable int column (`fiscal_year`, every dollar amount) arrives in pandas as float64,
because float is the only numpy dtype that can hold NaN. Left alone, `df.to_csv()` then
writes a year as ``2016.0`` and an amount as ``649.0`` — floats in a published dataset
that the schema declares as ``int | None``. These pin the Int64 coercion.
"""

from __future__ import annotations

import pandas as pd
import pytest

from approps.output.csv_writer import _coerce_int_columns, _int_fields
from approps.output.schemas import ComparativeStatementRow, InlineFundingRow


def test_int_fields_finds_optional_and_plain_ints():
    fields = _int_fields(ComparativeStatementRow)
    # `int | None` resolves to types.UnionType, `int` to itself — both must be found.
    assert "fiscal_year" in fields  # int | None
    assert "congress" in fields  # int
    assert "hierarchy_depth" in fields  # int
    assert {"prior_year_enacted", "budget_estimate", "committee_recommendation"} <= set(fields)


def test_int_fields_excludes_bool_float_and_str():
    fields = set(_int_fields(ComparativeStatementRow))
    # bool subclasses int at runtime, but its annotation is `bool` — must not be caught.
    assert not fields & {"verified", "is_subtotal", "in_thousands", "is_memo"}
    assert "real_factor_2024" not in fields  # float | None
    assert "report_id" not in fields  # str


def test_coerce_renders_nullable_year_as_int_not_float():
    df = pd.DataFrame({"fiscal_year": [2016.0, None, 2027.0], "report_id": ["a", "b", "c"]})
    out = _coerce_int_columns(df, ComparativeStatementRow)

    assert str(out["fiscal_year"].dtype) == "Int64"
    assert out.to_csv(index=False).splitlines()[1].startswith("2016,")
    assert "2016.0" not in out.to_csv(index=False)


def test_coerce_preserves_nulls_as_empty_csv_fields():
    # Multi-column, as the real output is: a lone empty field in a single-column frame
    # gets quoted (`""`) to avoid emitting a blank line, which would mask the behavior.
    df = pd.DataFrame(
        {"report_id": ["x", "y"], "committee_recommendation": [649.0, None]}
    )
    csv = _coerce_int_columns(df, ComparativeStatementRow).to_csv(index=False)

    assert csv.splitlines()[1:] == ["x,649", "y,"]


def test_coerce_leaves_float_columns_alone():
    df = pd.DataFrame({"real_factor_2024": [1.0523, None]})
    out = _coerce_int_columns(df, ComparativeStatementRow)

    assert str(out["real_factor_2024"].dtype) == "float64"
    assert "1.0523" in out.to_csv(index=False)


def test_coerce_raises_on_non_integral_rather_than_truncating():
    """A fractional amount means an upstream parse bug — surface it, don't silently floor."""
    df = pd.DataFrame({"committee_recommendation": [1234.5]})
    with pytest.raises(TypeError):
        _coerce_int_columns(df, ComparativeStatementRow)


def test_inline_row_amounts_also_coerced():
    fields = _int_fields(InlineFundingRow)
    assert "prior_year_amount" in fields
    assert "verified" not in fields
