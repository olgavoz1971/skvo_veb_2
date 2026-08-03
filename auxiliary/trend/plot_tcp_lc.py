"""Sandbox: read tcp.vot and plot the light curve (hardcoded paths only)."""

from pathlib import Path
from typing import Literal

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import lightkurve as lk
from astropy.io.votable import parse
from astropy.stats import biweight, biweight_location
from scipy.interpolate import BSpline, CubicSpline, LSQUnivariateSpline, UnivariateSpline
from scipy.signal import savgol_filter

DETREND_MODE: Literal["mag", "flux"] = "flux"
SplineKind = Literal["smoothing", "cubic_interp", "lsq"]
Method = Literal["SG", "LK", "biweght", "spline", "pspline"]

DATA_FILE = Path(__file__).resolve().parent / "data" / "tcp.vot"
# DATA_FILE = Path(__file__).resolve().parent / "data" / "detrended_spline.csv"


TIME_COLUMN = "obs_time"
PHOT_COLUMN = "phot"
PHOT_ERR_COLUMN = "flux_error"
MAG_COLUMN = "mag"
TREND_COLUMN = "lk_trend"
SPLINE_TREND_COLUMN = "spline_trend"

# Instrumental magnitude at ``FLUX_COLUMN == 1`` (Pogson: mag = ZP - 2.5 log10 flux).
MAG_ZERO_POINT = 20.0

JD_MIN = None
# JD_MAX = None
JD_MAX = 59860.1

# Full width of the centred median window, in the same time unit as ``obs_time`` (d).
MEDIAN_WINDOW_DAYS = 2.0
N_POINTS = 301
SG_POLYORDER = 5
# Gap breaks when delta-t exceeds ``BREAK_TOLERANCE * median(delta-t)`` (Lightkurve default 5).
BREAK_TOLERANCE: float | None = 5.0
# Optional: infer a point-count window from cadence inside [T_LEFT, T_RIGHT] (after cut).
ESTIMATE_N_POINTS_WINDOW = False
WINDOW_ESTIMATE_T_LEFT = 59855.0
WINDOW_ESTIMATE_T_RIGHT = 59858.0
# How to remove the trend from the observed curve (passed explicitly to detrending).

# Segment splines (after ``BREAK_TOLERANCE`` split).
# SPLINE_KIND: "smoothing" | "cubic_interp" | "lsq"
SPLINE_KIND: SplineKind = "smoothing"
# ``None`` -> ``s = len(segment) * var(y) * SPLINE_SMOOTHING_REL`` for UnivariateSpline.
SPLINE_SMOOTHING_S: float | None = None
SPLINE_SMOOTHING_REL = 0.05
SPLINE_LSQ_INTERIOR_KNOTS = 8

# P-spline: equispaced B-spline segments + penalty ``lambda * ||D^2 c||^2`` on coefficients.
PSPLINE_PENALTY_LAMBDA = 1.0e4
PSPLINE_N_SEGMENTS = 40
PSPLINE_TREND_COLUMN = "pspline_trend"

FIGSIZE = (20, 12)
FONT_SIZE = 20
DETREND_LK_CSV = Path(__file__).resolve().parent / "data" / "detrended_lk.csv"
DETREND_SPLINE_CSV = Path(__file__).resolve().parent / "data" / "detrended_spline.csv"


def load_detrended_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(
        path,
        comment="#",
        skiprows=1, # ignore column names
        names=["obs_time", "phot", "flux_error"]
    )
    return df


def load_tcp_vot(path: Path) -> pd.DataFrame:
    """Read a TESS cutout VOTable into a pandas DataFrame."""
    table = parse(path).get_first_table().to_table()
    return table.to_pandas()


def cut_by_time_limits(
    df: pd.DataFrame,
    time_col: str,
    t_min: float | None,
    t_max: float | None,
) -> pd.DataFrame:
    """Keep rows within optional inclusive time bounds; ``None`` skips that end."""
    times = df[time_col]
    keep = pd.Series(True, index=df.index)
    if t_min is not None:
        keep &= times >= t_min
    if t_max is not None:
        keep &= times <= t_max
    return df.loc[keep].copy()


