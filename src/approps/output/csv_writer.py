"""Generate structured CSV output from extracted data."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from approps.config import OUTPUT_DIR
from approps.normalization.account_names import clean_account_label
from approps.normalization.crosswalk import match_account
from approps.normalization.inflation import load_deflators
from approps.normalization.tango_crosswalk import TangoCrosswalk
from approps.output.schemas import (
    ComparativeStatementLine,
    ComparativeStatementRow,
    InlineFundingRow,
    InlineFundingTable,
)

logger = logging.getLogger(__name__)

_REAL_BASE_YEAR = 2024

# Account-name tokens used to gate inline corroboration: an inline record must share a
# meaningful word with the comparative row, not merely a coincidental amount. Generic
# appropriations vocabulary is dropped so it can't be the sole basis for a match.
_TIER_STOP = frozenset(
    "the of and for to a an in on fund funds account program office national salaries "
    "expenses department bureau administration".split()
)


def _acct_tokens(*texts: str | None) -> set[str]:
    out: set[str] = set()
    for t in texts:
        for w in re.findall(r"[a-z]+", (t or "").lower()):
            if len(w) > 3 and w not in _TIER_STOP:
                out.add(w)
    return out


def _build_inline_index(tables: list) -> dict[str, list[tuple[set[int], set[str]]]]:
    """report_id -> [(amounts, account-tokens)] for the string-verified inline funding
    tables, so a comparative row can be corroborated by the report's own prose."""
    index: dict[str, list[tuple[set[int], set[str]]]] = {}
    for t in tables or []:
        amts = {
            a.value
            for a in (t.prior_year, t.budget_estimate, t.committee_recommendation)
            if a is not None and a.value is not None
        }
        if not amts:
            continue
        toks = _acct_tokens(t.account_name, t.context_heading)
        index.setdefault(t.report_id, []).append((amts, toks))
    return index


def _verification_tier(
    line: ComparativeStatementLine, inline_index: dict[str, list[tuple[set[int], set[str]]]]
) -> str:
    """How this row's amount is independently supported, strongest first: delta > block >
    inline > none. See ComparativeStatementRow.verification_tier. block/inline require the
    row to actually carry an amount — a label-only leaf inside a reconciling block has no
    amount to corroborate and stays `none`."""
    if line.verified:
        return "delta"
    amts = {
        a.value
        for a in (line.committee_recommendation, line.budget_estimate, line.prior_year_enacted)
        if a is not None and a.value is not None
    }
    has_amount = bool(amts) or any(
        a is not None and a.value is not None
        for a in (line.delta_vs_enacted, line.delta_vs_estimate)
    )
    if not has_amount:
        return "none"
    if (line.account_inferred or "").strip():
        return "block"
    if amts:
        toks = _acct_tokens(line.line_item_text, line.account_inferred)
        for inl_amts, inl_toks in inline_index.get(line.report_id, []):
            if (amts & inl_amts) and (toks & inl_toks):
                return "inline"
    return "none"


def _enrich_accounts(lines: list[ComparativeStatementLine], rows: list[dict]) -> None:
    """Populate account_key/designation/real_factor on output rows (in place).

    The authoritative match is computed once per distinct (subcommittee, normalized account)
    and reused, so this stays fast over tens of thousands of rows. Only exact/agency-scoped
    matches are trusted into account_key; fuzzy suggestions are recorded in account_match
    but gated out of the key (see normalization.crosswalk)."""
    deflators = load_deflators()
    match_cache: dict[tuple, object] = {}

    for line, row in zip(lines, rows, strict=True):
        row["designation"] = clean_account_label(
            (line.account or line.account_inferred or line.line_item_text or "").strip()
        ).designation

        if not line.is_subtotal:
            # Try match candidates in priority order. account_inferred (arithmetic-verified
            # House grouping) is additive: it can supply a match where `account` is null, but
            # falling through to line_item_text on a miss means it never suppresses a match
            # the raw text would have found.
            context = " ".join(
                filter(None, [line.subcommittee, line.department, line.agency,
                              line.title_name, line.program])
            )
            best = None
            for candidate in (line.account, line.account_inferred, line.line_item_text):
                cleaned = clean_account_label((candidate or "").strip())
                if cleaned.is_fragment or not cleaned.normalized:
                    continue
                key = (line.subcommittee or "", cleaned.normalized)
                if key not in match_cache:
                    match_cache[key] = match_account(cleaned.normalized, context)
                m = match_cache[key]
                if best is None:
                    best = m  # first valid attempt — provenance if nothing trusts
                if m.account_key and not m.needs_review:
                    best = m
                    break
            if best is not None:
                row["account_match"] = best.method
                if best.account_key and not best.needs_review:
                    row["account_key"] = best.account_key
                    row["account_key_title"] = best.account_title

        fy = line.fiscal_year
        if fy in deflators and _REAL_BASE_YEAR in deflators:
            row["real_factor_2024"] = round(deflators[_REAL_BASE_YEAR] / deflators[fy], 4)


