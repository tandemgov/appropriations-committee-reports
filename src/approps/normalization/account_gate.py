"""Withhold account keys that are demonstrably wrong.

The crosswalk (`normalization.crosswalk`) and the Tango matcher (`normalization.tango_crosswalk`) resolve a row's label to a federal account symbol.
Both match on the label alone, so a label that names no particular account still resolves to one: "Offsetting collections" became a Treasury refunds account on 127 Interior rows, every Financial Services "Salaries and expenses" became FinCEN, and "DEPARTMENT OF THE ARMY" became the Army General Gift Fund.
`account_key` is the join key for longitudinal analysis, so a wrong key silently moves money between accounts.

This pass runs after matching and removes a key when any of these holds:

* `withheld_jurisdiction` — the key's agency is not one the row's subcommittee funds.
  The agency is the CGAC prefix of the symbol (`069-` is Transportation).
  Some accounts carry a prefix that is not their funding bill's (Payment to the Legal Services Corporation is `020-`, Treasury, and is funded in Commerce-Justice-Science), so a key is also allowed in any subcommittee where Senate rows attest it by an exact match on a specific, non-generic account heading in at least two reports.
  Agencies not in `JURISDICTION` are not checked.
* `withheld_heading` — the row is a department, title, or division heading, not an account.
* `withheld_generic` — every label on the row is appropriations boilerplate ("Salaries and expenses", "Rescission", "(emergency)"), nothing else on the row names the key's agency, and the label does not resolve to a single account within the subcommittee's jurisdiction.
* `withheld_ambiguous` — the crosswalk chose among several accounts sharing the label (`agency_scoped`) with no evidence on the row for its choice, and more than one of those accounts is within the subcommittee's jurisdiction.

A withheld key is kept in `account_key_withheld` so the decision can be reviewed; `account_key` is never populated by a guess.
"""

from __future__ import annotations

import re
from collections import defaultdict

from approps.normalization.account_names import normalize_account

_DEFENSE = frozenset({"Defense", "MilCon-VA"})

#: CGAC agency prefix -> subcommittees whose bills fund that agency's accounts.
JURISDICTION: dict[str, frozenset[str]] = {
    "009": frozenset({"Legislative-Branch"}),
    "010": frozenset({"Financial-Services"}),
    "011": frozenset({"Financial-Services", "State-Foreign-Ops", "Commerce-Justice-Science"}),
    "012": frozenset({"Agriculture", "Interior-Environment"}),  # Forest Service is in Interior
    "013": frozenset({"Commerce-Justice-Science"}),
    "014": frozenset({"Interior-Environment", "Energy-Water"}),  # Reclamation is in Energy-Water
    "015": frozenset({"Commerce-Justice-Science"}),
    "016": frozenset({"Labor-HHS-Education"}),
    "017": _DEFENSE,
    "019": frozenset({"State-Foreign-Ops"}),
    "020": frozenset({"Financial-Services", "State-Foreign-Ops"}),
    "021": _DEFENSE,
    "024": frozenset({"Financial-Services"}),
    "028": frozenset({"Labor-HHS-Education"}),
    "036": frozenset({"MilCon-VA"}),
    "047": frozenset({"Financial-Services"}),
    "049": frozenset({"Commerce-Justice-Science"}),
    "057": _DEFENSE,
    "068": frozenset({"Interior-Environment"}),
    "069": frozenset({"THUD"}),
    "070": frozenset({"Homeland-Security"}),
    "072": frozenset({"State-Foreign-Ops"}),
    "073": frozenset({"Financial-Services"}),
    # FDA is in Agriculture; Indian Health Service and the environmental-health institutes are in Interior.
    "075": frozenset({"Labor-HHS-Education", "Agriculture", "Interior-Environment"}),
    "080": frozenset({"Commerce-Justice-Science"}),
    "086": frozenset({"THUD"}),
    "089": frozenset({"Energy-Water"}),
    "091": frozenset({"Labor-HHS-Education"}),
    "096": frozenset({"Energy-Water"}),
    "097": _DEFENSE,
}

#: Normalized labels that name a kind of line, not a particular account.
GENERIC_LABELS = frozenset(
    s.strip()
    for s in """
    salaries and expenses|salaries|expenses|offsetting collections|rescission|rescissions|
    appropriation|appropriations|advance appropriation|advance appropriations|advances|
    budget year appropriations|administrative expenses|administrative costs|
    limitation on administrative expenses|program administration|program operations|
    program management|operating expenses|operations|administration|general administration|
    management and administration|departmental management|departmental administration|
    office of the secretary|immediate office of the secretary|office of inspector general|
    office of the inspector general|inspector general|office of general counsel|
    office of the general counsel|general counsel|legal services|operations and maintenance|
    operations and support|mission support|construction|procurement|
    procurement construction and improvements|research and development|research|grants|
    grants to states|state grants|federal funds|trust funds|working capital fund|
    undistributed adjustment|discretionary|mandatory|defense|nondefense|emergency|base|
    transfer|by transfer|transfer out|transfers|loan authorization|direct loans|
    loan guarantees|program account|subsidy|total|subtotal|payment|payments|
    information technology|facilities|fund|program|programs|overseas contingency operations
    """.split("|")
    if s.strip()
)

