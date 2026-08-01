"""Server-side storage for GP review figures (paginated final view)."""

from __future__ import annotations

import logging
from pathlib import Path

import diskcache

logger = logging.getLogger(__name__)

_CACHE: diskcache.Cache | None = None


def _review_cache() -> diskcache.Cache:
    """Returns the shared disk cache for GP review payloads.

    Returns:
        diskcache.Cache: Writable cache under ``cache/gp_review``.
    """
    global _CACHE
    if _CACHE is None:
        cache_dir = Path(__file__).resolve().parents[2] / "cache" / "gp_review"
        cache_dir.mkdir(parents=True, exist_ok=True)
        _CACHE = diskcache.Cache(str(cache_dir))
    return _CACHE


def save_gp_review_run(run_id: str, entries: list[dict]) -> None:
    """Persists serialised review entries for one GP batch run.

    Args:
        run_id (str): Unique run identifier stored in ``store-results-data``.
        entries (list[dict]): Storable rows (figures as JSON, badge specs, flags).
    """
    _review_cache().set(run_id, entries, expire=86400)
    logger.debug("Saved GP review run %s (%s entries)", run_id, len(entries))


def load_gp_review_run(run_id: str) -> list[dict]:
    """Loads serialised review entries for a run.

    Args:
        run_id (str): Run identifier from ``save_gp_review_run``.

    Returns:
        list[dict]: Stored entry list.

    Raises:
        KeyError: If the run id is missing or expired.
    """
    entries = _review_cache().get(run_id)
    if entries is None:
        raise KeyError(f"GP review run not found: {run_id!r}")
    return entries