def _column_layout(line: ComparativeStatementLine) -> str:
    """`category_split` when the row is a nonstandard category-split table crammed into the
    standard schema, else `standard`. Signature: the two columns the parser labelled prior
    and budget-estimate sum to the recommendation and the deltas merely echo them — a real
    comparative row essentially never satisfies all of these. See docs/KNOWN_ISSUES.md."""
    # A bare procurement line-item number ("29", "30") as the label means the program name
    # was lost — Defense procurement quantity-column tables the five-column parser can't map.
    if re.fullmatch(r"\d{1,3}\.?", (line.line_item_text or "").strip()):
        return "procurement_qty"

    def v(a):
        return a.value if a is not None else None

    pe, be, cr = v(line.prior_year_enacted), v(line.budget_estimate), v(line.committee_recommendation)
    de, dt = v(line.delta_vs_enacted), v(line.delta_vs_estimate)
    if None not in (pe, be, cr, de, dt) and pe and be and pe + be == cr and de == pe and dt == be:
        return "category_split"
    return "standard"


def _is_paren_nonadd(line: ComparativeStatementLine) -> bool:
    """Whether the row's recommendation is a parenthesized non-add memo — a limitation,
    transfer authority, GWOT/"of which" breakout — which by appropriations convention is
    NOT summed into the account total. Parens with an explicit minus (e.g. `(-2,491)`) are
    real negatives (rescissions), so require a positive value with no inner sign."""
    a = line.committee_recommendation
    if a is None or a.value is None or a.value <= 0:
        return False
    raw = (a.raw_text or "").strip()
    return raw.startswith("(") and "-" not in raw


def _line_has_amount(line: ComparativeStatementLine) -> bool:
    return any(
        a is not None and a.value is not None
        for a in (
            line.prior_year_enacted,
            line.budget_estimate,
            line.committee_recommendation,
            line.delta_vs_enacted,
            line.delta_vs_estimate,
        )
    )


def _enrich_tango(lines: list[ComparativeStatementLine], rows: list[dict]) -> None:
    """Assign a federal account (+ agency/bureau) to value-bearing rows the crosswalk left
    unkeyed, by matching their label against Tango's federal-account reference. Two passes:
    take unambiguous matches first, learn each subcommittee's agency set from them, then use
    that scope to resolve the ambiguous ones. Additive — never overwrites an existing key."""
    tc = TangoCrosswalk()
    if not tc._accounts:  # reference not present — skip silently
        return

    def label(line: ComparativeStatementLine) -> str:
        return (line.account_inferred or line.line_item_text or "").strip()

    def targets():
        for line, row in zip(lines, rows, strict=True):
            if line.is_subtotal or row.get("account_key") or not _line_has_amount(line):
                continue
            yield line, row

    def assign(row: dict, m, method: str) -> None:
        row["account_key"] = m.federal_account_symbol
        row["account_key_title"] = m.account_title
        row["account_match"] = method
        row["account_key_agency"] = m.agency
        row["account_key_bureau"] = m.bureau

    # Pass 1 — unambiguous matches; learn subcommittee -> agencies from them.
    subc_agencies: dict[str, set[str]] = {}
    for line, row in targets():
        m = tc.match(label(line))
        if m:
            assign(row, m, "tango")
            subc_agencies.setdefault(line.subcommittee or "", set()).add(m.agency)

    # Pass 2 — resolve the rest within their subcommittee's observed agency scope.
    for line, row in targets():
        scope = subc_agencies.get(line.subcommittee or "")
        m = tc.match(label(line), allowed_agencies=scope) if scope else None
        if m:
            assign(row, m, "tango_scoped")


