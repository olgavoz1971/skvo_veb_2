import io
import logging
import os
from typing import Literal

import lightkurve as lk
from lightkurve import LightkurveError
from lightkurve.config import get_cache_dir

from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

_CANNED_CORRUPT_DOWNLOAD = (
    "this file may be corrupt due to an interrupted download"
)
_TRUNCATED_MARKERS = (
    "buffer is too small for requested array",
    "file is truncated",
    "header missing end card",
    "incomplete or truncated",
)
_UNSUPPORTED_READER_MARKERS = (
    "unexpected keyword argument",
    "quality_bitmask",
    "not a recognised tess pipeline",
)

LightkurveFailureKind = Literal["truncated_cache", "unsupported_product", "other"]


def get_lightkurve_cache_dir() -> str:
    """
    Return the active Lightkurve download cache directory.

    Typically ``~/.lightkurve/cache`` (or legacy ``~/.lightkurve-cache`` if configured).
    """
    return get_cache_dir()


def _exception_chain_text(exc: BaseException) -> str:
    """Joins type names and messages from ``exc`` and its cause chain.

    Args:
        exc (BaseException): Outermost exception.

    Returns:
        str: Lower-cased diagnostic text.
    """
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return "\n".join(parts).lower()


def classify_lightkurve_read_failure(exc: BaseException) -> LightkurveFailureKind:
    """Classifies a Lightkurve retrieve failure for purge policy.

    Lightkurve appends a canned “interrupted download” sentence to almost
    every ``read()`` error. That text must not trigger a cache purge.
    Truncated FITS is recognised from the cause chain (e.g. NumPy buffer
    too small). Generic-reader keyword errors are unsupported products.

    Args:
        exc (BaseException): ``LightkurveError``, ``PipeException``, or cause.

    Returns:
        str: ``truncated_cache``, ``unsupported_product``, or ``other``.
    """
    text = _exception_chain_text(exc)
    if any(marker in text for marker in _TRUNCATED_MARKERS):
        return "truncated_cache"
    if any(marker in text for marker in _UNSUPPORTED_READER_MARKERS):
        return "unsupported_product"
    if "of type generic" in text and "typeerror" in text:
        return "unsupported_product"
    return "other"


def _strip_canned_corrupt_sentence(message: str) -> str:
    """Removes Lightkurve’s canned corrupt-download paragraph from a message.

    Args:
        message (str): Raw exception text.

    Returns:
        str: Remaining text, stripped.
    """
    lowered = message.lower()
    idx = lowered.find(_CANNED_CORRUPT_DOWNLOAD)
    if idx == -1:
        return message.strip()
    return message[:idx].strip()


def _author_for_row(search_result: lk.SearchResult, row_idx: int) -> str | None:
    """Returns the pipeline author tag for a search row when present.

    Args:
        search_result (lk.SearchResult): Parent search table.
        row_idx (int): Row index.

    Returns:
        str or None: Author string, or None when the column is absent.
    """
    table = search_result.table
    if "author" not in table.colnames:
        return None
    value = table["author"][row_idx]
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def format_lightkurve_retrieve_error(
    exc: BaseException,
    *,
    row_idx: int,
    author: str | None = None,
) -> str:
    """Builds a British English retrieve error without a false corrupt warning.

    Args:
        exc (BaseException): Failure from Lightkurve download or read.
        row_idx (int): Search-result row index.
        author (str, optional): Pipeline author tag when known.

    Returns:
        str: User-facing message.
    """
    kind = classify_lightkurve_read_failure(exc)
    if kind == "truncated_cache":
        return (
            f"Retrieve failed for row {row_idx}: the cached FITS file appears "
            "incomplete or truncated."
        )
    if kind == "unsupported_product":
        author_bit = f" (pipeline {author})" if author else ""
        return (
            f"Retrieve failed for row {row_idx}{author_bit}: this archive product "
            "is not a recognised TESS pipeline light curve, so it cannot be opened "
            "with the standard retrieve. The cached file was left unchanged."
        )
    inner = exc.__cause__ if isinstance(exc.__cause__, BaseException) else exc
    cleaned = _strip_canned_corrupt_sentence(str(inner))
    if not cleaned:
        cleaned = _strip_canned_corrupt_sentence(str(exc)) or "unknown Lightkurve error"
    return f"Retrieve failed for row {row_idx}: {cleaned}"


def _expected_mast_fits_path(search_result: lk.SearchResult, row_idx: int) -> str | None:
    """Returns the Lightkurve mastDownload path for a search row.

    Args:
        search_result (lk.SearchResult): Parent search result table.
        row_idx (int): Row index.

    Returns:
        str or None: Expected FITS path, or None for TESScut FFI rows.

    Raises:
        PipeException: When ``row_idx`` is out of range.
    """
    if row_idx < 0 or row_idx >= len(search_result):
        raise PipeException(f"Invalid search row index: {row_idx}")

    table = search_result.table
    row = table[row_idx]
    description = str(row["description"]) if "description" in table.colnames else ""
    if "FFI Cutout" in description:
        return None

    download_dir = search_result._default_download_dir()
    return os.path.join(
        download_dir.rstrip("/"),
        "mastDownload",
        row["obs_collection"],
        row["obs_id"],
        row["productFilename"],
    )


