"""Text-layer extractor for born-digital, typeset House committee prints.

Most historical House reports embed their comparative tables as page IMAGES, so
they need the vision pipeline (`comparative_house`). But the modern House
full-committee prints (e.g. the FY2027 Defense markup, docs.house.gov) are
born-digital and fully typeset: the funding tables are real text. For those this
module parses the text layer directly -- deterministic, free, exact -- and the
detector `is_born_digital_house_pdf` lets the router pick this path automatically.

The detailed data lives in "EXPLANATION OF PROJECT LEVEL ADJUSTMENTS" tables, one
per appropriations account, all [in thousands], three dollar columns: Budget
Request / Committee Recommended / Change from Request. Structure handled:

  * Account boundary  : "The Committee recommends the following appropriations for
                        <Account>:" precedes each table. The canonical account
                        name is the ALL-CAPS heading above that sentence (the
                        table TOTAL line is unreliable -- RDT&E totals drop the
                        service word "ARMY").
  * Line item         : "<code> <ITEM> <req> <rec> <chg>" where <code> is a P/M/
                        R/W-1 number, letter-suffixed (16A) or a Navy Sub-Activity
                        -Group code (1A1A, BSIT, 4C1P, 9999); some accounts list
                        uncoded items (LEBANON TRAIN AND EQUIP, Health Program).
  * Offset row        : non-add committee reductions, 2- or 3-column, from a fixed
                        vocabulary (LESS REIMBURSABLES, UNDISTRIBUTED ADJUSTMENT,
                        HISTORICAL UNOBLIGATED BALANCES, PROJECTED OVERESTIMATION
                        OF CIVILIAN COMPENSATION).
  * TOTAL / subtotal  : "TOTAL[, TITLE x], <name> <req> <rec> <chg>" -- emitted as
                        an is_subtotal line; the last TOTAL in an account span is
                        that account's level. TOTAL lines can wrap; merged first.

Self-verifying like `comparative_enacted`: each emitted amount's raw text is
confirmed to appear on its source page, so the JSON ships with verified=true
(there is no companion HTML for the `verify` command to use). Internal
arithmetic is checked separately by `reconcile` (covered in the tests).

GPO font substitutes a yen sign / slashed-O for a leading minus.
"""

from __future__ import annotations

import re

import pdfplumber

from approps.output.schemas import (
    Chamber,
    ComparativeStatementLine,
    DollarAmount,
    ExtractionMethod,
    HierarchyLevel,
    Stage,
)

_MINUS = {"¥": "-", "Ø": "-", "−": "-"}


def _norm(line: str) -> str:
    for k, v in _MINUS.items():
        line = line.replace(k, v)
    return line


_AMT_TOK = re.compile(r"^[+\-]?[\d,]+$")
_FURNITURE = re.compile(
    r"VerDate|Jkt \d|PO \d{5}|Frm \d|Fmt \d|Sfmt \d|E:\\HR|PFRM|SGNIRAEH|"
    r"DORP|nosliwMD|^htiw$|^no$|In thousands of dollars|Dollars in thousands"
)
_ANCHOR = "recommends the following appropriations for"
_HEADING = re.compile(r"^[A-Z0-9][A-Z0-9 ,&/.\-\[\]()']*[A-Z)\]]$")
_TITLE_RE = re.compile(r"^TITLE\s+([IVX]+)\b")
# Recap/summary rows use a dot leader (long names get only a 2-dot leader);
# detail line items never do.
_DOTS = re.compile(r"\.{2,}")
_CODE_RE = re.compile(r"^([0-9A-Z][0-9A-Z]{0,4})\s+(.+)$")
_OFFSETS = {
    "LESS REIMBURSABLES",
    "UNDISTRIBUTED ADJUSTMENT",
    "HISTORICAL UNOBLIGATED BALANCES",
    "PROJECTED OVERESTIMATION OF CIVILIAN COMPENSATION",
}
_MARKERS = ("EXPLANATION OF PROJECT LEVEL ADJUSTMENTS", _ANCHOR)

