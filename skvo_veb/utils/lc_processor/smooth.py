"""Smoothing algorithms for the Lightcurve processor.

Adopted from ``auxiliary/trend/detrend_core.py``. Apply smooth returns a trend
only; residual arithmetic lives in a later Detrend step.
"""

from __future__ import annotations

import logging
from typing import Literal

import lightkurve as lk
import numpy as np
from astropy.stats import biweight_location
from scipy.interpolate import BSpline, LSQUnivariateSpline, UnivariateSpline
from scipy.signal import savgol_filter

from skvo_veb.utils.lc_processor.running_parabola import (
    RunningParabolaConfig,
    evaluate_at_centre,
    smooth_running_parabola,
)

logger = logging.getLogger(__name__)

DetrendMode = Literal["mag", "flux"]
MethodId = Literal[
    "median",
    "biweight",
    "savgol",
    "lightkurve",
    "spline_smooth",
    "spline_lsq",
    "pspline",
    "running_parabola",
]

METHOD_LABELS: dict[str, str] = {
    "median": "Sliding median",
    "biweight": "Sliding biweight",
    "savgol": "Savitzky-Golay",
    "lightkurve": "Lightkurve flatten",
    "spline_smooth": "Smoothing spline",
    "spline_lsq": "Least-squares spline",
    "pspline": "P-spline",
    "running_parabola": "Running parabola",
}


def detrend_observed(
    observed: np.ndarray,
    trend: np.ndarray,
    mode: DetrendMode,
) -> np.ndarray:
    """Remove a trend by magnitude subtraction or flux division.

    Args:
        observed (numpy.ndarray): Observed photometry.
        trend (numpy.ndarray): Trend estimate, aligned with ``observed``.
        mode (str): ``mag`` subtracts; ``flux`` divides.

    Returns:
        numpy.ndarray: Detrended photometry.

    Raises:
        ValueError: If ``mode`` is invalid or a flux trend is non-positive.
    """
    observed = np.asarray(observed, dtype=float)
    trend = np.asarray(trend, dtype=float)
    if mode == "mag":
        return observed - trend
    if mode == "flux":
        finite = np.isfinite(trend)
        if np.any(finite & (trend <= 0)):
            raise ValueError("flux trend must be strictly positive for division")
        return observed / trend
    raise ValueError(f"mode must be 'mag' or 'flux', got {mode!r}")


def detrended_standard_error(
    observed: np.ndarray,
    trend: np.ndarray,
    obs_err: np.ndarray,
    mode: DetrendMode,
) -> np.ndarray:
    """Propagate measurement error to detrended values (trend treated as exact).

    Args:
        observed (numpy.ndarray): Observed photometry.
        trend (numpy.ndarray): Trend estimate.
        obs_err (numpy.ndarray): Measurement uncertainties.
        mode (str): ``mag`` or ``flux``.

    Returns:
        numpy.ndarray: Uncertainties on the detrended series (NaN where invalid).

    Raises:
        ValueError: If ``mode`` is unsupported.
    """
    observed = np.asarray(observed, dtype=float)
    trend = np.asarray(trend, dtype=float)
    obs_err = np.asarray(obs_err, dtype=float)
    sigma = np.full(observed.shape, np.nan, dtype=float)
    good = (
        np.isfinite(observed)
        & np.isfinite(trend)
        & np.isfinite(obs_err)
        & (obs_err > 0)
    )
    if mode == "mag":
        sigma[good] = obs_err[good]
    elif mode == "flux":
        good &= trend > 0
        sigma[good] = obs_err[good] / trend[good]
    else:
        raise ValueError(f"mode must be 'mag' or 'flux', got {mode!r}")
    return sigma


def contiguous_segment_bounds(
    times_sorted: np.ndarray,
    break_tolerance: float | None,
) -> list[tuple[int, int]]:
    """Return ``[l, h)`` index ranges split on gaps longer than a day threshold.

    ``times_sorted`` is Julian Date, so consecutive differences are already in
    days. A cut is placed wherever ``Δt`` exceeds ``break_tolerance`` days.

    Args:
        times_sorted (numpy.ndarray): Strictly time-ordered sample times (JD).
        break_tolerance (float | None): Maximum allowed gap in days. ``None``
            disables splitting (single segment).

    Returns:
        list[tuple[int, int]]: Half-open index intervals covering the series.
    """
    n = len(times_sorted)
    if n == 0:
        return []
    if n == 1 or break_tolerance is None:
        return [(0, n)]

    dt = times_sorted[1:] - times_sorted[:-1]
    cut = np.where(dt > float(break_tolerance))[0] + 1
    lows = np.concatenate(([0], cut))
    highs = np.concatenate((cut, [n]))
    return [(int(lo), int(hi)) for lo, hi in zip(lows, highs)]


def resolve_break_tolerance(split_on_gaps: bool, break_tolerance: float) -> float | None:
    """Return the gap length in days, or ``None`` when splitting is off.

    Args:
        split_on_gaps (bool): Whether to split on cadence gaps.
        break_tolerance (float): Maximum allowed gap in days.

    Returns:
        float | None: ``break_tolerance`` in days when splitting is enabled.

    Raises:
        ValueError: If splitting is on and the gap length is not positive.
    """
    if not split_on_gaps:
        return None
    if break_tolerance <= 0.0:
        raise ValueError("break tolerance must be a positive number of days")
    return float(break_tolerance)


