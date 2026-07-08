"""Shared dependencies for the API layer."""

from __future__ import annotations

import json
from functools import lru_cache

from approps.config import EXTRACTED_DIR
from approps.discovery.report_catalog import load_catalog
from approps.output.schemas import ReportMetadata


@lru_cache
def get_catalog() -> list[ReportMetadata]:
    """Load the report catalog (cached)."""
    return load_catalog()


def get_extracted_data(package_id: str) -> dict | None:
    """Load extracted JSON data for a report, if it exists."""
    # Search across congress/chamber subdirectories
    for path in EXTRACTED_DIR.rglob(f"{package_id}.json"):
        return json.loads(path.read_text())
    return None


def list_extracted_reports() -> list[str]:
    """List all package IDs that have extracted data."""
    if not EXTRACTED_DIR.exists():
        return []
    return [p.stem for p in EXTRACTED_DIR.rglob("*.json")]
