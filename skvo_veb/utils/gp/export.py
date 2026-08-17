"""GP prep sidebar download filename helpers."""

from __future__ import annotations

from skvo_veb.utils.lc_bridge import export_file_extension
from skvo_veb.utils.my_tools import sanitize_filename

GP_INTERVALS_EXPORT_EXTENSION = "dat"
GP_EXTREMA_COMPACT_EXTENSION = "dat"
GP_EXTREMA_EXTENDED_SUFFIX = "_gp_extrema"


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
    raw = (stem or "results_extrema").strip() or "results_extrema"
    safe = sanitize_filename(raw) or "results_extrema"
    for suffix in (".dat", ".zip"):
        if safe.lower().endswith(suffix):
            safe = safe[: -len(suffix)]
    return safe or "results_extrema"


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
        str: Sanitised ``*_gp_extrema.zip`` filename.
    """
    base = gp_extrema_export_stem(stem)
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
