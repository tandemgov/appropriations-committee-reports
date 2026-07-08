"""Generate verification audit reports."""

from __future__ import annotations

from datetime import datetime

from approps.output.schemas import (
    AuditReport,
    CrossCheckResult,
    VerificationResult,
)


def build_audit_report(
    report_id: str | None,
    verification_results: list[VerificationResult],
    cross_check_results: list[CrossCheckResult] | None = None,
) -> AuditReport:
    """Build an audit report from verification and cross-check results.

    Args:
        report_id: The report package ID (or None for aggregate)
        verification_results: Results from amount verification
        cross_check_results: Results from arithmetic cross-checks
    """
    total = len(verification_results)
    verified = sum(1 for r in verification_results if r.matched)
    unverified = total - verified
    rate = verified / total if total > 0 else 0.0

    # Count by tier
    tier_counts: dict[str, int] = {}
    for r in verification_results:
        tier_counts[r.tier.value] = tier_counts.get(r.tier.value, 0) + 1

    failures = [r for r in (cross_check_results or []) if not r.passed]

    return AuditReport(
        report_id=report_id,
        total_records=total,
        verified_count=verified,
        unverified_count=unverified,
        verification_rate=rate,
        cross_check_failures=failures,
        extraction_method_counts=tier_counts,
        timestamp=datetime.now(),
    )


def format_audit_report(report: AuditReport) -> str:
    """Format an audit report as a human-readable string."""
    lines = []
    header = f"Audit Report: {report.report_id or 'Aggregate'}"
    lines.append(header)
    lines.append("=" * len(header))
    lines.append(f"Total records:      {report.total_records}")
    lines.append(f"Verified:           {report.verified_count} ({report.verification_rate:.1%})")
    lines.append(f"Unverified:         {report.unverified_count}")
    lines.append("")

    if report.extraction_method_counts:
        lines.append("Verification tiers:")
        for tier, count in sorted(report.extraction_method_counts.items()):
            lines.append(f"  {tier}: {count}")
        lines.append("")

    if report.cross_check_failures:
        lines.append(f"Cross-check failures: {len(report.cross_check_failures)}")
        for failure in report.cross_check_failures[:10]:
            lines.append(f"  {failure.line_item_text}")
            lines.append(f"    expected={failure.expected_total}, computed={failure.computed_total}")
        if len(report.cross_check_failures) > 10:
            lines.append(f"  ... and {len(report.cross_check_failures) - 10} more")
    else:
        lines.append("Cross-check failures: 0")

    return "\n".join(lines)
