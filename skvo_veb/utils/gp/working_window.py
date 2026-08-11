"""Prep-step working time window (subset of light curve for fold and interval pick)."""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np

from skvo_veb.utils.lc_bridge import get_jd_limits
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
        store_data: ``store-gp-prep-working-window`` payload.

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
    """Maps a normalised window dict to ``(jd_min, jd_max)`` for phase clipping.

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
        time_axis_mode (str): Active prep plot time axis.
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
    """Resolves the current prep plot zoom to absolute JD limits.

    Args:
        relayout_data: ``prep-graph`` ``relayoutData``.
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


def count_observations_in_jd_window(
    lc_json_string: str,
    jd_min: float,
    jd_max: float,
) -> int:
    """Counts transport rows whose absolute JD lies in the closed window.

    Args:
        lc_json_string: Serialised light curve transport JSON.
        jd_min (float): Window start (absolute JD).
        jd_max (float): Window end (absolute JD).

    Returns:
        int: Number of finite time samples inside the window.
    """
    packet = json.loads(lc_json_string)
    jd0 = float(packet.get("meta", {}).get("jd0") or 0.0)
    lo, hi = sorted((float(jd_min), float(jd_max)))
    count = 0
    for row in packet.get("data") or []:
        t = float(row[0])
        if not np.isfinite(t):
            continue
        jd_abs = t + jd0
        if lo <= jd_abs <= hi:
            count += 1
    return count


def build_working_window_store(
    jd_min: float,
    jd_max: float,
    lc_json_string: str,
) -> dict[str, Any]:
    """Validates and serialises an enabled working window for ``dcc.Store``.

    Args:
        jd_min (float): Window start (absolute JD).
        jd_max (float): Window end (absolute JD).
        lc_json_string: Full light curve transport (unchanged in store).

    Returns:
        dict: ``{enabled, jd_min, jd_max}``.

    Raises:
        PipeException: If the window is empty or contains no observations.
    """
    lo, hi = sorted((float(jd_min), float(jd_max)))
    if hi <= lo:
        raise PipeException("The visible time range is empty.")
    n = count_observations_in_jd_window(lc_json_string, lo, hi)
    if n == 0:
        raise PipeException(
            "The visible time range contains no light curve points."
        )
    full_lo, full_hi = get_jd_limits(lc_json_string)
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


def clip_transport_json_to_jd_window(
    lc_json_string: str,
    jd_min: float,
    jd_max: float,
) -> str:
    """Returns transport JSON containing only rows inside the JD window.

    Args:
        lc_json_string: Full serialised light curve transport.
        jd_min (float): Window start (absolute JD).
        jd_max (float): Window end (absolute JD).

    Returns:
        str: New transport JSON with filtered ``data`` rows.

    Raises:
        PipeException: If no finite rows remain in the window.
    """
    packet = json.loads(lc_json_string)
    jd0 = float(packet.get("meta", {}).get("jd0") or 0.0)
    lo, hi = sorted((float(jd_min), float(jd_max)))
    kept = []
    for row in packet.get("data") or []:
        t_raw = float(row[0])
        if not np.isfinite(t_raw):
            continue
        jd_abs = t_raw + jd0
        if lo <= jd_abs <= hi:
            kept.append(row)
    if not kept:
        raise PipeException(
            "Working time range contains no light curve points to export."
        )
    clipped = dict(packet)
    clipped["data"] = kept
    return json.dumps(clipped)


def transport_json_for_prep_export(
    lc_json_string: str,
    working_window_store: dict | None,
) -> str:
    """Selects full or clipped transport for prep light curve export.

    Args:
        lc_json_string: Canonical prep transport in ``store-lc-data``.
        working_window_store: ``store-gp-prep-working-window`` payload.

    Returns:
        str: Transport JSON to pass to ``curvedash_from_transport_json``.
    """
    window = normalize_working_window(working_window_store)
    if window is None:
        return lc_json_string
    return clip_transport_json_to_jd_window(
        lc_json_string,
        window["jd_min"],
        window["jd_max"],
    )