def fill_detrend_trend(
    times: np.ndarray,
    values: np.ndarray,
    trend: np.ndarray,
    *,
    break_tolerance: float | None,
    max_interp_span: float | None = None,
) -> tuple[np.ndarray, dict[str, int]]:
    """Fills missing trend samples so every point can be detrended.

    Work is per gap-split piece. A piece that already has finite ``T``
    fills holes from the nearest finite ``T`` in that piece. An interior
    hole with finite ``T`` on both sides uses a linear interpolant of
    ``T`` when those two samples are at most ``max_interp_span`` days
    apart. A piece with no finite ``T`` uses the piece photometry median.
    Neighbouring nights are never used.

    Args:
        times (numpy.ndarray): Absolute JD.
        values (numpy.ndarray): Photometry aligned with ``times``.
        trend (numpy.ndarray): Overlay ``T``; holes are non-finite.
        break_tolerance (float | None): Gap used for the last smooth.
        max_interp_span (float | None): Maximum ``T`` interpolant span
            (days). ``None`` means nearest only.

    Returns:
        tuple: Filled trend and counts ``nearest``, ``interp``, ``median``.

    Raises:
        ValueError: If a piece has no usable photometry median.
    """
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    filled = np.asarray(trend, dtype=float).copy()
    n = int(times.size)
    if filled.size != n or values.size != n:
        raise ValueError("Trend, photometry, and time arrays must have equal length.")
    counts = {"nearest": 0, "interp": 0, "median": 0}
    if n == 0:
        return filled, counts
    order = np.argsort(times)
    t_sorted = times[order]
    y_sorted = values[order]
    trend_sorted = filled[order]
    for lo, hi in contiguous_segment_bounds(t_sorted, break_tolerance):
        piece = trend_sorted[lo:hi]
        y_piece = y_sorted[lo:hi]
        t_piece = t_sorted[lo:hi]
        good = np.flatnonzero(np.isfinite(piece))
        if good.size == 0:
            median = float(np.nanmedian(y_piece))
            if not np.isfinite(median):
                raise ValueError(
                    "Detrend cannot fill a piece with no finite photometry."
                )
            piece[:] = median
            counts["median"] += int(hi - lo)
            continue
        holes = np.flatnonzero(~np.isfinite(piece))
        t_good = t_piece[good]
        y_good = piece[good]
        for hole in holes:
            t_i = float(t_piece[hole])
            right = int(np.searchsorted(t_good, t_i, side="left"))
            left = right - 1
            has_left = left >= 0
            has_right = right < t_good.size
            if has_left and has_right:
                span = float(t_good[right] - t_good[left])
                if (
                    max_interp_span is not None
                    and span > 0.0
                    and span <= float(max_interp_span)
                ):
                    weight = (t_i - float(t_good[left])) / span
                    piece[hole] = float(y_good[left]) + weight * (
                        float(y_good[right]) - float(y_good[left])
                    )
                    counts["interp"] += 1
                    continue
            if has_left and has_right:
                use_left = (t_i - float(t_good[left])) <= (
                    float(t_good[right]) - t_i
                )
                piece[hole] = float(y_good[left] if use_left else y_good[right])
            elif has_left:
                piece[hole] = float(y_good[left])
            else:
                piece[hole] = float(y_good[right])
            counts["nearest"] += 1
    filled[order] = trend_sorted
    return filled, counts


def _lightkurve_break_multiplier(
    times: np.ndarray, gap_days: float | None
) -> float:
    """Convert a gap in days into Lightkurve's median-Δt multiplier.

    Lightkurve ``flatten`` still expects a unitless multiplier. This probe's
    widget is in days, so the conversion is ``gap_days / median(Δt)``.

    Args:
        times (numpy.ndarray): Observation times (JD, days).
        gap_days (float | None): Gap length in days, or ``None`` to disable
            Lightkurve's own split (a very large multiplier).

    Returns:
        float: Multiplier to pass to ``LightCurve.flatten``.

    Raises:
        ValueError: If ``gap_days`` is set but the median sampling step is
            missing or not positive.
    """
    if gap_days is None:
        return 1.0e12
    t = np.asarray(times, dtype=float)
    if t.size < 2:
        raise ValueError("need at least two times to convert a gap in days")
    dt = np.diff(np.sort(t))
    median_dt = float(np.nanmedian(dt))
    if not np.isfinite(median_dt) or median_dt <= 0:
        raise ValueError("median sampling step is not a positive number of days")
    return float(gap_days) / median_dt


def _segment_too_short_for_window(
    segment_length: int,
    window_length: int,
) -> bool:
    """Return True when a segment cannot host the full filter window.

    Args:
        segment_length (int): Number of samples in the segment.
        window_length (int): Filter window in points.

    Returns:
        bool: True when the segment should be filled with a constant.
    """
    return window_length > segment_length


def _odd_window_length(n_points: int, *, minimum: int = 3) -> int:
    """Return an odd window length at least ``minimum``.

    Args:
        n_points (int): Requested window in points.
        minimum (int): Smallest allowed odd length.

    Returns:
        int: Odd integer window length.
    """
    window = max(int(n_points), int(minimum))
    if window % 2 == 0:
        window += 1
    return window


def sliding_median_trend(
    times: np.ndarray,
    values: np.ndarray,
    window_days: float,
) -> np.ndarray:
    """Centred sliding median with a time window (not a point count).

    Args:
        times (numpy.ndarray): Observation times (same unit as ``window_days``).
        values (numpy.ndarray): Photometry aligned with ``times``.
        window_days (float): Full window width in time units.

    Returns:
        numpy.ndarray: Trend aligned with the input order.

    Raises:
        ValueError: If ``window_days`` is not positive.
    """
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    if window_days <= 0:
        raise ValueError("window_days must be positive")

    half = window_days / 2.0
    order = np.argsort(times)
    t_sorted = times[order]
    y_sorted = values[order]
    n = len(t_sorted)
    trend_sorted = np.empty(n, dtype=float)
    for i in range(n):
        lo = np.searchsorted(t_sorted, t_sorted[i] - half, side="left")
        hi = np.searchsorted(t_sorted, t_sorted[i] + half, side="right")
        trend_sorted[i] = np.median(y_sorted[lo:hi])

    trend = np.empty(n, dtype=float)
    trend[order] = trend_sorted
    return trend


