import logging
import os

import lightkurve as lk
from lightkurve import LightkurveError
from lightkurve.config import get_cache_dir

from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)


def get_lightkurve_cache_dir() -> str:
    """
    Return the active Lightkurve download cache directory.

    Typically ``~/.lightkurve/cache`` (or legacy ``~/.lightkurve-cache`` if configured).
    """
    return get_cache_dir()


def get_cached_fits_path(search_result: lk.SearchResult, row_idx: int) -> str | None:
    """
    Resolve the on-disk FITS path for a SearchResult row if it is already cached.

    Parameters
    ----------
    search_result : lk.SearchResult
        Parent search result table.
    row_idx : int
        Row index in the search result (the ``#`` column value).

    Returns
    -------
    str or None
        Absolute path to the cached FITS file, or None if not present on disk.
    """
    if row_idx < 0 or row_idx >= len(search_result):
        raise PipeException(f'Invalid search row index: {row_idx}')

    table = search_result.table
    row = table[row_idx]
    download_dir = search_result._default_download_dir()

    if 'FFI Cutout' in row['description']:
        logger.warning('TESScut FFI rows use a separate cache layout; FITS purge not supported here.')
        return None

    path = os.path.join(
        download_dir.rstrip('/'),
        'mastDownload',
        row['obs_collection'],
        row['obs_id'],
        row['productFilename'],
    )
    return path if os.path.isfile(path) else None


def purge_lightkurve_cached_fits(search_result: lk.SearchResult, row_idx: int) -> bool:
    """
    Delete a specific Lightkurve-cached FITS file for one SearchResult row.

    Parameters
    ----------
    search_result : lk.SearchResult
        Parent search result table.
    row_idx : int
        Row index in the search result.

    Returns
    -------
    bool
        True if a file was found and deleted, False if nothing was cached on disk.
    """
    path = get_cached_fits_path(search_result, row_idx)
    if not path:
        logger.info('[PURGE FITS] No cached file on disk for row %s', row_idx)
        return False

    try:
        os.remove(path)
        logger.info('[PURGE FITS] Deleted cached file: %s', path)
        return True
    except OSError as exc:
        msg = f'Failed to delete cached FITS file {path}: {exc}'
        logger.error(msg)
        raise PipeException(msg) from exc


def download_lightcurve_row(search_result: lk.SearchResult, row_idx: int):
    """
    Download a single light curve row from MAST (uses Lightkurve local cache after download).

    Returns
    -------
    Lightkurve LightCurve
    """
    if row_idx < 0 or row_idx >= len(search_result):
        raise PipeException(f'Invalid search row index: {row_idx}')

    logger.info('[DOWNLOAD FITS] Fetching row %s from MAST / Lightkurve cache...', row_idx)
    try:
        lc = search_result[row_idx].download()
    except LightkurveError as exc:
        logger.warning('download_lightcurve_row failed for row %s: %s', row_idx, exc)
        raise PipeException(f'Download failed for row {row_idx}: {exc}') from exc

    logger.info('[DOWNLOAD FITS] Success for row %s', row_idx)
    return lc


def download_lightcurve_row_with_recovery(search_result: lk.SearchResult, row_idx: int):
    """Download one row, purging corrupted local FITS cache automatically on failure."""
    try:
        return download_lightcurve_row(search_result, row_idx)
    except (LightkurveError, PipeException):
        logger.warning(
            '[DOWNLOAD FITS] Download failed for row %s; attempting cache purge and retry...',
            row_idx,
        )
        purge_lightkurve_cached_fits(search_result, row_idx)
        return download_lightcurve_row(search_result, row_idx)


def purge_and_redownload_row(search_result: lk.SearchResult, row_idx: int):
    """
    Purge a cached FITS file (if present) and force a fresh MAST download for one row.

    Returns
    -------
    tuple[bool, object]
        (was_purged, lightcurve)
    """
    was_purged = purge_lightkurve_cached_fits(search_result, row_idx)
    lc = download_lightcurve_row(search_result, row_idx)
    return was_purged, lc
