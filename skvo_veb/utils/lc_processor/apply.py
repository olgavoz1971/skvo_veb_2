"""Apply-smooth helpers: widget checks, knot grid, and overlay payload."""

from __future__ import annotations

import logging

import numpy as np

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_processor.smooth import (
    apply_smooth_method,
    build_lsq_knot_grid,
    p_spline_interior_knots,
    resolve_break_tolerance,
)
from skvo_veb.utils.lc_processor.view import (
    crop_curvedash_copy,
    display_mjd_to_absolute_jd,
    raw_labels,
)

logger = logging.getLogger(__name__)

SMOOTH_BLOB = "smooth"


def required_float(value, name: str) -> float:
    """Parses a required numeric widget.

    Args:
        value: Widget contents.
        name (str): Field name for the error.

    Returns:
        float: Parsed number.

    Raises:
        ValueError: If the field is empty or not finite.
    """
    if value is None or value == "":
        raise ValueError(f"{name} is required.")
    number = float(value)
    if not np.isfinite(number):
        raise ValueError(f"{name} must be a finite number.")
    return number


def required_int(value, name: str) -> int:
    """Parses a required integer widget.

    Args:
        value: Widget contents.
        name (str): Field name for the error.

    Returns:
        int: Parsed integer.

    Raises:
        ValueError: If the field is empty.
    """
    if value is None or value == "":
        raise ValueError(f"{name} is required.")
    return int(value)


def optional_float(value) -> float | None:
    """Parses an optional numeric widget.

    Args:
        value: Widget contents.

    Returns:
        float | None: Parsed number, or ``None`` when empty.
    """
    if value is None or value == "":
        return None
    return float(value)


def pack_smooth_payload(
    *,
    times: np.ndarray,
    trend: np.ndarray,
    domain: str,
    method: str,
    knots: list[float],
) -> dict:
    """Builds the session-cache overlay payload (no residual).

    Args:
        times (numpy.ndarray): Fitted absolute JD.
        trend (numpy.ndarray): ``T(t_i)``.
        domain (str): Working photometric domain.
        method (str): Smooth method id.
        knots (list[float]): Knots drawn on the plot.

    Returns:
        dict: JSON-safe overlay.
    """
    return {
        "jd": np.asarray(times, dtype=float).tolist(),
        "trend": np.asarray(trend, dtype=float).tolist(),
        "domain": domain,
        "method": method,
        "knots": [float(k) for k in knots],
    }


def overlay_trend(
    payload: dict | None,
    times: np.ndarray,
    *,
    domain: str,
    method: str,
) -> np.ndarray | None:
    """Returns the cached trend when it matches the current series.

    Args:
        payload (dict | None): Smooth overlay from the session cache.
        times (numpy.ndarray): Current (cropped) absolute JD.
        domain (str): Working domain.
        method (str): Active method id.

    Returns:
        numpy.ndarray | None: Trend, or ``None`` when unused.
    """
    if not payload:
        return None
    if payload.get("domain") != domain or payload.get("method") != method:
        return None
    trend = np.asarray(payload["trend"], dtype=float)
    if trend.size != int(np.asarray(times).size):
        return None
    return trend


def cropped_series(
    lcd: CurveDash,
    t_min,
    t_max,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray, np.ndarray]:
    """Returns cropped arrays for a fit or knot grid.

    Args:
        lcd (CurveDash): Cached working curve.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).

    Returns:
        tuple: ``(jd, y, err, perm_index, labels)``.
    """
    view = crop_curvedash_copy(
        lcd,
        display_mjd_to_absolute_jd(t_min),
        display_mjd_to_absolute_jd(t_max),
    )
    if view.jd is None or view.phot is None:
        raise ValueError("No photometry is loaded.")
    times = np.asarray(view.jd, dtype=float)
    values = np.asarray(view.phot, dtype=float)
    err = None if view.phot_err is None else np.asarray(view.phot_err, dtype=float)
    perm = np.asarray(view.perm_index, dtype=int)
    labels = raw_labels(view)
    return times, values, err, perm, labels


