"""Map report titles to the 12 appropriations subcommittees."""

from __future__ import annotations

import re

# Patterns to match report titles to subcommittees.
# Order matters: more specific patterns first to avoid false matches.
SUBCOMMITTEE_PATTERNS: dict[str, list[str]] = {
    "Agriculture": [
        "agriculture",
        "rural development",
        "food and drug",
    ],
    "Commerce-Justice-Science": [
        "commerce, justice",
        "science, and related",
    ],
    "Defense": [
        "department of defense appropriations",
        "defense appropriations",
    ],
    "Energy-Water": [
        "energy and water",
    ],
    "Financial-Services": [
        "financial services",
        "general government",
    ],
    "Homeland-Security": [
        "homeland security",
    ],
    "Interior-Environment": [
        "interior, environment",
        "interior and environment",
        "department of the interior",
    ],
    "Labor-HHS-Education": [
        "labor, health",
        "human services",
        "education, and related",
    ],
    "Legislative-Branch": [
        "legislative branch",
    ],
    "MilCon-VA": [
        "military construction",
        "veterans affairs",
    ],
    "State-Foreign-Ops": [
        "state, foreign operations",
        "foreign operations",
        # 119th Congress House renamed this subcommittee to
        # "National Security, Department of State, and Related Programs".
        "department of state, and related programs",
    ],
    "THUD": [
        "transportation, housing",
        "urban development",
        "transportation, and housing",
    ],
}


def classify_subcommittee(title: str) -> str | None:
    """Classify a report title to one of the 12 appropriations subcommittees.

    Returns the canonical subcommittee name, or None if no match is found.
    """
    title_lower = title.lower()

    for subcommittee, patterns in SUBCOMMITTEE_PATTERNS.items():
        for pattern in patterns:
            if pattern in title_lower:
                return subcommittee

    return None


def extract_fiscal_year(title: str) -> int | None:
    """Extract the fiscal year from a report title.

    Looks for patterns like:
    - "Appropriations Bill, 2025"
    - "fiscal year ending September 30, 2025"
    - "fiscal year 2025"
    - "Appropriation Bill, 2024"
    """
    # "Bill, YYYY" / "Act, YYYY" / "Bills, YYYY" (a combined Senate print covers plural "bills")
    match = re.search(r"(?:bill|act)s?,?\s+(\d{4})", title, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # "fiscal year ending September 30, YYYY"
    match = re.search(r"september\s+30,\s+(\d{4})", title, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # "fiscal year YYYY"
    match = re.search(r"fiscal\s+year\s+(\d{4})", title, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # "Appropriations, YYYY"
    match = re.search(r"appropriations?,\s+(\d{4})", title, re.IGNORECASE)
    if match:
        return int(match.group(1))

    return None


def classify_stage(title: str, package_id: str) -> str:
    """Classify the legislative stage from a report title and package ID.

    Returns: "subcommittee", "committee", or "conference"
    """
    title_lower = title.lower()

    if "conference" in title_lower or "joint explanatory" in title_lower:
        return "conference"

    # Conference reports often have specific report number patterns
    # but we primarily rely on the title

    return "committee"
