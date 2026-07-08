"""Parse hierarchical structure from comparative statement tables.

Comparative statements use indentation and capitalization to indicate hierarchy:
    TITLE I--AGRICULTURAL PROGRAMS          (Title level, all caps)
      DEPARTMENT OF AGRICULTURE             (Department level, all caps, indented)
        FARM SERVICE AGENCY                 (Agency level, all caps, more indented)
          Salaries and Expenses             (Account level, title case)
            Direct loans                    (Program level, lower case)

This module provides utilities for detecting hierarchy from text formatting.
Sprint 3 work — stub for now.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from approps.output.schemas import HierarchyLevel


@dataclass
class HierarchyNode:
    """A node in the hierarchy tree."""

    text: str
    level: HierarchyLevel
    indent: int
    children: list[HierarchyNode] = field(default_factory=list)


def detect_indent(line: str) -> int:
    """Count leading spaces in a line."""
    return len(line) - len(line.lstrip())


def detect_hierarchy_level(line: str, indent: int) -> HierarchyLevel:
    """Detect the hierarchy level of a line based on indentation and capitalization.

    This is a heuristic that will need tuning as we encounter more report formats.
    """
    stripped = line.strip()

    if not stripped:
        return HierarchyLevel.TITLE

    # Title lines: "TITLE I--..." at low indent
    if re.match(r"TITLE\s+[IVXLC]+", stripped):
        return HierarchyLevel.TITLE

    # All caps at low indent = department or agency
    if stripped.isupper() and indent < 8:
        return HierarchyLevel.DEPARTMENT

    if stripped.isupper() and indent >= 8:
        return HierarchyLevel.AGENCY

    # Title case or mixed case = account level
    if indent < 16:
        return HierarchyLevel.ACCOUNT

    # Deeper indent = program or subprogram
    if indent < 24:
        return HierarchyLevel.PROGRAM

    return HierarchyLevel.SUBPROGRAM


def is_subtotal_line(text: str) -> bool:
    """Check if a line is a subtotal or total line."""
    stripped = text.strip().lower()
    return (
        stripped.startswith(("total,", "subtotal,", "total ", "subtotal ", "total--", "subtotal--"))
        or stripped == "total"
        or stripped == "subtotal"
    )
