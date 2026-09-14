"""GP-only export stems: timing and extrema products.

Shared light-curve stems and download names live in
``skvo_veb.utils.lc_export``.
"""

from __future__ import annotations

from skvo_veb.utils.lc_export import export_stem_from_upload_filename
from skvo_veb.utils.my_tools import sanitize_filename

GP_INTERVALS_EXPORT_EXTENSION = "dat"
GP_INTERVALS_SUFFIX = "_int"
GP_INTERVALS_FALLBACK_STEM = "intervals_int"
GP_EXTREMA_COMPACT_EXTENSION = "dat"
GP_TIMING_SUFFIX = "_gp"
GP_TIMING_FALLBACK_STEM = "results_gp"


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


def gp_suggested_intervals_stem(filename: str | None) -> str:
    """Builds the suggested intervals export stem from a source file name.

    Args:
        filename (str | None): Light-curve or intervals upload filename.

    Returns:
        str: ``{stem}_int``, or ``intervals_int`` when no name is available.
        An existing ``_int`` suffix is not duplicated.
    """
    base = export_stem_from_upload_filename(filename).strip()
    if not base:
        return GP_INTERVALS_FALLBACK_STEM
    if base.lower().endswith(GP_INTERVALS_SUFFIX):
        return base
    return f"{base}{GP_INTERVALS_SUFFIX}"


def gp_extrema_export_stem(stem: str | None) -> str:
    """Normalises the GP extrema export basename from the review filename field.

    Args:
        stem (str | None): User-entered stem or legacy filename with extension.

    Returns:
        str: Sanitised basename without ``.dat``.
    """
    raw = (stem or GP_TIMING_FALLBACK_STEM).strip() or GP_TIMING_FALLBACK_STEM
    safe = sanitize_filename(raw) or GP_TIMING_FALLBACK_STEM
    suffix = f".{GP_EXTREMA_COMPACT_EXTENSION}"
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