def estimate_sliding_window_n_points(
    df: pd.DataFrame,
    time_col: str,
    t_left: float,
    t_right: float,
    window_days: float,
) -> int:
    """Map a time-window width (days) to an equivalent odd point count from local cadence.

    Uses the mean sampling rate (points per day) within ``[t_left, t_right]`` inclusive,
    then ``n_points ≈ window_days × (n_interval / span)``.

    Args:
        df: Light curve containing ``time_col``.
        time_col: Time column (same unit as ``t_left``, ``t_right``, ``window_days``).
        t_left: Start of the cadence estimation interval (inclusive).
        t_right: End of the cadence estimation interval (inclusive).
        window_days: Target smoother width in time units.

    Returns:
        Odd integer point count (minimum 3) suitable for point-indexed smoothers.
    """
    if t_left > t_right:
        raise ValueError("t_left must be <= t_right")
    if window_days <= 0:
        raise ValueError("window_days must be positive")

    times = df[time_col].to_numpy(dtype=float)
    in_interval = (times >= t_left) & (times <= t_right)
    n_interval = int(np.count_nonzero(in_interval))
    if n_interval < 2:
        raise ValueError(
            "need at least two points in [t_left, t_right] to estimate cadence"
        )

    span_days = float(t_right - t_left)
    if span_days <= 0:
        raise ValueError("t_right - t_left must be positive")

    points_per_day = n_interval / span_days
    n_points_float = window_days * points_per_day
    n_points = int(round(n_points_float))
    n_points = max(n_points, 3)
    if n_points % 2 == 0:
        n_points += 1
    return n_points


def add_magnitudes(
    df: pd.DataFrame,
    flux_col: str,
    flux_err_col: str,
    mag_col: str,
    mag_err_col: str,
    zero_point: float,
) -> pd.DataFrame:
    """Add instrumental magnitudes and Gaussian errors from flux (fixed zero point).

    Uses ``mag = zero_point - 2.5 log10(flux)`` and
    ``sigma_mag = (2.5 / ln 10) * sigma_flux / flux`` where ``sigma_flux`` is valid;
    otherwise ``mag_err`` is NaN for that row.
    """
    out = df.copy()
    flux = out[flux_col].to_numpy(dtype=float)
    flux_err = out[flux_err_col].to_numpy(dtype=float)
    if np.any(flux <= 0):
        raise ValueError(f"{flux_col} must be strictly positive for log10 conversion")

    out[mag_col] = zero_point - 2.5 * np.log10(flux)
    mag_err = np.full(flux.shape, np.nan, dtype=float)
    good_err = np.isfinite(flux_err) & (flux_err > 0)
    mag_err[good_err] = (2.5 / np.log(10.0)) * flux_err[good_err] / flux[good_err]
    out[mag_err_col] = mag_err
    return out


def detrend_observed(
    observed: np.ndarray,
    trend: np.ndarray,
    mode: Literal["mag", "flux"],
) -> np.ndarray:
    """Apply magnitude subtraction or flux division detrending."""
    observed = np.asarray(observed, dtype=float)
    trend = np.asarray(trend, dtype=float)
    if mode == "mag":
        return observed - trend
    if mode == "flux":
        if np.any(trend <= 0):
            raise ValueError("flux trend must be strictly positive for division")
        return observed / trend
    raise ValueError(f"mode must be 'mag' or 'flux', got {mode!r}")


