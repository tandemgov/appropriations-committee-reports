"""Normalization layer for the account-name crosswalk.

The same appropriations account appears with different text across fiscal years, chambers,
and stages. This module is the hygiene + canonicalization step that prepares a raw account
label for authoritative matching (see normalization.crosswalk). It deliberately does NOT
merge accounts on its own — naive fuzzy merging conflates distinct accounts (e.g. African
vs Asian Development Bank), so identity is resolved later against an authoritative account
list. See docs/crosswalk_scoping.md.

Per label it produces:
  - normalized:   a canonical string for matching (lowercased, de-noised, designation removed)
  - designation:  base | OCO | emergency | disaster | CHIMP | rescission  (a separate dimension)
  - is_fragment:  True for line-wrap / number-leak junk that should be quarantined
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Designation markers read ONLY from parentheticals/brackets or trailing ", X" qualifiers,
# never from the main account name — so "International Disaster Assistance" stays base while
# "International Disaster Assistance (emergency)" is tagged emergency.
_DESIGNATION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("OCO", re.compile(r"\b(oco|overseas contingency)", re.I)),
    ("emergency", re.compile(r"\bemergenc", re.I)),
    ("disaster", re.compile(r"\bdisaster (relief|designation)", re.I)),
    ("CHIMP", re.compile(r"\bchange[ds]? in mandatory|\bchimp", re.I)),
    ("rescission", re.compile(r"\brescis|\bcancellation", re.I)),
    ("base", re.compile(r"\bbase\b", re.I)),
]

# A trailing run of leaked amount columns. Amount columns frequently bleed in from the
# comparative table — one or several numbers where the thousands separator may be a comma
# OR a space (OCR). Each token is \d{1,3}(,or-space \d{3})*; a run of them is stripped from
# the end (e.g. "... 300 000", "... 1 320 743 743 577", "... 12 250 14 446 13 000").
_NUMBER_LEAK = re.compile(r"(?:\s+\$?\d{1,3}(?:[ ,]\d{3})*){1,}\s*$")
# Parenthetical / bracketed qualifier content.
_PARENS = re.compile(r"[(\[][^)\]]*[)\]]")
# Trailing ", Base" / ", Emergency" style qualifier.
_TRAILING_QUAL = re.compile(r",\s*(base|emergency|oco|disaster|rescission)\b.*$", re.I)


@dataclass(frozen=True)
class AccountLabel:
    """A cleaned account label: canonical string + designation dimension + quarantine flag."""

    normalized: str
    designation: str
    is_fragment: bool


def strip_number_leakage(text: str) -> str:
    """Remove trailing leaked amount columns (e.g. '... 300 000') while preserving years
    embedded mid-name ('Research at 1890 Institutions')."""
    prev = None
    while prev != text:
        prev = text
        text = _NUMBER_LEAK.sub("", text).strip()
    return text


def is_fragment(text: str) -> bool:
    """A line-wrap / junk fragment that should be quarantined, not treated as an account."""
    s = strip_number_leakage(text).strip()
    if len(s) < 4:
        return True
    if s[0].islower():  # real account titles start capitalized
        return True
    if s.count(")") > s.count("(") or s.count("]") > s.count("["):
        return True
    if s.endswith((",", "/", "-")):
        return True
    if re.match(r"^(and|or|the|of|operations|relief|appropriation)\b", s, re.I):
        return True
    return False


def extract_designation(raw_text: str) -> str:
    """Read the designation (base/OCO/emergency/…) from parentheticals and trailing
    qualifiers only — never from the account name body."""
    zones = " ".join(_PARENS.findall(raw_text))
    trail = _TRAILING_QUAL.search(raw_text)
    if trail:
        zones += " " + trail.group(0)
    for name, pat in _DESIGNATION_PATTERNS:
        if pat.search(zones):
            return name
    return "base"


def normalize_account(text: str) -> str:
    """Canonical matching string: drop leaked numbers, parentheticals, and qualifiers;
    lowercase; collapse punctuation/whitespace."""
    s = strip_number_leakage(text)
    s = _PARENS.sub("", s)
    s = _TRAILING_QUAL.sub("", s)
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_account_label(raw_text: str) -> AccountLabel:
    """Full hygiene + canonicalize pipeline for one raw account label."""
    return AccountLabel(
        normalized=normalize_account(raw_text),
        designation=extract_designation(raw_text),
        is_fragment=is_fragment(raw_text),
    )
