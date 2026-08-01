"""Cooperative stop flag for long-running GP batch fits (background callback)."""

from __future__ import annotations

import logging
from pathlib import Path

import diskcache

logger = logging.getLogger(__name__)

_STOP_KEY = "gp_batch_stop_requested"
_CACHE: diskcache.Cache | None = None


def _control_cache() -> diskcache.Cache:
    """Returns disk cache for GP run control flags.

    Returns:
        diskcache.Cache: Writable cache under ``cache/gp_run_control``.
    """
    global _CACHE
    if _CACHE is None:
        cache_dir = Path(__file__).resolve().parents[2] / "cache" / "gp_run_control"
        cache_dir.mkdir(parents=True, exist_ok=True)
        _CACHE = diskcache.Cache(str(cache_dir))
    return _CACHE


def clear_gp_batch_stop() -> None:
    """Clears the stop request at the start of a new GP batch run."""
    _control_cache().set(_STOP_KEY, False)
    logger.debug("GP batch stop flag cleared")


def request_gp_batch_stop() -> None:
    """Requests stop after the current extremum fit completes."""
    _control_cache().set(_STOP_KEY, True)
    logger.info("GP batch stop requested by user")


def gp_batch_stop_requested() -> bool:
    """Reports whether the user has requested an early stop.

    Returns:
        bool: True when ``request_gp_batch_stop`` was called for this run.
    """
    return bool(_control_cache().get(_STOP_KEY, False))