def detrended_standard_error(
    observed: np.ndarray,
    trend: np.ndarray,
    obs_err: np.ndarray,
    mode: Literal["mag", "flux"],
) -> np.ndarray:
    """Propagate measurement error to detrended values (trend treated as exact).

    Magnitude subtraction: ``sigma_detrended = sigma_obs``.
    Flux division for ``detrended = obs / trend``: ``sigma_detrended = sigma_obs / trend``.
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
    """Return ``[l, h)`` index ranges for contiguous cadence (Lightkurve-style gaps).

    Args:
        times_sorted: Strictly time-ordered sample times.
        break_tolerance: Multiplier on ``median(delta t)`` defining a gap; ``None`` disables
            splitting (single segment).

    Returns:
        List of half-open index intervals covering the series.
    """
    n = len(times_sorted)
    if n == 0:
        return []
    if n == 1 or break_tolerance is None:
        return [(0, n)]

    dt = times_sorted[1:] - times_sorted[:-1]
    median_dt = float(np.nanmedian(dt))
    if not np.isfinite(median_dt) or median_dt <= 0:
        return [(0, n)]

    gap_threshold = break_tolerance * median_dt
    cut = np.where(dt > gap_threshold)[0] + 1
    lows = np.concatenate(([0], cut))
    highs = np.concatenate((cut, [n]))
    return [(int(lo), int(hi)) for lo, hi in zip(lows, highs)]


def _trend_smoothing_spline_on_segment(
    t_segment: np.ndarray,
    y_segment: np.ndarray,
    smoothing_s: float | None,
    smoothing_rel: float,
) -> np.ndarray:
    """Penalised cubic spline trend (``UnivariateSpline``) on one segment."""
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


def _trend_cubic_interpolating_spline_on_segment(
    t_segment: np.ndarray,
    y_segment: np.ndarray,
) -> np.ndarray:
    """Interpolating cubic spline through all segment samples (can follow humps closely)."""
    n = len(t_segment)
    if n == 0:
        return np.array([], dtype=float)
    if n < 4:
        return np.full(n, np.nanmedian(y_segment), dtype=float)

    spline = CubicSpline(t_segment, y_segment)
    return spline(t_segment)


# lll
def _trend_least_squares_spline_on_segment(
    t_segment: np.ndarray,
    y_segment: np.ndarray,
    n_interior_knots: int,
) -> np.ndarray:
    """Least-squares cubic spline with fixed interior knot count on one segment."""
    n = len(t_segment)
    if n == 0:
        return np.array([], dtype=float)
    if n < 4:
        return np.full(n, np.nanmedian(y_segment), dtype=float)

    max_interior = max(n - 4, 0)
    n_use = min(max(n_interior_knots, 1), max_interior)
    if n_use == 0:
        return np.full(n, np.nanmedian(y_segment), dtype=float)

    knots = np.linspace(t_segment[0], t_segment[-1], n_use + 2)[1:-1]
    # knots = np.array([59853.66092207, 59854.4631498 , 
        # 59855.26537753, 59856.06760526, 59856.869833, 
        # 59857.67206073, 59858.47428846, 59859.2765162])
    knots = np.array([
        59853.20250622, 
        59853.5463181 , 
        59853.89012999, 
        59854.23394187,
        59854.5,
        59854.6,
        59854.7,
        59854.8,
        59854.9,
        59855.0,
        59855.26537753, 59855.60918942,
        59855.9530013 , 59856.29681319, 
        59856.4,
        59856.5,
        59856.6,
        59856.7,
        59856.8,
        59856.9,
        59857.0,
        59857.1,
        59857.2,
        59857.3,
        59857.4,
        59857.5,
        59857.6,
        59857.7,
        59857.8,
        59858.01587262, 59858.3596845 ,
        59858.70349639, 59859.04730827, 59859.39112016, 59859.73493204
       ])
    # knots = np.array([
    #     59854.0,
    #     59854.5,
    #     59854.6,
    #     59854.7,
    #     59854.8,
    #     59854.9,
    #     59855.0,
    #     59855.06,
    #     59855.26537753,
    #     59856.06760526,
    #     59856.4,
    #     59856.5,
    #     59856.6,
    #     59856.7,
    #     59856.8,
    #     59856.9,
    #     59857.0,
    #     59857.1,
    #     59857.2,
    #     59857.3,
    #     59857.4,
    #     59857.5,
    #     59857.6,
    #     59857.7,
    #     59857.8,
    #     59858.47428846,
    #     59858.7,
    #     59859.2765162,
    #     59859.5])
    # k is a spline degree
    spline = LSQUnivariateSpline(t_segment, y_segment, knots, k=3)
    return spline(t_segment)


# llll
def segment_trend_by_spline_kind(
    t_segment: np.ndarray,
    y_segment: np.ndarray,
    kind: SplineKind,
) -> np.ndarray:
    """Approximate segment trend with the selected spline flavour."""
    t_segment = np.asarray(t_segment, dtype=float)
    y_segment = np.asarray(y_segment, dtype=float)
    if len(t_segment) != len(y_segment):
        raise ValueError("t_segment and y_segment must have the same length")

    if kind == "smoothing":
        return _trend_smoothing_spline_on_segment(
            t_segment,
            y_segment,
            SPLINE_SMOOTHING_S,
            SPLINE_SMOOTHING_REL,
        )
    if kind == "cubic_interp":
        return _trend_cubic_interpolating_spline_on_segment(t_segment, y_segment)
    n_interior_knots=20
    if kind == "lsq":
        return _trend_least_squares_spline_on_segment(
            t_segment,
            y_segment,
            n_interior_knots=n_interior_knots,
        )
    raise ValueError(f"unknown spline kind {kind!r}")

# lll
def spline_trend_by_segments(
    times: np.ndarray,
    values: np.ndarray,
    break_tolerance: float | None,
    kind: SplineKind,
) -> np.ndarray:
    """Fit spline trends independently on each cadence-contiguous segment."""
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    order = np.argsort(times)
    t_sorted = times[order]
    y_sorted = values[order]
    trend_sorted = np.empty(len(y_sorted), dtype=float)
    for seg_lo, seg_hi in contiguous_segment_bounds(t_sorted, break_tolerance):
        trend_sorted[seg_lo:seg_hi] = segment_trend_by_spline_kind(
            t_sorted[seg_lo:seg_hi],
            y_sorted[seg_lo:seg_hi],
            kind,
        )

    trend = np.empty(len(values), dtype=float)
    trend[order] = trend_sorted
    return trend


def _segment_too_short_for_window(
    segment_length: int,
    window_length: int,
    break_tolerance: float | None,
) -> bool:
    """Lightkurve-style fallback when a segment cannot host the full filter window."""
    if break_tolerance is None:
        return window_length > segment_length
    return window_length > segment_length or segment_length < break_tolerance


def _biweight_trend_on_segment(
    y_segment: np.ndarray,
    n_points: int,
    break_tolerance: float | None,
) -> np.ndarray:
    """Sliding biweight on one contiguous segment (no cross-gap windows)."""
    seg_len = len(y_segment)
    if seg_len == 0:
        return np.array([], dtype=float)

    window_length = max(int(n_points), 1)
    if _segment_too_short_for_window(seg_len, window_length, break_tolerance):
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


def _savitzky_golay_trend_on_segment(
    y_segment: np.ndarray,
    window_length: int,
    polyorder: int,
    break_tolerance: float | None,
) -> np.ndarray:
    """Savitzky-Golay on one contiguous segment (no cross-gap windows)."""
    seg_len = len(y_segment)
    if seg_len == 0:
        return np.array([], dtype=float)

    if _segment_too_short_for_window(seg_len, window_length, break_tolerance):
        fill = np.nanmedian(y_segment)
        return np.full(seg_len, fill, dtype=float)

    effective_polyorder = min(polyorder, window_length - 1)
    return savgol_filter(
        y_segment,
        window_length=window_length,
        polyorder=effective_polyorder,
        mode="interp",
    )


def sliding_median_trend(
    times: np.ndarray,
    flux: np.ndarray,
    window_days: float,
) -> np.ndarray:
    """Centre a time window of width ``window_days`` and take the median flux at each time.

    Args:
        times: Observation times (same unit as ``window_days``).
        flux: Flux samples aligned with ``times``.
        window_days: Full window width in time units (not a point count).

    Returns:
        Trend array aligned with the input ``times`` / ``flux`` order.
    """
    times = np.asarray(times, dtype=float)
    flux = np.asarray(flux, dtype=float)
    if window_days <= 0:
        raise ValueError("window_days must be positive")

    half = window_days / 2.0
    order = np.argsort(times)
    t_sorted = times[order]
    y_sorted = flux[order]
    n = len(t_sorted)
    trend_sorted = np.empty(n, dtype=float)
    for i in range(n):
        lo = np.searchsorted(t_sorted, t_sorted[i] - half, side="left")
        hi = np.searchsorted(t_sorted, t_sorted[i] + half, side="right")
        trend_sorted[i] = np.median(y_sorted[lo:hi])

    trend = np.empty(n, dtype=float)
    trend[order] = trend_sorted
    return trend


def sliding_biweight_trend(
    times: np.ndarray,
    values: np.ndarray,
    n_points: int,
    break_tolerance: float | None,
) -> np.ndarray:
    """Centred sliding biweight with gap-aware segmentation (sorted by time).

    Args:
        times: Observation times (used for sort order and gap detection).
        values: Flux or magnitude samples aligned with ``times``.
        n_points: Full window width in points within each contiguous segment.
        break_tolerance: Passed to ``contiguous_segment_bounds``; see module constant.

    Returns:
        Trend array aligned with the input ``times`` / ``values`` order.
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
            break_tolerance,
        )

    trend = np.empty(len(values), dtype=float)
    trend[order] = trend_sorted
    return trend


