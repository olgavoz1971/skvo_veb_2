"""Apply-smooth and Apply-detrend helpers: widgets, overlay, and residual."""

from __future__ import annotations

import logging

import numpy as np

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_processor.config import (
    DEFAULT_RP_MIN_POINTS,
    DEFAULT_RP_STEP_DAYS,
    DEFAULT_RP_WINDOW_DAYS,
)
from skvo_veb.utils.lc_processor.smooth import (
    apply_smooth_method,
    build_lsq_knot_grid,
    detrend_observed,
    detrended_standard_error,
    fill_detrend_trend,
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
DETREND_BLOB = "detrend"


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
    break_tolerance: float | None = None,
    window_width_d: float | None = None,
    params: dict | None = None,
) -> dict:
    """Builds the session-cache overlay payload (no residual).

    Args:
        times (numpy.ndarray): Fitted absolute JD.
        trend (numpy.ndarray): ``T(t_i)``; non-finite samples become ``None``.
        domain (str): Working photometric domain.
        method (str): Smooth method id.
        knots (list[float]): Knots drawn on the plot.
        break_tolerance (float | None): Gap used for the fit, in days.
        window_width_d (float | None): Running-parabola window (days).
        params (dict | None): Applied method knobs for product-file comments.

    Returns:
        dict: JSON-safe overlay.
    """
    trend_arr = np.asarray(trend, dtype=float)
    return {
        "jd": np.asarray(times, dtype=float).tolist(),
        "trend": [None if not np.isfinite(v) else float(v) for v in trend_arr],
        "domain": domain,
        "method": method,
        "knots": [float(k) for k in knots],
        "break_tolerance": break_tolerance,
        "window_width_d": window_width_d,
        "params": {} if params is None else dict(params),
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
    rp_window=None,
    rp_step=None,
    rp_min_points=None,
    rp_use_weights=False,
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
        rp_window: Running-parabola window (days).
        rp_step: Running-parabola centre step (days).
        rp_min_points: Minimum in-window points.
        rp_use_weights: Inverse-variance switch.

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
    if method == "running_parabola":
        rp_window_days = required_float(rp_window, "Window")
        rp_step_days = required_float(rp_step, "Step")
        rp_n_min = required_int(rp_min_points, "Minimum points")
        if rp_window_days <= 0:
            raise ValueError("Window must be a positive number of days.")
        if rp_step_days <= 0:
            raise ValueError("Step must be a positive number of days.")
        if rp_n_min < 3:
            raise ValueError("Minimum points must be at least 3.")
    else:
        rp_window_days = DEFAULT_RP_WINDOW_DAYS
        rp_step_days = DEFAULT_RP_STEP_DAYS
        rp_n_min = DEFAULT_RP_MIN_POINTS

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
        rp_window_days=rp_window_days,
        rp_step_days=rp_step_days,
        rp_min_points=rp_n_min,
        rp_use_weights=bool(rp_use_weights),
    )
    params: dict = {
        "domain": lcd.active_domain or domain,
        "break_tolerance_d": gap,
    }
    if method == "median":
        params["window_days"] = float(median_days)
    elif method == "biweight":
        params["n_points"] = int(point_window)
    elif method in ("savgol", "lightkurve"):
        params["n_points"] = int(point_window)
        params["polyorder"] = int(poly)
    elif method == "spline_smooth":
        params["smoothing_rel"] = float(rel)
        explicit_s = optional_float(smooth_s)
        if explicit_s is not None:
            params["smoothing_s"] = float(explicit_s)
    elif method == "spline_lsq":
        params["n_knots"] = int(len(use_knots))
    elif method == "pspline":
        params["penalty_lambda"] = float(lam)
        params["n_segments"] = int(nseg)
    elif method == "running_parabola":
        params["window_days"] = float(rp_window_days)
        params["step_days"] = float(rp_step_days)
        params["min_points"] = int(rp_n_min)
        params["use_weights"] = bool(rp_use_weights)
    return pack_smooth_payload(
        times=times,
        trend=trend,
        domain=lcd.active_domain or domain,
        method=method,
        knots=display_knots,
        break_tolerance=gap,
        window_width_d=(
            rp_window_days if method == "running_parabola" else None
        ),
        params=params,
    )


DETREND_ORIGIN_SMOOTH = "smooth"
DETREND_ORIGIN_COPY = "copy"
_DETREND_ORIGINS = frozenset({DETREND_ORIGIN_SMOOTH, DETREND_ORIGIN_COPY})


