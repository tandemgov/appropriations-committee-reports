"""Download HTML and PDF reports from GovInfo."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential
from tqdm import tqdm

from approps.config import GOVINFO_RATE_LIMIT
from approps.download.cache import cache_path, is_cached, write_cache
from approps.output.schemas import Chamber, ReportMetadata, Stage

logger = logging.getLogger(__name__)


class ReportFetcher:
    """Downloads report HTML and PDF files from GovInfo with caching."""

    def __init__(self, rate_limit: float = GOVINFO_RATE_LIMIT):
        self._semaphore = asyncio.Semaphore(int(rate_limit))
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_not_exception_type(FileNotFoundError),
    )
    async def _download(self, url: str) -> bytes:
        """Download a URL with rate limiting and retries.

        GovInfo answers a missing content file with ``302 -> /error`` and that error
        page returns ``200 OK`` HTML, so ``raise_for_status()`` alone would silently
        accept the error page as the payload. Treat a redirect that lands on ``/error``
        as a not-found instead.
        """
        async with self._semaphore:
            client = await self._get_client()
            response = await client.get(url)
            response.raise_for_status()
            if response.url.path.rstrip("/") == "/error":
                raise FileNotFoundError(
                    f"GovInfo has no content file for {url} (redirected to /error). "
                    "The package may be multi-part or content-less; check the preservation zip."
                )
            return response.content

    @staticmethod
    def _raw_subdir(report: ReportMetadata) -> str:
        """Raw-cache subdirectory: enacted CPRT prints live under 'cprt', else chamber."""
        return "cprt" if report.stage == Stage.ENACTED else report.chamber.value

    async def fetch_html(self, report: ReportMetadata) -> Path:
        """Download and cache the HTML version of a report.

        Returns the local file path.
        """
        path = cache_path(
            report.package_id, report.congress, self._raw_subdir(report), extension="htm"
        )
        if is_cached(path):
            logger.debug(f"HTML cached: {report.package_id}")
            return path

        content = await self._download(report.html_url)
        write_cache(path, content)
        logger.info(f"Downloaded HTML: {report.package_id} ({len(content)} bytes)")
        return path

    async def fetch_pdf(self, report: ReportMetadata) -> Path:
        """Download and cache the PDF version of a report.

        Returns the local file path.
        """
        path = cache_path(
            report.package_id, report.congress, self._raw_subdir(report), extension="pdf"
        )
        if is_cached(path):
            logger.debug(f"PDF cached: {report.package_id}")
            return path

        content = await self._download(report.pdf_url)
        if not content.startswith(b"%PDF"):
            raise ValueError(
                f"Downloaded content for {report.package_id} is not a PDF "
                f"(first bytes: {content[:16]!r}). Refusing to cache a non-PDF as .pdf."
            )
        write_cache(path, content)
        logger.info(f"Downloaded PDF: {report.package_id} ({len(content)} bytes)")
        return path

    async def fetch_report(self, report: ReportMetadata) -> dict[str, Path]:
        """Download HTML (always) and PDF (for House reports) for a report.

        Returns dict with keys "html" and optionally "pdf".
        """
        paths: dict[str, Path] = {}

        # Enacted CPRT prints are PDF-only (no companion HTML on GovInfo).
        if report.stage == Stage.ENACTED:
            paths["pdf"] = await self.fetch_pdf(report)
            return paths

        paths["html"] = await self.fetch_html(report)

        # House reports need PDFs for comparative statement extraction
        if report.chamber == Chamber.HOUSE:
            paths["pdf"] = await self.fetch_pdf(report)

        return paths

    async def fetch_all(
        self, reports: list[ReportMetadata], show_progress: bool = True
    ) -> dict[str, dict[str, Path]]:
        """Download all reports with progress tracking.

        Returns a dict mapping package_id -> {"html": Path, "pdf": Path}.
        """
        results: dict[str, dict[str, Path]] = {}

        iterator = tqdm(reports, desc="Downloading reports") if show_progress else reports
        for report in iterator:
            try:
                paths = await self.fetch_report(report)
                results[report.package_id] = paths
            except Exception as e:
                logger.error(f"Failed to download {report.package_id}: {e}")

        return results
