"""Enacted dot-leader rows keep labels that carry dashes and typographic apostrophes.

The label character class once stopped at ASCII, so `F–22`, `AH–64 Mods`, and `Counter-Lord’s Resistance Army` never matched and their rows were dropped.
"""

from approps.extraction.comparative_enacted import extract_enacted_pages

PAGE = "\n".join([
    "DIVISION A—DEPARTMENT OF DEFENSE",
    "Aircraft Procurement, Air Force:",
    "   F–22 ........................................................ 83,261,000",
    "   AH–64 Mods .................................................. 3,372,000",
    "   General Information Technology—TDNE ......................... 37,100,000",
    "   Counter-Lord’s Resistance Army .............................. 10,000,000",
    "   Plain Line Item ............................................. 1,000,000",
])


def test_dash_and_apostrophe_labels_are_extracted():
    rows = extract_enacted_pages([PAGE], "CPRT-TEST", 118, 2024)
    got = {r.line_item_text: r.committee_recommendation.value for r in rows}
    assert got == {
        "F–22": 83_261_000,
        "AH–64 Mods": 3_372_000,
        "General Information Technology—TDNE": 37_100_000,
        "Counter-Lord’s Resistance Army": 10_000_000,
        "Plain Line Item": 1_000_000,
    }
