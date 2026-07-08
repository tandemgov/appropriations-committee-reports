"""Verify vision-extracted House comparative data against the authoritative HTML.

This is an INDEPENDENT cross-check, not a self-consistency check. The numbers in
the report's narrative HTML ("Appropriation, fiscal year 2024 ... / Budget request
... / Recommended in the bill ...") are authoritative source text. We extract those
trios directly from the HTML (bypassing the inline CSV, which has a known
block-association bug), then ask: does the vision extraction contain a row with that
EXACT (enacted, budget, recommended) trio?

An exact 3-number match across two fully independent extraction methods
(regex-on-HTML-text vs vision-OCR-of-image-table) is conclusive for that account:
three 9-digit dollar figures do not collide by chance. Partial matches localize
exactly which column the vision model misread.

Coverage note: the HTML narrative only states account-level totals (~55 accounts).
The deep program / sub-program leaf lines appear ONLY in the image tables and are
NOT covered by this check — they need a separate method (dual-model agreement or
subtotal arithmetic).
"""

from __future__ import annotations

import html as html_mod
import json
import re
import sys
from pathlib import Path

HTML = Path("data/raw/118/house/CRPT-118hrpt553.htm")
VISION = Path("data/extracted/118/house/CRPT-118hrpt553.json")


def _num(s: str) -> int | None:
    s = s.strip()
    if not s or set(s) <= {"-", " "}:  # "- - -"
        return None
    return int(s.replace(",", "").replace("$", ""))


def ground_truth() -> list[dict]:
    text = html_mod.unescape(re.sub(r"<[^>]+>", " ", HTML.read_text()))
    text = re.sub(r"\s+", " ", text)
    block = re.compile(
        r"Appropriation, fiscal year 2024[ .]*\$?([\d,]+|- - -)"
        r".*?Budget request, fiscal year 2025[ .]*\$?([\d,]+|- - -)"
        r".*?Recommended in the bill[ .]*\$?([\d,]+|- - -)"
    )
    out = []
    for m in block.finditer(text):
        # Account heading = the text just before "Appropriation, fiscal year 2024"
        pre = text[max(0, m.start() - 120) : m.start()].strip()
        heading = pre.split(".")[0][-70:].strip()
        out.append(
            {
                "heading": heading,
                "enacted": _num(m.group(1)),
                "budget": _num(m.group(2)),
                "recommended": _num(m.group(3)),
            }
        )
    return out


def vision_triples() -> list[tuple]:
    d = json.loads(VISION.read_text())
    trips = []
    for x in d["comparative_lines"]:
        e = (x.get("prior_year_enacted") or {}).get("value")
        b = (x.get("budget_estimate") or {}).get("value")
        r = (x.get("committee_recommendation") or {}).get("value")
        trips.append((e, b, r, x.get("line_item_text", "")))
    return trips


def main() -> None:
    gt = ground_truth()
    vis = vision_triples()
    vis_trip_set = {(e, b, r) for (e, b, r, _) in vis}
    vis_rec_set = {r for (_, _, r, _) in vis if r}

    exact = partial = missing = 0
    details = []
    for g in gt:
        key = (g["enacted"], g["budget"], g["recommended"])
        if key in vis_trip_set:
            exact += 1
            continue
        # how many columns match the best vision row?
        best = 0
        best_row = None
        for (e, b, r, t) in vis:
            score = sum(
                [g["enacted"] == e, g["budget"] == b, g["recommended"] == r]
            )
            if score > best:
                best, best_row = score, (e, b, r, t)
        if g["recommended"] in vis_rec_set or best >= 1:
            partial += 1
            details.append(("PARTIAL", g, best, best_row))
        else:
            missing += 1
            details.append(("MISSING", g, best, best_row))

    n = len(gt)
    print(f"Authoritative account blocks in HTML: {n}")
    print(f"  EXACT 3-number match in vision data: {exact}  ({exact/n:.0%})")
    print(f"  PARTIAL (1-2 of 3 columns match):    {partial}")
    print(f"  MISSING (account not found at all):  {missing}")
    print()
    for tag, g, best, br in details:
        print(f"[{tag}] {g['heading']!r}")
        print(f"    HTML : enacted={g['enacted']} budget={g['budget']} rec={g['recommended']}")
        if br:
            print(f"    best : enacted={br[0]} budget={br[1]} rec={br[2]}  ({best}/3)  {br[3]!r}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    main()
