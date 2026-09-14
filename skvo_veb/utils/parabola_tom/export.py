"""Parabola ToM compact ``.dat`` export (JD and σ only)."""

from __future__ import annotations

from skvo_veb.utils.lc_export import export_stem_from_upload_filename
from skvo_veb.utils.lc_working_window import format_max_half_width_comment
from skvo_veb.utils.my_tools import PipeException, sanitize_filename

PARABOLA_EXTREMA_COMPACT_EXTENSION = "dat"
PARABOLA_TIMING_SUFFIX = "_parabola"
PARABOLA_TIMING_FALLBACK_STEM = "results_parabola"


def parabola_suggested_timing_stem(lc_filename: str | None) -> str:
    """Builds the suggested parabola timing export stem from a light-curve name.

    Args:
        lc_filename (str | None): Uploaded light-curve filename.

    Returns:
        str: ``{lc_stem}_parabola``, or ``results_parabola`` when no name
        is available.
    """
    base = export_stem_from_upload_filename(lc_filename).strip()
    if not base:
        return PARABOLA_TIMING_FALLBACK_STEM
    if base.lower().endswith(PARABOLA_TIMING_SUFFIX):
        return base
    return f"{base}{PARABOLA_TIMING_SUFFIX}"


def parabola_extrema_export_stem(stem: str | None) -> str:
    """Normalises the parabola extrema export basename from the review field.

    Args:
        stem (str | None): User-entered stem or legacy filename with extension.

    Returns:
        str: Sanitised basename without ``.dat``.
    """
    raw = (stem or PARABOLA_TIMING_FALLBACK_STEM).strip() or PARABOLA_TIMING_FALLBACK_STEM
    safe = sanitize_filename(raw) or PARABOLA_TIMING_FALLBACK_STEM
    if safe.lower().endswith(f".{PARABOLA_EXTREMA_COMPACT_EXTENSION}"):
        safe = safe[: -(len(PARABOLA_EXTREMA_COMPACT_EXTENSION) + 1)]
    return safe or PARABOLA_TIMING_FALLBACK_STEM


def parabola_compact_extrema_download_name(stem: str | None) -> str:
    """Resolves the compact parabola extrema ``.dat`` download filename.

    Args:
        stem (str | None): User-entered export stem.

    Returns:
        str: Sanitised ``*.dat`` filename.
    """
    return f"{parabola_extrema_export_stem(stem)}.{PARABOLA_EXTREMA_COMPACT_EXTENSION}"


def format_compact_extrema_dat(
    rows: list[dict],
    include_flags: list[bool],
    *,
    extrema_mode: str,
    period: str | None = None,
    epoch: str | None = None,
    use_weights: bool | None = None,
    max_half_width_d: float | None = None,
) -> str:
    """Formats the compact extrema timing file (selected successes only).

    Args:
        rows (list[dict]): Slim rows from ``store-parabola-results-data``.
        include_flags (list[bool]): Per-row include flags.
        extrema_mode (str): ``min`` or ``max`` from the Parabola sidebar.
        period (str | None): Folding period from accordion 1 (comment only).
        epoch (str | None): Display epoch from accordion 1 (comment only).
        use_weights (bool | None): Inverse-variance switch used for this run.
        max_half_width_d (float | None): Optional half-width cap used for this run.

    Returns:
        str: ``.dat`` file body.

    Raises:
        PipeException: If a selected success row has no ToM.
    """
    mode_label = "Minimum" if extrema_mode == "min" else "Maximum"
    lines = [
        f"# Parabola {mode_label} Results\n",
    ]
    if use_weights is not None:
        lines.append(f"# weights: {'on' if use_weights else 'off'}\n")
    lines.append(format_max_half_width_comment(max_half_width_d))
    if period:
        lines.append(f"# PERIOD = {period}\n")
    if epoch:
        lines.append(f"# EPOCH = {epoch}\n")
    lines.append(f"# JD_{mode_label}\tJD_Std\n")
    for is_selected, row in zip(include_flags, rows, strict=True):
        if is_selected and not row.get("is_fail"):
            jd_peak = row.get("jd_peak")
            if jd_peak is None:
                raise PipeException(
                    "Selected parabola result is missing ToM (jd_peak)."
                )
            jd_std = row.get("jd_peak_std")
            std_txt = "" if jd_std is None else f"{float(jd_std):.6f}"
            lines.append(f"{float(jd_peak):.6f}\t{std_txt}\n")
    return "".join(lines)
