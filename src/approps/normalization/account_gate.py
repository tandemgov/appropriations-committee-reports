"""Withhold account keys that are demonstrably wrong.

The crosswalk (`normalization.crosswalk`) and the Tango matcher (`normalization.tango_crosswalk`) resolve a row's label to a federal account symbol by the label alone.
A label that names no particular account still resolves to one: "Direct" on Agriculture loan rows became Treasury's Direct E-File Taskforce, "Mission Support" on Homeland rows became NASA, and "User Fees" on Labor-HHS rows became National Park Service filming fees.
`account_key` is the join key for longitudinal analysis, so a wrong key silently moves money between accounts.

After matching, a key is withheld when:

* `withheld_unmapped_agency` — the key's agency (the CGAC prefix of the symbol) has no entry in `JURISDICTION`, so nothing can say which bill funds it.
* `withheld_jurisdiction` — the agency is not funded by the row's subcommittee, or it is only through particular bureaus (`BUREAU_JURISDICTION`: Forest Service in Interior, FDA in Agriculture) and the account is not one of them, and the pairing is not one of the reviewed cross-coded accounts in `CROSS_CODED`.
  Repetition is not evidence: the same label-only match in many reports is still a label-only match, so there is no data-driven exception.
* `withheld_heading` — the row is a title, division, or bare department heading.
* `withheld_generic` — every label on the row is appropriations boilerplate ("Salaries and expenses", "Trust Funds", "(emergency)") and nothing else on the row names the key's agency.
* `withheld_partial_label` — the only specific label is a single word that merely begins a longer account title ("Direct", "Guaranteed", "Lead"), with nothing else on the row naming the agency.
* `withheld_ambiguous` — the crosswalk chose among several same-titled accounts (`agency_scoped`) with no evidence on the row, and more than one of them is within the subcommittee's jurisdiction.

The withheld key is kept in `account_key_withheld` for review.
The gate removes keys it can show are wrong; it does not prove the rest right (see docs/KNOWN_ISSUES.md #16).
"""

from __future__ import annotations

import re
from collections import defaultdict

from approps.normalization.account_names import normalize_account

_AG = "Agriculture"
_CJS = "Commerce-Justice-Science"
_DEF = "Defense"
_EW = "Energy-Water"
_FS = "Financial-Services"
_DHS = "Homeland-Security"
_INT = "Interior-Environment"
_LHHS = "Labor-HHS-Education"
_LEG = "Legislative-Branch"
_MCVA = "MilCon-VA"
_SFOPS = "State-Foreign-Ops"
_THUD = "THUD"


def _subs(*names: str) -> frozenset[str]:
    return frozenset(names)


