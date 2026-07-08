"""Apply the deterministic recommendation repair across all extracted reports.

Recovers blank committee-recommendation values (and corrects over-determined
mismatches) from the redundant comparative columns -- see verification.repair.
Writes the repaired JSON back in place. Use --dry-run to preview counts only.

Usage: uv run python scripts/repair_corpus.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from approps.verification.repair import repair_report

EXTRACTED = Path("data/extracted")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report counts, do not write")
    args = ap.parse_args()

    by_track = defaultdict(lambda: {"reports": 0, "touched": 0, "recovered": 0, "corrected": 0})
    for path in sorted(EXTRACTED.rglob("*.json")):
        parts = path.relative_to(EXTRACTED).parts
        if len(parts) < 3:
            continue
        track = parts[1]
        data = json.loads(path.read_text())
        c = repair_report(data)
        t = by_track[track]
        t["reports"] += 1
        t["recovered"] += c["recovered"]
        t["corrected"] += c["corrected"]
        if c["recovered"] or c["corrected"]:
            t["touched"] += 1
            if not args.dry_run:
                path.write_text(json.dumps(data, indent=2))

    print(f"{'track':9} {'reports':>7} {'touched':>7} {'recovered':>9} {'corrected':>9}")
    print("-" * 45)
    tot = defaultdict(int)
    for track, t in sorted(by_track.items()):
        print(f"{track:9} {t['reports']:>7} {t['touched']:>7} {t['recovered']:>9} {t['corrected']:>9}")
        for k in ("reports", "touched", "recovered", "corrected"):
            tot[k] += t[k]
    print("-" * 45)
    print(f"{'ALL':9} {tot['reports']:>7} {tot['touched']:>7} {tot['recovered']:>9} {tot['corrected']:>9}")
    print("\n(dry run -- nothing written)" if args.dry_run else "\nwritten back in place.")


if __name__ == "__main__":
    main()
