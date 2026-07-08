"""Enacted-stage extractor: Joint Explanatory Statement allocation tables.

The final enacted program-level appropriations live in the House Rules Committee Prints
(GovInfo CPRT collection) — the "Consolidated Appropriations Act, {year}" two-book pairs
whose Joint Explanatory Statement carries the allocation tables. These are born-digital,
text-extractable PDFs (pdfplumber), so this is a dot-leader / column regex parse, NOT a
vision problem.

Two table shapes are handled:

1. Single-column "Program ......... $amount" dot-leader tables (the dominant shape). The
   single amount IS the final enacted level (-> committee_recommendation).

2. Two-column "Budget Request | Final Bill" adjustment tables (mainly Defense). ALL-CAPS
   rows carry the absolute account levels: Final Bill -> committee_recommendation (enacted),
   Budget Request -> budget_estimate. The lowercase "Program increase/decrease—..." rows
   are DELTAS and are intentionally skipped so they do not pollute absolute amounts.

Known limitation: divisions that present their detail in prose rather than tables (e.g.
Energy-Water, Homeland Security) are under-captured; pulling dollar figures out of
narrative sentences is deliberately avoided to preserve the verified-amount guarantee.

Each emitted line is self-verified: its enacted amount is confirmed to appear verbatim on
its source page, so enacted JSON ships with verified=true (there is no companion HTML for
the HTML-based `verify` command to use).
"""

from __future__ import annotations

import re

import pdfplumber

from approps.output.schemas import (
    Chamber,
    ComparativeStatementLine,
    DollarAmount,
    ExtractionMethod,
    Stage,
    VerificationMethod,
)

# Single-column dot-leader row: label, dot leaders, optional $, comma-grouped amount.
_DOT_LINE = re.compile(
    r"^(?P<label>[A-Za-z0-9][\w\s,&()'./\-]+?)\s*\.{2,}\s*(?P<amt>\$?\d{1,3}(?:,\d{3})+)\s*$"
)
# Subtotal/total line without dot leaders: "Subtotal, Animal Health 395,570".
_TOTAL_LINE = re.compile(
    r"^(?P<label>(?:Sub)?total\b[^.]*?)\s+(?P<amt>\$?\d{1,3}(?:,\d{3})+)\s*$", re.I
)
# A table's unit header. These prints spell it fourteen different ways —  "[In thousands of
# dollars]", "(Dollars in thousands)", "[$ in thousands]", "(Amounts in thousands)",
# "[Budget authority in thousands of dollars]", … — so match on a bracketed span containing
# "thousand" rather than one fixed phrase. Anchoring on the opening bracket (and forbidding
# nested brackets inside) keeps an enumerated legend like "(6) Budget year dollars in
# thousands" and a bare "thousands);" from being mistaken for a header.
_THOUSANDS = re.compile(r"[\[(][^\[\]()]{0,40}thousand[^\[\]()]{0,24}[\])]", re.I)

# The narrower phrasing this module was originally written against. It governs only the
# *table-shape* context (two-column detection and account headings), deliberately NOT the units
# decision. Broadening the shape detection is a separate change with its own hazards: the
# "(Dollars in thousands)" NRC tables announce a "Final Bill" column but carry a single amount,
# and routing them down the two-column path drops their mixed-case rows. Kept narrow so this
# module's units fix provably changes units and nothing else. See docs/KNOWN_ISSUES.md #5.
_THOUSANDS_TABLE_SHAPE = re.compile(r"\(?\[?in thousands of dollars\]?\)?", re.I)
_DIVISION = re.compile(r"^DIVISION\s+([A-Z])\b[\s—–-]*(.*)$")
_NUMTOK = re.compile(r"\$?\d{1,3}(?:,\d{3})+")
# An ALL-CAPS account/agency heading (the JES account names) used as table context.
_CAPS_HEADING = re.compile(r"^[A-Z][A-Z0-9\s,&()'./\-]{3,58}$")


def _to_dollars(raw: str, in_thousands: bool) -> int | None:
    digits = raw.replace("$", "").replace(",", "").strip()
    if not digits.isdigit():
        return None
    return int(digits) * (1000 if in_thousands else 1)


def _is_thousands_marker(s: str) -> bool:
    """True for a table's column-units header, e.g. `[Budget authority in thousands of dollars]`.

    These prints repeat the header on every page of a table, so a page carrying one is a
    thousands page and a page without one is a whole-dollar page. The length bound keeps a
    narrative sentence that happens to say "in thousands of dollars" from being mistaken for
    a header.
    """
    return bool(_THOUSANDS.search(s)) and len(s) < 45


def _norm_nums(s: str) -> str:
    """Repair OCR-split numbers: '134 ,529' -> '134,529'."""
    s = re.sub(r"(\d)\s+,", r"\1,", s)
    return re.sub(r",\s+(\d)", r",\1", s)


