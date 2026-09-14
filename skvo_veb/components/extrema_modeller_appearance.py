"""Graphic configuration for the Extrema modeller page (``/gp``).

Science (fit defaults) stays in ``utils/gp|mavka|parabola_tom/config.py``.
Photometric zero-point fallbacks for incomplete uploads live in ``lc_config``.
Change display time, card grid, card plot height, and trace colours here.
"""

from __future__ import annotations

import math

import numpy as np

from skvo_veb.utils.lc_config import JD_TO_MJD, TIME_AXIS_MJD

# --- Display time (plots, epoch fields, O-C, failed-card popovers, export) ---
# The origin is the only switch; ``page_time_label()`` names it for the UI.
# ``JD_TO_MJD`` (2400000.5) → MJD.  ``0.0`` → JD.  Any other float → JD-<origin>
# (for example 2450000.0 → JD-2450000).  Reduced JD 2400000.0 is not MJD.
PAGE_DISPLAY_EPOCH_JD = JD_TO_MJD
# PAGE_DISPLAY_EPOCH_JD = 0.0
# PAGE_DISPLAY_EPOCH_JD = 2450000.0

# Numeric Plotly axis (not calendar Date). The radio still offers Date separately.
PAGE_TIME_AXIS_MODE = TIME_AXIS_MJD

# --- Live and review card grid (Bootstrap 12-column row) ---
CARDS_PER_ROW = 3
CARD_ROWS_PER_PAGE = 2

if CARDS_PER_ROW < 1:
    raise ValueError(f"CARDS_PER_ROW must be at least 1; got {CARDS_PER_ROW}.")
if CARD_ROWS_PER_PAGE < 1:
    raise ValueError(
        f"CARD_ROWS_PER_PAGE must be at least 1; got {CARD_ROWS_PER_PAGE}."
    )
if 12 % CARDS_PER_ROW != 0:
    raise ValueError(
        f"CARDS_PER_ROW={CARDS_PER_ROW} does not divide Bootstrap's 12-column row."
    )

CARD_COL_WIDTH = 12 // CARDS_PER_ROW
PAGE_SIZE = CARDS_PER_ROW * CARD_ROWS_PER_PAGE

# Plotly height for every live/review card (success and failed).
REVIEW_CARD_PLOT_HEIGHT = 300

# Trace paint (not physics).
MAVKA_PIECE_COLOURS = {
    "left": "#6a3d9a",
    "core": "#33a02c",
    "right": "#ff7f00",
}
MAVKA_METHOD_A_COLOUR = "#9467bd"
PARABOLA_LINE_COLOUR = "#1f77b4"


def _origin_for_label(origin: float) -> str:
    """Formats a non-standard display origin for ``JD-<origin>`` captions.

    Args:
        origin (float): Julian Date subtracted from absolute JD.

    Returns:
        str: Integer text when the origin is a whole number, otherwise ``:g``.
    """
    if origin == int(origin):
        return str(int(origin))
    return f"{origin:g}"


def page_time_label() -> str:
    """Returns the short name of the page display time scale.

    Derived from ``PAGE_DISPLAY_EPOCH_JD`` only. MJD is the IAU name for
    ``JD - 2400000.5``; any other origin keeps an explicit ``JD-`` caption.

    Returns:
        str: ``MJD``, ``JD``, or ``JD-<origin>`` for a non-standard origin.
    """
    origin = float(PAGE_DISPLAY_EPOCH_JD)
    if origin == 0.0:
        return "JD"
    if origin == float(JD_TO_MJD):
        return "MJD"
    return f"JD-{_origin_for_label(origin)}"


def page_epoch_addon_label() -> str:
    """Returns the Epoch input-group caption for this page.

    Returns:
        str: For example ``Epoch (MJD)`` or ``Epoch (JD-2450000)``.
    """
    return f"Epoch ({page_time_label()})"


def page_numeric_axis_title(timesys_suffix: str = "") -> str:
    """Returns the numeric (non-Date) axis title for this page.

    Args:
        timesys_suffix (str): Optional ingested TIMESYS suffix, e.g. `` (TCB)``.

    Returns:
        str: ``MJD``, ``JD``, or ``JD-<origin>``, plus the suffix when present.
    """
    label = page_time_label()
    if timesys_suffix:
        return f"{label}{timesys_suffix}"
    return label


