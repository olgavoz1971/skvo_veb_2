"""MAVKA extrema timing compact ``.dat`` export."""

from __future__ import annotations

from skvo_veb.utils.lc_working_window import format_max_half_width_comment
from skvo_veb.utils.mavka.config import DEFAULT_METHOD
from skvo_veb.utils.my_tools import PipeException, sanitize_filename

MAVKA_EXTREMA_COMPACT_EXTENSION = "dat"
MAVKA_TIMING_FALLBACK_PREFIX = "results"


def mavka_extrema_export_stem(stem: str | None) -> str:
    """Normalises the MAVKA extrema export basename from the review filename field.

    Args:
        stem (str | None): User-entered stem or legacy filename with extension.

    Returns:
        str: Sanitised basename without ``.dat``.
    """
    raw = (stem or "results_mavka").strip() or "results_mavka"
    safe = sanitize_filename(raw) or "results_mavka"
    suffix = f".{MAVKA_EXTREMA_COMPACT_EXTENSION}"
    if safe.lower().endswith(suffix):
        safe = safe[: -len(suffix)]
    return safe or "results_mavka"


def mavka_suggested_timing_stem(
    lc_filename: str | None,
    method: str | None,
) -> str:
    """Builds the suggested MAVKA timing export stem from LC name and method.

    Args:
        lc_filename (str | None): Uploaded light-curve filename.
        method (str | None): Approximation id (``WSAP``, ``WSL``, ``AP``, ``A``).

    Returns:
        str: ``{lc_stem}_{method}``, or ``results_{method}`` when no LC name
        is available.
    """
    tag = str(method or "").strip() or DEFAULT_METHOD
    safe_tag = sanitize_filename(tag) or DEFAULT_METHOD
    if not lc_filename:
        return f"{MAVKA_TIMING_FALLBACK_PREFIX}_{safe_tag}"
    base = lc_filename.rsplit(".", 1)[0].strip()
    if not base:
        return f"{MAVKA_TIMING_FALLBACK_PREFIX}_{safe_tag}"
    suffix = f"_{safe_tag}"
    if base.lower().endswith(suffix.lower()):
        return base
    return f"{base}{suffix}"


def mavka_compact_extrema_download_name(stem: str | None) -> str:
    """Resolves the compact MAVKA extrema ``.dat`` download filename.

    Args:
        stem (str | None): User-entered export stem.

    Returns:
        str: Sanitised ``*.dat`` filename.
    """
    return f"{mavka_extrema_export_stem(stem)}.{MAVKA_EXTREMA_COMPACT_EXTENSION}"


def format_compact_extrema_dat(
    rows: list[dict],
    include_flags: list[bool],
    *,
    extrema_mode: str,
    period: str | None = None,
    epoch: str | None = None,
    method: str | None = None,
    max_half_width_d: float | None = None,
) -> str:
    """Formats the compact extrema timing file (selected successes only).

    Args:
        rows (list[dict]): Slim rows from ``store-mavka-results-data``.
        include_flags (list[bool]): Per-row include flags.
        extrema_mode (str): ``min`` or ``max`` from the MAVKA sidebar.
        period (str | None): Folding period from accordion 1 (comment only).
        epoch (str | None): Display epoch from accordion 1 (comment only).
        method (str | None): Approximation id written next to the MAVKA header.
        max_half_width_d (float | None): Optional half-width cap used for this run.

    Returns:
        str: ``.dat`` file body.

    Raises:
        PipeException: If a selected success row has no TOM.
    """
    mode_label = "Minimum" if extrema_mode == "min" else "Maximum"
    lines = [
        f"# MAVKA {mode_label} Results\n",
    ]
    method_tag = str(method or "").strip()
    if method_tag:
        lines.append(f"# method: {method_tag}\n")
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
                    "Selected MAVKA result is missing TOM (jd_peak)."
                )
            jd_std = row.get("jd_peak_std")
            std_txt = "" if jd_std is None else f"{float(jd_std):.6f}"
            lines.append(f"{float(jd_peak):.6f}\t{std_txt}\n")
    return "".join(lines)
