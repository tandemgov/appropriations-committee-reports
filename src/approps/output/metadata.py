"""Provenance and lineage tracking for extracted data."""

from __future__ import annotations

import subprocess
from datetime import datetime

from pydantic import BaseModel


class ExtractionProvenance(BaseModel):
    """Provenance metadata attached to extraction results."""

    report_id: str
    extraction_timestamp: str
    pipeline_version: str
    source_url: str
    source_sha256: str | None = None

    @classmethod
    def create(
        cls,
        report_id: str,
        source_url: str,
        source_sha256: str | None = None,
    ) -> ExtractionProvenance:
        return cls(
            report_id=report_id,
            extraction_timestamp=datetime.now().isoformat(),
            pipeline_version=_get_git_version(),
            source_url=source_url,
            source_sha256=source_sha256,
        )


def _get_git_version() -> str:
    """Get the current git commit hash, or 'unknown' if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"