def _comparative_line_to_row(line: ComparativeStatementLine) -> ComparativeStatementRow:
    """Flatten a ComparativeStatementLine to a CSV-ready row."""
    return ComparativeStatementRow(
        report_id=line.report_id,
        congress=line.congress,
        chamber=line.chamber.value,
        fiscal_year=line.fiscal_year,
        subcommittee=line.subcommittee,
        stage=line.stage.value,
        title_name=line.title_name,
        department=line.department,
        agency=line.agency,
        account=line.account,
        account_inferred=line.account_inferred,
        non_add_inferred=line.non_add_inferred or _is_paren_nonadd(line),
        program=line.program,
        line_item_text=line.line_item_text,
        prior_year_enacted=line.prior_year_enacted.value if line.prior_year_enacted else None,
        budget_estimate=line.budget_estimate.value if line.budget_estimate else None,
        committee_recommendation=(
            line.committee_recommendation.value if line.committee_recommendation else None
        ),
        delta_vs_enacted=line.delta_vs_enacted.value if line.delta_vs_enacted else None,
        delta_vs_estimate=line.delta_vs_estimate.value if line.delta_vs_estimate else None,
        is_subtotal=line.is_subtotal,
        hierarchy_depth=line.hierarchy_depth,
        in_thousands=line.in_thousands,
        extraction_method=line.extraction_method.value,
        verified=line.verified,
    )


def _inline_table_to_row(table: InlineFundingTable) -> InlineFundingRow:
    """Flatten an InlineFundingTable to a CSV-ready row."""
    return InlineFundingRow(
        report_id=table.report_id,
        congress=table.congress,
        chamber=table.chamber.value,
        fiscal_year=table.fiscal_year,
        subcommittee=table.subcommittee,
        context_heading=table.context_heading,
        account_name=table.account_name,
        prior_year_amount=table.prior_year.value if table.prior_year else None,
        budget_estimate=table.budget_estimate.value if table.budget_estimate else None,
        committee_recommendation=(
            table.committee_recommendation.value if table.committee_recommendation else None
        ),
        delta_vs_enacted=table.delta_vs_enacted.value if table.delta_vs_enacted else None,
        delta_vs_estimate=table.delta_vs_estimate.value if table.delta_vs_estimate else None,
        raw_text_block=table.raw_text_block,
        verified=table.verified,
    )


def write_comparative_csv(
    lines: list[ComparativeStatementLine],
    output_path: Path | None = None,
    inline_tables: list | None = None,
) -> Path:
    """Write comparative statement data to CSV.

    Pass the report's inline funding tables to enable the `inline` corroboration tier
    (a row whose amount + account is restated in the string-verified prose)."""
    output_path = output_path or (OUTPUT_DIR / "comparative_statements.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [_comparative_line_to_row(line).model_dump() for line in lines]
    _enrich_accounts(lines, rows)
    _enrich_tango(lines, rows)
    inline_index = _build_inline_index(inline_tables or [])
    for line, row in zip(lines, rows, strict=True):
        row["verification_tier"] = _verification_tier(line, inline_index)
        row["column_layout"] = _column_layout(line)
    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False)
    logger.info(f"Wrote {len(rows)} rows to {output_path}")
    return output_path


def write_inline_csv(
    tables: list[InlineFundingTable],
    output_path: Path | None = None,
) -> Path:
    """Write inline funding table data to CSV."""
    output_path = output_path or (OUTPUT_DIR / "inline_funding_tables.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [_inline_table_to_row(t).model_dump() for t in tables]
    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False)
    logger.info(f"Wrote {len(rows)} rows to {output_path}")
    return output_path
