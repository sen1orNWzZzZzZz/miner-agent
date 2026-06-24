"""In-memory TTL cache shared across requests.

Used to cache expensive operations within a short window so repeated work
(re-parsing the same PDF, re-running an identical briefing) is served from
memory instead of re-calling the LLM / MCP tools. This saves both latency and
tokens. The cache is process-local and ephemeral by design — a 30-minute TTL is
plenty for "I just asked that" deduplication without risking stale results.
"""

import hashlib
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


def _ttl_from_env() -> float:
    """Cache TTL in seconds; defaults to 30 minutes, overridable via env."""
    try:
        return float(os.environ.get("CACHE_TTL_SECONDS", "1800"))
    except ValueError:
        return 1800.0


class TTLCache:
    """A minimal thread-safe key/value cache with per-entry expiry."""

    def __init__(self, ttl: float | None = None) -> None:
        self._ttl = ttl if ttl is not None else _ttl_from_env()
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """Return the cached value, or None if missing/expired."""
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expiry, value = entry
            if now >= expiry:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        """Store a value with the configured TTL."""
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Shared cache instances.
pdf_cache = TTLCache()
briefing_cache = TTLCache()


def pdf_cache_key(pdf_url: str) -> str:
    """Derive a stable cache key for a PDF extraction.

    For locally-uploaded files we hash the file *content* so the same PDF maps to
    the same key regardless of its filename or the URL used to reach it. For
    external URLs we fall back to keying on the URL string.
    """
    name = os.path.basename(pdf_url.split("?")[0]) if pdf_url else ""
    data_dir = os.environ.get("AGENT_DATA_DIR", "/app/data")
    local_path = os.path.join(data_dir, "uploads", name)
    if name and os.path.exists(local_path):
        try:
            with open(local_path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            return f"pdf:sha256:{digest}"
        except OSError:
            pass
    return f"pdf:url:{pdf_url}"


def content_cache_key(contents: bytes) -> str:
    """Cache key for raw PDF bytes (used by the upload endpoint)."""
    return f"pdf:sha256:{hashlib.sha256(contents).hexdigest()}"


def briefing_cache_key(query: str, attachments: list[str]) -> str:
    """Cache key for a briefing request (query + sorted attachment names)."""
    payload = query.strip() + " " + " ".join(sorted(attachments))
    return f"briefing:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