def _biweight_trend_on_segment(
    y_segment: np.ndarray,
    n_points: int,
) -> np.ndarray:
    """Sliding biweight on one contiguous segment (no cross-gap windows).

    Args:
        y_segment (numpy.ndarray): Photometry in the segment.
        n_points (int): Full window width in points.

    Returns:
        numpy.ndarray: Segment trend.
    """
    seg_len = len(y_segment)
    if seg_len == 0:
        return np.array([], dtype=float)

    window_length = max(int(n_points), 1)
    if _segment_too_short_for_window(seg_len, window_length):
        fill = np.nanmedian(y_segment)
        return np.full(seg_len, fill, dtype=float)

    half = window_length // 2
    trend = np.empty(seg_len, dtype=float)
    for i in range(seg_len):
        lo = max(0, i - half)
        hi = min(seg_len, lo + window_length)
        lo = max(0, hi - window_length)
        trend[i] = biweight_location(y_segment[lo:hi])
    return trend


def sliding_biweight_trend(
    times: np.ndarray,
    values: np.ndarray,
    n_points: int,
    break_tolerance: float | None,
) -> np.ndarray:
    """Centred sliding biweight with gap-aware segmentation.

    Args:
        times (numpy.ndarray): Observation times.
        values (numpy.ndarray): Photometry aligned with ``times``.
        n_points (int): Full window width in points within each segment.
        break_tolerance (float | None): Maximum gap in days; ``None`` for no split.

    Returns:
        numpy.ndarray: Trend aligned with the input order.

    Raises:
        ValueError: If ``n_points`` is less than 1.
    """
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    if n_points < 1:
        raise ValueError("n_points must be at least 1")

    order = np.argsort(times)
    t_sorted = times[order]
    y_sorted = values[order]
    trend_sorted = np.empty(len(y_sorted), dtype=float)
    for seg_lo, seg_hi in contiguous_segment_bounds(t_sorted, break_tolerance):
        trend_sorted[seg_lo:seg_hi] = _biweight_trend_on_segment(
            y_sorted[seg_lo:seg_hi],
            n_points,
        )

    trend = np.empty(len(values), dtype=float)
    trend[order] = trend_sorted
    return trend


def _savitzky_golay_trend_on_segment(
    y_segment: np.ndarray,
    window_length: int,
    polyorder: int,
) -> np.ndarray:
    """Savitzky-Golay on one contiguous segment (no cross-gap windows).

    Args:
        y_segment (numpy.ndarray): Photometry in the segment.
        window_length (int): Odd filter window in points.
        polyorder (int): Local polynomial degree.

    Returns:
        numpy.ndarray: Segment trend.
    """
    seg_len = len(y_segment)
    if seg_len == 0:
        return np.array([], dtype=float)

    if _segment_too_short_for_window(seg_len, window_length):
        fill = np.nanmedian(y_segment)
        return np.full(seg_len, fill, dtype=float)

    effective_polyorder = min(polyorder, window_length - 1)
    return savgol_filter(
        y_segment,
        window_length=window_length,
        polyorder=effective_polyorder,
        mode="interp",
    )


def sliding_savitzky_golay_trend(
    times: np.ndarray,
    values: np.ndarray,
    n_points: int,
    polyorder: int,
    break_tolerance: float | None,
) -> np.ndarray:
    """Savitzky-Golay trend with gap-aware segmentation (window in points).

    Args:
        times (numpy.ndarray): Observation times.
        values (numpy.ndarray): Photometry aligned with ``times``.
        n_points (int): Target full window width in points (adjusted to odd).
        polyorder (int): Local polynomial degree (must be less than window length).
        break_tolerance (float | None): Maximum gap in days; ``None`` for no split.

    Returns:
        numpy.ndarray: Trend aligned with the input order.

    Raises:
        ValueError: If ``polyorder`` is invalid for the window.
    """
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    window_length = _odd_window_length(n_points)
    if polyorder < 0:
        raise ValueError("polyorder must be non-negative")
    if polyorder >= window_length:
        raise ValueError("polyorder must be less than window length")

    order = np.argsort(times)
    t_sorted = times[order]
    y_sorted = values[order]
    trend_sorted = np.empty(len(y_sorted), dtype=float)
    for seg_lo, seg_hi in contiguous_segment_bounds(t_sorted, break_tolerance):
        trend_sorted[seg_lo:seg_hi] = _savitzky_golay_trend_on_segment(
            y_sorted[seg_lo:seg_hi],
            window_length,
            polyorder,
        )

    trend = np.empty(len(values), dtype=float)
    trend[order] = trend_sorted
    return trend


