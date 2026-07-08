"""Ad-hoc runner for the enacted-stage extractor (thin wrapper over the module).

For pipeline use prefer the CLI: `approps download --stage enacted` then
`approps extract --stage enacted`. This script is handy for one-off runs against an
already-downloaded CPRT print.

    uv run python scripts/extract_enacted.py CPRT-117HPRT50347 [CPRT-117HPRT50348 ...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from approps.discovery.enacted_prints import ENACTED_PRINTS
from approps.extraction.comparative_enacted import extract_enacted_pdf

ROOT = Path(__file__).resolve().parents[1]
_PKG_RE = re.compile(r"^CPRT-(\d+)HPRT(\d+)$")


def main() -> None:
    package_ids = sys.argv[1:] or list(ENACTED_PRINTS)
    for pid in package_ids:
        m = _PKG_RE.match(pid)
        congress = int(m.group(1)) if m else None
        fy = ENACTED_PRINTS.get(pid)
        pdf_path = ROOT / "data" / "raw" / str(congress) / "cprt" / f"{pid}.pdf"
        print(f"Extracting {pid} (FY{fy}) ...", flush=True)
        lines = extract_enacted_pdf(pdf_path, pid, congress, fy)
        out_dir = ROOT / "data" / "extracted" / str(congress) / "enacted"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{pid}.json"
        out.write_text(
            json.dumps(
                {
                    "report_id": pid,
                    "inline_tables": [],
                    "comparative_lines": [ln.model_dump(mode="json") for ln in lines],
                },
                indent=2,
            )
        )
        verified = sum(1 for ln in lines if ln.verified)
        print(f"  {len(lines)} lines ({verified} self-verified) -> {out}")


if __name__ == "__main__":
    main()