_HEADING = re.compile(r"^(title [ivxlcdm]+|division [a-z]|chapter \d+)\b", re.I)
_DEPARTMENT = re.compile(r"^departments? of\b", re.I)

_CONTEXT_STOP = frozenset(
    "the of and for to a an in on at by salaries expenses account fund funds program programs "
    "office administration department departments agency service services united states "
    "national federal".split()
)


def _tokens(*texts: str | None) -> set[str]:
    out: set[str] = set()
    for t in texts:
        for w in normalize_account(t or "").split():
            if len(w) > 2 and w not in _CONTEXT_STOP:
                out.add(w)
    return out


def _labels(row: dict) -> list[str]:
    """The labels the matchers try, in their order: `account`, `account_inferred`, `line_item_text`."""
    return [
        v.strip()
        for v in (row.get("account"), row.get("account_inferred"), row.get("line_item_text"))
        if isinstance(v, str) and v.strip()
    ]


def is_generic_label(label: str) -> bool:
    norm = normalize_account(label)
    return not norm or norm in GENERIC_LABELS


def is_heading_label(label: str) -> bool:
    """A title or division heading, or a bare department name ("DEPARTMENT OF THE ARMY", "Department of State").

    A department-prefixed account title ("Department of Defense Family Housing Improvement Fund") is not a heading.
    """
    s = re.sub(r"[.\s]+$", "", label.strip())
    if _HEADING.match(s):
        return True
    if _DEPARTMENT.match(s):
        return s.isupper() or len(normalize_account(s).split()) <= 4
    return False


def _specific(labels: list[str]) -> list[str]:
    return [lb for lb in labels if not is_generic_label(lb) and not is_heading_label(lb)]


def _in_jurisdiction(code: str, sub: str | None) -> bool:
    allowed = JURISDICTION.get(code[:3])
    return allowed is None or sub is None or sub in allowed


def _jurisdiction_candidates(label: str, sub: str | None) -> set[str] | None:
    """Account codes whose authoritative title starts with this label, among every agency that could appear in the subcommittee.

    None when the subcommittee is unknown, because then there is no jurisdiction to narrow by.
    Accounts of agencies outside `JURISDICTION` count as candidates everywhere: they are unchecked, not excluded.
    """
    from approps.normalization.crosswalk import load_reference

    norm = normalize_account(label)
    if not norm or sub is None:
        return None
    return {
        r.code
        for r in load_reference()
        if (r.title_norm == norm or r.title_norm.startswith(norm + " ")) and _in_jurisdiction(r.code, sub)
    }


def attested_keys(rows: list[dict], min_reports: int = 2) -> set[tuple[str, str]]:
    """(account_key, subcommittee) pairs Senate rows attest by an exact match on a specific account heading."""
    reports: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        if r.get("chamber") != "senate" or r.get("account_match") != "exact":
            continue
        key, sub = r.get("account_key"), r.get("subcommittee")
        if key and sub and _specific(_labels(r)):
            reports[(key, sub)].add(r.get("report_id"))
    return {pair for pair, rids in reports.items() if len(rids) >= min_reports}


def withhold_reason(row: dict, attested: set[tuple[str, str]]) -> str | None:
    """Why this row's `account_key` must be withheld, or None to keep it."""
    key = row.get("account_key")
    if not key:
        return None
    sub = row.get("subcommittee")
    labels = _labels(row)

    if not _in_jurisdiction(key, sub) and (key, sub) not in attested:
        return "withheld_jurisdiction"

    if is_heading_label(row.get("line_item_text") or ""):
        return "withheld_heading"

    # Evidence on the row beyond its labels and its subcommittee's name.
    context = _tokens(row.get("department"), row.get("agency"), row.get("title_name"), row.get("program"))
    context -= _tokens(*labels) | _tokens(sub)
    key_tokens = _tokens(row.get("account_key_title"), row.get("account_key_agency"), row.get("account_key_bureau"))
    corroborated = bool(context & key_tokens)
    if corroborated:
        return None

    def unique_in_jurisdiction(label: str) -> bool:
        # Only a checked agency can be the unique winner; an unchecked one proves nothing about the bill.
        return key[:3] in JURISDICTION and _jurisdiction_candidates(label, sub) == {key}

    if not _specific(labels):
        if any(unique_in_jurisdiction(lb) for lb in labels):
            return None
        return "withheld_generic"
    if row.get("account_match") == "agency_scoped":
        if any(unique_in_jurisdiction(lb) for lb in labels):
            return None
        return "withheld_ambiguous"
    return None


def gate_account_keys(rows: list[dict]) -> dict[str, int]:
    """Withhold failing keys in place. Returns a count per withholding reason."""
    attested = attested_keys(rows)
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        reason = withhold_reason(r, attested)
        if reason is None:
            continue
        r["account_key_withheld"] = r["account_key"]
        for col in ("account_key", "account_key_title", "account_key_agency", "account_key_bureau"):
            r[col] = None
        r["account_match"] = reason
        counts[reason] += 1
    return dict(counts)