def lightkurve_flatten_trend(
    times: np.ndarray,
    values: np.ndarray,
    values_err: np.ndarray | None,
    n_points: int,
    polyorder: int,
    break_tolerance: float | None,
) -> np.ndarray:
    """Trend from ``lightkurve.LightCurve.flatten`` (Savitzky-Golay inside Lightkurve).

    Args:
        times (numpy.ndarray): Observation times.
        values (numpy.ndarray): Photometry aligned with ``times``.
        values_err (numpy.ndarray | None): Optional uncertainties (used when all finite).
        n_points (int): Target SG window in points (adjusted to odd).
        polyorder (int): SG polynomial order.
        break_tolerance (float | None): Maximum gap in days; ``None`` disables splits.

    Returns:
        numpy.ndarray: Trend aligned with the input order.

    Raises:
        ValueError: If Lightkurve returns a mismatched trend length.
    """
    window_length = _odd_window_length(n_points)
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    flux_err = None
    if values_err is not None:
        err = np.asarray(values_err, dtype=float)
        if np.all(np.isfinite(err)):
            flux_err = err

    lk_break = _lightkurve_break_multiplier(times, break_tolerance)
    lc = lk.LightCurve(time=times, flux=values, flux_err=flux_err)
    _, trend_lc = lc.flatten(
        window_length=window_length,
        polyorder=polyorder,
        break_tolerance=lk_break,
        return_trend=True,
    )
    trend = np.asarray(trend_lc.flux, dtype=float)
    if trend.shape != values.shape:
        raise ValueError("Lightkurve trend length does not match input light curve")
    return trend


def _trend_smoothing_spline_on_segment(
    t_segment: np.ndarray,
    y_segment: np.ndarray,
    smoothing_s: float | None,
    smoothing_rel: float,
) -> np.ndarray:
    """Penalised cubic spline trend (``UnivariateSpline``) on one segment.

    Args:
        t_segment (numpy.ndarray): Segment times.
        y_segment (numpy.ndarray): Segment photometry.
        smoothing_s (float | None): Explicit ``s``; ``None`` uses ``n * var(y) * rel``.
        smoothing_rel (float): Relative smoothing when ``smoothing_s`` is ``None``.

    Returns:
        numpy.ndarray: Segment trend.
    """
    n = len(t_segment)
    if n == 0:
        return np.array([], dtype=float)
    if n < 4:
        return np.full(n, np.nanmedian(y_segment), dtype=float)

    if smoothing_s is None:
        y_var = float(np.nanvar(y_segment))
        if y_var <= 0 or not np.isfinite(y_var):
            y_var = 1.0
        s = n * y_var * smoothing_rel
    else:
        s = smoothing_s

    spline = UnivariateSpline(t_segment, y_segment, k=3, s=s)
    return spline(t_segment)


def smoothing_spline_trend(
    times: np.ndarray,
    values: np.ndarray,
    break_tolerance: float | None,
    smoothing_s: float | None,
    smoothing_rel: float,
) -> np.ndarray:
    """Fit smoothing splines independently on each cadence-contiguous segment.

    Args:
        times (numpy.ndarray): Observation times.
        values (numpy.ndarray): Photometry aligned with ``times``.
        break_tolerance (float | None): Maximum gap in days; ``None`` for one segment.
        smoothing_s (float | None): Explicit UnivariateSpline ``s``.
        smoothing_rel (float): Relative ``s`` factor when ``smoothing_s`` is ``None``.

    Returns:
        numpy.ndarray: Trend aligned with the input order.
    """
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    order = np.argsort(times)
    t_sorted = times[order]
    y_sorted = values[order]
    trend_sorted = np.empty(len(y_sorted), dtype=float)
    for seg_lo, seg_hi in contiguous_segment_bounds(t_sorted, break_tolerance):
        trend_sorted[seg_lo:seg_hi] = _trend_smoothing_spline_on_segment(
            t_sorted[seg_lo:seg_hi],
            y_sorted[seg_lo:seg_hi],
            smoothing_s,
            smoothing_rel,
        )
    trend = np.empty(len(values), dtype=float)
    trend[order] = trend_sorted
    return trend


def interior_knots_equispaced(times: np.ndarray, n_interior: int) -> np.ndarray:
    """Build strictly interior, equally spaced knots on the data time span.

    Args:
        times (numpy.ndarray): Observation times (any order).
        n_interior (int): Number of interior knots.

    Returns:
        numpy.ndarray: Knot times, possibly empty.
    """
    times = np.asarray(times, dtype=float)
    if n_interior < 1 or times.size < 2:
        return np.asarray([], dtype=float)
    t_min = float(np.min(times))
    t_max = float(np.max(times))
    if t_max <= t_min:
        return np.asarray([], dtype=float)
    return np.linspace(t_min, t_max, int(n_interior) + 2)[1:-1]


def _allocate_by_occupancy(
    weights: np.ndarray,
    n_total: int,
    caps: np.ndarray,
) -> np.ndarray:
    """Distribute ``n_total`` integer counts by occupancy, honouring per-bin caps.

    Uses largest-remainder (Hamilton) allocation, then repeatedly redistributes
    leftover counts onto bins that still have capacity.

    Args:
        weights (numpy.ndarray): Non-negative occupancy weights.
        n_total (int): Counts to place.
        caps (numpy.ndarray): Maximum counts per bin (same length as ``weights``).

    Returns:
        numpy.ndarray: Integer allocation, shape matching ``weights``.
    """
    n_bins = len(weights)
    alloc = np.zeros(n_bins, dtype=int)
    if n_bins == 0 or n_total < 1:
        return alloc
    w = np.asarray(weights, dtype=float)
    cap = np.asarray(caps, dtype=int)
    left = min(int(n_total), int(np.maximum(cap, 0).sum()))
    guard = 0
    while left > 0 and guard < n_bins + n_total + 2:
        guard += 1
        room = cap - alloc
        active = room > 0
        if not np.any(active):
            break
        w_act = np.where(active, np.maximum(w, 0.0), 0.0)
        w_sum = float(w_act.sum())
        if w_sum <= 0:
            break
        share = left * w_act / w_sum
        add = np.minimum(np.floor(share).astype(int), room)
        leftover = left - int(add.sum())
        frac = share - np.floor(share)
        for idx in np.argsort(-frac, kind="stable"):
            if leftover == 0:
                break
            if active[idx] and add[idx] < room[idx]:
                add[idx] += 1
                leftover -= 1
        added = int(add.sum())
        if added == 0:
            idx = int(np.argmax(np.where(active, w_act, -1.0)))
            add[idx] = 1
            added = 1
        alloc += add
        left -= added
    return alloc


