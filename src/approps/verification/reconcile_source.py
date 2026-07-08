"""Load the published dataset into the neutral row shape ``reconcile`` expects.

The gate deliberately reads ``data/release`` rather than ``data/extracted``: the release is
what a consumer downloads, it carries the final ``is_memo`` and ``is_subtotal``
flags, and a check that validates anything other than the shipped artifact is checking the
wrong thing. Row order in the release is document order, which is the only ordering the
reconciler needs.
"""

from __future__ import annotations

from pathlib import Path

from approps.config import DATA_DIR
from approps.verification.reconcile import LEVEL_COLUMNS

DEFAULT_RELEASE = DATA_DIR / "release" / "comparative_statements.parquet"

_AMOUNT_COLUMNS = (*LEVEL_COLUMNS, "delta_vs_enacted", "delta_vs_estimate")
_FLAG_COLUMNS = ("is_subtotal", "is_memo")
_NEEDED = ("report_id", "line_item_text", "chamber", "stage", *_FLAG_COLUMNS, *_AMOUNT_COLUMNS)


def _to_int(value) -> int | None:
    """pandas nullable ints arrive as pd.NA / NaN; the reconciler wants int or None."""
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except TypeError:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value) and value == value


def load_release(path: Path | None = None) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """Return ``(rows_by_report, track_by_report)`` in document order.

    ``track`` collapses chamber and stage into the three extraction tracks the corpus
    actually has -- house, senate, enacted -- since enacted prints are House-numbered and
    would otherwise hide inside the House track.
    """
    import pandas as pd

    path = Path(path) if path else DEFAULT_RELEASE
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build the release first: uv run python scripts/build_release.py"
        )

    if path.suffix == ".parquet":
        frame = pd.read_parquet(path, columns=list(_NEEDED))
    else:
        frame = pd.read_csv(path, usecols=list(_NEEDED), low_memory=False)

    rows_by_report: dict[str, list[dict]] = {}
    track_by_report: dict[str, str] = {}

    for report_id, group in frame.groupby("report_id", sort=False):
        first = group.iloc[0]
        track = "enacted" if first["stage"] == "enacted" else str(first["chamber"])
        track_by_report[str(report_id)] = track

        rows: list[dict] = []
        for record in group.to_dict("records"):
            row: dict = {"line_item_text": record.get("line_item_text") or ""}
            for column in _FLAG_COLUMNS:
                row[column] = _to_bool(record.get(column))
            for column in _AMOUNT_COLUMNS:
                row[column] = _to_int(record.get(column))
            rows.append(row)
        rows_by_report[str(report_id)] = rows

    return rows_by_report, track_by_report
