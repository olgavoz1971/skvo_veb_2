"""GP prep sidebar light curve download helpers."""

from __future__ import annotations

from skvo_veb.utils.lc_bridge import export_file_extension
from skvo_veb.utils.my_tools import sanitize_filename


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
