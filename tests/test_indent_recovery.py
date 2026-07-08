"""Gemini non-add double-gate: recover over-summing House subtotal blocks.

The arithmetic (`_oversum_blocks`, the reconcile gate) is tested directly; the one
non-deterministic dependency — Gemini's per-line non-add call — is stubbed, so these
tests are hermetic and never hit the network.
"""

from __future__ import annotations

import sys
import types

from approps.normalization import indent_recovery
from approps.normalization.indent_recovery import _oversum_blocks, recover_indent


def _line(text, rec=None, is_subtotal=False, account=None, page=2):
    """A comparative line. `page` is encoded the way extraction does it: line_number = page*100."""
    d = {
        "line_item_text": text,
        "is_subtotal": is_subtotal,
        "line_number": page * 100,
    }
    if rec is not None:
        d["committee_recommendation"] = {"value": rec, "in_thousands": True}
    if account is not None:
        d["account"] = account
    return d


class _FakePDF:
    """Stand-in for a pdfplumber PDF: only `.pages` (length) is consulted once
    `_render_page_b64` is stubbed out."""

    def __init__(self, n_pages: int):
        self.pages = [None] * n_pages


def _patch_boundaries(monkeypatch, flagged_by_page):
    """Stub the PDF open, page render, and Gemini call so recover_indent runs offline.

    `flagged_by_page` maps a 1-based page number to the {block_letter: [idx]} Gemini would
    have returned for that page.
    """
    fake_pdfplumber = types.ModuleType("pdfplumber")
    fake_pdfplumber.open = lambda _path: _FakePDF(50)
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    monkeypatch.setattr(indent_recovery, "_render_page_b64", lambda pdf, page: f"page-{page}")

    def fake_gemini(image_b64, blocks_on_page):
        page = int(image_b64.split("-")[1])
        return flagged_by_page.get(page, {})

    monkeypatch.setattr(indent_recovery, "_gemini_nonadd", fake_gemini)


# --- The over-sum detector ---------------------------------------------------


def test_oversum_block_detected():
    # 100 + 200 + 50 = 350 but the subtotal is 300 => over-sums by the 50 non-add line.
    lines = [
        _line("Program A", 100),
        _line("Program B", 200),
        _line("of which: transfer", 50),
        _line("Subtotal, Operations and Support", 300, is_subtotal=True),
    ]
    blocks = _oversum_blocks(lines)
    assert len(blocks) == 1
    assert blocks[0]["subtotal_name"] == "Operations and Support"
    assert len(blocks[0]["leaves"]) == 3


def test_exactly_reconciling_block_is_not_a_candidate():
    # A block the base reconciler already handles is not an over-sum candidate.
    lines = [
        _line("Program A", 100),
        _line("Program B", 200),
        _line("Subtotal, X", 300, is_subtotal=True),
    ]
    assert _oversum_blocks(lines) == []


def test_undersum_block_is_not_a_candidate():
    # Under-summing (missing a line) is a different failure the double gate can't fix.
    lines = [
        _line("Program A", 100),
        _line("Subtotal, X", 300, is_subtotal=True),
    ]
    assert _oversum_blocks(lines) == []


# --- The double gate ---------------------------------------------------------


def test_recovers_when_excluding_flagged_line_reconciles(monkeypatch):
    lines = [
        _line("Program A", 100),
        _line("Program B", 200),
        _line("of which: transfer", 50),  # line 3 in the block — the non-add child
        _line("Subtotal, Operations and Support", 300, is_subtotal=True),
    ]
    _patch_boundaries(monkeypatch, {2: {"A": [3]}})
    stats = recover_indent("dummy.pdf", lines)

    assert stats["blocks_recovered"] == 1
    assert stats["rows_labeled"] == 2
    assert stats["lines_marked_nonadd"] == 1
    assert lines[0]["account_inferred"] == "Operations and Support"
    assert lines[1]["account_inferred"] == "Operations and Support"
    # the flagged non-add line is marked and NOT given the account label
    assert lines[2].get("non_add_inferred") is True
    assert "account_inferred" not in lines[2]
    # the subtotal row itself is untouched
    assert "account_inferred" not in lines[3]