def format_page_fit_title(
    jd_abs,
    *,
    kind: str,
    digits: int = 2,
    epoch: float | None = None,
) -> str:
    """Formats a live/review card title with the page time scale.

    Args:
        jd_abs: Absolute Julian Date of the peak or ToM.
        kind (str): ``Peak`` or ``ToM``.
        digits (int): Decimal places for the displayed time.
        epoch (float | None): Origin subtracted; default ``PAGE_DISPLAY_EPOCH_JD``.

    Returns:
        str: For example ``   Peak (MJD): 60829.96``.
    """
    value = format_page_time(jd_abs, digits=digits, epoch=epoch)
    if value is None:
        return f"   {kind} ({page_time_label()})"
    return f"   {kind} ({page_time_label()}): {value}"


def format_vertex_outside_window(
    vertex_jd,
    jd_min,
    jd_max,
    *,
    digits: int = 6,
    epoch: float | None = None,
) -> str:
    """Formats a parabola out-of-window failure in the page display scale.

    Args:
        vertex_jd: Rejected vertex (absolute JD).
        jd_min: Inclusive window start (absolute JD).
        jd_max: Inclusive window stop (absolute JD).
        digits (int): Decimal places.
        epoch (float | None): Origin to subtract; default ``PAGE_DISPLAY_EPOCH_JD``.

    Returns:
        str: Reason with page-scale times and the scale name in parentheses.
    """
    vertex = format_page_time(vertex_jd, digits=digits, epoch=epoch)
    lo = format_page_time(jd_min, digits=digits, epoch=epoch)
    hi = format_page_time(jd_max, digits=digits, epoch=epoch)
    scale = page_time_label()
    if vertex is None or lo is None or hi is None:
        return f"Parabola vertex lies outside the fit window ({scale})"
    return (
        f"Parabola vertex {vertex} lies outside the fit window [{lo}, {hi}] ({scale})"
    )


def to_page_time(jd_abs, *, epoch: float | None = None):
    """Converts absolute Julian Date(s) to the page display scale.

    Args:
        jd_abs: Scalar or array-like absolute JD.
        epoch (float | None): Origin to subtract; default ``PAGE_DISPLAY_EPOCH_JD``.

    Returns:
        float or numpy.ndarray: ``jd_abs - epoch``.
    """
    origin = float(PAGE_DISPLAY_EPOCH_JD if epoch is None else epoch)
    if np.isscalar(jd_abs):
        return float(jd_abs) - origin
    arr = np.asarray(jd_abs, dtype=float)
    return arr - origin


def from_page_time(page_value, *, epoch: float | None = None):
    """Converts page display time(s) back to absolute Julian Date.

    Args:
        page_value: Scalar or array-like display time (MJD when the origin is MJD).
        epoch (float | None): Origin that was subtracted; default
            ``PAGE_DISPLAY_EPOCH_JD``.

    Returns:
        float or numpy.ndarray: ``page_value + epoch``.
    """
    origin = float(PAGE_DISPLAY_EPOCH_JD if epoch is None else epoch)
    if np.isscalar(page_value):
        return float(page_value) + origin
    arr = np.asarray(page_value, dtype=float)
    return arr + origin


def format_page_time(jd_abs, *, digits: int = 2, epoch: float | None = None) -> str | None:
    """Formats one absolute JD as a page-scale number.

    Args:
        jd_abs: Absolute Julian Date.
        digits (int): Decimal places.
        epoch (float | None): Origin to subtract; default ``PAGE_DISPLAY_EPOCH_JD``.

    Returns:
        str | None: Formatted value, or ``None`` when the input is not finite.
    """
    try:
        value = to_page_time(jd_abs, epoch=epoch)
    except (TypeError, ValueError):
        return None
    if value is None or not math.isfinite(float(value)):
        return None
    return f"{float(value):.{int(digits)}f}"


def format_page_time_range(
    jd_min,
    jd_max,
    *,
    digits: int = 2,
    epoch: float | None = None,
) -> str | None:
    """Formats an absolute-JD window in the page display scale.

    Args:
        jd_min: Inclusive start (absolute JD).
        jd_max: Inclusive stop (absolute JD).
        digits (int): Decimal places.
        epoch (float | None): Origin to subtract; default ``PAGE_DISPLAY_EPOCH_JD``.

    Returns:
        str | None: e.g. ``MJD: 60829.96-60829.98``, or ``None`` if bounds are missing.
    """
    lo = format_page_time(jd_min, digits=digits, epoch=epoch)
    hi = format_page_time(jd_max, digits=digits, epoch=epoch)
    if lo is None or hi is None:
        return None
    return f"{page_time_label()}: {lo}-{hi}"