def _hdu_column_names(path: str) -> list[str]:
    """Returns lower-case column names from the first table HDU.

    Args:
        path (str): Local FITS path.

    Returns:
        list[str]: Column names, or an empty list when none exist.
    """
    from astropy.io import fits

    with fits.open(path) as hdulist:
        for hdu in hdulist[1:]:
            columns = getattr(hdu, "columns", None)
            names = getattr(columns, "names", None)
            if names:
                return [str(name).lower() for name in names]
    return []


def open_lightcurve_product(
    path: str,
    *,
    row_idx: int = 0,
    author: str | None = None,
):
    """Opens a cached FITS light curve without forcing SPOC reader kwargs.

    Typed Kepler/TESS products keep ``quality_bitmask='default'``. Generic
    HLSPs (for example TARS) are opened only when HDU 1 has ``TIME`` and
    ``FLUX``; ``quality_bitmask`` is not passed. Missing those columns is an
    unsupported product, not a corrupt cache.

    Args:
        path (str): Local FITS path.
        row_idx (int): Search-result row index for error text.
        author (str, optional): Pipeline author tag for error text.

    Returns:
        lightkurve.LightCurve or TargetPixelFile: Opened product.

    Raises:
        PipeException: When the file cannot be opened honestly.
        LightkurveError: When Lightkurve ``read`` fails for a typed product.
    """
    from astropy.io import fits
    from lightkurve.io.detect import detect_filetype
    from lightkurve.io.read import read

    with fits.open(path) as hdulist:
        kind = detect_filetype(hdulist)

    if kind in (None, "generic"):
        names = set(_hdu_column_names(path))
        if "time" not in names or "flux" not in names:
            raise PipeException(
                format_lightkurve_retrieve_error(
                    PipeException("not a recognised TESS pipeline light curve"),
                    row_idx=row_idx,
                    author=author,
                )
            )
        logger.info(
            "Opening generic FITS light curve without quality_bitmask path=%s",
            path,
        )
        return read(path)

    return read(path, quality_bitmask="default")


def ensure_mast_product_fits(search_result: lk.SearchResult, row_idx: int) -> str:
    """Returns a local mastDownload FITS path, fetching from MAST if needed.

    Args:
        search_result (lk.SearchResult): Parent search result table.
        row_idx (int): Row index.

    Returns:
        str: Absolute path to the product FITS file.

    Raises:
        PipeException: When the row is a TESScut FFI or MAST download fails.
        LightkurveError: When MAST reports a non-complete download.
    """
    path = _expected_mast_fits_path(search_result, row_idx)
    if path is None:
        raise PipeException(
            f"Retrieve failed for row {row_idx}: TESScut FFI rows are not "
            "opened through the archive light-curve cache."
        )
    if os.path.isfile(path):
        logger.info("[DOWNLOAD FITS] Cache HIT path=%s", path)
        return path

    from astroquery.mast import Observations

    download_dir = search_result._default_download_dir()
    one_row = search_result[row_idx]
    logger.info("[DOWNLOAD FITS] Cache MISS; fetching from MAST row=%s", row_idx)
    download_response = Observations.download_products(
        one_row.table,
        mrp_only=False,
        download_dir=download_dir,
    )[0]
    status = download_response["Status"]
    if status != "COMPLETE":
        raise LightkurveError(
            f"Download of row {row_idx} failed. MAST returns {status}: "
            f"{download_response['Message']}"
        )
    local_path = download_response["Local Path"]
    logger.info("[DOWNLOAD FITS] MAST download complete path=%s", local_path)
    return local_path


def _attach_search_author(lc, author: str | None) -> None:
    """Copies the MAST author tag onto a Lightkurve object when missing.

    Args:
        lc: Lightkurve product.
        author (str, optional): Search-table author.
    """
    if not author:
        return
    meta = getattr(lc, "meta", None)
    if not isinstance(meta, dict):
        return
    if meta.get("AUTHOR"):
        return
    meta["AUTHOR"] = author


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

    path = _expected_mast_fits_path(search_result, row_idx)
    return path if path and os.path.isfile(path) else None


_MAST_FITS_GONE = (
    "The original MAST FITS file is missing or unreadable. "
    "Please retrieve the light curve again."
)


def mast_pipeline_fits_pointer(
    search_result: lk.SearchResult, row_idx: int
) -> dict[str, str] | None:
    """Builds a session pointer to a MAST pipeline FITS product.

    FFI/TESScut rows have no mastDownload light-curve product.

    Args:
        search_result (lk.SearchResult): Parent search result table.
        row_idx (int): Row index in the search result.

    Returns:
        dict or None: ``obs_collection``, ``obs_id``, and ``product_filename``,
        or ``None`` when the row is not a pipeline light-curve FITS.

    Raises:
        PipeException: When ``row_idx`` is out of range.
    """
    if row_idx < 0 or row_idx >= len(search_result):
        raise PipeException(f"Invalid search row index: {row_idx}")
    table = search_result.table
    description = str(table["description"][row_idx]) if "description" in table.colnames else ""
    if "FFI Cutout" in description:
        return None
    row = table[row_idx]
    return {
        "obs_collection": str(row["obs_collection"]),
        "obs_id": str(row["obs_id"]),
        "product_filename": str(row["productFilename"]),
    }