def _caps_fraction(label: str) -> float:
    letters = [c for c in label if c.isalpha()]
    return sum(c.isupper() for c in letters) / len(letters) if letters else 0.0


def _amount(raw: str | None, in_thousands: bool, page_text: str) -> tuple[DollarAmount | None, bool]:
    """Build a DollarAmount and report whether its raw text appears on the source page."""
    if raw is None:
        return None, True
    bare = raw.replace("$", "")
    seen = bare in page_text or bare.replace(",", "") in page_text.replace(",", "")
    return DollarAmount(value=_to_dollars(raw, in_thousands), raw_text=raw, in_thousands=in_thousands), seen


def extract_enacted_pages(
    page_texts,
    report_id: str,
    congress: int,
    fiscal_year: int | None,
) -> list[ComparativeStatementLine]:
    """Parse enacted line items from an iterable of page texts.

    Split out from `extract_enacted_pdf` so the parse — in particular the per-page
    thousands-vs-dollars decision — is testable without a PDF fixture.
    """
    lines_out: list[ComparativeStatementLine] = []
    division = division_title = None
    line_no = 0

    for page_text in page_texts:
        rows = page_text.split("\n")
        headings: list[str] = []
        account_ctx = ""
        # Default to whole dollars. These prints publish most tables in dollars and mark
        # the thousands ones with a repeated column header, so scaling requires positive
        # evidence: a page with no header is dollars. Defaulting the other way multiplied
        # every unmarked amount by 1,000, and no arithmetic check could see it, because the
        # delta identity is scale-invariant. See docs/KNOWN_ISSUES.md #4.
        in_thousands = False
        two_col = False

        for i, ln in enumerate(rows):
            s = ln.strip()
            if not s:
                headings = []
                continue

            m = _DIVISION.match(s)
            if m:
                division, division_title = m.group(1), (m.group(2).strip()[:80] or division_title)
                two_col = False
                continue

            if _is_thousands_marker(s):
                # Units: any bracketed "thousands" header, however spelled.
                in_thousands = True
                # Table shape: only the phrasing the two-column heuristic was tuned against.
                if _THOUSANDS_TABLE_SHAPE.search(s):
                    ahead = " ".join(rows[i + 1 : i + 4]).lower()
                    two_col = "final bill" in ahead
                    account_ctx = " / ".join(headings[-3:])
                continue

            label = enacted_raw = request_raw = None
            is_subtotal = False

            if two_col:
                nums = _NUMTOK.findall(_norm_nums(s))
                cand = _norm_nums(re.split(r"\.{2,}|\s\s+|\d", s, maxsplit=1)[0]).strip(" .")
                if nums and cand and len(cand) > 3 and _caps_fraction(cand) >= 0.7:
                    label = re.sub(r"\s+", " ", cand)
                    request_raw = nums[0] if len(nums) >= 2 else None
                    enacted_raw = nums[-1]
                    is_subtotal = bool(re.match(r"(?i)^(sub)?total\b", label))
            else:
                row = _DOT_LINE.match(s) or _TOTAL_LINE.match(s)
                if row:
                    label = re.sub(r"\s+", " ", row.group("label")).strip(" .")
                    enacted_raw = row.group("amt")
                    is_subtotal = bool(re.match(r"(?i)^(sub)?total\b", label))

            if label and enacted_raw:
                rec, rec_ok = _amount(enacted_raw, in_thousands, page_text)
                est, est_ok = _amount(request_raw, in_thousands, page_text)
                line_no += 1
                title = f"DIVISION {division}—{division_title}" if division else division_title
                lines_out.append(
                    ComparativeStatementLine(
                        report_id=report_id,
                        congress=congress,
                        chamber=Chamber.HOUSE,  # House Rules Committee print
                        fiscal_year=fiscal_year,
                        subcommittee=None,
                        stage=Stage.ENACTED,
                        title_name=title,
                        account=account_ctx or None,
                        program=label,
                        line_item_text=label,
                        budget_estimate=est,
                        committee_recommendation=rec,
                        is_subtotal=is_subtotal,
                        in_thousands=in_thousands,
                        line_number=line_no,
                        verified=rec_ok and est_ok,
                        verification_method=VerificationMethod.when(
                            rec_ok and est_ok, VerificationMethod.VERBATIM_PAGE
                        ),
                        extraction_method=ExtractionMethod.RULE_BASED,
                    )
                )
                continue

            if _CAPS_HEADING.match(s) and _caps_fraction(s) >= 0.85:
                headings.append(s)

    return lines_out


def extract_enacted_pdf(
    pdf_path,
    report_id: str,
    congress: int,
    fiscal_year: int | None,
) -> list[ComparativeStatementLine]:
    """Parse enacted line items from a CPRT explanatory-statement PDF."""

    def _page_texts():
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                yield page.extract_text() or ""
                page.flush_cache()  # release per-page objects; these PDFs are 1400-1700 pages

    return extract_enacted_pages(_page_texts(), report_id, congress, fiscal_year)
