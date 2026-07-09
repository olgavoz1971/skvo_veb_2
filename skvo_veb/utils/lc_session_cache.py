"""Server-side CurveDash session cache shared by interactive lightcurve pages.

Heavy lightcurve payloads live in a disk-backed cache keyed by browser tab id
and page namespace. Dash stores hold only lightweight revision triggers and
selection state.
"""

from __future__ import annotations

import logging
import os
import uuid

import diskcache

from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

_CACHE_EXPIRE_SECONDS = 86400
_user_cache: diskcache.Cache | None = None


def get_lc_user_cache() -> diskcache.Cache:
    """Returns the process-wide disk cache for per-tab lightcurve payloads.

    Returns:
        diskcache.Cache: Cache instance rooted at ``USER_CACHE_DIR``.
    """
    global _user_cache
    if _user_cache is None:
        cache_dir = os.getenv('USER_CACHE_DIR')
        _user_cache = diskcache.Cache(cache_dir)
    return _user_cache


def compose_lc_cache_key(page_namespace: str, user_tab_id: str) -> str:
    """Builds a deterministic cache key for a page tab session.

    Args:
        page_namespace (str): Short page identifier (e.g. ``asassn``, ``tess_lc_srv``).
        user_tab_id (str): Browser session tab id from ``dcc.Store``.

    Returns:
        str: Cache key string.
    """
    return f'{page_namespace}_{user_tab_id}_data'


def has_cached_lc(page_namespace: str, user_tab_id: str | None) -> bool:
    """Checks whether a serialized lightcurve exists for the tab session.

    Args:
        page_namespace (str): Page namespace prefix.
        user_tab_id (str): Browser session tab id.

    Returns:
        bool: True when cached data is present.
    """
    if not user_tab_id:
        return False
    user_key = compose_lc_cache_key(page_namespace, user_tab_id)
    return get_lc_user_cache().get(user_key, default=None) is not None


def read_serialized_lc(page_namespace: str, user_tab_id: str | None) -> str:
    """Reads a serialized CurveDash payload from the session cache.

    Args:
        page_namespace (str): Page namespace prefix.
        user_tab_id (str): Browser session tab id.

    Returns:
        str: JSON string from ``CurveDash.serialize()``.

    Raises:
        PipeException: When the tab id is missing or cache entry expired.
    """
    if user_tab_id is None:
        raise PipeException('Please, download the lightcurve first')
    user_key = compose_lc_cache_key(page_namespace, user_tab_id)
    user_data = get_lc_user_cache().get(user_key, default=None)
    if user_data is None:
        logger.warning(
            'lc_session_cache.read_serialized_lc: empty cache for namespace=%s tab=%s',
            page_namespace,
            user_tab_id,
        )
        raise PipeException('Please, download the lightcurve. Session cache is empty')
    get_lc_user_cache().set(user_key, user_data, expire=_CACHE_EXPIRE_SECONDS)
    return user_data


def write_serialized_lc(page_namespace: str, user_tab_id: str, serialized: str) -> None:
    """Writes a serialized CurveDash payload to the session cache.

    Args:
        page_namespace (str): Page namespace prefix.
        user_tab_id (str): Browser session tab id.
        serialized (str): JSON string from ``CurveDash.serialize()``.
    """
    user_key = compose_lc_cache_key(page_namespace, user_tab_id)
    get_lc_user_cache().set(user_key, serialized, expire=_CACHE_EXPIRE_SECONDS)
    logger.info(
        'lc_session_cache.write_serialized_lc: namespace=%s tab=%s',
        page_namespace,
        user_tab_id,
    )


def generate_user_tab_id() -> str:
    """Creates a new unique browser tab id for session-scoped cache keys.

    Returns:
        str: UUID string.
    """
    user_tab_id = str(uuid.uuid4())
    logger.info('lc_session_cache.generate_user_tab_id: %s', user_tab_id)
    return user_tab_id
