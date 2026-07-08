"""Match House appropriations line labels to canonical federal accounts via Tango.

House committee rows carry a readable label (`account_inferred`, else `line_item_text`)
but often no authoritative account identity. This maps that label to a **federal account
symbol** (USASpending/OMB account code) from Tango's TAS reference
(`data/reference/tango_accounts.csv`, refreshed by `scripts/fetch_tango_accounts.py`),
which also carries the agency + bureau the House rows otherwise lack entirely.

The match is conservative — never guess:
  - the label's significant tokens must be a subset of the account title's (containment),
  - and resolve to exactly ONE federal account symbol.
When several accounts across different agencies share a title fragment, the match is
ambiguous and is only taken if an `allowed_agencies` scope (derived from the report's
subcommittee) narrows it to one account. Anything still ambiguous is left unmatched.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from approps.config import REFERENCE_DIR

_STOP = frozenset(
    "the of and for to a an in on at by salaries expenses account accounts fund funds "
    "revolving appropriation appropriations".split()
)


def _tokens(s: str | None) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[a-z]+", (s or "").lower()) if len(w) > 2 and w not in _STOP)


@dataclass(frozen=True)
class TangoMatch:
    federal_account_symbol: str
    account_title: str
    agency: str
    bureau: str


class TangoCrosswalk:
    """Loads the federal-account reference once and matches labels against it."""

    def __init__(self, path: Path | None = None):
        path = path or (REFERENCE_DIR / "tango_accounts.csv")
        self._accounts: list[tuple[frozenset[str], TangoMatch]] = []
        self._postings: dict[str, set[int]] = {}
        if not path.exists():
            return
        with path.open(newline="") as fh:
            for r in csv.DictReader(fh):
                toks = _tokens(r.get("account_title"))
                if len(toks) < 2:
                    continue
                i = len(self._accounts)
                self._accounts.append(
                    (
                        toks,
                        TangoMatch(
                            federal_account_symbol=(r.get("federal_account_symbol") or "").strip(),
                            account_title=(r.get("account_title") or "").strip(),
                            agency=(r.get("agency") or "").strip(),
                            bureau=(r.get("bureau") or "").strip(),
                        ),
                    )
                )
                for t in toks:
                    self._postings.setdefault(t, set()).add(i)

    def _candidates(self, label_tokens: frozenset[str]) -> list[TangoMatch]:
        """Accounts whose title tokens are a superset of the label's (label ⊆ title)."""
        if len(label_tokens) < 2:
            return []
        # intersect the shortest posting lists first, then verify containment
        posting_sets = [self._postings.get(t) for t in label_tokens]
        if any(p is None for p in posting_sets):
            return []
        hits = set.intersection(*posting_sets)
        return [self._accounts[i][1] for i in hits if label_tokens <= self._accounts[i][0]]

    def match(self, label: str, allowed_agencies: set[str] | None = None) -> TangoMatch | None:
        """A single federal account for the label, or None if unmatched/ambiguous.

        Resolves when the candidates point to exactly one federal account symbol — either
        outright, or after narrowing to `allowed_agencies` (the subcommittee's agency scope)."""
        cands = self._candidates(_tokens(label))
        if not cands:
            return None
        if len({c.federal_account_symbol for c in cands}) == 1:
            return cands[0]
        if allowed_agencies:
            scoped = [c for c in cands if c.agency in allowed_agencies]
            if scoped and len({c.federal_account_symbol for c in scoped}) == 1:
                return scoped[0]
        return None