def _interior_knots_on_clump(t_segment: np.ndarray, n_knots: int) -> np.ndarray:
    """Place strictly interior knots on one cadence clump.

    One knot sits at the median time (occupancy centre). Several knots are
    quantiles of the clump times, excluding the endpoints.

    Args:
        t_segment (numpy.ndarray): Sorted times in the clump.
        n_knots (int): How many interior knots to place.

    Returns:
        numpy.ndarray: Strictly increasing times inside ``(t[0], t[-1])``.
    """
    t_segment = np.asarray(t_segment, dtype=float)
    if n_knots < 1 or t_segment.size < 2:
        return np.asarray([], dtype=float)
    t_lo = float(t_segment[0])
    t_hi = float(t_segment[-1])
    if not np.isfinite(t_lo) or not np.isfinite(t_hi) or t_hi <= t_lo:
        return np.asarray([], dtype=float)
    span = t_hi - t_lo
    eps = max(span * 1e-12, np.finfo(float).eps)
    if n_knots == 1:
        knot = float(np.median(t_segment))
        if knot <= t_lo or knot >= t_hi:
            knot = 0.5 * (t_lo + t_hi)
        if knot <= t_lo or knot >= t_hi:
            return np.asarray([], dtype=float)
        return np.asarray([knot], dtype=float)
    quantiles = np.linspace(0.0, 1.0, int(n_knots) + 2)[1:-1]
    knots = np.quantile(t_segment, quantiles)
    knots = np.clip(np.asarray(knots, dtype=float), t_lo + eps, t_hi - eps)
    unique = np.unique(knots)
    return unique[(unique > t_lo) & (unique < t_hi)]


def interior_knots_by_occupancy(
    times: np.ndarray,
    n_interior: int,
    break_tolerance: float | None,
) -> np.ndarray:
    """Distribute interior knots onto cadence clumps by point occupancy.

    Eligible nights (at least five points) each receive one knot at the median
    time when the requested count is large enough. Any extra knots are shared
    by occupancy, with per-night cap ``n - 4``. If fewer knots are requested
    than nights, the densest nights receive one centre knot each.

    Args:
        times (numpy.ndarray): Observation times (any order).
        n_interior (int): Requested number of interior knots.
        break_tolerance (float | None): Maximum gap in days; ``None`` treats the
            whole series as one clump.

    Returns:
        numpy.ndarray: Sorted unique interior knot times.
    """
    times = np.asarray(times, dtype=float)
    if n_interior < 1 or times.size < 2:
        return np.asarray([], dtype=float)
    order = np.argsort(times)
    t_sorted = times[order]
    clumps: list[np.ndarray] = []
    caps: list[int] = []
    weights: list[int] = []
    for lo, hi in contiguous_segment_bounds(t_sorted, break_tolerance):
        t_seg = t_sorted[lo:hi]
        n_pts = int(t_seg.size)
        cap = max(n_pts - 4, 0)
        if cap < 1:
            continue
        clumps.append(t_seg)
        caps.append(cap)
        weights.append(n_pts)
    if not clumps:
        return np.asarray([], dtype=float)
    n_clumps = len(clumps)
    caps_arr = np.asarray(caps, dtype=int)
    weights_arr = np.asarray(weights, dtype=float)
    n_use = min(int(n_interior), int(caps_arr.sum()))
    alloc = np.zeros(n_clumps, dtype=int)
    if n_use >= n_clumps:
        alloc[:] = 1
        extra = n_use - n_clumps
        if extra > 0:
            alloc += _allocate_by_occupancy(weights_arr, extra, caps_arr - alloc)
    else:
        dense = np.argsort(-weights_arr, kind="stable")
        for idx in dense[:n_use]:
            alloc[idx] = 1
    placed: list[float] = []
    for t_seg, n_k in zip(clumps, alloc):
        if n_k < 1:
            continue
        placed.extend(_interior_knots_on_clump(t_seg, int(n_k)).tolist())
    if not placed:
        return np.asarray([], dtype=float)
    return np.asarray(sorted(set(placed)), dtype=float)


def build_lsq_knot_grid(
    times: np.ndarray,
    n_interior: int,
    *,
    mode: str,
    break_tolerance: float | None,
) -> np.ndarray:
    """Build an LSQ interior-knot grid in uniform or occupancy mode.

    Args:
        times (numpy.ndarray): Observation times.
        n_interior (int): Requested knot count.
        mode (str): ``uniform`` or ``occupancy``.
        break_tolerance (float | None): Maximum gap in days for occupancy mode.

    Returns:
        numpy.ndarray: Interior knot times.

    Raises:
        ValueError: If ``mode`` is not recognised.
    """
    if mode == "uniform":
        return interior_knots_equispaced(times, n_interior)
    if mode == "occupancy":
        return interior_knots_by_occupancy(times, n_interior, break_tolerance)
    raise ValueError(f"unknown LSQ knot-grid mode {mode!r}")