def place_knot_grid(
    times: np.ndarray,
    *,
    method: str,
    split_gaps: bool,
    break_tol,
    n_knots,
    knot_grid_mode: str,
    n_segments,
) -> tuple[list[float], int]:
    """Builds the LSQ or P-spline knot grid without fitting.

    Args:
        times (numpy.ndarray): Absolute JD.
        method (str): ``spline_lsq`` or ``pspline``.
        split_gaps (bool): Split-on-gaps switch.
        break_tol: Break tolerance widget.
        n_knots: LSQ knot-count widget.
        knot_grid_mode (str): ``uniform`` or ``occupancy``.
        n_segments: P-spline segment widget.

    Returns:
        tuple: Placed knots and the requested count.

    Raises:
        ValueError: If the method cannot place knots or a widget is empty.
    """
    gap = resolve_break_tolerance(bool(split_gaps), required_float(break_tol, "Break tolerance"))
    if method == "pspline":
        requested = required_int(n_segments, "Segments")
        placed = p_spline_interior_knots(times, requested).tolist()
        return placed, requested
    if method != "spline_lsq":
        raise ValueError("Place knots applies to the least-squares spline or P-spline.")
    if knot_grid_mode not in ("uniform", "occupancy"):
        raise ValueError("Knot grid must be Uniform or By occupancy.")
    requested = required_int(n_knots, "Interior knots")
    placed = build_lsq_knot_grid(
        times,
        requested,
        mode=knot_grid_mode,
        break_tolerance=gap,
    ).tolist()
    return placed, requested


def fit_smooth_overlay(
    lcd: CurveDash,
    *,
    method: str,
    domain: str,
    split_gaps: bool,
    break_tol,
    t_min,
    t_max,
    median_window,
    n_points,
    n_points_biweight,
    polyorder,
    smooth_rel,
    smooth_s,
    knots: list[float],
    n_knots,
    knot_grid_mode: str,
    penalty_lambda,
    n_segments,
) -> dict:
    """Fits the selected smoother on the cropped working curve.

    LSQ with an empty knot list fails: Place knots first.

    Args:
        lcd (CurveDash): Cached working curve.
        method (str): Method id.
        domain (str): Working domain (must match ``lcd``).
        split_gaps (bool): Gap-split switch.
        break_tol: Break-tolerance widget.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).
        median_window: Median window (days).
        n_points: SG / Lightkurve window.
        n_points_biweight: Biweight window.
        polyorder: Polynomial order.
        smooth_rel: Relative smoothing ``s``.
        smooth_s: Explicit smoothing ``s``.
        knots (list[float]): Current LSQ knots.
        n_knots: LSQ knot-count widget (unused once knots exist).
        knot_grid_mode (str): Grid mode (unused once knots exist).
        penalty_lambda: P-spline lambda.
        n_segments: P-spline segments.

    Returns:
        dict: Overlay payload for the session cache.

    Raises:
        ValueError: If a required widget is empty or the fit cannot run.
    """
    del n_knots, knot_grid_mode
    times, values, err, _perm, _labels = cropped_series(lcd, t_min, t_max)
    gap = resolve_break_tolerance(bool(split_gaps), required_float(break_tol, "Break tolerance"))
    use_knots = [float(k) for k in knots]
    if method == "spline_lsq" and not use_knots:
        raise ValueError("Place knots first.")

    if method == "biweight":
        point_window = required_int(n_points_biweight, "Window (points)")
    elif method in ("savgol", "lightkurve"):
        point_window = required_int(n_points, "Window (points)")
    else:
        point_window = 3

    display_knots = use_knots
    if method == "pspline":
        display_knots = p_spline_interior_knots(
            times, required_int(n_segments, "Segments")
        ).tolist()
    elif method != "spline_lsq":
        display_knots = []

    median_days = (
        required_float(median_window, "Median window") if method == "median" else 1.0
    )
    poly = (
        required_int(polyorder, "Polynomial order")
        if method in ("savgol", "lightkurve")
        else 1
    )
    rel = (
        required_float(smooth_rel, "Smoothing (relative)")
        if method == "spline_smooth"
        else 0.0
    )
    lam = (
        required_float(penalty_lambda, "Penalty lambda")
        if method == "pspline"
        else 0.0
    )
    nseg = required_int(n_segments, "Segments") if method == "pspline" else 1

    trend = apply_smooth_method(
        times,
        values,
        err,
        method=method,
        break_tolerance=gap,
        median_window_days=median_days,
        n_points=point_window,
        polyorder=poly,
        smoothing_s=optional_float(smooth_s),
        smoothing_rel=rel,
        knots=np.asarray(use_knots, dtype=float),
        penalty_lambda=lam,
        n_segments=nseg,
    )
    return pack_smooth_payload(
        times=times,
        trend=trend,
        domain=lcd.active_domain or domain,
        method=method,
        knots=display_knots,
    )