def _savitzky_golay_window_length(n_points: int) -> int:
    """Return an odd window length at least 3 (SciPy Savitzky-Golay requirement)."""
    window = max(int(n_points), 3)
    if window % 2 == 0:
        window += 1
    return window


def sliding_savitzky_golay_trend(
    times: np.ndarray,
    values: np.ndarray,
    n_points: int,
    polyorder: int,
    break_tolerance: float | None,
) -> np.ndarray:
    """Savitzky-Golay trend with gap-aware segmentation (window in points).

    Args:
        times: Observation times (sort order and gap detection).
        values: Flux or magnitude samples aligned with ``times``.
        n_points: Target full window width in points (adjusted to odd if needed).
        polyorder: Local polynomial degree (must be less than window length).
        break_tolerance: Gap multiplier on ``median(delta t)``; ``None`` for no splits.

    Returns:
        Trend array aligned with the input ``times`` / ``values`` order.
    """
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    window_length = _savitzky_golay_window_length(n_points)
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
            break_tolerance,
        )

    trend = np.empty(len(values), dtype=float)
    trend[order] = trend_sorted
    return trend


def plot_raw_lightcurve(df: pd.DataFrame, value_col: str, invert_y:bool) -> None:
    """Scatter plot of the cut light curve."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(
        df[TIME_COLUMN],
        df[value_col],
        ".",
        markersize=10,
        alpha=0.5,
        label="observed",
    )
    ax.set_xlabel("obs_time (d)")
    ax.set_ylabel("phot")
    ax.set_title("Raw light curve")
    if invert_y:
        ax.invert_yaxis()
    ax.legend()
    fig.tight_layout()
    plt.show()


def plot_lightcurve_with_trend(
    df: pd.DataFrame,
    trend: np.ndarray,
    value_col: str,
    *,
    title: str,
    invert_y: bool,
    trend_label: str = "trend",
) -> None:
    """Observed light curve plus overlaid trend curve."""

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(
        df[TIME_COLUMN],
        df[value_col],
        ".",
        markersize=10,
        alpha=0.5,
        label="observed",
    )
    ax.plot(
        df[TIME_COLUMN],
        trend,
        "-",
        color="C1",
        linewidth=2,
        label=trend_label,
    )
    ax.set_xlabel("obs_time (d)")
    ax.set_ylabel("phot")
    ax.set_title(title)
    if invert_y:
        ax.invert_yaxis()
    ax.legend()
    fig.tight_layout()
    plt.show()


def trend_sliding_median(
    df: pd.DataFrame,
    window_days: float,
    invert_y: bool,
) -> np.ndarray:
    """
        Estimate trend via time-window sliding median and plot.
        Always uses phot and phot_err columns
    """
    trend = sliding_median_trend(
        df[TIME_COLUMN].to_numpy(),
        df[PHOT_COLUMN].to_numpy(),
        window_days,
    )
    plot_lightcurve_with_trend(
        df,
        trend,
        PHOT_COLUMN,
        title=f"Sliding median trend (window = {window_days} d)",
        invert_y=invert_y,
        trend_label="sliding median trend",
    )
    return trend


def trend_sliding_biweight(
    df: pd.DataFrame,
    n_points: int,
    invert_y: bool,
    break_tolerance: float | None,
) -> np.ndarray:
    """Estimate trend via point-window sliding biweight and plot (uses ``PHOT_COLUMN``)."""
    trend = sliding_biweight_trend(
        df[TIME_COLUMN].to_numpy(),
        df[PHOT_COLUMN].to_numpy(),
        n_points,
        break_tolerance,
    )
    plot_lightcurve_with_trend(
        df,
        trend,
        PHOT_COLUMN,
        title=f"Sliding biweight trend (window = {n_points} points)",
        invert_y=invert_y,
        trend_label="sliding biweight trend",
    )
    return trend


def trend_savitzky_golay(
    df: pd.DataFrame,
    n_points: int,
    polyorder: int,
    invert_y: bool,
    break_tolerance: float | None, 
) -> np.ndarray:
    """Estimate trend via Savitzky-Golay filter and plot (uses ``PHOT_COLUMN``)."""
    window_length = _savitzky_golay_window_length(n_points)
    trend = sliding_savitzky_golay_trend(
        df[TIME_COLUMN].to_numpy(),
        df[PHOT_COLUMN].to_numpy(),
        n_points,
        polyorder,
        break_tolerance,
    )
    plot_lightcurve_with_trend(
        df,
        trend,
        PHOT_COLUMN,
        title=(
            f"Savitzky-Golay trend (window = {window_length} points, "
            f"polyorder = {polyorder})"
        ),
        invert_y=invert_y,
        trend_label="Savitzky-Golay trend",
    )
    return trend


def trend_lightkurve_flatten(
    df: pd.DataFrame,
    window_length: int,
    polyorder: int,
    break_tolerance: float | None,
    invert_y: bool,
) -> pd.DataFrame:
    """Estimate trend with ``LightCurve.flatten`` (Savitzky-Golay), plot, store in ``TREND_COLUMN``.

    Args:
        df: Light curve with ``TIME_COLUMN`` and ``PHOT_COLUMN`` (flux or mag in column).
        window_length: Target SG window in points (adjusted to odd).
        polyorder: SG polynomial order.
        break_tolerance: Lightkurve gap multiplier; ``None`` disables segment splitting.
        invert_y: Invert y-axis when plotting magnitudes.

    Returns:
        Copy of ``df`` with the fitted trend in ``TREND_COLUMN``.
    """
    window_length = _savitzky_golay_window_length(window_length)
    times = df[TIME_COLUMN].to_numpy(dtype=float)
    flux = df[PHOT_COLUMN].to_numpy(dtype=float)

    flux_err = None
    if PHOT_ERR_COLUMN in df.columns:
        err = df[PHOT_ERR_COLUMN].to_numpy(dtype=float)
        if np.all(np.isfinite(err)):
            flux_err = err

    lc = lk.LightCurve(time=times, flux=flux, flux_err=flux_err)
    _, trend_lc = lc.flatten(
        window_length=window_length,
        polyorder=polyorder,
        break_tolerance=break_tolerance,
        return_trend=True,
    )

    trend = np.asarray(trend_lc.flux, dtype=float)
    if trend.shape != flux.shape:
        raise ValueError("Lightkurve trend length does not match input light curve")

    out = df.copy()
    out[TREND_COLUMN] = trend

    plot_lightcurve_with_trend(
        out,
        out[TREND_COLUMN].to_numpy(),
        PHOT_COLUMN,
        title=(
            f"Lightkurve flatten trend (window = {window_length} points, "
            f"polyorder = {polyorder}, break_tolerance = {break_tolerance})"
        ),
        invert_y=invert_y,
        trend_label="Lightkurve flatten trend",
    )
    return out

# lll
def _pspline_second_difference_matrix(n_coeffs: int) -> np.ndarray:
    """Matrix ``D`` so ``||D c||^2`` penalises second differences of B-spline coefficients."""
    if n_coeffs <= 2:
        return np.zeros((0, n_coeffs))
    return np.diff(np.eye(n_coeffs), n=2, axis=0)


def p_spline_trend(
    t: np.ndarray,
    y: np.ndarray,
    penalty_lambda: float,
    n_segments: int,
    spline_degree: int = 3,
) -> np.ndarray:
    """P-spline trend for one contiguous segment (times need not be sorted).

    Args:
        t: Observation times.
        y: Flux or magnitudes.
        penalty_lambda: Roughness penalty (larger -> smoother trend).
        n_segments: Number of equispaced intervals on ``[min(t), max(t)]`` for B-spline knots.
        spline_degree: B-spline degree (default cubic).

    Returns:
        Trend aligned with the input ``t`` / ``y`` order.
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
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


