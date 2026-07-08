"""Arithmetic-gated account inference for House vision rows."""

from __future__ import annotations

from approps.normalization.account_inference import infer_block_accounts


def _line(text, rec=None, is_subtotal=False, account=None):
    d = {"line_item_text": text, "is_subtotal": is_subtotal}
    if rec is not None:
        d["committee_recommendation"] = {"value": rec, "in_thousands": True}
    if account is not None:
        d["account"] = account
    return d


def test_labels_a_reconciling_block():
    lines = [
        _line("Program A", 100),
        _line("Program B", 200),
        _line("Subtotal, Operations and Support", 300, is_subtotal=True),
    ]
    n = infer_block_accounts(lines)
    assert n == 2
    assert lines[0]["account_inferred"] == "Operations and Support"
    assert lines[1]["account_inferred"] == "Operations and Support"
    # the subtotal row itself is not labeled
    assert "account_inferred" not in lines[2]


def test_skips_a_nonreconciling_block():
    lines = [
        _line("Program A", 100),
        _line("Program B", 250),  # sums to 350, not 300
        _line("Subtotal, Something", 300, is_subtotal=True),
    ]
    assert infer_block_accounts(lines) == 0
    assert all("account_inferred" not in ln for ln in lines)


def test_memo_only_rows_excluded_from_sum_but_labeled():
    # A parenthetical-only memo line carries a non-add amount; it must not break the sum.
    lines = [
        _line("Program A", 100),
        _line("(transfer out)", 999),  # memo, excluded from the addends
        _line("Program B", 200),
        _line("Total, Federal Assistance", 300, is_subtotal=True),
    ]
    n = infer_block_accounts(lines)
    assert n == 3  # both programs and the memo row get the label
    assert lines[1]["account_inferred"] == "Federal Assistance"


def test_does_not_overwrite_extracted_account():
    lines = [
        _line("Program A", 100, account="EXISTING ACCOUNT"),
        _line("Program B", 200),
        _line("Subtotal, X", 300, is_subtotal=True),
    ]
    n = infer_block_accounts(lines)
    assert n == 1  # only the row without an extracted account
    assert "account_inferred" not in lines[0]
    assert lines[1]["account_inferred"] == "X"


def test_nested_subtotal_reconciles_at_both_levels():
    # A reconciled inner subtotal collapses into a single addend for its parent, so both
    # levels reconcile: inner leaves get the PPA name, the outer's direct leaf gets the
    # account name. Total, Outer = inner subtotal (100) + C (50) = 150.
    lines = [
        _line("Inner A", 40),
        _line("Inner B", 60),
        _line("Subtotal, Inner", 100, is_subtotal=True),
        _line("Outer C", 50),
        _line("Total, Outer", 150, is_subtotal=True),
    ]
    infer_block_accounts(lines)
    assert lines[0]["account_inferred"] == "Inner"
    assert lines[1]["account_inferred"] == "Inner"
    # "Outer C" is a direct child of Outer; the inner group keeps its own label
    assert lines[3]["account_inferred"] == "Outer"


def test_recognizes_period_total_the_flag_missed():
    # The vision model sometimes emits "Total. X" (a period) and fails to flag it
    # is_subtotal, so it would be summed as data and double-count. It must be treated
    # as a rollup: excluded from the sum, and it names + closes its block.
    lines = [
        _line("Joint Economic Committee", 40),
        _line("Joint Committee on Taxation", 60),
        _line("Total. Joint Items", 100, is_subtotal=False),  # period, flag missed
    ]
    n = infer_block_accounts(lines)
    assert n == 2
    assert lines[0]["account_inferred"] == "Joint Items"
    assert "account_inferred" not in lines[2]  # the total row itself is not a leaf


def test_bare_subtotal_is_a_barrier_not_a_rollup():
    # A nameless "Subtotal" can't name a block and is ambiguous as a rollup, so it acts
    # as a barrier — it neither labels nor rolls its value up into the enclosing total
    # (rolling it up empirically produced spurious parent matches on real data).
    lines = [
        _line("A", 40),
        _line("B", 60),
        _line("Subtotal", 100, is_subtotal=True),  # no name -> barrier
        _line("C", 50),
        _line("Total, Account", 150, is_subtotal=True),
    ]
    infer_block_accounts(lines)
    assert all("account_inferred" not in ln for ln in lines)


def test_excludes_parenthesized_memo_amounts_from_the_sum():
    # Parentheses on an amount mark a non-add memo (limitation/transfer/gross), not a
    # negative. A block whose total is net-of-memo reconciles once they're excluded.
    def paren(text, value):
        return {
            "line_item_text": text,
            "is_subtotal": False,
            "committee_recommendation": {"value": value, "raw_text": f"({value})"},
        }

    lines = [
        _line("Program A", 100),
        paren("(Limitation on admin expenses)", 30),  # non-add memo
        _line("Program B", 200),
        _line("Subtotal, X", 300, is_subtotal=True),  # 100 + 200, memo excluded
    ]
    n = infer_block_accounts(lines)
    assert n == 3  # all three leaves belong to X; the memo is excluded only from the sum
    assert lines[0]["account_inferred"] == "X"
    assert lines[1]["account_inferred"] == "X"


def test_with_memo_sum_still_wins_so_no_regression():
    # If the block reconciles WITH the parenthesized amount included, that must still be
    # honored (the memo exclusion is only a fallback, never forces a different answer).
    def paren(text, value):
        return {
            "line_item_text": text,
            "is_subtotal": False,
            "committee_recommendation": {"value": value, "raw_text": f"({value})"},
        }

    lines = [
        _line("Program A", 100),
        paren("component counted in the net", 200),  # paren amount, normal label
        _line("Subtotal, Y", 300, is_subtotal=True),  # 100 + 200 WITH the paren amount
    ]
    n = infer_block_accounts(lines)
    assert n == 2
    assert lines[0]["account_inferred"] == "Y"


def test_reconciles_on_an_alternate_column_when_one_is_ocr_mangled():
    # committee_recommendation is broken on B, but budget_estimate closes the block.
    def dual(text, cr, be, is_subtotal=False):
        return {
            "line_item_text": text,
            "is_subtotal": is_subtotal,
            "committee_recommendation": {"value": cr},
            "budget_estimate": {"value": be},
        }

    lines = [
        dual("Program A", 100, 100),
        dual("Program B", 99999, 200),  # cr OCR-mangled, be intact
        dual("Subtotal, X", 300, 300, is_subtotal=True),
    ]
    n = infer_block_accounts(lines)
    assert n == 2
    assert lines[0]["account_inferred"] == "X"