# Some single-appropriation accounts (Title VII Related Agencies) appear not as
# line-item tables but as a 3-line inline funding block:
#   "Fiscal year 2027 budget request ....... $514,000"
#   "Committee recommendation .............. $514,000"
#   "Change from budget request ............ $0"
# Amounts carry a '$' (in thousands). The "Committee recommendation" line and the
# '$' distinguish funding blocks from end-strength tables ("Fiscal year 2027
# recommendation ..... 1,342,000"), which are troop counts, not dollars.
_FY_REQ = re.compile(r"^Fiscal year \d{4} budget request\b")
_CR = re.compile(r"^Committee recommendation\b")
_CHG = re.compile(r"^Change from budget request\b")
_BLOCK_AMT = re.compile(r"(-?)\$(-?)([\d,]+)")


def _to_int(raw: str) -> int | None:
    raw = raw.strip().replace(",", "")
    if not raw or set(raw) <= {".", " ", "-", "+"}:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _trailing_amounts(s: str) -> tuple[str, list[str]]:
    """Split a row into (text_before, [trailing raw amount tokens])."""
    toks = s.split()
    n = 0
    while n < len(toks) and _AMT_TOK.match(toks[len(toks) - 1 - n]):
        n += 1
    if n == 0:
        return s, []
    return " ".join(toks[: len(toks) - n]), toks[len(toks) - n:]


def _flatten(pdf) -> tuple[list[tuple[int, str]], dict[int, str]]:
    """Normalized (page_number, line) pairs with wrapped TOTAL lines merged.

    A TOTAL line whose amounts spill onto the next physical line (RDT&E, FUDS) is
    joined with its successor so the three columns parse as one row. Also returns
    a {page_number: full_text} map for verbatim amount verification.
    """
    raw: list[tuple[int, str]] = []
    page_text: dict[int, str] = {}
    for pidx, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        page_text[pidx + 1] = text
        for line in text.split("\n"):
            s = _norm(line).strip()
            if s and not _FURNITURE.search(s):
                raw.append((pidx + 1, s))
    merged: list[tuple[int, str]] = []
    i = 0
    while i < len(raw):
        pno, s = raw[i]
        if s.startswith("TOTAL") and len(_trailing_amounts(s)[1]) < 3 and i + 1 < len(raw):
            s = f"{s} {raw[i + 1][1]}"
            i += 1
        merged.append((pno, s))
        i += 1
    return merged, page_text


def _account_name(lines: list[tuple[int, str]], anchor_idx: int) -> str | None:
    """Canonical account name = ALL-CAPS heading above the anchor sentence."""
    j = anchor_idx - 1
    while j >= 0 and (not lines[j][1] or lines[j][1].isdigit() or lines[j][1].startswith("(")):
        j -= 1
    if j < 0:
        return None
    base = lines[j][1]
    if base.startswith("TOTAL") or _trailing_amounts(base)[1]:
        return None
    head = [base]
    k = j - 1
    while k >= 0:
        prev = lines[k][1]
        if not prev:
            k -= 1
            continue
        if (
            prev.endswith(",")
            and _HEADING.match(prev.rstrip(","))
            and not prev.startswith("TOTAL")
            and not _trailing_amounts(prev)[1]
        ):
            head.insert(0, prev)
            k -= 1
        else:
            break
    name = re.sub(r"\s+", " ", " ".join(head)).strip()
    return name if _HEADING.match(name) else None


def _block_raw(s: str) -> str | None:
    """Pull the signed amount from an inline-block line (requires a '$')."""
    m = _BLOCK_AMT.search(s)
    if not m:
        return None
    sign = "-" if (m.group(1) == "-" or m.group(2) == "-") else ""
    return sign + m.group(3)


def _inline_heading(lines: list[tuple[int, str]], idx: int) -> str | None:
    """Account name for an inline block = the ALL-CAPS heading lines above it."""
    head: list[str] = []
    k = idx - 1
    while k >= 0 and len(head) < 4:
        prev = lines[k][1]
        if not prev:
            k -= 1
            continue
        if (_HEADING.match(prev) and not prev.startswith("TOTAL")
                and not _trailing_amounts(prev)[1] and "recommendation" not in prev.lower()):
            head.insert(0, prev)
            k -= 1
        else:
            break
    name = re.sub(r"\s+", " ", " ".join(head)).strip()
    return name or None


_RECAP_TITLE = re.compile(r"^(Title\s+[IVX]+)\s*[—–-]\s*(.+?)\.{2,}")
_NUMTOK = re.compile(r"[+\-]?\d{1,3}(?:,\d{3})+")