def _knots_inside_segment(knots: np.ndarray, t_lo: float, t_hi: float) -> np.ndarray:
    """Keep strictly increasing knots strictly inside ``(t_lo, t_hi)``.

    Args:
        knots (numpy.ndarray): Candidate interior knots.
        t_lo (float): Segment start time.
        t_hi (float): Segment end time.

    Returns:
        numpy.ndarray: Filtered knot times.
    """
    knots = np.asarray(knots, dtype=float)
    if knots.size == 0 or not np.isfinite(t_lo) or not np.isfinite(t_hi) or t_hi <= t_lo:
        return np.asarray([], dtype=float)
    inside = knots[(knots > t_lo) & (knots < t_hi) & np.isfinite(knots)]
    if inside.size == 0:
        return np.asarray([], dtype=float)
    unique = np.unique(inside)
    return unique


def _lsq_spline_on_segment(
    t_segment: np.ndarray,
    y_segment: np.ndarray,
    knots: np.ndarray,
) -> np.ndarray:
    """Least-squares cubic spline on one segment with explicit interior knots.

    Args:
        t_segment (numpy.ndarray): Segment times (sorted).
        y_segment (numpy.ndarray): Segment photometry.
        knots (numpy.ndarray): Interior knots strictly inside the segment.

    Returns:
        numpy.ndarray: Segment trend.

    Raises:
        ValueError: If SciPy rejects the knot vector.
    """
    n = len(t_segment)
    if n == 0:
        return np.array([], dtype=float)
    if n < 4:
        return np.full(n, np.nanmedian(y_segment), dtype=float)

    use = _knots_inside_segment(knots, float(t_segment[0]), float(t_segment[-1]))
    max_interior = max(n - 4, 0)
    if use.size == 0 or max_interior == 0:
        return np.full(n, np.nanmedian(y_segment), dtype=float)
    if use.size > max_interior:
        raise ValueError(
            f"too many interior knots for this segment ({use.size} > {max_interior})"
        )
    spline = LSQUnivariateSpline(t_segment, y_segment, use, k=3)
    return spline(t_segment)


def lsq_spline_trend(
    times: np.ndarray,
    values: np.ndarray,
    knots: np.ndarray,
    break_tolerance: float | None,
) -> np.ndarray:
    """Least-squares cubic spline per cadence segment using shared interior knots.

    Knots that fall inside a segment are used there; knots in gaps are ignored
    for that segment.

    Args:
        times (numpy.ndarray): Observation times.
        values (numpy.ndarray): Photometry aligned with ``times``.
        knots (numpy.ndarray): Interior knot times (absolute JD).
        break_tolerance (float | None): Maximum gap in days; ``None`` for one segment.

    Returns:
        numpy.ndarray: Trend aligned with the input order.
    """
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    knots = np.asarray(knots, dtype=float)
    order = np.argsort(times)
    t_sorted = times[order]
    y_sorted = values[order]
    trend_sorted = np.empty(len(y_sorted), dtype=float)
    for seg_lo, seg_hi in contiguous_segment_bounds(t_sorted, break_tolerance):
        trend_sorted[seg_lo:seg_hi] = _lsq_spline_on_segment(
            t_sorted[seg_lo:seg_hi],
            y_sorted[seg_lo:seg_hi],
            knots,
        )
    trend = np.empty(len(values), dtype=float)
    trend[order] = trend_sorted
    return trend


def _pspline_second_difference_matrix(n_coeffs: int) -> np.ndarray:
    """Matrix ``D`` so ``||D c||^2`` penalises second differences of B-spline coefficients.

    Args:
        n_coeffs (int): Number of B-spline coefficients.

    Returns:
        numpy.ndarray: Second-difference matrix.
    """
    if n_coeffs <= 2:
        return np.zeros((0, n_coeffs))
    return np.diff(np.eye(n_coeffs), n=2, axis=0)


def p_spline_trend(
    times: np.ndarray,
    values: np.ndarray,
    penalty_lambda: float,
    n_segments: int,
    spline_degree: int = 3,
) -> np.ndarray:
    """P-spline trend for one series (times need not be sorted).

    Args:
        times (numpy.ndarray): Observation times.
        values (numpy.ndarray): Photometry.
        penalty_lambda (float): Roughness penalty (larger → smoother).
        n_segments (int): Number of equispaced intervals on ``[min(t), max(t)]``.
        spline_degree (int): B-spline degree (default cubic).

    Returns:
        numpy.ndarray: Trend aligned with the input order.

    Raises:
        ValueError: If ``penalty_lambda`` is negative or ``n_segments`` < 1.
    """
    t = np.asarray(times, dtype=float)
    y = np.asarray(values, dtype=float)
    if penalty_lambda < 0:
        raise ValueError("penalty_lambda must be non-negative")
    if n_segments < 1:
        raise ValueError("n_segments must be at least 1")

    order = np.argsort(t)
    t_sorted = t[order]
    y_sorted = y[order]
    n = len(t_sorted)

    if n <= spline_degree + 1:
        trend_sorted = np.full(n, np.nanmedian(y_sorted), dtype=float)
    else:
        t_min = float(t_sorted[0])
        t_max = float(t_sorted[-1])
        if t_max <= t_min:
            trend_sorted = np.full(n, float(y_sorted[0]), dtype=float)
        else:
            internal = np.linspace(t_min, t_max, n_segments + 2)[1:-1]
            knots = np.r_[
                [t_min] * (spline_degree + 1),
                internal,
                [t_max] * (spline_degree + 1),
            ]
            design = BSpline.design_matrix(t_sorted, knots, spline_degree)
            x_mat = design.toarray() if hasattr(design, "toarray") else np.asarray(design)
            n_coeffs = x_mat.shape[1]
            diff = _pspline_second_difference_matrix(n_coeffs)
            if diff.shape[0] == 0:
                coef = np.linalg.lstsq(x_mat, y_sorted, rcond=None)[0]
            else:
                normal = x_mat.T @ x_mat + penalty_lambda * (diff.T @ diff)
                rhs = x_mat.T @ y_sorted
                coef = np.linalg.solve(normal, rhs)
            trend_sorted = x_mat @ coef

    trend = np.empty(n, dtype=float)
    trend[order] = trend_sorted
    return trend


