"""GP prep sidebar download helpers."""

from __future__ import annotations

import logging

from skvo_veb.utils.lc_bridge import export_file_extension
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, absolute_jd_from_display_epoch
from skvo_veb.utils.my_tools import safe_float, sanitize_filename

logger = logging.getLogger(__name__)

GP_INTERVALS_EXPORT_EXTENSION = "dat"
GP_EXTREMA_COMPACT_EXTENSION = "dat"
GP_EXTREMA_EXTENDED_SUFFIX = "_gp_extrema"
GP_TIMING_SUFFIX = "_gp"
GP_TIMING_FALLBACK_STEM = "results_gp"


def export_stem_from_upload_filename(filename: str | None) -> str:
    """Returns a basename-only export stem from an uploaded file name.

    Args:
        filename (str | None): Original upload filename.

    Returns:
        str: Stem without extension, or empty when ``filename`` is missing.
    """
    if not filename:
        return ""
    return filename.rsplit(".", 1)[0]


def gp_suggested_timing_stem(lc_filename: str | None) -> str:
    """Builds the suggested GP timing export stem from a light-curve file name.

    Args:
        lc_filename (str | None): Uploaded light-curve filename.

    Returns:
        str: ``{lc_stem}_gp``, or ``results_gp`` when no name is available.
    """
    base = export_stem_from_upload_filename(lc_filename).strip()
    if not base:
        return GP_TIMING_FALLBACK_STEM
    if base.lower().endswith(GP_TIMING_SUFFIX):
        return base
    return f"{base}{GP_TIMING_SUFFIX}"


def gp_intervals_export_download_name(stem: str | None) -> str:
    """Resolves a browser download filename for a GP intervals export.

    Args:
        stem (str | None): User-entered basename (extension omitted in the UI).

    Returns:
        str: Sanitised filename ending in ``.dat`` when the stem has no extension.
    """
    raw = (stem or "").strip() or "intervals_export"
    safe = sanitize_filename(raw) or "intervals_export"
    if "." in safe:
        return safe
    return f"{safe}.{GP_INTERVALS_EXPORT_EXTENSION}"


def gp_extrema_export_stem(stem: str | None) -> str:
    """Normalises the GP extrema export basename from the review filename field.

    Args:
        stem (str | None): User-entered stem or legacy filename with extension.

    Returns:
        str: Sanitised basename without ``.dat`` / ``.zip`` suffixes.
    """
    raw = (stem or GP_TIMING_FALLBACK_STEM).strip() or GP_TIMING_FALLBACK_STEM
    safe = sanitize_filename(raw) or GP_TIMING_FALLBACK_STEM
    for suffix in (".dat", ".zip"):
        if safe.lower().endswith(suffix):
            safe = safe[: -len(suffix)]
    return safe or GP_TIMING_FALLBACK_STEM


def gp_compact_extrema_download_name(stem: str | None) -> str:
    """Resolves the compact GP extrema ``.dat`` download filename.

    Args:
        stem (str | None): User-entered export stem.

    Returns:
        str: Sanitised ``*.dat`` filename.
    """
    return f"{gp_extrema_export_stem(stem)}.{GP_EXTREMA_COMPACT_EXTENSION}"


def gp_extended_extrema_download_name(stem: str | None) -> str:
    """Resolves the extended GP extrema ZIP download filename.

    Args:
        stem (str | None): User-entered export stem.

    Returns:
        str: Sanitised ``*_gp_extrema.zip``, or ``{stem}_extrema.zip`` when
        ``stem`` already ends with ``_gp``.
    """
    base = gp_extrema_export_stem(stem)
    if base.lower().endswith(GP_TIMING_SUFFIX):
        return f"{base}_extrema.zip"
    return f"{base}{GP_EXTREMA_EXTENDED_SUFFIX}.zip"


def gp_lc_export_download_name(stem: str | None, table_format: str) -> str:
    """Resolves a browser download filename for a GP light curve export.

    Args:
        stem (str | None): User-entered basename or full filename.
        table_format (str): Export format identifier from ``EXPORT_FORMAT_OPTIONS``.

    Returns:
        str: Sanitised filename with extension when the stem has none.
    """
    raw = (stem or "gp_lightcurve").strip()
    safe = sanitize_filename(raw)
    if "." in safe:
        return safe
    ext = export_file_extension(table_format)
    return f"{safe}.{ext}"


def apply_prep_fold_ephemeris(
    lcd,
    period,
    epoch_display,
    *,
    display_epoch: float = DEFAULT_EPOCH_JD,
):
    """Applies GP sidebar P / Epoch widgets to a CurveDash before export.

    User-entered values win over ingest-time transport metadata, matching
    ``docs/lightcurve_data_flow.md``. Empty widgets leave existing metadata.

    Args:
        lcd: ``CurveDash`` rebuilt from GP transport JSON.
        period: Sidebar period in days, or empty.
        epoch_display: Sidebar epoch as MJD offset (``JD - display_epoch``), or empty.
        display_epoch (float): Same offset as the GP prep plot and Epoch field.

    Returns:
        CurveDash: The same instance, mutated in place.
    """
    period_val = safe_float(period)
    if period_val is not None and period_val > 0:
        lcd.period = period_val
        lcd.period_unit = "d"
        logger.debug("GP export period set from sidebar: %s d", period_val)

    epoch_abs = absolute_jd_from_display_epoch(epoch_display, display_epoch)
    if epoch_abs is not None:
        lcd.epoch = epoch_abs
        logger.debug("GP export epoch set from sidebar: JD %s", epoch_abs)
    return lcd
