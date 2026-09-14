"""Shared light-curve export stems, download names, and sidebar ephemeris.

Used by the Lightcurve processor and the GP prep page. GP-only timing and
extrema stems stay in ``skvo_veb.utils.gp.export``.
"""

from __future__ import annotations

import logging

from skvo_veb.utils.lc_bridge import export_file_extension
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, absolute_jd_from_display_epoch
from skvo_veb.utils.my_tools import safe_float, sanitize_filename

logger = logging.getLogger(__name__)

INTERVALS_DAT_EXTENSION = "dat"
LC_EXPORT_SUFFIX = "_lc"
LC_EXPORT_FALLBACK_STEM = "lightcurve_lc"
DETRENDED_EXPORT_SUFFIX = "_detrended"
DETRENDED_EXPORT_FALLBACK_STEM = "lightcurve_detrended"
INTERVALS_EXPORT_SUFFIX = "_int"
INTERVALS_EXPORT_FALLBACK_STEM = "lightcurve_int"
ROUGH_TOMS_EXPORT_SUFFIX = "_rough_toms"
ROUGH_TOMS_EXPORT_FALLBACK_STEM = "lightcurve_rough_toms"


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


def suggested_lc_export_stem(filename: str | None) -> str:
    """Builds the shared light-curve export stem from an upload file name.

    Args:
        filename (str | None): Uploaded light-curve filename.

    Returns:
        str: ``{stem}_lc``, or ``lightcurve_lc`` when no name is available.
        An existing ``_lc`` suffix is not duplicated.
    """
    base = export_stem_from_upload_filename(filename).strip()
    if not base:
        return LC_EXPORT_FALLBACK_STEM
    if base.lower().endswith(LC_EXPORT_SUFFIX):
        return base
    return f"{base}{LC_EXPORT_SUFFIX}"


def _stem_from_lc_field(stem: str | None, suffix: str, fallback: str) -> str:
    """Strips a trailing ``_lc`` and applies an export suffix.

    Args:
        stem (str | None): Working-curve stem, typically ending in ``_lc``.
        suffix (str): Product suffix, including the leading underscore.
        fallback (str): Stem used when the field is empty.

    Returns:
        str: ``{base}{suffix}``, without a duplicated suffix.
    """
    base = (stem or "").strip()
    if base.lower().endswith(LC_EXPORT_SUFFIX):
        base = base[: -len(LC_EXPORT_SUFFIX)]
    if not base:
        return fallback
    if base.lower().endswith(suffix):
        return base
    return f"{base}{suffix}"


def suggested_detrended_export_stem(stem: str | None) -> str:
    """Builds the detrended export stem from the shared ``_lc`` field.

    Args:
        stem (str | None): Working-curve stem, typically ending in ``_lc``.

    Returns:
        str: ``{base}_detrended``, without a duplicated ``_lc`` or suffix.
    """
    return _stem_from_lc_field(
        stem, DETRENDED_EXPORT_SUFFIX, DETRENDED_EXPORT_FALLBACK_STEM
    )


def suggested_intervals_export_stem(stem: str | None) -> str:
    """Builds the intervals export stem from the shared ``_lc`` field.

    Args:
        stem (str | None): Working-curve stem, typically ending in ``_lc``.

    Returns:
        str: ``{base}_int``, without a duplicated ``_lc`` or suffix.
    """
    return _stem_from_lc_field(
        stem, INTERVALS_EXPORT_SUFFIX, INTERVALS_EXPORT_FALLBACK_STEM
    )


def suggested_rough_toms_export_stem(stem: str | None) -> str:
    """Builds the rough-timing export stem from the shared ``_lc`` field.

    Args:
        stem (str | None): Working-curve stem, typically ending in ``_lc``.

    Returns:
        str: ``{base}_rough_toms``, without a duplicated ``_lc`` or suffix.
    """
    return _stem_from_lc_field(
        stem, ROUGH_TOMS_EXPORT_SUFFIX, ROUGH_TOMS_EXPORT_FALLBACK_STEM
    )


def rough_toms_export_download_name(stem: str | None) -> str:
    """Resolves a browser download filename for a rough ToM export.

    Args:
        stem (str | None): User-entered basename (extension omitted in the UI).

    Returns:
        str: Sanitised filename ending in ``.dat`` when the stem has no extension.
    """
    raw = (stem or "").strip() or ROUGH_TOMS_EXPORT_FALLBACK_STEM
    safe = sanitize_filename(raw) or ROUGH_TOMS_EXPORT_FALLBACK_STEM
    if "." in safe:
        return safe
    return f"{safe}.{INTERVALS_DAT_EXTENSION}"


def intervals_export_download_name(stem: str | None) -> str:
    """Resolves a browser download filename for an intervals ``.dat`` export.

    Args:
        stem (str | None): User-entered basename (extension omitted in the UI).

    Returns:
        str: Sanitised filename ending in ``.dat`` when the stem has no extension.
    """
    raw = (stem or "").strip() or "intervals_export"
    safe = sanitize_filename(raw) or "intervals_export"
    if "." in safe:
        return safe
    return f"{safe}.{INTERVALS_DAT_EXTENSION}"


def lc_export_download_name(stem: str | None, table_format: str) -> str:
    """Resolves a browser download filename for a light-curve export.

    Args:
        stem (str | None): User-entered basename or full filename.
        table_format (str): Export format identifier from ``EXPORT_FORMAT_OPTIONS``.

    Returns:
        str: Sanitised filename with extension when the stem has none.
    """
    raw = (stem or "lightcurve").strip()
    safe = sanitize_filename(raw)
    if "." in safe:
        return safe
    ext = export_file_extension(table_format)
    return f"{safe}.{ext}"


def apply_export_ephemeris(
    lcd,
    period,
    epoch_display,
    *,
    display_epoch: float = DEFAULT_EPOCH_JD,
):
    """Writes sidebar P / Epoch onto a ``CurveDash`` before export.

    User-entered values win over ingest-time metadata. Empty widgets leave
    the existing values.

    Args:
        lcd: ``CurveDash`` instance.
        period: Sidebar period in days, or empty.
        epoch_display: Sidebar epoch as MJD offset (``JD - display_epoch``),
            or empty.
        display_epoch (float): Same offset as the plot Epoch field.

    Returns:
        CurveDash: The same instance, mutated in place.
    """
    period_val = safe_float(period)
    if period_val is not None and period_val > 0:
        lcd.period = period_val
        lcd.period_unit = "d"
        logger.debug("Export period set from sidebar: %s d", period_val)

    epoch_abs = absolute_jd_from_display_epoch(epoch_display, display_epoch)
    if epoch_abs is not None:
        lcd.epoch = epoch_abs
        logger.debug("Export epoch set from sidebar: JD %s", epoch_abs)
    return lcd