def pack_detrend_payload(
    *,
    times: np.ndarray,
    residual: np.ndarray,
    residual_err: np.ndarray | None,
    domain: str,
    method: str,
    fill: dict[str, int] | None = None,
    origin: str = DETREND_ORIGIN_SMOOTH,
    tilts: list | None = None,
) -> dict:
    """Builds the session-cache residual payload.

    Non-finite residual samples are stored as ``None``.

    Args:
        times (numpy.ndarray): Absolute JD of the residual.
        residual (numpy.ndarray): Detrended photometry.
        residual_err (numpy.ndarray | None): Residual uncertainties.
        domain (str): Working photometric domain.
        method (str): Smooth method that produced the trend, or ``copy``.
        fill (dict | None): Hole-fill counts from ``fill_detrend_trend``.
        origin (str): ``smooth`` (Apply detrend) or ``copy`` (plot 1).
        tilts (list | None): Applied local-tilt records.

    Returns:
        dict: JSON-safe residual.

    Raises:
        ValueError: If ``origin`` is not ``smooth`` or ``copy``.
    """
    if origin not in _DETREND_ORIGINS:
        raise ValueError(f"origin must be 'smooth' or 'copy', got {origin!r}")
    res_arr = np.asarray(residual, dtype=float)
    payload = {
        "jd": np.asarray(times, dtype=float).tolist(),
        "residual": [None if not np.isfinite(v) else float(v) for v in res_arr],
        "domain": domain,
        "method": method,
        "origin": origin,
        "tilts": list(tilts or []),
        "fill": dict(fill or {"nearest": 0, "interp": 0, "median": 0}),
    }
    if residual_err is None:
        payload["residual_err"] = None
    else:
        err_arr = np.asarray(residual_err, dtype=float)
        payload["residual_err"] = [
            None if not np.isfinite(v) else float(v) for v in err_arr
        ]
    return payload


def overlay_residual(
    payload: dict | None,
    times: np.ndarray,
    *,
    domain: str,
) -> tuple[np.ndarray, np.ndarray | None] | None:
    """Returns the cached residual when it matches the current series.

    Args:
        payload (dict | None): Detrend blob from the session cache.
        times (numpy.ndarray): Current (cropped) absolute JD.
        domain (str): Working domain.

    Returns:
        tuple | None: ``(residual, residual_err)``, or ``None`` when unused.
    """
    if not payload:
        return None
    if payload.get("domain") != domain:
        return None
    residual = np.asarray(payload.get("residual"), dtype=float)
    if residual.size != int(np.asarray(times).size):
        return None
    raw_err = payload.get("residual_err")
    err = None if raw_err is None else np.asarray(raw_err, dtype=float)
    return residual, err


def apply_detrend_from_smooth(
    lcd: CurveDash,
    smooth_payload: dict | None,
    *,
    method: str,
    domain: str,
    t_min,
    t_max,
) -> dict:
    """Builds the residual from the last smooth overlay (screen domain).

    Magnitude subtracts the trend. Flux divides by the trend. Missing
    overlay samples are filled inside each gap-split piece (nearest
    finite ``T``, a short interpolant of ``T``, or the piece median) so
    every point in the series is kept.

    Args:
        lcd (CurveDash): Cached working curve.
        smooth_payload (dict | None): Last Apply-smooth overlay.
        method (str): Active smooth method id.
        domain (str): Working domain (must match the overlay).
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).

    Returns:
        dict: Residual payload for the session cache.

    Raises:
        ValueError: If there is no matching smooth, a flux fill is not
            strictly positive, or the residual is empty.
    """
    times, values, err, _perm, _labels = cropped_series(lcd, t_min, t_max)
    trend = overlay_trend(
        smooth_payload,
        times,
        domain=lcd.active_domain or domain,
        method=method,
    )
    if trend is None:
        raise ValueError("Apply smooth first.")
    mode = lcd.active_domain or domain
    raw_span = None if smooth_payload is None else smooth_payload.get("window_width_d")
    filled, fill = fill_detrend_trend(
        times,
        values,
        trend,
        break_tolerance=(
            None if smooth_payload is None else smooth_payload.get("break_tolerance")
        ),
        max_interp_span=None if raw_span is None else float(raw_span),
    )
    n_fill = int(fill["nearest"] + fill["interp"] + fill["median"])
    if n_fill:
        logger.info(
            "Detrend filled %s of %s point(s) (nearest=%s, interp=%s, median=%s)",
            n_fill,
            filled.size,
            fill["nearest"],
            fill["interp"],
            fill["median"],
        )
    residual = detrend_observed(values, filled, mode)
    if not np.any(np.isfinite(residual)):
        raise ValueError("Detrend produced no finite residual points.")
    if int(np.count_nonzero(~np.isfinite(residual))):
        raise ValueError("Detrend left non-finite residual points.")
    det_err = None
    if err is not None:
        det_err = detrended_standard_error(values, filled, err, mode)
    return pack_detrend_payload(
        times=times,
        residual=residual,
        residual_err=det_err,
        domain=mode,
        method=method,
        fill=fill,
    )