def fit_pspline_lightcurve_segment(
    df: pd.DataFrame,
    penalty_lambda: float,
    n_segments: int,
    detrend_mode: Literal["mag", "flux"],
    invert_y: bool,
) -> pd.DataFrame:
    """Fit P-spline trend on ``df`` (single segment), plot trend and detrended residual.

    Does not split on gaps; ``df`` must already be the intended segment.

    Args:
        df: Light curve with ``TIME_COLUMN`` and ``PHOT_COLUMN``.
        penalty_lambda: P-spline roughness penalty.
        n_segments: Equispaced B-spline segment count on the time span.
        detrend_mode: ``"mag"`` subtracts trend; ``"flux"`` divides by trend.
        invert_y: Invert y-axis on magnitude plots.

    Returns:
        Copy of ``df`` with ``PSPLINE_TREND_COLUMN`` set.
    """
    times = df[TIME_COLUMN].to_numpy(dtype=float)
    observed = df[PHOT_COLUMN].to_numpy(dtype=float)
    trend = p_spline_trend(times, observed, penalty_lambda, n_segments)

    out = df.copy()
    out[PSPLINE_TREND_COLUMN] = trend

    plot_lightcurve_with_trend(
        out,
        trend,
        PHOT_COLUMN,
        title=(
            f"P-spline trend (lambda = {penalty_lambda:g}, "
            f"n_segments = {n_segments})"
        ),
        invert_y=invert_y,
        trend_label="P-spline trend",
    )

    if detrend_mode == "mag":
        detrended = detrend_observed(observed, trend, "mag")
        ylabel = r"$\Delta$mag (obs $-$ trend)"
        detrend_title = "P-spline detrended (magnitude subtraction)"
        det_invert = True
    elif detrend_mode == "flux":
        detrended = detrend_observed(observed, trend, "flux")
        ylabel = "flux / trend"
        detrend_title = "P-spline detrended (flux division)"
        det_invert = False
    else:
        raise ValueError(f"detrend_mode must be 'mag' or 'flux', got {detrend_mode!r}")

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(
        out[TIME_COLUMN],
        detrended,
        ".",
        markersize=10,
        alpha=0.5,
        label="detrended",
    )
    ax.set_xlabel("obs_time (d)")
    ax.set_ylabel(ylabel)
    ax.set_title(detrend_title)
    if det_invert:
        ax.invert_yaxis()
    ax.legend()
    fig.tight_layout()
    plt.show()

    return out