#: CGAC agency prefix -> the subcommittees whose bills fund that agency's accounts.
#: Every agency that appears in the corpus is listed; a key from an unlisted agency is withheld rather than left unchecked.
JURISDICTION: dict[str, frozenset[str]] = {
    # Legislative branch
    "000": _subs(_LEG), "001": _subs(_LEG), "003": _subs(_LEG), "004": _subs(_LEG), "005": _subs(_LEG),
    "008": _subs(_LEG), "009": _subs(_LEG),
    # Judiciary and the Executive Office of the President
    "010": _subs(_FS),
    "011": _subs(_FS, _SFOPS, _CJS),  # EOP and Funds Appropriated to the President: international assistance in SFOPS, OSTP in CJS
    # Cabinet departments
    "012": _subs(_AG, _INT),  # Forest Service is in Interior
    "013": _subs(_CJS),
    "014": _subs(_INT, _EW),  # Reclamation and the Central Utah Project are in Energy-Water
    "015": _subs(_CJS),
    "016": _subs(_LHHS),
    "017": _subs(_DEF, _MCVA), "021": _subs(_DEF, _MCVA), "057": _subs(_DEF, _MCVA), "097": _subs(_DEF, _MCVA),
    "019": _subs(_SFOPS),
    "020": _subs(_FS, _SFOPS),  # Treasury international programs are in SFOPS
    "036": _subs(_MCVA),
    "069": _subs(_THUD),
    "070": _subs(_DHS),
    "075": _subs(_LHHS, _AG, _INT),  # FDA is in Agriculture; Indian Health Service and environmental-health programs are in Interior
    "086": _subs(_THUD),
    "089": _subs(_EW),
    "091": _subs(_LHHS),
    "096": _subs(_EW),
    # Independent agencies and other entities
    "018": _subs(_FS),   # Postal Service
    "024": _subs(_FS),   # Office of Personnel Management
    "025": _subs(_FS),   # National Credit Union Administration
    "026": _subs(_FS),   # Federal Retirement Thrift Investment Board
    "027": _subs(_FS),   # Federal Communications Commission
    "028": _subs(_LHHS),  # Social Security Administration
    "031": _subs(_EW),   # Nuclear Regulatory Commission
    "033": _subs(_INT),  # Kennedy Center; Wilson Center
    "047": _subs(_FS),   # General Services Administration
    "049": _subs(_CJS),  # National Science Foundation
    "050": _subs(_FS),   # Securities and Exchange Commission
    "051": _subs(_FS),   # FDIC Inspector General
    "056": _subs(_DEF),  # CIA Retirement and Disability System
    "060": _subs(_LHHS),  # Railroad Retirement Board
    "062": _subs(_FS),   # Office of Special Counsel
    "068": _subs(_INT),  # Environmental Protection Agency
    "071": _subs(_SFOPS),  # Overseas Private Investment Corporation
    "072": _subs(_SFOPS),  # USAID
    "073": _subs(_FS),   # Small Business Administration
    "074": _subs(_MCVA),  # American Battle Monuments Commission
    "080": _subs(_CJS),  # NASA
    "083": _subs(_SFOPS),  # Export-Import Bank
    "084": _subs(_MCVA),  # Armed Forces Retirement Home
    "088": _subs(_FS),   # National Archives
    "164": _subs(_SFOPS),  # Inter-American Foundation
    "235": _subs(_LHHS),  # Medicare Payment Advisory Commission
    "242": _subs(_SFOPS),  # Western Hemisphere Drug Policy Commission
    "246": _subs(_DEF),  # National Commission on Military Aviation Safety
    "272": _subs(_SFOPS),  # Congressional-Executive Commission on the PRC
    "290": _subs(_FS),   # Public Buildings Reform Board
    "295": _subs(_SFOPS),  # Commission on International Religious Freedom
    "302": _subs(_FS),   # Administrative Conference of the U.S.
    "309": _subs(_EW),   # Appalachian Regional Commission
    "310": _subs(_THUD),  # Access Board
    "323": _subs(_INT),  # Commission of Fine Arts
    "338": _subs(_LHHS),  # Committee for Purchase from People Who Are Blind or Severely Disabled
    "347": _subs(_EW),   # Defense Nuclear Facilities Safety Board
    "349": _subs(_FS),   # District of Columbia Courts
    "373": _subs(_INT),  # Institute of American Indian and Alaska Native Culture and Arts Development
    "376": _subs(_THUD),  # Interagency Council on Homelessness
    "387": _subs(_CJS),  # Marine Mammal Commission
    "417": _subs(_INT),  # National Endowment for the Arts
    "428": _subs(_THUD),  # Neighborhood Reinvestment Corporation
    "431": _subs(_EW),   # Nuclear Waste Technical Review Board
    "432": _subs(_LHHS),  # Occupational Safety and Health Review Commission
    "434": _subs(_FS),   # Office of Government Ethics
    "435": _subs(_INT),  # Office of Navajo and Hopi Indian Relocation
    "453": _subs(_CJS),  # State Justice Institute
    "458": _subs(_SFOPS),  # U.S. Institute of Peace
    "473": _subs(_FS),   # Federal Permitting Improvement Steering Council
    "474": _subs(_LHHS),  # Institute of Museum and Library Services
    "485": _subs(_LHHS),  # Corporation for National and Community Service
    "487": _subs(_INT, _FS),  # Udall Foundation
    "510": _subs(_INT),  # Chemical Safety Board
    "511": _subs(_FS),   # Court Services and Offender Supervision Agency
    "512": _subs(_INT),  # Presidio Trust
    "513": _subs(_EW),   # Denali Commission
    "514": _subs(_SFOPS),  # U.S. Agency for Global Media
    "517": _subs(_EW),   # Delta Regional Authority
    "519": _subs(_SFOPS),  # Vietnam Education Foundation
    "524": _subs(_SFOPS),  # Millennium Challenge Corporation
    "525": _subs(_FS),   # Election Assistance Commission
    "537": _subs(_THUD),  # Federal Housing Finance Agency Inspector General
    "539": _subs(_FS),   # Recovery Accountability and Transparency Board
    "542": _subs(_FS),   # Council of the Inspectors General on Integrity and Efficiency
    "546": _subs(_CJS),  # Commission on the State of U.S. Olympics and Paralympics
    "548": _subs(_SFOPS, _LEG),  # House Democracy Partnership
    "569": _subs(_EW),   # Southwest Border Regional Commission
    "570": _subs(_SFOPS),  # Eisenhower Exchange Fellowship Program
    "573": _subs(_EW),   # Northern Border Regional Commission
    "574": _subs(_EW),   # Southeast Crescent Regional Commission
    "575": _subs(_THUD),  # Amtrak Inspector General
    "579": _subs(_LHHS),  # Patient-Centered Outcomes Research Trust Fund
}