def test_gate_rejects_when_exclusion_still_does_not_reconcile(monkeypatch):
    # Gemini flags line 3, but excluding it leaves 100 + 200 = 300 != 320: no reconcile.
    lines = [
        _line("Program A", 100),
        _line("Program B", 200),
        _line("stray", 20),
        _line("Subtotal, X", 320, is_subtotal=True),
    ]
    _patch_boundaries(monkeypatch, {2: {"A": [1]}})  # flags the wrong line
    stats = recover_indent("dummy.pdf", lines)

    assert stats["blocks_recovered"] == 0
    assert all("account_inferred" not in ln for ln in lines)
    assert all("non_add_inferred" not in ln for ln in lines)


def test_gate_rejects_when_gemini_flags_nothing(monkeypatch):
    lines = [
        _line("Program A", 100),
        _line("Program B", 200),
        _line("of which: transfer", 50),
        _line("Subtotal, X", 300, is_subtotal=True),
    ]
    _patch_boundaries(monkeypatch, {2: {"A": []}})
    stats = recover_indent("dummy.pdf", lines)
    assert stats["blocks_recovered"] == 0
    assert all("account_inferred" not in ln for ln in lines)


def test_additive_never_overwrites_existing_account(monkeypatch):
    lines = [
        _line("Program A", 100, account="EXTRACTED ACCOUNT"),
        _line("Program B", 200),
        _line("of which: transfer", 50),
        _line("Subtotal, Operations and Support", 300, is_subtotal=True),
    ]
    _patch_boundaries(monkeypatch, {2: {"A": [3]}})
    stats = recover_indent("dummy.pdf", lines)

    # Program A keeps its extracted account; only the unlabeled Program B is newly labeled.
    assert lines[0]["account"] == "EXTRACTED ACCOUNT"
    assert "account_inferred" not in lines[0]
    assert lines[1]["account_inferred"] == "Operations and Support"
    assert stats["rows_labeled"] == 1


def test_failed_page_is_counted_so_the_report_stays_retryable(monkeypatch):
    # When the Gemini call raises (e.g. depleted API credits), the page is counted in
    # pages_failed and no labels are produced — the batch runner keys off pages_failed to
    # avoid stamping a resume marker on an unfinished report.
    lines = [
        _line("Program A", 100),
        _line("of which: transfer", 50),
        _line("Subtotal, X", 100, is_subtotal=True),
    ]
    fake_pdfplumber = types.ModuleType("pdfplumber")
    fake_pdfplumber.open = lambda _path: _FakePDF(50)
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)
    monkeypatch.setattr(indent_recovery, "_render_page_b64", lambda pdf, page: "img")

    def boom(image_b64, blocks_on_page):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(indent_recovery, "_gemini_nonadd", boom)
    stats = recover_indent("dummy.pdf", lines)
    assert stats["pages_failed"] == 1
    assert stats["pages_reread"] == 0
    assert stats["blocks_recovered"] == 0
    assert all("account_inferred" not in ln for ln in lines)


def test_no_blocks_short_circuits_without_opening_pdf(monkeypatch):
    # No over-summing block => recover_indent returns before touching the PDF/Gemini.
    def _boom(*a, **k):
        raise AssertionError("should not open a PDF when there is nothing to recover")

    monkeypatch.setitem(sys.modules, "pdfplumber", types.SimpleNamespace(open=_boom))
    lines = [
        _line("Program A", 100),
        _line("Subtotal, X", 100, is_subtotal=True),
    ]
    stats = recover_indent("dummy.pdf", lines)
    assert stats["oversum_blocks"] == 0
    assert stats["blocks_recovered"] == 0
