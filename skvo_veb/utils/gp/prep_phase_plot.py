"""Extended phase-axis prep plot and folded interval selection (GP O-C page)."""

from __future__ import annotations

import numpy as np

from skvo_veb.utils.my_tools import PipeException

EXTENDED_PHASE_XMIN = -0.5
EXTENDED_PHASE_XMAX = 1.5
MAX_PHASE_SELECTION_WIDTH = 1.0
_PHASE_AXIS_EPS = 1e-9


def validate_extended_phase_selection(phi_min: float, phi_max: float) -> tuple[float, float]:
    """Checks a box selection on the extended phase prep plot before JD conversion.

    Args:
        phi_min (float): Lower x bound from Plotly ``selectedData.range``.
        phi_max (float): Upper x bound.

    Returns:
        tuple[float, float]: Ordered ``(phi_min, phi_max)`` on the extended axis.

    Raises:
        PipeException: When the range is inverted, too wide, or outside the plot axis.
    """
    lo = float(min(phi_min, phi_max))
    hi = float(max(phi_min, phi_max))
    width = hi - lo
    if width <= 0:
        raise PipeException(
            "Invalid phase selection: the box has zero width. Drag a horizontal range "
            "on the folded light curve."
        )
    if width > MAX_PHASE_SELECTION_WIDTH + _PHASE_AXIS_EPS:
        raise PipeException(
            f"Ambiguous phase selection: width {width:.4f} exceeds one period "
            f"({MAX_PHASE_SELECTION_WIDTH}). Narrow the box so it covers a single "
            "feature (max width 1.0 in phase). On the extended axis "
            f"[{EXTENDED_PHASE_XMIN}, {EXTENDED_PHASE_XMAX}], do not span multiple "
            "copies of the curve."
        )
    if lo < EXTENDED_PHASE_XMIN - _PHASE_AXIS_EPS or hi > EXTENDED_PHASE_XMAX + _PHASE_AXIS_EPS:
        raise PipeException(
            f"Phase selection [{lo:.4f}, {hi:.4f}] lies outside the displayed axis "
            f"[{EXTENDED_PHASE_XMIN}, {EXTENDED_PHASE_XMAX}]."
        )
    return lo, hi


def assert_phase_intervals_not_duplicates(
    new_intervals: list,
    existing_intervals: list | None,
) -> None:
    """Rejects adding JD intervals that are already in the registry.

    Args:
        new_intervals (list): ``[[jd_start, jd_end], ...]`` from phase conversion.
        existing_intervals (list, optional): Current registry rows.

    Raises:
        PipeException: When there are no new cycles or any cycle duplicates a row.
    """
    if not new_intervals:
        raise PipeException(
            "No observations fall in the selected phase window. "
            "Check period, epoch, and the box position."
        )
    existing = existing_intervals or []
    existing_set = {tuple(row) for row in existing}
    duplicates = [row for row in new_intervals if tuple(row) in existing_set]
    if duplicates:
        raise PipeException(
            "These JD intervals are already registered (same phase window applied "
            f"to {len(duplicates)} cycle(s)). Remove them from the list first or "
            "choose a different phase range."
        )


def build_extended_phase_plot_arrays(
    x_jd: np.ndarray,
    y,
    err,
    t0_abs: float,
    period: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Builds triple-stripe phase coordinates for prep-plot display only.

    Each point appears at ``phi``, ``phi - 1``, and ``phi + 1`` when that copy lies
    within ``[EXTENDED_PHASE_XMIN, EXTENDED_PHASE_XMAX]``.

    Args:
        x_jd (numpy.ndarray): Absolute Julian dates.
        y: Photometry values (same length as ``x_jd``).
        err: Per-point errors or None.
        t0_abs (float): Folding epoch (absolute JD).
        period (float): Fold period in days.

    Returns:
        tuple: ``(x_phase, y, err)`` concatenated for Scattergl (err may be None).
    """
    x_jd = np.asarray(x_jd, dtype=float)
    y_arr = np.asarray(y)
    err_arr = None if err is None else np.asarray(err)
    phi = ((x_jd - t0_abs) / period) % 1.0

    x_parts: list[np.ndarray] = []
    y_parts: list[np.ndarray] = []
    e_parts: list[np.ndarray] = []

    for offset in (-1.0, 0.0, 1.0):
        x_copy = phi + offset
        mask = (x_copy >= EXTENDED_PHASE_XMIN - _PHASE_AXIS_EPS) & (
            x_copy <= EXTENDED_PHASE_XMAX + _PHASE_AXIS_EPS
        )
        if not np.any(mask):
            continue
        x_parts.append(x_copy[mask])
        y_parts.append(y_arr[mask])
        if err_arr is not None:
            e_parts.append(err_arr[mask])

    if not x_parts:
        return np.array([]), np.array([]), None

    x_out = np.concatenate(x_parts)
    y_out = np.concatenate(y_parts)
    err_out = np.concatenate(e_parts) if e_parts else None
    return x_out, y_out, err_out


def phase_vrect_bounds_extended(
    jd_min: float,
    jd_max: float,
    epoch_jd: float,
    period: float,
) -> list[tuple[float, float]]:
    """Maps a JD interval to vrect bounds on the extended phase prep axis.

    Args:
        jd_min (float): Interval start (absolute JD).
        jd_max (float): Interval end (absolute JD).
        epoch_jd (float): Folding epoch (absolute JD).
        period (float): Period in days.

    Returns:
        list[tuple[float, float]]: ``(x0, x1)`` segments on ``[-0.5, 1.5]``.
    """
    if period <= 0 or not np.isfinite(period):
        return []
    start = float(min(jd_min, jd_max))
    end = float(max(jd_min, jd_max))
    if end <= start:
        return []

    canonical = _canonical_phase_segments(start, end, epoch_jd, period)
    extended: list[tuple[float, float]] = []
    for phi0, phi1 in canonical:
        for offset in (-1.0, 0.0, 1.0):
            x0, x1 = phi0 + offset, phi1 + offset
            clip_lo = max(x0, EXTENDED_PHASE_XMIN)
            clip_hi = min(x1, EXTENDED_PHASE_XMAX)
            if clip_hi > clip_lo + _PHASE_AXIS_EPS:
                extended.append((clip_lo, clip_hi))
    return extended


def _canonical_phase_segments(
    start_jd: float,
    end_jd: float,
    epoch_jd: float,
    period: float,
) -> list[tuple[float, float]]:
    """Phase segments on ``[0, 1]`` for one JD interval (same convention as prep plot)."""
    phi0 = ((start_jd - epoch_jd) / period) % 1.0
    phi1 = ((end_jd - epoch_jd) / period) % 1.0
    if (end_jd - start_jd) >= period:
        return [(0.0, 1.0)]
    if phi0 <= phi1:
        return [(phi0, phi1)]
    return [(phi0, 1.0), (0.0, phi1)]