def _parse_recap(lines: list[tuple[int, str]]) -> list[dict]:
    """The page-2 RECAPITULATION: title-level totals (incl. Title VIII general
    provisions, which has no account table) and the bill grand total. These rows
    are dot-leadered, so the detail parser skips them; capture them here for
    topline closure and an independent title cross-check.
    """
    out: list[dict] = []
    seen: set[str] = set()  # the recap is reprinted later; keep the first of each
    for pno, s in lines:
        m = _RECAP_TITLE.match(s)
        if m:
            nums = [_to_int(t) for t in _trailing_amounts(s)[1]]
            if len(nums) >= 3:
                req, rec = nums[0], nums[1]
            elif len(nums) == 2:        # Title VIII: blank request column
                req, rec = None, nums[0]
            else:
                continue
            name = f"{m.group(1)}—{re.sub(r'\s+', ' ', m.group(2)).strip()}"
            if name not in seen:
                seen.add(name)
                out.append({"name": name, "page": pno, "kind": "title", "req": req, "rec": rec})
        elif s.startswith("Total, Department of Defense") and "Total, Department of Defense" not in seen:
            nums = _NUMTOK.findall(s)
            if len(nums) >= 2:
                seen.add("Total, Department of Defense")
                out.append({"name": "Total, Department of Defense", "page": pno,
                            "kind": "grand", "req": _to_int(nums[0]), "rec": _to_int(nums[1])})
    return out