def running_parabola_trend(
    times: np.ndarray,
    values: np.ndarray,
    values_err: np.ndarray | None,
    *,
    window_width_d: float,
    step_d: float,
    min_points: int,
    use_weights: bool,
    break_tolerance: float | None,
) -> np.ndarray:
    """Returns the running-parabola trend at the observation times.

    The native product is ``a`` at each two-sided window centre. ``T(t_i)``
    is the linear interpolant of neighbouring centres only when they are
    at most one window apart. Other observations are evaluated as a
    parabola centred on that time, or left ``NaN`` if the local window is
    sparse or one-sided. A night shorter than the window is not discarded:
    those points still try a local evaluation. The user is told only when
    no point can be fitted.

    Args:
        times (numpy.ndarray): Observation times (absolute JD).
        values (numpy.ndarray): Photometry in the working domain.
        values_err (numpy.ndarray | None): Uncertainties, or ``None``.
        window_width_d (float): Full window width (days).
        step_d (float): Centre-grid step (days).
        min_points (int): Minimum in-window points for a fit.
        use_weights (bool): Inverse-variance weights from errors.
        break_tolerance (float | None): Gap split in days, or ``None``.

    Returns:
        numpy.ndarray: Trend ``T(t_i)`` aligned with ``times``.

    Raises:
        ValueError: If a required geometry parameter is invalid, or every
            segment fails to produce a fit.
    """
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    n = int(times.size)
    if values_err is None:
        err = np.full(n, np.nan, dtype=float)
    else:
        err = np.asarray(values_err, dtype=float)
        if err.size != n:
            raise ValueError(
                f"error length {err.size} does not match photometry length {n}"
            )
    cfg = RunningParabolaConfig(
        window_width_d=float(window_width_d),
        step_d=float(step_d),
        min_points=int(min_points),
        use_weights=bool(use_weights),
    )
    order = np.argsort(times)
    t_sorted = times[order]
    y_sorted = values[order]
    e_sorted = err[order]
    trend_sorted = np.empty(n, dtype=float)
    for lo, hi in contiguous_segment_bounds(t_sorted, break_tolerance):
        t_seg = t_sorted[lo:hi]
        y_seg = y_sorted[lo:hi]
        e_seg = e_sorted[lo:hi]
        trend_sorted[lo:hi] = _running_parabola_on_segment(t_seg, y_seg, e_seg, cfg)
    n_ok = int(np.count_nonzero(np.isfinite(trend_sorted)))
    n_skip = n - n_ok
    if n_ok == 0:
        raise ValueError(
            "Running parabola produced no successful fits "
            f"({n} point(s) skipped)."
        )
    if n_skip:
        logger.warning(
            "Running parabola skipped %s of %s observation(s) "
            "(sparse window or short segment)",
            n_skip,
            n,
        )
    trend = np.empty(n, dtype=float)
    trend[order] = trend_sorted
    return trend


def _interp_centres_within_window(
    t_obs: np.ndarray,
    t_c: np.ndarray,
    y_c: np.ndarray,
    window_width_d: float,
) -> np.ndarray:
    """Linearly interpolates ``T`` only between centres at most one window apart.

    A single centre is not broadcast. A hole larger than the window stays
    ``NaN``.

    Args:
        t_obs (numpy.ndarray): Observation times (absolute JD).
        t_c (numpy.ndarray): Successful window centres, sorted.
        y_c (numpy.ndarray): Parabola value ``a`` at each centre.
        window_width_d (float): Full window width (days).

    Returns:
        numpy.ndarray: Trend at ``t_obs``; ``NaN`` where no close pair applies.
    """
    trend = np.full(t_obs.shape, np.nan, dtype=float)
    if t_c.size < 2:
        return trend
    t_obs = np.asarray(t_obs, dtype=float)
    for left, right in zip(range(t_c.size - 1), range(1, t_c.size)):
        dt_c = float(t_c[right] - t_c[left])
        if dt_c <= 0.0 or dt_c > float(window_width_d):
            continue
        mask = (t_obs >= t_c[left]) & (t_obs <= t_c[right])
        if not np.any(mask):
            continue
        weight = (t_obs[mask] - t_c[left]) / dt_c
        trend[mask] = y_c[left] + weight * (y_c[right] - y_c[left])
    return trend


