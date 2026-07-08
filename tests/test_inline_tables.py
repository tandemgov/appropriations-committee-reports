"""Tests for inline narrative table extraction."""

from pathlib import Path

from approps.extraction.inline_tables import extract_inline_tables

FIXTURES = Path(__file__).parent / "fixtures"


class TestSenateInlineTables:
    def _get_senate_text(self) -> str:
        """Load the full Senate Interior report for testing."""
        path = Path("/tmp/CRPT-118srpt83.htm")
        if path.exists():
            return path.read_text()
        # Fall back to fixture
        return (FIXTURES / "senate_inline_table.txt").read_text()

    def test_extracts_tables_from_fixture(self):
        text = (FIXTURES / "senate_inline_table.txt").read_text()
        tables = extract_inline_tables(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            chamber="senate",
            fiscal_year=2024,
            subcommittee="Interior-Environment",
        )
        assert len(tables) >= 3

    def test_first_table_values(self):
        text = (FIXTURES / "senate_inline_table.txt").read_text()
        tables = extract_inline_tables(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            chamber="senate",
        )
        t = tables[0]
        assert t.prior_year is not None
        assert t.prior_year.value == 1_368_969_000
        assert t.budget_estimate is not None
        assert t.budget_estimate.value == 1_497_069_000
        assert t.committee_recommendation is not None
        assert t.committee_recommendation.value == 1_371_619_000

    def test_heading_detected(self):
        text = (FIXTURES / "senate_inline_table.txt").read_text()
        tables = extract_inline_tables(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            chamber="senate",
        )
        assert tables[0].context_heading == "MANAGEMENT OF LANDS AND RESOURCES"

    def test_full_report_extraction(self):
        """Test against the full downloaded report if available."""
        path = Path("/tmp/CRPT-118srpt83.htm")
        if not path.exists():
            return  # Skip if report not downloaded

        text = path.read_text()
        tables = extract_inline_tables(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            chamber="senate",
            fiscal_year=2024,
            subcommittee="Interior-Environment",
        )
        # The full report should have many funding tables
        assert len(tables) > 50
        # Spot-check first table
        assert tables[0].prior_year is not None


class TestHouseInlineTables:
    def test_extracts_tables_from_fixture(self):
        text = (FIXTURES / "house_inline_table.txt").read_text()
        tables = extract_inline_tables(
            text=text,
            report_id="CRPT-118hrpt553",
            congress=118,
            chamber="house",
            fiscal_year=2025,
            subcommittee="Homeland-Security",
        )
        assert len(tables) >= 3

    def test_first_table_values(self):
        text = (FIXTURES / "house_inline_table.txt").read_text()
        tables = extract_inline_tables(
            text=text,
            report_id="CRPT-118hrpt553",
            congress=118,
            chamber="house",
        )
        t = tables[0]
        assert t.prior_year is not None
        assert t.prior_year.value == 404_695_000
        assert t.budget_estimate is not None
        assert t.budget_estimate.value == 358_466_000
        assert t.committee_recommendation is not None
        assert t.committee_recommendation.value == 281_358_000

    def test_delta_extraction(self):
        text = (FIXTURES / "house_inline_table.txt").read_text()
        tables = extract_inline_tables(
            text=text,
            report_id="CRPT-118hrpt553",
            congress=118,
            chamber="house",
        )
        t = tables[0]
        assert t.delta_vs_enacted is not None
        assert t.delta_vs_enacted.value == -123_337_000
        assert t.delta_vs_estimate is not None
        assert t.delta_vs_estimate.value == -77_108_000

    def test_dash_amounts(self):
        """Test that '- - -' is handled as None."""
        text = (FIXTURES / "house_inline_table.txt").read_text()
        tables = extract_inline_tables(
            text=text,
            report_id="CRPT-118hrpt553",
            congress=118,
            chamber="house",
        )
        # Third table has "- - -" values
        t = tables[2]
        assert t.budget_estimate is not None
        assert t.budget_estimate.value is None  # "- - -"
        assert t.committee_recommendation is not None
        assert t.committee_recommendation.value is None  # "- - -"

    def test_full_report_extraction(self):
        """Test against the full downloaded report if available."""
        path = Path("/tmp/CRPT-118hrpt553.htm")
        if not path.exists():
            return

        text = path.read_text()
        tables = extract_inline_tables(
            text=text,
            report_id="CRPT-118hrpt553",
            congress=118,
            chamber="house",
            fiscal_year=2025,
            subcommittee="Homeland-Security",
        )
        assert len(tables) > 20


class TestForwardProgress:
    """A block-start line that is not itself a funding line must not loop forever.

    Regression for CRPT-119hrpt622 (MilCon-VA FY2027): the line
    "Appropriation, fiscal year 2026 cost of direct loan   $11,710,000" matches the
    House block-start pattern but not the funding-line pattern (spaces, no dot leaders),
    which left the scan index pinned and hung extract_inline_tables indefinitely.
    """

    def test_bare_appropriation_start_line_terminates(self):
        text = "\n".join([
            "Some heading",
            "Appropriation, fiscal year 2026 cost of direct loan          $11,710,000",
            "More narrative text that is not a funding line",
            "Appropriation, fiscal year 2025 ...................... 10,000",
            "Committee recommendation .......................... 12,000",
        ])
        # Must return promptly (no infinite loop); the assertion is that it returns at all.
        tables = extract_inline_tables(
            text=text, report_id="X", congress=119, chamber="house",
            fiscal_year=2027, subcommittee="MilCon-VA",
        )
        assert isinstance(tables, list)


class TestBornDigitalSenateProse:
    """Senate reports published only as a born-digital PDF (e.g. CRPT-119srpt55,
    Labor-HHS FY2026) carry their figures in per-account prose mini-tables with
    whole-dollar amounts and a decorative drop-cap on section headers that the PDF
    text layer drops. Same parser as HTML, exercised on the PDF-text shape.
    """

    def test_whole_dollar_prose_block(self):
        text = "\n".join([
            "COMMUNITY SERVICE EMPLOYMENT FOR OLDER AMERICANS",
            "Appropriations, 2025 ............................................. $405,000,000",
            "Committee recommendation ....................................... 395,000,000",
            "The Committee provides $395,000,000 for CSEOA.",
        ])
        tables = extract_inline_tables(
            text=text, report_id="CRPT-119srpt55", congress=119, chamber="senate",
            fiscal_year=2026, subcommittee="Labor-HHS-Education",
        )
        assert len(tables) == 1
        t = tables[0]
        assert t.context_heading == "COMMUNITY SERVICE EMPLOYMENT FOR OLDER AMERICANS"
        # Whole dollars, not thousands: the value is stored unscaled.
        assert t.prior_year.value == 405_000_000
        assert t.prior_year.in_thousands is False
        assert t.committee_recommendation.value == 395_000_000

    def test_dropcap_heading_repaired(self):
        # The PDF text layer omits the drop-cap first letter, leaving "ENSION ...".
        text = "\n".join([
            "ENSION BENEFIT GUARANTY CORPORATION",
            "Appropriations, 2025 ............................................. $492,905,000",
            "Committee recommendation ....................................... 492,905,000",
        ])
        tables = extract_inline_tables(
            text=text, report_id="CRPT-119srpt55", congress=119, chamber="senate",
            fiscal_year=2026, subcommittee="Labor-HHS-Education",
        )
        assert tables[0].context_heading == "PENSION BENEFIT GUARANTY CORPORATION"
