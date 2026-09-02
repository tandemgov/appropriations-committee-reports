"""Verified-coverage floor — catches a gate that never ran.

Re-extraction clears the flags `approps verify` persists into the extracted JSON, so a skipped re-run ships a silently unverified track.
No per-row gate objects: every such row is truthfully unverified, so the defect exists only in aggregate.

Floors are per-track (the tracks differ by ~48 points) and sit below observed coverage, bounding the skipped-gate failure rather than ordinary erosion.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from approps.output.schemas import ComparativeStatementLine

# Headroom below observed coverage: House vision ~52%, Senate HTML ~95%, enacted 100%.
COVERAGE_FLOORS: dict[tuple[str, str], float] = {
    ("committee", "house"): 0.40,
    ("committee", "senate"): 0.85,
    ("enacted", "house"): 0.99,
}


@dataclass(frozen=True)
class CoverageFinding:
    stage: str
    chamber: str
    verified: int
    total: int
    floor: float

    @property
    def fraction(self) -> float:
        return self.verified / self.total if self.total else 0.0

    def __str__(self) -> str:
        return (
            f"{self.stage}/{self.chamber}: {self.verified:,} of {self.total:,} verified "
            f"({self.fraction:.1%}) — below the {self.floor:.0%} floor; "
            f"did `approps verify --all` run after the last extraction?"
        )


def underverified_tracks(
    lines: list[ComparativeStatementLine],
    floors: dict[tuple[str, str], float] | None = None,
) -> list[CoverageFinding]:
    """Tracks whose verified fraction has fallen below its floor.

    A track absent from `floors` is not checked — an unrecognized track has no calibrated expectation.
    """
    floors = COVERAGE_FLOORS if floors is None else floors
    tallies: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for line in lines:
        stage = str(getattr(line.stage, "value", line.stage))
        chamber = str(getattr(line.chamber, "value", line.chamber))
        tally = tallies[(stage, chamber)]
        tally[0] += 1
        if line.verified:
            tally[1] += 1

    findings = []
    for track, (total, verified) in sorted(tallies.items()):
        floor = floors.get(track)
        if floor is None or not total:
            continue
        if verified / total < floor:
            findings.append(
                CoverageFinding(
                    stage=track[0], chamber=track[1], verified=verified, total=total, floor=floor
                )
            )
    return findings
