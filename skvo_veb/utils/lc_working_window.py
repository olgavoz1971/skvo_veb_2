"""Working time window on an absolute-JD sample array.

Shared by the Lightcurve processor (plot 2) and GP prep. Transport-JSON
wrappers stay in ``skvo_veb.utils.gp.working_window``.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from skvo_veb.utils.lc_interaction import (
    extract_display_x_range_from_relayout,
    plot_x_to_jd,
)
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

WORKING_WINDOW_DISABLED: dict[str, Any] = {"enabled": False}


def normalize_working_window(store_data: dict | None) -> dict | None:
    """Returns active JD bounds when subset mode is on.

    Args:
        store_data: Working-window store payload.

    Returns:
        dict or None: ``{jd_min, jd_max}`` when enabled, else ``None``.
    """
    if not store_data or not store_data.get("enabled"):
        return None
    jd_min = store_data.get("jd_min")
    jd_max = store_data.get("jd_max")
    if jd_min is None or jd_max is None:
        return None
    lo, hi = sorted((float(jd_min), float(jd_max)))
    if hi <= lo:
        return None
    return {"jd_min": lo, "jd_max": hi}


def observation_jd_bounds_tuple(window: dict | None) -> tuple[float, float] | None:
    """Maps a normalised window dict to ``(jd_min, jd_max)``.

    Args:
        window: Result of ``normalize_working_window``.

    Returns:
        tuple or None: Sorted absolute JD ends.
    """
    if window is None:
        return None
    return (window["jd_min"], window["jd_max"])


def display_x_range_to_jd_bounds(
    x_range: tuple,
    time_axis_mode: str,
    display_epoch: float,
) -> tuple[float, float]:
    """Converts a plot x-axis window to absolute Julian Date limits.

    Args:
        x_range: ``(x_min, x_max)`` from relayout or zoom state.
        time_axis_mode (str): Active plot time axis.
        display_epoch (float): MJD reference epoch.

    Returns:
        tuple[float, float]: Sorted ``(jd_min, jd_max)``.

    Raises:
        ValueError: If coordinates cannot be parsed.
    """
    left_jd = plot_x_to_jd(x_range[0], time_axis_mode, display_epoch)
    right_jd = plot_x_to_jd(x_range[1], time_axis_mode, display_epoch)
    return tuple(sorted((left_jd, right_jd)))


def jd_bounds_from_visible_plot(
    relayout_data: dict | None,
    *,
    time_axis_mode: str,
    display_epoch: float,
) -> tuple[float, float]:
    """Resolves the current plot zoom to absolute JD limits.

    Args:
        relayout_data: Graph ``relayoutData``.
        time_axis_mode (str): Active time axis mode.
        display_epoch (float): MJD display epoch.

    Returns:
        tuple[float, float]: Sorted JD bounds for the visible x-axis.

    Raises:
        PipeException: If the user has not zoomed to a finite x range.
    """
    x_range = extract_display_x_range_from_relayout(relayout_data)
    if x_range is None:
        raise PipeException(
            "Zoom the light curve to the time range you want, then use visible range."
        )
    try:
        return display_x_range_to_jd_bounds(
            x_range, time_axis_mode, display_epoch
        )
    except (TypeError, ValueError) as exc:
        raise PipeException(
            "Could not read the visible time range from the plot."
        ) from exc


def build_working_window_store_from_times(
    jd_min: float,
    jd_max: float,
    times_jd: np.ndarray,
) -> dict[str, Any]:
    """Validates a working window against an absolute-JD sample array.

    Args:
        jd_min (float): Window start (absolute JD).
        jd_max (float): Window end (absolute JD).
        times_jd (numpy.ndarray): Sample times (absolute JD).

    Returns:
        dict: ``{enabled, jd_min, jd_max}``, or disabled when the window
        covers every finite sample.

    Raises:
        PipeException: If the window is empty or contains no samples.
    """
    lo, hi = sorted((float(jd_min), float(jd_max)))
    if hi <= lo:
        raise PipeException("The visible time range is empty.")
    times = np.asarray(times_jd, dtype=float)
    finite = times[np.isfinite(times)]
    if finite.size == 0:
        raise PipeException("The visible time range contains no light curve points.")
    n = int(np.count_nonzero((finite >= lo) & (finite <= hi)))
    if n == 0:
        raise PipeException(
            "The visible time range contains no light curve points."
        )
    full_lo = float(np.min(finite))
    full_hi = float(np.max(finite))
    if lo <= full_lo and hi >= full_hi:
        logger.info("Visible range covers full light curve; keeping full-curve mode.")
        return dict(WORKING_WINDOW_DISABLED)
    return {"enabled": True, "jd_min": lo, "jd_max": hi}


def filter_plot_arrays_by_jd_window(
    x_jd: np.ndarray,
    y_data: np.ndarray,
    err_data: np.ndarray | None,
    jd_min: float,
    jd_max: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Keeps only samples inside the working JD window.

    Args:
        x_jd: Absolute Julian dates per point.
        y_data: Y values aligned with ``x_jd``.
        err_data: Optional errors aligned with ``x_jd``.
        jd_min (float): Window start (absolute JD).
        jd_max (float): Window end (absolute JD).

    Returns:
        tuple: Filtered ``(x_jd, y_data, err_data)``.

    Raises:
        PipeException: If no samples remain after filtering.
    """
    lo, hi = sorted((float(jd_min), float(jd_max)))
    x = np.asarray(x_jd, dtype=float)
    mask = (x >= lo) & (x <= hi) & np.isfinite(x)
    if not np.any(mask):
        raise PipeException(
            "Working time range contains no light curve points."
        )
    y = np.asarray(y_data)[mask]
    err = None
    if err_data is not None:
        err = np.asarray(err_data)[mask]
    return x[mask], y, err