def trend_spline_segments(
    df: pd.DataFrame,
    spline_kind: SplineKind,
    break_tolerance: float | None,
    invert_y: bool,
) -> pd.DataFrame:
    """Split by gaps, fit per-segment splines, plot, store trend in ``SPLINE_TREND_COLUMN``."""
    trend = spline_trend_by_segments(
        df[TIME_COLUMN].to_numpy(),
        df[PHOT_COLUMN].to_numpy(),
        break_tolerance,
        spline_kind,
    )
    out = df.copy()
    out[SPLINE_TREND_COLUMN] = trend

    plot_lightcurve_with_trend(
        out,
        trend,
        PHOT_COLUMN,
        title=(
            f"Segment spline trend ({spline_kind}, "
            f"break_tolerance = {break_tolerance})"
        ),
        invert_y=invert_y,
        trend_label=f"spline trend ({spline_kind})",
    )
    return out


def detrend_and_plot(
    df: pd.DataFrame,
    trend: np.ndarray,
    mode: Literal["mag", "flux"],
    save: Path | str | None = None,
) -> np.ndarray:
    """Remove trend from the light curve and plot the residual.

    Args:
        df: Light curve table (times from ``TIME_COLUMN``).
        trend: Trend estimate aligned row-for-row with ``df``.
        mode: ``"mag"`` subtracts trend; ``"flux"`` divides observed by trend.
        save: If set, write ``TIME_COLUMN``, ``PHOT_COLUMN``, trend, and detrended to CSV.

    Returns:
        Detrended samples aligned with ``df``.
    """
    observed = df[PHOT_COLUMN].to_numpy(dtype=float)
    trend = np.asarray(trend, dtype=float)
    if len(observed) != len(trend):
        raise ValueError("observed and trend must have the same length")

    detrended = detrend_observed(observed, trend, mode)

    if mode == "mag":
        ylabel = r"$\Delta$mag (obs $-$ trend)"
        invert_y = True
        title = "Detrended light curve (magnitude subtraction)"
    elif mode == "flux":
        ylabel = "flux / trend"
        invert_y = False
        title = "Detrended light curve (flux division)"
    else:
        raise ValueError(f"mode must be 'mag' or 'flux', got {mode!r}")

    if save is not None:
        export = pd.DataFrame(
            {
                TIME_COLUMN: df[TIME_COLUMN].to_numpy(),
                "detrended": detrended,
            }
        )
        if PHOT_ERR_COLUMN in df.columns:
            export[PHOT_ERR_COLUMN] = detrended_standard_error(
                observed,
                trend,
                df[PHOT_ERR_COLUMN].to_numpy(dtype=float),
                mode,
            )
        export.to_csv(Path(save), index=False)

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(
        df[TIME_COLUMN],
        detrended,
        ".",
        markersize=10,
        alpha=0.5,
        label="detrended",
    )
    ax.set_xlabel("obs_time (d)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if invert_y:
        ax.invert_yaxis()
    ax.legend()
    fig.tight_layout()
    plt.show()
    return detrended


def _apply_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.size": FONT_SIZE,
            "axes.labelsize": FONT_SIZE,
            "axes.titlesize": FONT_SIZE,
            "xtick.labelsize": FONT_SIZE,
            "ytick.labelsize": FONT_SIZE,
            "legend.fontsize": FONT_SIZE,
        }
    )


