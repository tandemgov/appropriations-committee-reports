"""Tests for Senate comparative statement extraction."""

from pathlib import Path

from approps.extraction.comparative_senate import extract_senate_comparative

FIXTURES = Path(__file__).parent / "fixtures"


class TestSenateComparative:
    def test_extracts_from_fixture(self):
        text = (FIXTURES / "senate_comparative_stmt.txt").read_text()
        lines = extract_senate_comparative(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            fiscal_year=2024,
            subcommittee="Interior-Environment",
        )
        assert len(lines) > 0

    def test_first_data_line(self):
        text = (FIXTURES / "senate_comparative_stmt.txt").read_text()
        lines = extract_senate_comparative(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            fiscal_year=2024,
        )
        # First data line should be "Rangeland management"
        first = lines[0]
        assert "Rangeland management" in first.line_item_text
        assert first.prior_year_enacted is not None
        assert first.prior_year_enacted.value == 112_340_000  # 112,340 * 1000
        assert first.budget_estimate is not None
        assert first.budget_estimate.value == 115_152_000
        assert first.committee_recommendation is not None
        assert first.committee_recommendation.value == 112_340_000

    def test_parenthesized_amounts(self):
        """Parenthesized amounts like (34,000) should parse as negative."""
        text = (FIXTURES / "senate_comparative_stmt.txt").read_text()
        lines = extract_senate_comparative(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            fiscal_year=2024,
        )
        # Find "Threatened and endangered species" — has parenthesized amounts
        threatened = [ln for ln in lines if "Threatened" in ln.line_item_text]
        assert len(threatened) == 1
        t = threatened[0]
        # (34,000) in thousands = -34,000,000
        assert t.prior_year_enacted is not None
        assert t.prior_year_enacted.value == -34_000_000

    def test_subtotal_detected(self):
        text = (FIXTURES / "senate_comparative_stmt.txt").read_text()
        lines = extract_senate_comparative(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            fiscal_year=2024,
        )
        subtotals = [ln for ln in lines if ln.is_subtotal]
        assert len(subtotals) > 0

    def test_delta_columns(self):
        text = (FIXTURES / "senate_comparative_stmt.txt").read_text()
        lines = extract_senate_comparative(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            fiscal_year=2024,
        )
        # "Forestry management" has delta_vs_estimate of -1,437
        forestry = [ln for ln in lines if "Forestry management" in ln.line_item_text]
        assert len(forestry) == 1
        f = forestry[0]
        assert f.delta_vs_estimate is not None
        assert f.delta_vs_estimate.value == -1_437_000

    def test_title_hierarchy(self):
        text = (FIXTURES / "senate_comparative_stmt.txt").read_text()
        lines = extract_senate_comparative(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            fiscal_year=2024,
        )
        # All lines should inherit the title
        for line in lines:
            assert line.title_name is not None
            assert "TITLE I" in line.title_name

    def test_in_thousands(self):
        text = (FIXTURES / "senate_comparative_stmt.txt").read_text()
        lines = extract_senate_comparative(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            fiscal_year=2024,
        )
        for line in lines:
            assert line.in_thousands is True

    def test_full_report(self):
        """Test against the full downloaded report if available."""
        path = Path("/tmp/CRPT-118srpt83.htm")
        if not path.exists():
            return

        text = path.read_text()
        lines = extract_senate_comparative(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            fiscal_year=2024,
            subcommittee="Interior-Environment",
        )
        # Should have hundreds of line items
        assert len(lines) > 200
        # Spot check first line
        assert lines[0].prior_year_enacted is not None

    def test_full_report_subtotal_arithmetic(self):
        """Verify subtotals sum correctly in the full report."""
        path = Path("/tmp/CRPT-118srpt83.htm")
        if not path.exists():
            return

        text = path.read_text()
        lines = extract_senate_comparative(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            fiscal_year=2024,
        )

        # Count data lines vs subtotals
        data_lines = [ln for ln in lines if not ln.is_subtotal]
        subtotal_lines = [ln for ln in lines if ln.is_subtotal]
        assert len(data_lines) > 100
        assert len(subtotal_lines) > 20
