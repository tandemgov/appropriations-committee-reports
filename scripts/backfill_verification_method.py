"""Backfill `verification_method` onto already-extracted reports.

The producers now record which gate set `verified` (see output.schemas.VerificationMethod), but
the reports in `data/extracted` predate the field. Re-running the gates to populate it is not an
option: `scripts/verify_house.py` and `extraction.verify` re-parse every amount from its
`raw_text`, which discards the values `verification.repair` recovered for rows whose raw text is
a dot leader. So the field is reconstructed instead, from the track that produced each row.

The mapping is exact rather than heuristic — each track has exactly one gate, and the House's
two are separated by `extraction_method`:

    stage=enacted                     -> verbatim_page   (amount appears on its source page)
    chamber=senate                    -> string_match    (raw text found in the source HTML)
    chamber=house, extraction=llm     -> delta_arithmetic (vision rows; delta identities close)
    chamber=house, extraction=rule_based -> verbatim_page (typeset committee prints)

A row that is not `verified` gets `none`. `verified` itself is never touched: this backfill only
records what already happened, and asserts it can name the gate for every verified row.

    uv run python scripts/backfill_verification_method.py [--apply]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

EXTRACTED = Path("data/extracted")


def method_for(line: dict) -> str:
    if not line.get("verified"):
        return "none"
    if line.get("stage") == "enacted":
        return "verbatim_page"
    if line.get("chamber") == "senate":
        return "string_match"
    if line.get("chamber") == "house":
        return "delta_arithmetic" if line.get("extraction_method") == "llm" else "verbatim_page"
    raise ValueError(f"cannot name the gate for a verified row: {line.get('report_id')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write; otherwise report only")
    args = parser.parse_args()

    counts: Counter[str] = Counter()
    files = changed_files = 0

    for path in sorted(EXTRACTED.rglob("*.json")):
        if len(path.relative_to(EXTRACTED).parts) < 3:
            continue
        if path.stem.endswith(("_nemotron", "_hybrid")):
            continue  # intermediate vision passes; never read by the output build
        data = json.loads(path.read_text())
        lines = data.get("comparative_lines", [])
        if not lines:
            continue
        files += 1

        changed = 0
        for line in lines:
            method = method_for(line)
            counts[method] += 1
            if line.get("verification_method") != method:
                line["verification_method"] = method
                changed += 1
        if changed:
            changed_files += 1
            if args.apply:
                path.write_text(json.dumps(data, indent=2))

    print(f"{'method':20} {'rows':>9}")
    print("-" * 30)
    for method, n in counts.most_common():
        print(f"{method:20} {n:>9,}")
    print("-" * 30)
    print(f"{'total':20} {sum(counts.values()):>9,}")
    print(f"\nfiles: {files}   needing backfill: {changed_files}")
    print("APPLIED" if args.apply else "DRY RUN — pass --apply to write")


if __name__ == "__main__":
    main()
