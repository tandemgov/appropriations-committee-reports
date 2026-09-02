"""Re-run the issue #2 archetype probe on `unreconciled` totals.

Reproduces the two cheap explanations the issue tested, now that the 682 dropped Senate rows are back in the corpus:
  A. the miss exactly equals an EARLIER printed total in the same report
     (a double-count, or a rollup the reconciler failed to collapse)
  B. the miss exactly equals a SINGLE nearby leaf (block boundary off by one)
Anything else is unexplained -- the residual the issue calls "the real work".
"""

from __future__ import annotations

import sys
from collections import Counter

from approps.verification.reconcile import (
    PRIMARY_COLUMN,
    Status,
    is_total,
    recover_primary,
    reconcile_report,
)
from approps.verification.reconcile_source import load_release

WINDOW = 12  # rows either side, for "nearby leaf"


def main() -> None:
    rows_by_report, track_by_report = load_release()
    per_track: dict[str, Counter] = {}
    misses: dict[str, list[int]] = {}

    for rid, rows in rows_by_report.items():
        track = track_by_report.get(rid, "?")
        result = reconcile_report(rid, rows)

        printed_totals_before: list[tuple[int, int]] = []  # (index, printed value)
        for check in result.checks:
            col = check.columns.get(PRIMARY_COLUMN)
            if col is not None and col.printed is not None:
                printed_totals_before.append((check.index, col.printed))

        for check in result.checks:
            if check.status is not Status.UNRECONCILED:
                continue
            col = check.columns.get(PRIMARY_COLUMN)
            if col is None or col.delta is None:
                continue
            miss = abs(col.delta)
            bucket = per_track.setdefault(track, Counter())
            misses.setdefault(track, []).append(miss)

            # A: miss equals an earlier printed total in this report
            if any(abs(v) == miss for i, v in printed_totals_before if i < check.index):
                bucket["A_earlier_total"] += 1
                continue

            # B: miss equals a single nearby leaf
            lo, hi = max(0, check.index - WINDOW), min(len(rows), check.index + WINDOW)
            hit = False
            for j in range(lo, hi):
                row = rows[j]
                if is_total(row):
                    continue
                val = recover_primary(row)
                if val is not None and abs(val) == miss and miss != 0:
                    hit = True
                    break
            bucket["B_nearby_leaf" if hit else "C_unexplained"] += 1

    print(
        f"{'track':10s} {'unrec':>7s} {'A earlier total':>16s} {'B nearby leaf':>15s} {'C unexplained':>15s}"
    )
    grand = Counter()
    for track in sorted(per_track):
        c = per_track[track]
        n = sum(c.values())
        grand.update(c)
        print(
            f"{track:10s} {n:7d} "
            f"{c['A_earlier_total']:9d} {c['A_earlier_total'] / n:5.0%} "
            f"{c['B_nearby_leaf']:8d} {c['B_nearby_leaf'] / n:5.0%} "
            f"{c['C_unexplained']:8d} {c['C_unexplained'] / n:5.0%}"
        )
    n = sum(grand.values())
    print(
        f"{'ALL':10s} {n:7d} "
        f"{grand['A_earlier_total']:9d} {grand['A_earlier_total'] / n:5.0%} "
        f"{grand['B_nearby_leaf']:8d} {grand['B_nearby_leaf'] / n:5.0%} "
        f"{grand['C_unexplained']:8d} {grand['C_unexplained'] / n:5.0%}"
    )

    print()
    for track in sorted(misses):
        vals = sorted(misses[track])
        mid = vals[len(vals) // 2]
        p90 = vals[int(len(vals) * 0.9)]
        print(
            f"{track:10s} median miss ${mid:,}  p90 ${p90:,}  zero-miss {sum(1 for v in vals if v == 0)}"
        )


if __name__ == "__main__":
    sys.exit(main())