def _path_from_mast_fits_pointer(pointer: dict[str, str]) -> str:
    """Resolves a session pointer against the shared Lightkurve cache.

    Args:
        pointer (dict): Stored ``obs_collection``, ``obs_id``, ``product_filename``.

    Returns:
        str: Absolute path under ``mastDownload``.
    """
    download_dir = get_lightkurve_cache_dir().rstrip("/")
    return os.path.join(
        download_dir,
        "mastDownload",
        pointer["obs_collection"],
        pointer["obs_id"],
        pointer["product_filename"],
    )


def read_cached_mast_pipeline_fits(pointer: dict[str, str] | None) -> tuple[bytes, str]:
    """Reads original pipeline FITS bytes from the shared MAST cache.

    Args:
        pointer (dict, optional): Session pointer from the last archive retrieve.

    Returns:
        tuple: ``(fits_bytes, product_filename)``.

    Raises:
        PipeException: When the pointer is missing or the file is gone or corrupt.
    """
    if not pointer:
        raise PipeException(
            "Retrieve a TESS archive light curve before downloading the original MAST FITS."
        )
    try:
        filename = str(pointer["product_filename"])
        path = _path_from_mast_fits_pointer(pointer)
    except (KeyError, TypeError) as exc:
        raise PipeException(_MAST_FITS_GONE) from exc

    if not os.path.isfile(path):
        raise PipeException(_MAST_FITS_GONE)

    try:
        from astropy.io import fits

        with open(path, "rb") as handle:
            payload = handle.read()
        if not payload:
            raise PipeException(_MAST_FITS_GONE)
        with fits.open(io.BytesIO(payload), memmap=False) as hdulist:
            if len(hdulist) < 1:
                raise PipeException(_MAST_FITS_GONE)
    except PipeException:
        raise
    except Exception as exc:
        logger.warning("read_cached_mast_pipeline_fits failed path=%s: %s", path, exc)
        raise PipeException(_MAST_FITS_GONE) from exc

    logger.info(
        "Serving cached MAST pipeline FITS name=%s nbytes=%s",
        filename,
        len(payload),
    )
    return payload, filename


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
    """Downloads one SearchResult row from MAST or the Lightkurve cache.

    Args:
        search_result (lk.SearchResult): Parent search result table.
        row_idx (int): Row index in the search result.

    Returns:
        Lightkurve LightCurve: Opened product.

    Raises:
        PipeException: When the row index is invalid or Lightkurve cannot
            open the product. The message does not claim a corrupt cache
            unless the failure looks like truncated FITS.
    """
    if row_idx < 0 or row_idx >= len(search_result):
        raise PipeException(f'Invalid search row index: {row_idx}')

    logger.info('[DOWNLOAD FITS] Fetching row %s from MAST / Lightkurve cache...', row_idx)
    author = _author_for_row(search_result, row_idx)
    table = search_result.table
    description = (
        str(table["description"][row_idx]) if "description" in table.colnames else ""
    )
    try:
        if "FFI Cutout" in description:
            lc = search_result[row_idx].download()
        else:
            path = ensure_mast_product_fits(search_result, row_idx)
            lc = open_lightcurve_product(path, row_idx=row_idx, author=author)
            _attach_search_author(lc, author)
    except LightkurveError as exc:
        message = format_lightkurve_retrieve_error(exc, row_idx=row_idx, author=author)
        logger.warning('download_lightcurve_row failed for row %s: %s', row_idx, message)
        raise PipeException(message) from exc

    logger.info('[DOWNLOAD FITS] Success for row %s', row_idx)
    return lc


def download_lightcurve_row_with_recovery(search_result: lk.SearchResult, row_idx: int):
    """Downloads one row, purging cache only when the FITS looks truncated.

    Unsupported-product failures (for example Lightkurve generic reader
    rejecting ``quality_bitmask``) must not delete a complete cached file.

    Args:
        search_result (lk.SearchResult): Parent search result table.
        row_idx (int): Row index in the search result.

    Returns:
        Lightkurve LightCurve: Downloaded or cache-opened curve.

    Raises:
        PipeException: When retrieve fails (honest message; see
            ``format_lightkurve_retrieve_error``).
    """
    try:
        return download_lightcurve_row(search_result, row_idx)
    except PipeException as exc:
        if classify_lightkurve_read_failure(exc) != "truncated_cache":
            raise
        logger.warning(
            '[DOWNLOAD FITS] Cached FITS looks truncated for row %s; purging and retrying...',
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