def main() -> None:
    _apply_plot_style()
    
    path_to_data = DATA_FILE
    if path_to_data.suffix.lower() == ".vot":
        df = load_tcp_vot(path_to_data)
    elif path_to_data.suffix.lower() == ".csv":
        df = load_detrended_csv(path_to_data)
    
    df = cut_by_time_limits(df, TIME_COLUMN, JD_MIN, JD_MAX)

    n_points_window = None
    if ESTIMATE_N_POINTS_WINDOW:
        import sys
        n_points_window = estimate_sliding_window_n_points(
            df,
            TIME_COLUMN,
            WINDOW_ESTIMATE_T_LEFT,
            WINDOW_ESTIMATE_T_RIGHT,
            MEDIAN_WINDOW_DAYS,
        )
        print(f"{n_points_window=} points corresponded to {MEDIAN_WINDOW_DAYS} d" )
        sys.exit(0)

    plot_raw_lightcurve(df, PHOT_COLUMN, invert_y=False)
    if DETREND_MODE == "mag":
        df = add_magnitudes(df, flux_col=PHOT_COLUMN, flux_err_col=PHOT_ERR_COLUMN,
            mag_col=MAG_COLUMN, mag_err_col='mag_err', 
            zero_point=MAG_ZERO_POINT)
        df[PHOT_COLUMN] = df[MAG_COLUMN]
        df[PHOT_ERR_COLUMN] = df['mag_err']
    
    method: Method      
    method = 'spline'
    # method = 'pspline'
    if method == 'biweight':
        trend = trend_sliding_biweight(
            df=df, 
            n_points=N_POINTS,
            invert_y=DETREND_MODE == "mag",
            break_tolerance=BREAK_TOLERANCE)
    elif method == 'SG':
        trend = trend_savitzky_golay(
            df=df, 
            n_points=N_POINTS, 
            polyorder=SG_POLYORDER, 
            invert_y=DETREND_MODE=="mag",
            break_tolerance=BREAK_TOLERANCE,
        )
        detrend_and_plot(df, trend, DETREND_MODE, save=DETREND_LK_CSV)
    
    elif method == "LK":
        df = trend_lightkurve_flatten(
            df=df,
            n_points=N_POINTS,
            polyorder=SG_POLYORDER,
            break_tolerance=BREAK_TOLERANCE,
            invert_y=DETREND_MODE == "mag")
        
        detrend_and_plot(
            df,
            df[TREND_COLUMN].to_numpy(),
            DETREND_MODE,
            save=None
            )

    elif method == 'spline':
        # SplineKind = Literal["smoothing", "cubic_interp", "lsq"]
        # do not use cubic_interp -- it tryis to pass throgh all points
        spline_kind = "lsq"
        # spline_kind = "smoothing"
        df = trend_spline_segments(
            df=df,
            spline_kind=spline_kind,
            break_tolerance=BREAK_TOLERANCE,
            invert_y=DETREND_MODE == "mag",
        )
        detrend_and_plot(df, df[SPLINE_TREND_COLUMN].to_numpy(), 
            DETREND_MODE, save=DETREND_SPLINE_CSV)

    elif method == 'pspline':
        fit_pspline_lightcurve_segment(
            df,
            PSPLINE_PENALTY_LAMBDA,
            PSPLINE_N_SEGMENTS,
            DETREND_MODE,
            invert_y=DETREND_MODE == "mag",
        )


if __name__ == "__main__":
    main()
