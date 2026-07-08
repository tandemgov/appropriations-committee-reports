"""Guards that stop the fetcher from silently caching a non-PDF as a .pdf.

GovInfo answers a missing content file with ``302 -> /error`` (which itself returns
``200 OK`` HTML), so without these guards the HTML error page would be written to
disk as ``<package>.pdf`` and only fail later at extraction time. The redirect-to-
``/error`` half is exercised live against GovInfo; here we cover the magic-byte half
without network by monkeypatching ``_download``.
"""

from __future__ import annotations

import asyncio

import pytest

from approps.download.fetcher import ReportFetcher
from approps.output.schemas import Chamber, ReportMetadata, Stage


def _report() -> ReportMetadata:
    return ReportMetadata(
        package_id="CRPT-118hrpt999",
        congress=118,
        chamber=Chamber.HOUSE,
        report_number=999,
        title="TEST",
        subcommittee="Agriculture",
        fiscal_year=2025,
        stage=Stage.COMMITTEE,
        date_issued="2024-07-12",
        html_url="https://example.gov/x.htm",
        pdf_url="https://example.gov/x.pdf",
    )


def test_fetch_pdf_rejects_non_pdf_bytes(monkeypatch):
    """An HTML error page returned in place of a PDF must raise, not get cached."""
    fetcher = ReportFetcher()

    async def fake_download(url: str) -> bytes:
        return b"<!DOCTYPE html><html><body>error</body></html>"

    monkeypatch.setattr(fetcher, "_download", fake_download)

    async def go():
        with pytest.raises(ValueError, match="not a PDF"):
            await fetcher.fetch_pdf(_report())
        await fetcher.close()

    asyncio.run(go())


def test_fetch_pdf_accepts_real_pdf_bytes(monkeypatch, tmp_path):
    """A genuine PDF payload passes the magic-byte guard and is cached."""
    fetcher = ReportFetcher()
    dest = tmp_path / "x.pdf"

    async def fake_download(url: str) -> bytes:
        return b"%PDF-1.4\n%fake body\n"

    # Redirect the cache location into tmp_path so the test never touches data/raw.
    monkeypatch.setattr(fetcher, "_download", fake_download)
    monkeypatch.setattr("approps.download.fetcher.cache_path", lambda *a, **k: dest)
    monkeypatch.setattr("approps.download.fetcher.is_cached", lambda p: False)

    async def go():
        path = await fetcher.fetch_pdf(_report())
        assert path.read_bytes().startswith(b"%PDF")
        await fetcher.close()

    asyncio.run(go())