def interval_overlaps_jd_window(
    interval: list[float],
    jd_min: float,
    jd_max: float,
) -> bool:
    """Tests whether an absolute-JD interval intersects the working window.

    Args:
        interval: ``[start_jd, end_jd]``.
        jd_min (float): Working window start.
        jd_max (float): Working window end.

    Returns:
        bool: ``True`` when the interval overlaps the closed window.
    """
    lo, hi = sorted((float(jd_min), float(jd_max)))
    start, end = sorted((float(interval[0]), float(interval[1])))
    return end >= lo and start <= hi


def resolve_max_half_width_d(value) -> float | None:
    """Parses the optional max fit half-width from a sidebar field.

    Args:
        value: Raw input (empty, ``None``, or a number of days).

    Returns:
        float | None: Positive half-width in days, or ``None`` for no cap.

    Raises:
        ValueError: If a value is present but is not a positive finite number.
    """
    if value is None or value == "":
        return None
    try:
        width = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Max half-width must be a positive number of days, or empty for no limit."
        ) from exc
    if not math.isfinite(width) or width <= 0.0:
        raise ValueError(
            "Max half-width must be a positive number of days, or empty for no limit."
        )
    return width


def apply_half_width_cap(
    jd_min: float,
    jd_max: float,
    max_half_width_d: float | None,
) -> tuple[float, float, bool]:
    """Trims a marked interval to ± ``max_half_width_d`` around its midpoint.

    Narrower intervals are left unchanged. ``None`` means no extra limit.

    Args:
        jd_min (float): Marked interval start (absolute JD).
        jd_max (float): Marked interval stop (absolute JD).
        max_half_width_d (float | None): Optional maximum half-width (days).

    Returns:
        tuple: ``(fit_jd_min, fit_jd_max, was_capped)``.

    Raises:
        ValueError: If ``max_half_width_d`` is set but is not positive and finite.
    """
    lo, hi = sorted((float(jd_min), float(jd_max)))
    if max_half_width_d is None:
        return lo, hi, False
    width = resolve_max_half_width_d(max_half_width_d)
    if width is None:
        return lo, hi, False
    half = 0.5 * (hi - lo)
    if half <= width:
        return lo, hi, False
    mid = 0.5 * (lo + hi)
    return mid - width, mid + width, True


def format_max_half_width_comment(max_half_width_d: float | None) -> str:
    """Formats the compact-export comment for the optional half-width cap.

    Args:
        max_half_width_d (float | None): Cap used for the run, or ``None``.

    Returns:
        str: One ``#`` comment line ending in a newline.
    """
    if max_half_width_d is None:
        return "# max_half_width_d: none\n"
    return f"# max_half_width_d: {float(max_half_width_d)}\n"