#: Where an agency is funded by several bills, the bureaus that justify each secondary bill.
#: Forest Service accounts are in Interior, but USDA's Hazardous Materials Management account is not; a key from that agency in that subcommittee must name one of these bureaus.
BUREAU_JURISDICTION: dict[tuple[str, str], re.Pattern] = {
    ("012", _INT): re.compile(r"Forest Service", re.I),
    ("014", _EW): re.compile(r"Reclamation|Central Utah", re.I),
    ("075", _AG): re.compile(r"Food and Drug", re.I),
    ("075", _INT): re.compile(r"Indian Health|Environmental Health Sciences|Toxic Substances", re.I),
    ("011", _CJS): re.compile(r"Science and Technology Policy|Space Council|Trade Representative", re.I),
    ("011", _SFOPS): re.compile(r"Funds Appropriated to the President|International|Foreign|Peacekeeping|Military Financing|Economic Support|Narcotics|Nonproliferation|Migration|Refugee", re.I),
    ("020", _SFOPS): re.compile(r"International|Multilateral|Debt|Global Environment|Tropical Forest|Development|Contribution|Technical Assistance|Clean Technology|Green Climate|Montreal Protocol", re.I),
}
for _prefix in ("017", "021", "057", "097"):
    BUREAU_JURISDICTION[(_prefix, _MCVA)] = re.compile(
        r"Construction|Family Housing|Base Realignment|Base Closure|NATO|North Atlantic Treaty|Security Investment|Improvement Fund|Homeowners Assistance|Cemeterial|Arlington", re.I
    )

#: Accounts whose symbol carries another agency's prefix but which the named subcommittee funds, each checked against the bills.
CROSS_CODED: dict[tuple[str, str], str] = {
    ("020-0501", _CJS): "Payment to the Legal Services Corporation carries a Treasury symbol and is appropriated in the CJS bill.",
    ("011-1453", _INT): "The Council on Environmental Quality carries an Executive Office symbol and is appropriated in the Interior bill.",
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
    information technology|facilities|fund|program|programs|overseas contingency operations|
    direct|guaranteed|user fees|enforcement|protection|training|equipment|preparedness
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


def in_jurisdiction(account_key: str, subcommittee: str | None, title: str | None = None) -> bool | None:
    """True or False for a mapped agency; None when the agency has no jurisdiction entry. A row without a subcommittee is not checked.

    Without a title, only the agency-level table is consulted.
    """
    allowed = JURISDICTION.get(account_key[:3])
    if allowed is None:
        return None
    if subcommittee is None:
        return True
    if (account_key, subcommittee) in CROSS_CODED:
        return True
    if subcommittee not in allowed:
        return False
    bureau = BUREAU_JURISDICTION.get((account_key[:3], subcommittee))
    return bureau is None or title is None or bool(bureau.search(title))


def _jurisdiction_candidates(label: str, sub: str | None) -> set[str] | None:
    """Account codes whose authoritative title starts with this label and fall within the subcommittee's jurisdiction."""
    from approps.normalization.crosswalk import load_reference

    norm = normalize_account(label)
    if not norm or sub is None:
        return None
    return {
        r.code
        for r in load_reference()
        if (r.title_norm == norm or r.title_norm.startswith(norm + " ")) and in_jurisdiction(r.code, sub, r.title)
    }


def _partial_single_word(label: str, title: str | None) -> bool:
    """A one-word label that only begins a longer title: "Direct" for "Direct E-File Taskforce"."""
    words = normalize_account(label).split()
    first = normalize_account((title or "").split(",")[0])
    return len(words) == 1 and words[0] != first


def withhold_reason(row: dict) -> str | None:
    """Why this row's `account_key` must be withheld, or None to keep it."""
    key = row.get("account_key")
    if not key:
        return None
    sub = row.get("subcommittee")
    labels = _labels(row)

    juris = in_jurisdiction(key, sub, row.get("account_key_title") or "")
    if juris is None:
        return "withheld_unmapped_agency"
    if not juris:
        return "withheld_jurisdiction"

    if is_heading_label(row.get("line_item_text") or ""):
        return "withheld_heading"

    specific = _specific(labels)
    # A lone word that is not the account's name is not rescued by a department heading on the row.
    if specific and all(_partial_single_word(lb, row.get("account_key_title")) for lb in specific):
        return "withheld_partial_label"

    # Evidence on the row beyond its labels and its subcommittee's name.
    context = _tokens(row.get("department"), row.get("agency"), row.get("title_name"), row.get("program"))
    context -= _tokens(*labels) | _tokens(sub)
    key_tokens = _tokens(row.get("account_key_title"), row.get("account_key_agency"), row.get("account_key_bureau"))
    if context & key_tokens:
        return None

    if not specific:
        return "withheld_generic"
    if row.get("account_match") == "agency_scoped":
        if any(_jurisdiction_candidates(lb, sub) == {key} for lb in labels):
            return None
        return "withheld_ambiguous"
    return None


def gate_account_keys(rows: list[dict]) -> dict[str, int]:
    """Withhold failing keys in place. Returns a count per withholding reason."""
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        reason = withhold_reason(r)
        if reason is None:
            continue
        r["account_key_withheld"] = r["account_key"]
        for col in ("account_key", "account_key_title", "account_key_agency", "account_key_bureau"):
            r[col] = None
        r["account_match"] = reason
        counts[reason] += 1
    return dict(counts)