def _parse(pdf_path) -> dict:
    """Parse the report into accounts (rows + totals) and a reconciliation ledger."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        lines, page_text = _flatten(pdf)

    accounts: list[dict] = []
    inline: list[dict] = []
    ledger: list[dict] = []
    current = None
    current_title = None
    pending = None  # last value/offset row, for attaching adjustment marks

    for idx, (pno, s) in enumerate(lines):
        mt = _TITLE_RE.match(s)
        if mt and len(s) < 60:
            current_title = f"Title {mt.group(1)}"

        # Inline 3-line funding block (e.g. Title VII related agencies).
        if (_FY_REQ.match(s) and idx + 2 < len(lines)
                and _CR.match(lines[idx + 1][1]) and _CHG.match(lines[idx + 2][1])):
            req, rec = _block_raw(s), _block_raw(lines[idx + 1][1])
            if req is not None and rec is not None:        # '$' present -> dollars, not end strength
                inline.append({"title": current_title, "account": _inline_heading(lines, idx),
                               "page": pno, "req": req, "rec": rec,
                               "chg": _block_raw(lines[idx + 2][1])})
            continue

        if _ANCHOR in s:
            current = {"title": current_title, "account": _account_name(lines, idx),
                       "rows": [], "totals": []}
            accounts.append(current)
            pending = None
            continue
        if current is None or _DOTS.search(s):
            continue

        text, amts = _trailing_amounts(s)

        if s.startswith("TOTAL") and len(amts) >= 3:
            current["totals"].append({"label": text, "page": pno,
                                      "req": amts[-3], "rec": amts[-2], "chg": amts[-1]})
            ledger.append({"kind": "total", "label": text, "account": current["account"],
                           "req": _to_int(amts[-3]), "rec": _to_int(amts[-2])})
            pending = None
            continue

        if len(amts) >= 3 and not text.lower().startswith(("the ", "section ")):
            mc = _CODE_RE.match(text)
            if text in _OFFSETS:
                code, item, rtype = None, text, "offset"
            elif mc and (any(ch.isdigit() for ch in mc.group(1)) or len(mc.group(1)) >= 4):
                code, item, rtype = mc.group(1), mc.group(2).strip(), "line_item"
            else:
                code, item, rtype = None, text, "line_item"
            pending = {"code": code, "item": item, "row_type": rtype, "page": pno,
                       "req": amts[-3], "rec": amts[-2], "chg": amts[-1], "adjustments": []}
            current["rows"].append(pending)
            ledger.append({"kind": "value", "req": _to_int(amts[-3]), "rec": _to_int(amts[-2])})
            continue

        if len(amts) == 2 and text in _OFFSETS:
            pending = {"code": None, "item": text, "row_type": "offset", "page": pno,
                       "req": None, "rec": amts[-2], "chg": amts[-1], "adjustments": []}
            current["rows"].append(pending)
            ledger.append({"kind": "value", "req": 0, "rec": _to_int(amts[-2])})
            continue

        # Adjustment sub-row (one trailing amount) -> a congressional mark.
        if len(amts) == 1 and pending is not None and text and not text.isupper():
            pending["adjustments"].append({"description": text, "amount": _to_int(amts[0])})

    return {"accounts": accounts, "inline": inline, "recap": _parse_recap(lines),
            "ledger": ledger, "page_text": page_text}


def reconcile(ledger: list[dict]) -> dict:
    """Hierarchical check: every TOTAL equals either the line items since the
    previous TOTAL (a leaf) or a rollup of recent subtotals. Returns counts and
    the mismatching nodes. A clean extraction yields bad == 0.
    """
    stack: list[tuple[int, int]] = []
    since_req = since_rec = since_n = 0
    leaf = rollup = bad = 0
    mismatches = []
    for e in ledger:
        if e["kind"] == "value":
            since_req += e["req"] or 0
            since_rec += e["rec"] or 0
            since_n += 1
            continue
        tr, tc = e["req"], e["rec"]
        if since_n and since_req == tr and since_rec == tc:
            leaf += 1
            stack.append((tr, tc))
            since_req = since_rec = since_n = 0
            continue
        acc_r, acc_c = since_req, since_rec
        matched = False
        for k in range(len(stack) - 1, -1, -1):
            acc_r += stack[k][0]
            acc_c += stack[k][1]
            if acc_r == tr and acc_c == tc:
                del stack[k:]
                stack.append((tr, tc))
                since_req = since_rec = since_n = 0
                rollup += 1
                matched = True
                break
        if matched:
            continue
        bad += 1
        mismatches.append({"label": e["label"], "account": e["account"],
                           "since_req": since_req, "tot_req": tr})
        stack.append((tr, tc))
        since_req = since_rec = since_n = 0
    return {"leaf": leaf, "rollup": rollup, "bad": bad,
            "nodes": leaf + rollup + bad, "mismatches": mismatches}


def is_born_digital_house_pdf(pdf_path) -> bool:
    """True if this House report's TABLES are real text (parse here) rather than
    images (send to the vision pipeline).

    Must reject hybrid PDFs whose narrative front-matter is born-digital text but
    whose comparative tables are embedded images -- a text-density check alone
    false-positives on those. So: a large image on ANY page means image tables ->
    vision; otherwise require the comparative markers in the text. Returns on the
    first big image, so image/hybrid reports (the common case) are fast; only a
    truly all-text report scans to the end.
    """
    with pdfplumber.open(str(pdf_path)) as pdf:
        seen_marker = False
        for page in pdf.pages:
            for im in page.images:
                if im.get("width", 0) > 200 and im.get("height", 0) > 200:
                    return False
            if not seen_marker:
                text = page.extract_text() or ""
                if any(m in text for m in _MARKERS):
                    seen_marker = True
        return seen_marker


def _amount(raw: str, page_text: str, in_thousands: bool = True) -> tuple[DollarAmount | None, bool]:
    """Build a DollarAmount and report whether its digits appear on the page.

    The comparative tables are [in thousands] (value stored x1000 to actual
    dollars, the pipeline convention). The Title VII inline funding blocks instead
    print whole dollars, so pass in_thousands=False to leave them unscaled.
    """
    n = _to_int(raw)
    if n is None:
        return None, True
    bare = raw.replace(",", "").lstrip("+-")
    seen = bare in page_text.replace(",", "")
    return DollarAmount(value=n * 1000 if in_thousands else n, raw_text=raw,
                        in_thousands=in_thousands), seen


def extract_house_text(
    pdf_path,
    report_id: str,
    congress: int,
    fiscal_year: int | None = None,
    subcommittee: str | None = None,
) -> list[ComparativeStatementLine]:
    """Extract comparative line items from a born-digital House committee print.

    Columns map onto the schema as: Budget Request -> budget_estimate, Committee
    Recommended -> committee_recommendation, Change from Request ->
    delta_vs_estimate. (These prints carry no prior-year column.)
    """
    parsed = _parse(pdf_path)
    page_text = parsed["page_text"]
    out: list[ComparativeStatementLine] = []
    line_no = 0

    for acct in parsed["accounts"]:
        name = acct["account"]
        for r in acct["rows"]:
            line_no += 1
            est, est_ok = (_amount(r["req"], page_text[r["page"]]) if r["req"] else (None, True))
            rec, rec_ok = _amount(r["rec"], page_text[r["page"]])
            dlt, dlt_ok = (_amount(r["chg"], page_text[r["page"]]) if r["chg"] else (None, True))
            text = f"{r['code']} {r['item']}" if r["code"] else r["item"]
            out.append(ComparativeStatementLine(
                report_id=report_id, congress=congress, chamber=Chamber.HOUSE,
                fiscal_year=fiscal_year, subcommittee=subcommittee, stage=Stage.COMMITTEE,
                title_name=acct["title"], account=name, program=r["item"],
                hierarchy_depth=HierarchyLevel.PROGRAM.value, line_item_text=text,
                budget_estimate=est, committee_recommendation=rec, delta_vs_estimate=dlt,
                is_subtotal=False, in_thousands=True, line_number=line_no,
                verified=rec_ok and est_ok and dlt_ok,
                extraction_method=ExtractionMethod.RULE_BASED,
            ))
        # The account's grand total (last TOTAL in its span) as a subtotal line.
        if acct["totals"]:
            t = acct["totals"][-1]
            line_no += 1
            est, est_ok = _amount(t["req"], page_text[t["page"]])
            rec, rec_ok = _amount(t["rec"], page_text[t["page"]])
            dlt, dlt_ok = _amount(t["chg"], page_text[t["page"]])
            out.append(ComparativeStatementLine(
                report_id=report_id, congress=congress, chamber=Chamber.HOUSE,
                fiscal_year=fiscal_year, subcommittee=subcommittee, stage=Stage.COMMITTEE,
                title_name=acct["title"], account=name, program=None,
                hierarchy_depth=HierarchyLevel.ACCOUNT.value, line_item_text=t["label"],
                budget_estimate=est, committee_recommendation=rec, delta_vs_estimate=dlt,
                is_subtotal=True, in_thousands=True, line_number=line_no,
                verified=rec_ok and est_ok and dlt_ok,
                extraction_method=ExtractionMethod.RULE_BASED,
            ))

    # Inline funding blocks (single-appropriation accounts, e.g. Title VII).
    pt = parsed["page_text"]
    for blk in parsed["inline"]:
        line_no += 1
        est, est_ok = _amount(blk["req"], pt[blk["page"]], in_thousands=False)
        rec, rec_ok = _amount(blk["rec"], pt[blk["page"]], in_thousands=False)
        dlt, dlt_ok = (_amount(blk["chg"], pt[blk["page"]], in_thousands=False)
                       if blk["chg"] else (None, True))
        out.append(ComparativeStatementLine(
            report_id=report_id, congress=congress, chamber=Chamber.HOUSE,
            fiscal_year=fiscal_year, subcommittee=subcommittee, stage=Stage.COMMITTEE,
            title_name=blk["title"], account=blk["account"], program=blk["account"],
            hierarchy_depth=HierarchyLevel.ACCOUNT.value, line_item_text=blk["account"],
            budget_estimate=est, committee_recommendation=rec, delta_vs_estimate=dlt,
            is_subtotal=False, in_thousands=True, line_number=line_no,
            verified=rec_ok and est_ok and dlt_ok,
            extraction_method=ExtractionMethod.RULE_BASED,
        ))

    # RECAPITULATION: title-level totals (incl. Title VIII) + the bill grand total.
    for rc in parsed["recap"]:
        line_no += 1
        est, est_ok = (_amount(str(rc["req"]), pt[rc["page"]]) if rc["req"] is not None else (None, True))
        rec, rec_ok = _amount(str(rc["rec"]), pt[rc["page"]])
        out.append(ComparativeStatementLine(
            report_id=report_id, congress=congress, chamber=Chamber.HOUSE,
            fiscal_year=fiscal_year, subcommittee=subcommittee, stage=Stage.COMMITTEE,
            title_name=rc["name"], account=None, program=None,
            hierarchy_depth=HierarchyLevel.TITLE.value, line_item_text=rc["name"],
            budget_estimate=est, committee_recommendation=rec,
            is_subtotal=True, in_thousands=True, line_number=line_no,
            verified=rec_ok and est_ok, extraction_method=ExtractionMethod.RULE_BASED,
        ))
    return out
