"""Build MAVKA fit summary figures for the extrema modeller page."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, TIME_AXIS_MJD
from skvo_veb.utils.lc_figure import absolute_jd_to_plot_x, apply_time_xaxis_format
from skvo_veb.utils.mavka.config import MAVKA_METHOD_A_COLOUR, MAVKA_PIECE_COLOURS
from skvo_veb.utils.mavka.models import ApproxFitResult, model_curve

_SEGMENT_POINTS = 200
_FULL_CURVE_POINTS = 500


def _piecewise_time_grids(
    method: str,
    t_min: float,
    t_max: float,
    c4: float,
    c5: float,
) -> list[tuple[str, np.ndarray, str, float]]:
    """Builds time grids for left, core, and right model pieces.

    Args:
        method (str): Approximation method id.
        t_min (float): Interval start (absolute JD).
        t_max (float): Interval stop (absolute JD).
        c4 (float): Left junction (absolute JD).
        c5 (float): Right junction (absolute JD).

    Returns:
        list[tuple]: ``(name, times, colour, line_width)`` for each drawn piece.

    Raises:
        ValueError: If no left, core, or right segment falls in the time window.
    """
    if method == "A" or not (np.isfinite(c4) and np.isfinite(c5)):
        colour = MAVKA_METHOD_A_COLOUR if method == "A" else MAVKA_PIECE_COLOURS["core"]
        t_line = np.linspace(t_min, t_max, _FULL_CURVE_POINTS)
        return [("model", t_line, colour, 2.0)]

    pieces: list[tuple[str, np.ndarray, str, float]] = []
    left_hi = min(c4, t_max)
    if left_hi > t_min:
        pieces.append(
            (
                "left",
                np.linspace(t_min, left_hi, _SEGMENT_POINTS),
                MAVKA_PIECE_COLOURS["left"],
                2.0,
            )
        )
    core_lo = max(c4, t_min)
    core_hi = min(c5, t_max)
    if core_hi > core_lo:
        pieces.append(
            (
                "core",
                np.linspace(core_lo, core_hi, _SEGMENT_POINTS),
                MAVKA_PIECE_COLOURS["core"],
                2.5,
            )
        )
    right_lo = max(c5, t_min)
    if t_max > right_lo:
        pieces.append(
            (
                "right",
                np.linspace(right_lo, t_max, _SEGMENT_POINTS),
                MAVKA_PIECE_COLOURS["right"],
                2.0,
            )
        )
    if not pieces:
        raise ValueError(
            f"No MAVKA model pieces to plot (C4={c4}, C5={c5}, "
            f"t=[{t_min}, {t_max}])"
        )
    return pieces


def figure_from_mavka_result(
    t_obs: np.ndarray,
    y_obs: np.ndarray,
    fit: ApproxFitResult,
    *,
    display_epoch: float = DEFAULT_EPOCH_JD,
    invert_y: bool = False,
    y_label: str = "Magnitude",
) -> go.Figure:
    """Build a Plotly figure for one successful MAVKA interval fit.

    Times are shown in MJD (``JD - display_epoch``), matching the prep light curve.

    Args:
        t_obs (numpy.ndarray): Absolute JD of the interval points.
        y_obs (numpy.ndarray): Photometry in the working Mag/Flux view.
        fit (ApproxFitResult): Successful fit (``ok`` must be true).
        display_epoch (float): Reference subtracted for the x-axis.
        invert_y (bool): Reverse the y-axis (magnitude convention).
        y_label (str): Y-axis title.

    Returns:
        plotly.graph_objects.Figure: Data, model curve, junctions, and TOM markers.

    Raises:
        ValueError: If ``fit.ok`` is false or arrays are empty.
    """
    if not fit.ok:
        raise ValueError("Cannot build a MAVKA figure for a failed fit")
    t_obs = np.asarray(t_obs, dtype=float)
    y_obs = np.asarray(y_obs, dtype=float)
    if t_obs.size == 0:
        raise ValueError("Cannot build a MAVKA figure from an empty interval")

    def _plot_x(jd_values):
        return absolute_jd_to_plot_x(jd_values, TIME_AXIS_MJD, display_epoch)

    x = np.asarray(_plot_x(t_obs), dtype=float)
    t_min = float(np.min(t_obs))
    t_max = float(np.max(t_obs))
    pieces = _piecewise_time_grids(
        fit.method, t_min, t_max, float(fit.c4), float(fit.c5)
    )

    tom_mjd = float(_plot_x(fit.t_ext))
    tom_std_mjd = (
        float(fit.sigma_t_ext) if np.isfinite(fit.sigma_t_ext) else float("nan")
    )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y_obs,
            mode="markers",
            marker=dict(color="black", size=6),
            hovertemplate="Data: %{y:.4f}<extra></extra>",
            name="Data",
        )
    )
    for name, t_seg, colour, width in pieces:
        y_seg = model_curve(fit.method, fit.params, t_seg)
        fig.add_trace(
            go.Scatter(
                x=np.asarray(_plot_x(t_seg), dtype=float),
                y=y_seg,
                mode="lines",
                line=dict(color=colour, width=width),
                hovertemplate="Model: %{y:.4f}<extra></extra>",
                name=name.capitalize(),
            )
        )
    if np.isfinite(fit.c4):
        fig.add_vline(
            x=float(_plot_x(fit.c4)),
            line_width=1.5,
            line_dash="dot",
            line_color="maroon",
        )
    if np.isfinite(fit.c5):
        fig.add_vline(
            x=float(_plot_x(fit.c5)),
            line_width=1.5,
            line_dash="dot",
            line_color="maroon",
        )
    fig.add_vline(x=tom_mjd, line_width=2, line_dash="dash", line_color="magenta")
    if np.isfinite(tom_std_mjd):
        fig.add_vrect(
            x0=tom_mjd - tom_std_mjd,
            x1=tom_mjd + tom_std_mjd,
            fillcolor="magenta",
            opacity=0.1,
            layer="below",
            line_width=0,
        )
        fig.add_vline(
            x=tom_mjd - tom_std_mjd,
            line_width=1.5,
            line_dash="dot",
            line_color="magenta",
        )
        fig.add_vline(
            x=tom_mjd + tom_std_mjd,
            line_width=1.5,
            line_dash="dot",
            line_color="magenta",
        )

    fig.update_layout(
        margin=dict(l=0, r=10, t=20, b=20),
        showlegend=False,
        title=dict(text=f"   TOM: {tom_mjd:.2f}", font=dict(size=14), y=0.95),
        template="plotly_white",
        height=400,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.9)",
            font_size=12,
            font_family="Rockwell",
        ),
        yaxis_title=y_label,
    )
    if invert_y:
        fig.update_yaxes(autorange="reversed")
    apply_time_xaxis_format(fig, phase_view=False, time_axis_mode=TIME_AXIS_MJD)
    return fig
