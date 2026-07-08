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
    non_add_inferred: bool = Field(
        default=False,
        description=(
            "True when the Gemini non-add double-gate identified this row as a non-add "
            "sub-detail (a transfer, limitation, or 'of which' breakout) whose amount was "
            "wrongly summed into its subtotal by the flattened vision extraction. Set only "
            "when excluding exactly the flagged rows makes the block reconcile, so it is "
            "arithmetic-verified. Such a row's amount should not be added into its account "
            "total. Additive: the amount fields are left untouched."
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
    non_add_inferred: bool
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
    # Corroboration tier (assigned by the output build): how the row's amount is
    # independently supported — `delta` (its own delta-column arithmetic closes, i.e.
    # verified=True), `block` (a member of a subtotal block whose amounts reconcile
    # exactly), `inline` (its amount + account restated in the report's string-verified
    # inline funding tables), or `none` (no in-document second witness).
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