def _running_parabola_on_segment(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    e_seg: np.ndarray,
    cfg: RunningParabolaConfig,
) -> np.ndarray:
    """Fits one contiguous segment and returns ``T(t)`` on its samples.

    Window centres are optional. A night shorter than the window still
    tries a local evaluation at each observation. ``a`` is never painted
    onto the whole piece.

    Args:
        t_seg (numpy.ndarray): Sorted segment times (absolute JD).
        y_seg (numpy.ndarray): Segment photometry.
        e_seg (numpy.ndarray): Segment uncertainties.
        cfg (RunningParabolaConfig): Window, step, and weight settings.

    Returns:
        numpy.ndarray: Segment trend.

    Raises:
        ValueError: Not raised for sparse or one-sided windows; those stay
            ``NaN``.
    """
    n_seg = int(t_seg.size)
    if n_seg == 0:
        return np.asarray([], dtype=float)
    trend_seg = np.full(n_seg, np.nan, dtype=float)
    if n_seg < cfg.min_points:
        logger.warning(
            "Running parabola: skipping segment of %s point(s) "
            "(need at least %s)",
            n_seg,
            cfg.min_points,
        )
        return trend_seg
    t_c = np.asarray([], dtype=float)
    y_c = np.asarray([], dtype=float)
    try:
        points = smooth_running_parabola(t_seg, y_seg, e_seg, cfg=cfg)
    except ValueError as exc:
        logger.warning(
            "Running parabola: no centre-grid on %s point(s): %s",
            n_seg,
            exc,
        )
    else:
        t_c = np.asarray([pt.jd for pt in points], dtype=float)
        y_c = np.asarray([pt.smooth for pt in points], dtype=float)
        order_c = np.argsort(t_c)
        t_c = t_c[order_c]
        y_c = y_c[order_c]
        trend_seg = _interp_centres_within_window(
            t_seg, t_c, y_c, cfg.window_width_d
        )
    missing = np.flatnonzero(~np.isfinite(trend_seg))
    for idx in missing:
        t_i = float(t_seg[idx])
        try:
            trend_seg[idx] = evaluate_at_centre(
                t_seg, y_seg, e_seg, t_i, cfg=cfg
            )
        except ValueError as exc:
            logger.debug(
                "Running parabola: skipping JD %.8f: %s",
                t_i,
                exc,
            )
            trend_seg[idx] = np.nan
    return trend_seg


def p_spline_interior_knots(times: np.ndarray, n_segments: int) -> np.ndarray:
    """Return the equispaced interior knots implied by a P-spline segment count.

    Args:
        times (numpy.ndarray): Observation times.
        n_segments (int): Number of equispaced intervals.

    Returns:
        numpy.ndarray: Interior knot times (may be empty).
    """
    times = np.asarray(times, dtype=float)
    if times.size < 2 or n_segments < 1:
        return np.asarray([], dtype=float)
    t_min = float(np.min(times))
    t_max = float(np.max(times))
    if t_max <= t_min:
        return np.asarray([], dtype=float)
    return np.linspace(t_min, t_max, int(n_segments) + 2)[1:-1]


def apply_smooth_method(
    times: np.ndarray,
    values: np.ndarray,
    values_err: np.ndarray | None,
    *,
    method: str,
    break_tolerance: float | None,
    median_window_days: float,
    n_points: int,
    polyorder: int,
    smoothing_s: float | None,
    smoothing_rel: float,
    knots: np.ndarray,
    penalty_lambda: float,
    n_segments: int,
    rp_window_days: float = 0.05,
    rp_step_days: float = 0.0125,
    rp_min_points: int = 5,
    rp_use_weights: bool = False,
) -> np.ndarray:
    """Fits one smoother and returns the trend at the observation times.

    Residual subtraction / division is not done here.

    Args:
        times (numpy.ndarray): Observation times.
        values (numpy.ndarray): Photometry in the working domain.
        values_err (numpy.ndarray | None): Uncertainties, or ``None``.
        method (str): Method id from ``METHOD_LABELS``.
        break_tolerance (float | None): Maximum gap in days, or ``None``.
        median_window_days (float): Sliding-median window (days).
        n_points (int): Point-window for biweight / SG / Lightkurve.
        polyorder (int): SG / Lightkurve polynomial order.
        smoothing_s (float | None): Explicit smoothing-spline ``s``.
        smoothing_rel (float): Relative ``s`` when ``smoothing_s`` is ``None``.
        knots (numpy.ndarray): Interior knots for the LSQ spline.
        penalty_lambda (float): P-spline roughness penalty.
        n_segments (int): P-spline segment count.
        rp_window_days (float): Running-parabola window (days).
        rp_step_days (float): Running-parabola centre step (days).
        rp_min_points (int): Minimum in-window points.
        rp_use_weights (bool): Inverse-variance weights.

    Returns:
        numpy.ndarray: Trend ``T(t_i)``.

    Raises:
        ValueError: If ``method`` is unknown or a fit constraint fails.
    """
    method_id = str(method).strip().lower()
    if method_id == "median":
        trend = sliding_median_trend(times, values, median_window_days)
    elif method_id == "biweight":
        trend = sliding_biweight_trend(times, values, n_points, break_tolerance)
    elif method_id == "savgol":
        trend = sliding_savitzky_golay_trend(
            times, values, n_points, polyorder, break_tolerance
        )
    elif method_id == "lightkurve":
        trend = lightkurve_flatten_trend(
            times, values, values_err, n_points, polyorder, break_tolerance
        )
    elif method_id == "spline_smooth":
        trend = smoothing_spline_trend(
            times, values, break_tolerance, smoothing_s, smoothing_rel
        )
    elif method_id == "spline_lsq":
        trend = lsq_spline_trend(times, values, knots, break_tolerance)
    elif method_id == "pspline":
        trend = p_spline_trend(times, values, penalty_lambda, n_segments)
    elif method_id == "running_parabola":
        trend = running_parabola_trend(
            times,
            values,
            values_err,
            window_width_d=rp_window_days,
            step_d=rp_step_days,
            min_points=rp_min_points,
            use_weights=rp_use_weights,
            break_tolerance=break_tolerance,
        )
    else:
        raise ValueError(f"unknown smooth method {method!r}")
    logger.info("Fitted %s smooth on %s points", method_id, len(times))
    return trend
