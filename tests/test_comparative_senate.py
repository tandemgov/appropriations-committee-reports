"""Tests for Senate comparative statement extraction."""

from pathlib import Path

from approps.extraction.comparative_senate import extract_senate_comparative
from approps.verification.reconcile import Status, reconcile_report

FIXTURES = Path(__file__).parent / "fixtures"

_AMOUNTS = (
    "prior_year_enacted",
    "budget_estimate",
    "committee_recommendation",
    "delta_vs_enacted",
    "delta_vs_estimate",
)


def _row(line) -> dict:
    """An extracted line in the neutral shape ``verification.reconcile`` consumes."""
    row: dict = {
        "line_item_text": line.line_item_text,
        "is_subtotal": line.is_subtotal,
        "is_memo": line.is_memo,
    }
    for name in _AMOUNTS:
        amount = getattr(line, name, None)
        row[name] = amount.value if amount is not None else None
    return row


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

    def test_parenthesized_amounts_are_positive_non_add_memos(self):
        """A parenthesized amount is a non-add memo, not a negative.

        The printed subtotal is the proof: 149,938 + 59,247 = 209,185, with the (35,000)
        excluded. Reading it as -35,000 would make the block sum to 174,185, and reading it
        as +35,000 *and summing it* would give 244,185. Only "positive, and not summed"
        reproduces the number the committee printed. See test_full_report_subtotal_arithmetic.
        """
        text = (FIXTURES / "senate_comparative_stmt.txt").read_text()
        lines = extract_senate_comparative(
            text=text,
            report_id="CRPT-118srpt83",
            congress=118,
            fiscal_year=2024,
        )
        threatened = [ln for ln in lines if "Threatened" in ln.line_item_text]
        assert len(threatened) == 1
        t = threatened[0]
        assert t.prior_year_enacted is not None
        assert t.prior_year_enacted.value == 34_000_000  # (34,000) in thousands
        assert t.committee_recommendation is not None
        assert t.committee_recommendation.value == 35_000_000
        assert t.is_memo is True

    def test_an_explicit_minus_stays_negative_and_a_paren_does_not(self):
        """Sign comes from the minus, never from the parentheses.

        `Wildlife habitat management` prints a `-12,045` delta -- a real decrease. The memo row
        below it prints `(+1,000)`, parenthesized and explicitly positive. Both must survive the
        Senate extractor with the sign the committee actually printed.
        """
        text = (FIXTURES / "senate_comparative_stmt.txt").read_text()
        lines = extract_senate_comparative(
            text=text, report_id="CRPT-118srpt83", congress=118, fiscal_year=2024
        )
        by_text = {ln.line_item_text: ln for ln in lines}

        wildlife = by_text["Wildlife habitat management"]
        assert wildlife.delta_vs_estimate is not None
        assert wildlife.delta_vs_estimate.value == -12_045_000
        assert not wildlife.is_memo

        threatened = by_text["Threatened and endangered species"]
        assert threatened.delta_vs_enacted is not None
        assert threatened.delta_vs_enacted.value == 1_000_000  # "(+1,000)"

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
        """The line items must reproduce every subtotal the committee printed.

        This replaces a test of the same name that read a report from /tmp, returned silently
        when it was absent -- which it always was -- and asserted only row counts even when it
        ran. It is the check that would have caught the parenthesis sign defect on day one.
        """
        text = (FIXTURES / "senate_comparative_stmt.txt").read_text()
        lines = extract_senate_comparative(
            text=text, report_id="CRPT-118srpt83", congress=118, fiscal_year=2024
        )

        result = reconcile_report("CRPT-118srpt83", [_row(ln) for ln in lines])
        assert result.checkable, "fixture must contain at least one checkable subtotal"

        failures = [
            f"{c.label!r} printed {c.primary.printed:,} but its {len(c.child_indices)} "
            f"line items sum to {c.primary.computed:,}"
            for c in result.checks
            if c.is_genuine_failure
        ]
        assert not failures, "subtotals do not reconcile:\n  " + "\n  ".join(failures)
        assert result.strict_pass_rate == 1.0

    def test_the_wildlife_block_reproduces_its_printed_subtotal(self):
        """The concrete arithmetic, spelled out: 149,938 + 59,247 = 209,185."""
        text = (FIXTURES / "senate_comparative_stmt.txt").read_text()
        lines = extract_senate_comparative(
            text=text, report_id="CRPT-118srpt83", congress=118, fiscal_year=2024
        )
        result = reconcile_report("CRPT-118srpt83", [_row(ln) for ln in lines])

        by_label = [c for c in result.checks if c.primary.printed == 209_185_000]
        assert len(by_label) == 1
        check = by_label[0]
        assert check.status is Status.OK
        assert check.primary.computed == 209_185_000
        # The memo row sits between the two children and is not one of them.
        assert len(check.child_indices) == 2
