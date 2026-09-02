"""The verified-coverage tripwire: catch a gate that never ran.

No per-row gate can see this — every row in a skipped-verify build is truthfully unverified.
"""

from __future__ import annotations

from approps.output.schemas import (
    Chamber,
    ComparativeStatementLine,
    Stage,
)
from approps.verification.coverage import underverified_tracks


def _lines(
    n: int, verified: int, chamber: Chamber = Chamber.SENATE, stage: Stage = Stage.COMMITTEE
) -> list[ComparativeStatementLine]:
    return [
        ComparativeStatementLine(
            report_id="CRPT-118srpt83",
            congress=118,
            chamber=chamber,
            fiscal_year=2024,
            stage=stage,
            line_item_text="Salaries and Expenses",
            verified=i < verified,
        )
        for i in range(n)
    ]


def test_flags_the_regression_that_started_this():
    """The Senate re-extraction left all 29,042 rows unverified and nothing objected."""
    findings = underverified_tracks(_lines(29_042, 0))

    assert len(findings) == 1
    assert findings[0].chamber == "senate"
    assert findings[0].verified == 0


def test_healthy_senate_coverage_passes():
    assert underverified_tracks(_lines(29_042, 27_472)) == []


def test_house_vision_coverage_is_not_held_to_the_senate_floor():
    """House runs ~52% by nature — the remainder are structural rows with no checkable amount."""
    assert underverified_tracks(_lines(68_350, 35_832, chamber=Chamber.HOUSE)) == []


def test_house_collapse_still_trips():
    assert len(underverified_tracks(_lines(68_350, 0, chamber=Chamber.HOUSE))) == 1


def test_unrecognized_track_is_not_checked():
    """A new source format has no calibrated expectation; inventing one would fire on every build."""
    lines = _lines(100, 0, chamber=Chamber.SENATE, stage=Stage.ENACTED)

    assert underverified_tracks(lines) == []


def test_reports_each_failing_track():
    findings = underverified_tracks(_lines(1_000, 0) + _lines(1_000, 0, chamber=Chamber.HOUSE))

    assert {f.chamber for f in findings} == {"house", "senate"}
