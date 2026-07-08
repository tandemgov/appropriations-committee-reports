"""GovInfo API client for discovering and fetching committee report metadata."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from approps.config import GOVINFO_API_KEY, GOVINFO_BASE_URL

logger = logging.getLogger(__name__)


class GovInfoClient:
    """Client for the GovInfo API (api.govinfo.gov)."""

    def __init__(self, api_key: str = GOVINFO_API_KEY, rate_limit: float = 10.0):
        self.api_key = api_key
        self.base_url = GOVINFO_BASE_URL
        self._semaphore = asyncio.Semaphore(int(rate_limit))
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={"Accept": "application/json"},
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _get(self, url: str, params: dict[str, Any] | None = None) -> dict:
        """Make a GET request to the GovInfo API with rate limiting and retries."""
        async with self._semaphore:
            client = await self._get_client()
            params = params or {}
            params["api_key"] = self.api_key
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def get_package_summary(self, package_id: str) -> dict:
        """Get metadata for a single package (report).

        Returns fields like: title, congress, chamber, dateIssued, documentType, etc.
        """
        url = f"{self.base_url}/packages/{package_id}/summary"
        return await self._get(url)

    async def list_published(
        self,
        start_date: str,
        collection: str = "CRPT",
        congress: int | None = None,
        offset: int = 0,
        page_size: int = 100,
    ) -> dict:
        """List published documents from a collection starting from a date.

        Args:
            start_date: ISO date string, e.g. "2023-01-01"
            collection: Collection code, default "CRPT"
            congress: Filter by congress number
            offset: Pagination offset
            page_size: Number of results per page
        """
        url = f"{self.base_url}/published/{start_date}"
        params: dict[str, Any] = {
            "collection": collection,
            "offset": offset,
            "pageSize": page_size,
        }
        if congress is not None:
            params["congress"] = congress
        return await self._get(url, params)

    async def list_all_published(
        self,
        start_date: str,
        collection: str = "CRPT",
        congress: int | None = None,
    ) -> list[dict]:
        """List ALL published documents, handling pagination automatically."""
        all_packages = []
        offset = 0
        page_size = 100

        while True:
            data = await self.list_published(
                start_date=start_date,
                collection=collection,
                congress=congress,
                offset=offset,
                page_size=page_size,
            )
            packages = data.get("packages", [])
            all_packages.extend(packages)

            next_page = data.get("nextPage")
            if not next_page or len(packages) < page_size:
                break

            offset += page_size
            logger.info(f"Fetched {len(all_packages)} packages so far...")

        return all_packages

    async def get_collection_packages(
        self,
        congress: int,
        doc_class: str | None = None,
        offset: int = 0,
        page_size: int = 100,
    ) -> dict:
        """List packages in the CRPT collection for a given congress.

        Args:
            congress: Congress number (e.g. 118)
            doc_class: Filter by document class (e.g. "HRPT", "SRPT")
            offset: Pagination offset
            page_size: Results per page
        """
        url = f"{self.base_url}/collections/CRPT/{congress}"
        params: dict[str, Any] = {
            "offset": offset,
            "pageSize": page_size,
        }
        if doc_class:
            params["docClass"] = doc_class
        return await self._get(url, params)
