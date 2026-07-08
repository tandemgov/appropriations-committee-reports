"""Local file cache for downloaded reports."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from approps.config import RAW_DIR

logger = logging.getLogger(__name__)


def cache_path(package_id: str, congress: int, chamber: str, extension: str = "htm") -> Path:
    """Get the local cache path for a report file.

    Structure: data/raw/{congress}/{chamber}/{package_id}.{ext}
    """
    return RAW_DIR / str(congress) / chamber / f"{package_id}.{extension}"


def is_cached(path: Path) -> bool:
    """Check if a file exists in the cache and has content."""
    return path.exists() and path.stat().st_size > 0


def write_cache(path: Path, content: bytes) -> None:
    """Write content to the cache, creating directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    # Write sha256 sidecar for integrity checking
    sha = hashlib.sha256(content).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(sha)
    logger.debug(f"Cached {path.name} ({len(content)} bytes, sha256={sha[:12]}...)")


def verify_cache(path: Path) -> bool:
    """Verify a cached file against its sha256 sidecar."""
    sha_path = path.with_suffix(path.suffix + ".sha256")
    if not sha_path.exists():
        return True  # No sidecar means no verification possible; assume ok

    expected = sha_path.read_text().strip()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    return expected == actual
