"""What `verification_tier` says a row's amount rests on.

When the row passed its track's primary gate, the tier names *that gate* — never a uniform
`delta`, which was true only of the House vision rows and false of the other 52%. Otherwise it
names a second witness found elsewhere in the document: block > inline > none.
"""

from __future__ import annotations

from approps.output.csv_writer import _build_inline_index, _verification_tier
from approps.output.schemas import (
    Chamber,
    ComparativeStatementLine,
    DollarAmount,
    InlineFundingTable,
    VerificationMethod,
)


def _amt(v):
    return DollarAmount(value=v, raw_text=str(v), in_thousands=True)


def _line(
    text,
    rec=None,
    verified=False,
    account_inferred=None,
    report_id="R1",
    method=VerificationMethod.NONE,
):
    return ComparativeStatementLine(
        report_id=report_id,
        congress=119,
        chamber=Chamber.HOUSE,
        line_item_text=text,
        committee_recommendation=_amt(rec) if rec is not None else None,
        verified=verified,
        verification_method=method,
        account_inferred=account_inferred,
    )


def _inline(text, rec, report_id="R1"):
    return InlineFundingTable(
        report_id=report_id,
        congress=119,
        chamber=Chamber.HOUSE,
        context_heading=text,
        account_name=text,
        committee_recommendation=_amt(rec),
        raw_text_block=f"{text} {rec}",
        line_number=100,
    )


def test_a_verified_row_reports_the_gate_that_actually_passed():
    """The regression this column exists to prevent: three different checks, three names."""
    for method in (
        VerificationMethod.DELTA_ARITHMETIC,
        VerificationMethod.STRING_MATCH,
        VerificationMethod.VERBATIM_PAGE,
    ):
        line = _line("Coast Guard Operations", rec=100, verified=True, method=method,
                     account_inferred="X")
        assert _verification_tier(line, {}) == method.value

    # A string-matched Senate row must never be labelled `delta`. It was, for the life of the
    # project, and the label hid a sign defect on 9,629 amounts.
    senate = _line("Rangeland management", rec=100, verified=True,
                   method=VerificationMethod.STRING_MATCH)
    assert _verification_tier(senate, {}) != "delta"


def test_the_method_and_the_verified_flag_cannot_disagree():
    assert VerificationMethod.when(True, VerificationMethod.STRING_MATCH) is (
        VerificationMethod.STRING_MATCH
    )
    assert VerificationMethod.when(False, VerificationMethod.STRING_MATCH) is VerificationMethod.NONE


def test_block_when_in_reconciling_subtotal_block():
    # Not delta-verified, but account_inferred is set only on reconciling blocks.
    line = _line("Coast Guard Operations", rec=100, account_inferred="Operations")
    assert _verification_tier(line, {}) == "block"


def test_inline_when_amount_and_account_restated_in_prose():
    line = _line("Coast Guard Operations and Support", rec=1234)
    index = _build_inline_index([_inline("Coast Guard Operations", 1234)])
    assert _verification_tier(line, index) == "inline"


def test_coincidental_amount_without_account_overlap_is_not_inline():
    # Same amount, unrelated account -> must NOT count as corroboration.
    line = _line("Coast Guard Operations", rec=1000)
    index = _build_inline_index([_inline("Bureau of Prisons", 1000)])
    assert _verification_tier(line, index) == "none"


def test_none_when_no_witness():
    line = _line("Some Program", rec=500)
    assert _verification_tier(line, {}) == "none"


def test_label_only_leaf_with_no_amount_is_not_block():
    # account_inferred is set on a label row inside a reconciling block, but it carries no
    # amount — there is nothing to corroborate, so it must stay `none`, not `block`.
    line = _line("Heading With No Number", rec=None, account_inferred="Operations")
    assert _verification_tier(line, {}) == "none"
