"""Pydantic models for all data types in the approps pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Chamber(str, Enum):
    HOUSE = "house"
    SENATE = "senate"


class Stage(str, Enum):
    SUBCOMMITTEE = "subcommittee"
    COMMITTEE = "committee"
    CONFERENCE = "conference"
    ENACTED = "enacted"


class ExtractionMethod(str, Enum):
    RULE_BASED = "rule_based"
    LLM = "llm"


class VerificationMethod(str, Enum):
    """What was actually checked when a row was marked `verified`.

    These are three genuinely different claims, and conflating them cost this project a
    shipped sign defect on 9,629 amounts (docs/KNOWN_ISSUES.md #6). Both `string_match` and
    `delta_arithmetic` compare a row only to itself, so neither can catch a *misinterpretation*
    of the source as opposed to a *mistranscription* of it. Only a witness outside the row --
    `block`, or the standalone `approps reconcile` -- can.
    """

    DELTA_ARITHMETIC = "delta_arithmetic"
    """The row's own delta identities close. Invariant to a sign flip across its columns."""

    STRING_MATCH = "string_match"
    """The amount's raw text appears in the source HTML. Says nothing about how it was parsed."""

    VERBATIM_PAGE = "verbatim_page"
    """The amount appears verbatim on its source PDF page."""

    NONE = "none"
    """Not verified by any primary gate."""

    @classmethod
    def when(cls, passed: bool, method: VerificationMethod) -> VerificationMethod:
        """`method` if the gate passed, else NONE — so the two can never disagree."""
        return method if passed else cls.NONE


class HierarchyLevel(int, Enum):
    TITLE = 0
    DEPARTMENT = 1
    AGENCY = 2
    ACCOUNT = 3
    PROGRAM = 4
    SUBPROGRAM = 5


# --- Report Metadata ---


class ReportMetadata(BaseModel):
    """Metadata for a single appropriations committee report."""

    package_id: str = Field(description="GovInfo package ID, e.g. CRPT-118srpt83")
    congress: int
    chamber: Chamber
    report_number: int
    title: str
    subcommittee: str | None = None
    fiscal_year: int | None = None
    stage: Stage = Stage.COMMITTEE
    date_issued: str | None = None
    html_url: str
    pdf_url: str

    @property
    def raw_filename(self) -> str:
        return f"{self.package_id}.htm"

    @property
    def pdf_filename(self) -> str:
        return f"{self.package_id}.pdf"


# --- Extraction Results ---


class DollarAmount(BaseModel):
    """A parsed dollar amount with its raw text for verification."""

    value: int | None = Field(description="Amount in dollars (None if not applicable)")
    raw_text: str = Field(description="Original text as it appeared in the source")
    in_thousands: bool = Field(
        default=False, description="Whether the source used [In thousands of dollars]"
    )


class InlineFundingTable(BaseModel):
    """A 3-5 line narrative funding table extracted from the report body."""

    report_id: str
    congress: int
    chamber: Chamber
    fiscal_year: int | None = None
    subcommittee: str | None = None
    context_heading: str = Field(description="Nearest heading above the table")
    account_name: str | None = Field(default=None, description="Inferred account/program name")
    prior_year: DollarAmount | None = None
    budget_estimate: DollarAmount | None = None
    committee_recommendation: DollarAmount | None = None
    delta_vs_enacted: DollarAmount | None = None
    delta_vs_estimate: DollarAmount | None = None
    raw_text_block: str = Field(description="Verbatim text of the full block")
    line_number: int = Field(description="Line number in source where block starts")
    verified: bool = False
    extraction_method: ExtractionMethod = ExtractionMethod.RULE_BASED


class ComparativeStatementLine(BaseModel):
    """A single line item from a comparative statement table."""

    report_id: str
    congress: int
    chamber: Chamber
    fiscal_year: int | None = None
    subcommittee: str | None = None
    stage: Stage = Stage.COMMITTEE

    # Hierarchy
    title_name: str | None = None
    department: str | None = None
    agency: str | None = None
    account: str | None = None
    account_inferred: str | None = Field(
        default=None,
        description=(
            "Account grouping inferred from a reconciling subtotal block (House vision "
            "rows, where `account` is not extracted). Set only when the block's line "
            "amounts sum exactly to the subtotal's amount, so it is arithmetic-verified, "
            "never guessed. Additive: `account` is left untouched."
        ),
    )
    is_memo: bool = Field(
        default=False,
        description=(
            "True when this row is a memo line rather than an ordinary additive line item: a "
            "limitation, a transfer authority, an 'of which' breakout. Set by either signal — "
            "a parenthesized amount (the comparative-statement convention; see "
            "dollar_parser.is_paren_memo), or the Gemini non-add double-gate, which flags a "
            "sub-detail the flattened vision extraction wrongly summed into its subtotal and "
            "is arithmetic-verified (excluding exactly the flagged rows makes the block "
            "reconcile). Additive: the amount fields are left untouched.\n\n"
            "This says what the row IS, not whether it sums. A memo is non-add with respect to "
            "*some* total, but ~20% are added in by the total that immediately encloses them — "
            "a transfer that is real budget authority at the account level and double-counting "
            "at the title level. The printed total adjudicates; verification.reconcile does so "
            "per total and reports the verdict as `memo_mode`. Do not blanket-filter this "
            "column before summing: it will understate those account totals."
        ),
    )
    program: str | None = None
    hierarchy_depth: int = 0
    line_item_text: str = Field(description="Full text of the line item as it appears")

    # Amounts
    prior_year_enacted: DollarAmount | None = None
    budget_estimate: DollarAmount | None = None
    committee_recommendation: DollarAmount | None = None
    delta_vs_enacted: DollarAmount | None = None
    delta_vs_estimate: DollarAmount | None = None

    is_subtotal: bool = False
    in_thousands: bool = True  # Comparative statements are typically in thousands
    line_number: int = 0
    verified: bool = False
    verification_method: VerificationMethod = Field(
        default=VerificationMethod.NONE,
        description=(
            "Which gate set `verified`. Recorded by the producer, because it cannot be "
            "inferred downstream: the House track alone uses two (vision rows are checked by "
            "delta arithmetic, typeset-print rows by verbatim-on-page). Before this existed, "
            "every verified row was labelled `delta` regardless of what was actually checked."
        ),
    )
    extraction_method: ExtractionMethod = ExtractionMethod.RULE_BASED


# --- Verification ---


class VerificationTier(str, Enum):
    EXACT = "exact"
    NORMALIZED = "normalized"
    SPACELESS = "spaceless"
    FAILED = "failed"


class VerificationResult(BaseModel):
    """Result of verifying a single dollar amount against source text."""

    amount: DollarAmount
    tier: VerificationTier
    matched: bool
    source_context: str | None = Field(
        default=None, description="Surrounding text where match was found"
    )


class CrossCheckResult(BaseModel):
    """Result of an arithmetic cross-check (subtotal vs children)."""

    line_item_text: str
    expected_total: int
    computed_total: int
    difference: int
    passed: bool
    children: list[str] = Field(default_factory=list)


class AuditReport(BaseModel):
    """Verification summary for a report or the full dataset."""

    report_id: str | None = None
    total_records: int = 0
    verified_count: int = 0
    unverified_count: int = 0
    verification_rate: float = 0.0
    cross_check_failures: list[CrossCheckResult] = Field(default_factory=list)
    extraction_method_counts: dict[str, int] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


# --- Output (flat CSV-oriented) ---


class ComparativeStatementRow(BaseModel):
    """Flattened row for comparative_statements.csv output."""

    report_id: str
    congress: int
    chamber: str
    fiscal_year: int | None
    subcommittee: str | None
    stage: str
    title_name: str | None
    department: str | None
    agency: str | None
    account: str | None
    account_inferred: str | None
    is_memo: bool
    program: str | None
    line_item_text: str
    prior_year_enacted: int | None
    budget_estimate: int | None
    committee_recommendation: int | None
    delta_vs_enacted: int | None
    delta_vs_estimate: int | None
    is_subtotal: bool
    hierarchy_depth: int
    in_thousands: bool
    extraction_method: str
    verified: bool
    # What was actually checked to set `verified`, carried through from extraction. See
    # VerificationMethod: `delta_arithmetic`, `string_match`, `verbatim_page`, or `none`.
    verification_method: str = "none"
    # How the row's amount is supported (assigned by the output build). When `verified`, this
    # is the primary gate that passed — the same value as `verification_method`, surfaced here
    # so a single column answers "how do I know this number?". Otherwise it is a *second
    # witness* found elsewhere in the document: `block` (a member of a subtotal block whose
    # amounts reconcile exactly), `inline` (its amount + account restated in the report's
    # string-verified inline funding tables), or `none` (no in-document corroboration).
    #
    # This column used to report `delta` for every verified row, on all three tracks. It was a
    # misnomer on 52% of them, and it hid a real defect — see docs/KNOWN_ISSUES.md #6.
    verification_tier: str = "none"
    # Column layout: `standard` (the usual prior-year / request / recommendation / delta
    # shape) or `category_split` — a nonstandard table (e.g. Energy-Water Reclamation/Corps
    # "Water and Related Resources") whose funding is split across category columns that the
    # standard schema mis-labels. On `category_split` rows the recommendation total is
    # correct, but `prior_year_enacted` / `budget_estimate` / the deltas are mislabeled
    # category columns and must not be read as prior-year/request. See docs/KNOWN_ISSUES.md.
    column_layout: str = "standard"
    # Account crosswalk + normalization (added by the output enrichment step)
    account_key: str | None = None
    account_key_title: str | None = None
    account_match: str | None = None
    # Agency + bureau of the matched federal account (from the Tango crosswalk). House
    # committee rows carry no extracted agency, so this fills that hierarchy where the
    # account keyed. Populated only when account_match starts with `tango`.
    account_key_agency: str | None = None
    account_key_bureau: str | None = None
    designation: str | None = None
    real_factor_2024: float | None = None


class InlineFundingRow(BaseModel):
    """Flattened row for inline_funding_tables.csv output."""

    report_id: str
    congress: int
    chamber: str
    fiscal_year: int | None
    subcommittee: str | None
    context_heading: str
    account_name: str | None
    prior_year_amount: int | None
    budget_estimate: int | None
    committee_recommendation: int | None
    delta_vs_enacted: int | None
    delta_vs_estimate: int | None
    raw_text_block: str
    verified: bool
