"""Authoritative account crosswalk.

Resolves each extracted account name to a stable authoritative identity — the USASpending
federal-account code (the OMB symbol, e.g. 072-1035), sourced in
data/reference/federal_accounts.json. Anchoring to authoritative codes (rather than fuzzy
self-clustering) is what keeps distinct-but-similar accounts apart — e.g. African vs Asian
Development Bank — see docs/crosswalk_scoping.md.

Conservative by design — it never invents a merge it cannot justify:

  1. exact/prefix-unique   our normalized account is a unique token-prefix of an authoritative title
  2. agency-scoped         several authoritative accounts share that prefix; pick the one whose
                           agency/bureau tokens overlap the row's own context (subcommittee,
                           department, agency, title). No unique winner -> needs_review.
  3. fuzzy (tight)         no prefix; a token_set_ratio >= 92 single best whose agency tokens
                           also overlap the context. Otherwise unmatched.

Anything not confidently resolved is left blank with method=unmatched/needs_review for a
human queue — coverage is gated by account-extraction quality (program-level rows and
OCR/wording drift do not have a 1:1 account), so partial coverage is expected and reported
honestly rather than forced.
"""

from __future__ import annotations

import csv
import functools
import json
from dataclasses import dataclass

from rapidfuzz import fuzz

from approps.config import RAW_DIR
from approps.normalization.account_names import normalize_account

_REF_DIR = RAW_DIR.parent / "reference"
_FEDERAL_ACCOUNTS = _REF_DIR / "federal_accounts.json"

_FUZZY_THRESHOLD = 92


@dataclass(frozen=True)
class AccountMatch:
    account_key: str
    account_title: str
    method: str  # exact | agency_scoped | fuzzy | unmatched
    needs_review: bool


_UNMATCHED = AccountMatch("", "", "unmatched", True)


@dataclass(frozen=True)
class _Ref:
    code: str
    title: str
    title_norm: str
    agency_tokens: frozenset


@functools.lru_cache(maxsize=1)
def load_reference() -> list[_Ref]:
    data = json.loads(_FEDERAL_ACCOUNTS.read_text())
    accounts = data["accounts"] if isinstance(data, dict) else data
    refs = []
    for a in accounts:
        title = a.get("account_title") or ""
        agency = " ".join(
            str(a.get(k) or "")
            for k in ("managing_agency", "managing_agency_acronym", "bureau_name")
        )
        refs.append(
            _Ref(
                code=a["federal_account_code"],
                title=title,
                title_norm=normalize_account(title),
                agency_tokens=frozenset(normalize_account(agency).split()),
            )
        )
    return refs


def _ctx_tokens(context: str) -> frozenset:
    return frozenset(normalize_account(context).split())


def match_account(normalized_account: str, context: str = "") -> AccountMatch:
    """Resolve one normalized account name (+ optional context text) to an authoritative code."""
    if not normalized_account:
        return _UNMATCHED
    refs = load_reference()
    ctx = _ctx_tokens(context)

    # Pass 1/2: token-prefix candidates (authoritative title starts with our account name).
    prefix = [
        r for r in refs
        if r.title_norm == normalized_account or r.title_norm.startswith(normalized_account + " ")
    ]
    if len(prefix) == 1:
        r = prefix[0]
        return AccountMatch(r.code, r.title, "exact", needs_review=False)
    if len(prefix) > 1:
        scored = sorted(prefix, key=lambda r: len(r.agency_tokens & ctx), reverse=True)
        best = len(scored[0].agency_tokens & ctx)
        # require a clear, non-zero agency winner
        if best > 0 and (len(scored) == 1 or len(scored[1].agency_tokens & ctx) < best):
            r = scored[0]
            return AccountMatch(r.code, r.title, "agency_scoped", needs_review=False)
        return AccountMatch("", "", "ambiguous", needs_review=True)

    # Pass 3: tight fuzzy, agency-constrained.
    best_r, best_score = None, 0
    for r in refs:
        if ctx and not (r.agency_tokens & ctx):
            continue
        score = fuzz.token_set_ratio(normalized_account, r.title_norm)
        if score > best_score:
            best_r, best_score = r, score
    if best_r and best_score >= _FUZZY_THRESHOLD:
        # Fuzzy is a SUGGESTION, never a trusted assignment: token_set_ratio over-credits
        # short/generic names (e.g. "communications", "mexico") and would over-merge. The
        # suggested key rides in the crosswalk file for review but is gated out of the
        # trusted output (see method == "fuzzy" / needs_review).
        return AccountMatch(best_r.code, best_r.title, "fuzzy", needs_review=True)
    return _UNMATCHED


def write_crosswalk(crosswalk: dict[tuple[str, str], AccountMatch], path) -> None:
    """Persist the distinct-account crosswalk for inspection / human review."""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["subcommittee", "normalized_account", "account_key", "account_title",
                    "method", "needs_review"])
        for (sub, norm), m in sorted(crosswalk.items()):
            w.writerow([sub, norm, m.account_key, m.account_title, m.method, m.needs_review])
