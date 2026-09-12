"""Scientific defaults for the Lightcurve processor.

All algorithm knobs live here: constant fallbacks and any period-scaled
formulae. The page must not invent its own scientific numbers.

When the Light curve period field holds a positive ``P`` (days), the
marked formulae replace the constant fallback for that knob. Empty or
non-positive period uses the constant.
"""

from __future__ import annotations

import logging

import numpy as np

from skvo_veb.utils.my_tools import safe_float

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared: gap split (all smoothers)
# ---------------------------------------------------------------------------
# Cut the crop into independent pieces wherever consecutive Δt exceeds this
# many days. Times are Julian Date, so the difference is already in days.
DEFAULT_BREAK_TOLERANCE_DAYS = 0.7


# ---------------------------------------------------------------------------
# Sliding median
# ---------------------------------------------------------------------------
# Calendar-time window (days). T at t_i is the median inside [t_i − W/2, t_i + W/2].
DEFAULT_MEDIAN_WINDOW_DAYS = 2.0


# ---------------------------------------------------------------------------
# Sliding biweight
# ---------------------------------------------------------------------------
# Centred point window (odd-preferred). Short pieces use nanmedian.
DEFAULT_BIWEIGHT_N_POINTS = 301


# ---------------------------------------------------------------------------
# Savitzky–Golay and Lightkurve flatten
# ---------------------------------------------------------------------------
# Point window (even values are bumped to odd) and polynomial order.
DEFAULT_SAVGOL_N_POINTS = 301
DEFAULT_SAVGOL_POLYORDER = 5


# ---------------------------------------------------------------------------
# Smoothing spline (SciPy UnivariateSpline)
# ---------------------------------------------------------------------------
# Relative smoothing sets s from the scatter when the explicit s box is empty.
DEFAULT_SPLINE_SMOOTH_REL = 0.05


# ---------------------------------------------------------------------------
# Least-squares spline
# ---------------------------------------------------------------------------
DEFAULT_LSQ_N_KNOTS = 20
DEFAULT_LSQ_KNOT_GRID = "occupancy"  # "uniform" or "occupancy"


# ---------------------------------------------------------------------------
# P-spline
# ---------------------------------------------------------------------------
DEFAULT_PSPLINE_LAMBDA = 1.0e4
DEFAULT_PSPLINE_SEGMENTS = 40


# ---------------------------------------------------------------------------
# Running parabola
# ---------------------------------------------------------------------------
# Constant fallbacks when no period is set.
DEFAULT_RP_WINDOW_DAYS = 0.05
DEFAULT_RP_MIN_POINTS = 5

# If P is known: window = P * RP_WINDOW_PERIOD_FACTOR
RP_WINDOW_PERIOD_FACTOR = 0.5

# Step is always a fraction of the resolved window (fallback or period-scaled):
#   step = window * RP_STEP_WINDOW_FRACTION
RP_STEP_WINDOW_FRACTION = 0.25
DEFAULT_RP_STEP_DAYS = DEFAULT_RP_WINDOW_DAYS * RP_STEP_WINDOW_FRACTION


# ---------------------------------------------------------------------------
# Rough extrema
# ---------------------------------------------------------------------------
# Constant fallbacks when no period is set.
DEFAULT_MIN_PEAK_DISTANCE_DAYS = 0.3
DEFAULT_INTERVAL_DELTA_DAYS = 0.025

# Finite overlay samples required in a run before find_peaks is allowed.
# Below 3 a peak cannot have two neighbours. Not period-scaled.
MIN_EXTREMA_SEGMENT_POINTS_FLOOR = 3
DEFAULT_MIN_EXTREMA_SEGMENT_POINTS = 5

# If P is known:
#   min. peak distance = P * MIN_PEAK_DISTANCE_PERIOD_FACTOR
#   interval half-width = P * INTERVAL_DELTA_PERIOD_FACTOR
MIN_PEAK_DISTANCE_PERIOD_FACTOR = 0.7
INTERVAL_DELTA_PERIOD_FACTOR = 1.0 / 3.0


# Decimal places shown in the calculated Input widgets (window, step,
# min. peak distance, interval half-width).
DISPLAY_DECIMALS = 3


def display_number(value: float) -> float:
    """Rounds a float for an Input widget.

    Args:
        value (float): Full-precision number.

    Returns:
        float: Value rounded to ``DISPLAY_DECIMALS`` places.
    """
    return float(round(float(value), int(DISPLAY_DECIMALS)))


def positive_period_days(period) -> float | None:
    """Returns a positive finite period in days, or ``None``.

    Args:
        period: Sidebar period widget value.

    Returns:
        float | None: Period in days when it can be used, otherwise ``None``.
    """
    value = safe_float(period)
    if value is None or not np.isfinite(value) or value <= 0.0:
        return None
    return float(value)


def resolve_widget_defaults(period) -> tuple[float, float, float, float]:
    """Resolves RP window, RP step, peak distance, and interval δ.

    Args:
        period: Sidebar period in days, or empty.

    Returns:
        tuple: ``(rp_window_days, rp_step_days, min_peak_distance_days,
        interval_delta_days)``.
    """
    p = positive_period_days(period)
    if p is None:
        window = DEFAULT_RP_WINDOW_DAYS
        distance = DEFAULT_MIN_PEAK_DISTANCE_DAYS
        delta = DEFAULT_INTERVAL_DELTA_DAYS
    else:
        window = p * RP_WINDOW_PERIOD_FACTOR
        distance = p * MIN_PEAK_DISTANCE_PERIOD_FACTOR
        delta = p * INTERVAL_DELTA_PERIOD_FACTOR
    step = window * RP_STEP_WINDOW_FRACTION
    logger.debug(
        "Processor defaults: P=%s d -> window=%s, step=%s, min_distance=%s, delta=%s",
        p,
        window,
        step,
        distance,
        delta,
    )
    return (
        display_number(window),
        display_number(step),
        display_number(distance),
        display_number(delta),
    )
