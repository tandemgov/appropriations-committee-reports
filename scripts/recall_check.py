"""Audit recall of a House comparative extraction against the verified inline tables.

Reports how many inline accounts (deterministic ground truth) are present in the
comparative extraction by name. Missing names are silent recall gaps the delta gate
cannot see. Optionally maps them to comparative pages for targeted re-extraction.

Usage:
    uv run python scripts/recall_check.py data/extracted/118/house/CRPT-118hrpt553_nemotron.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from approps.verification.recall_check import (  # noqa: E402
    audit_recall,
    load_inline_accounts,
    suspect_pages_from_missing,
)


def main() -> None:
    path = Path(sys.argv[1])
    d = json.loads(path.read_text())
    report_id = d["report_id"]
    lines = d["comparative_lines"]

    inline = load_inline_accounts(report_id)
    if not inline:
        print(f"No inline CSV for {report_id} (data/extracted/{report_id}_inline.csv). "
              "Generate it first; recall check skipped.")
        return

    r = audit_recall(lines, inline)
    pages, unmappable = suspect_pages_from_missing(r["missing"], lines)

    print(f"file: {path.name}")
    print(f"inline accounts (ground truth): {r['inline_accounts']}")
    print(f"  found by value (exact $):   {r['found_by_value']}")
    print(f"  found by name (offset diff): {r['found_by_name']}")
    print(f"  MISSING (silent recall gap): {len(r['missing'])}")
    print(f"  recall: {r['recall']:.1%}")
    print(f"\nmissing accounts -> {len(pages)} pages to re-check: {sorted(pages)}")
    for acc in r["missing"]:
        val = acc["committee_recommendation"]
        vs = f"${val:,}" if val is not None else "n/a"
        print(f"    MISSING: {acc['account_name'][:60]!r}  rec={vs}")
    if unmappable:
        print(f"\n{len(unmappable)} missing accounts could not be mapped to a page (manual review):")
        for acc in unmappable:
            print(f"    {acc['account_name'][:60]!r}")


if __name__ == "__main__":
    main()
