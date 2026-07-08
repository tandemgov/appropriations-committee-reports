"""Recall cross-check: are all inline-table accounts present in the comparative data?

The delta-arithmetic gate (verify_house.py / verify.py) validates the VALUES of the
rows that were extracted, but it is blind to rows that were never extracted at all.
Vision extraction (Nemotron crop mode especially) can silently drop rows on a page
whose surviving rows still pass arithmetic.

The inline narrative funding tables are extracted deterministically from the report
HTML and are 100% verified, so they are an independent ground truth for which
accounts MUST appear. This module checks every inline account against the comparative
extraction by NAME (presence), not value — value differences are expected for a few
accounts (offsetting collections: inline is gross, comparative is net) and are the
delta gate's concern. A missing NAME means a silently dropped account → a recall gap.

Used both as a standalone audit (scripts/recall_check.py) and as an extra suspect-page
signal for the hybrid extractor.
"""

from __future__ import annotations

import csv
import json
import re

from approps.config import EXTRACTED_DIR

_PREFIX_RE = re.compile(r"^\s*(sub)?total[,:]?\s*", re.IGNORECASE)
_NONALNUM_RE = re.compile(r"[^a-z0-9]+")
# Generic words that should not by themselves drive a name match.
_STOPWORDS = {"of", "the", "and", "for", "office", "and", "to", "in", "a"}


def normalize(name: str) -> str:
    """Canonicalise an account label: drop Total/Subtotal prefix, dots, punctuation."""
    name = _PREFIX_RE.sub("", name or "")
    name = _NONALNUM_RE.sub(" ", name.lower())
    return name.strip()


def _tokens(norm: str) -> set[str]:
    return {w for w in norm.split() if w not in _STOPWORDS and len(w) > 1}


def _account(name: str, context: str, value: int | None) -> dict:
    return {
        "account_name": name,
        "context_heading": context or "",
        "committee_recommendation": value,
        "norm": normalize(name),
    }


def load_inline_accounts(report_id: str) -> list[dict]:
    """Load the verified inline funding accounts for a report.

    Prefers the flat ``{report_id}_inline.csv``; falls back to the ``inline_tables``
    stored in the extracted ``{report_id}.json``. Returns [] if neither has inline
    data (recall check is then skipped).
    """
    # 1. Flat inline CSV
    path = EXTRACTED_DIR / f"{report_id}_inline.csv"
    if path.exists():
        out = []
        with path.open() as f:
            for row in csv.DictReader(f):
                rec = row.get("committee_recommendation") or ""
                try:
                    value = int(float(rec)) if rec else None
                except ValueError:
                    value = None
                name = row.get("account_name") or row.get("context_heading") or ""
                if name.strip():
                    out.append(_account(name, row.get("context_heading") or "", value))
        if out:
            return out

    # 2. Fallback: inline_tables in the extracted report JSON
    for jpath in EXTRACTED_DIR.rglob(f"{report_id}.json"):
        data = json.loads(jpath.read_text())
        tables = data.get("inline_tables") or []
        out = []
        for t in tables:
            name = t.get("account_name") or t.get("context_heading") or ""
            value = (t.get("committee_recommendation") or {}).get("value")
            if name.strip():
                out.append(_account(name, t.get("context_heading") or "", value))
        if out:
            return out

    return []


def _comp_value(line: dict) -> int | None:
    return (line.get("committee_recommendation") or {}).get("value")


def _name_match(inline_norm: str, inline_tokens: set[str], comp_index: list[tuple]) -> dict | None:
    """Find a comparative row matching by name. comp_index is (norm, tokens, line)."""
    for norm, _t, line in comp_index:  # exact
        if norm == inline_norm and inline_norm:
            return line
    if len(inline_tokens) >= 2:  # containment (guard against trivially short names)
        for norm, _t, line in comp_index:
            if inline_norm and norm and (inline_norm in norm or norm in inline_norm):
                return line
    best, best_j = None, 0.0  # token Jaccard
    for _norm, t, line in comp_index:
        if not t or not inline_tokens:
            continue
        j = len(inline_tokens & t) / len(inline_tokens | t)
        if j > best_j:
            best, best_j = line, j
    return best if best_j >= 0.7 else None


def audit_recall(comparative_lines: list[dict], inline_accounts: list[dict]) -> dict:
    """Check every inline account for presence in the comparative extraction.

    Anchors on the committee-recommendation VALUE: dollar figures (9-10 digits) are
    effectively unique, so they disambiguate accounts that share a generic name (every
    agency has an "Operations and Support"). Name matching is the fallback for the few
    accounts whose comparative total is NET of offsetting collections (value differs).

    Returns a summary with the list of MISSING accounts (silent recall gaps).
    """
    comp_index = [
        (normalize(x.get("line_item_text", "")), _tokens(normalize(x.get("line_item_text", ""))), x)
        for x in comparative_lines
        if x.get("line_item_text")
    ]
    value_set = {_comp_value(x) for x in comparative_lines if _comp_value(x) is not None}

    found_value = found_name = 0
    missing = []
    for acc in inline_accounts:
        v = acc["committee_recommendation"]
        if v is not None and v in value_set:
            found_value += 1  # unique dollar figure present -> account covered
        elif _name_match(acc["norm"], _tokens(acc["norm"]), comp_index) is not None:
            found_name += 1  # present by name; value differs (offsetting collections)
        else:
            missing.append(acc)
    total = len(inline_accounts)
    return {
        "inline_accounts": total,
        "found_by_value": found_value,
        "found_by_name": found_name,
        "missing": missing,
        "recall": ((total - len(missing)) / total) if total else None,
    }


def suspect_pages_from_missing(missing: list[dict], comparative_lines: list[dict]) -> tuple[set[int], list[dict]]:
    """Map missing accounts to comparative pages via department/context token overlap.

    Returns (pages_to_recheck, unmappable_missing). A missing account is mapped to the
    page(s) of comparative rows in the same department/context; if none overlap, it is
    unmappable (cannot be auto-routed — surface for manual/whole-report handling).
    """
    pages: set[int] = set()
    unmappable = []
    for acc in missing:
        ctx = _tokens(normalize(acc.get("context_heading") or acc["account_name"]))
        hit = set()
        for x in comparative_lines:
            dept = _tokens(normalize(
                (x.get("department") or "") + " " + (x.get("title_name") or "") + " " + x.get("line_item_text", "")
            ))
            if ctx and len(ctx & dept) / len(ctx) >= 0.6:
                hit.add(x.get("line_number", 0) // 100)
        if hit:
            pages |= hit
        else:
            unmappable.append(acc)
    return pages, unmappable
