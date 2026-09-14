"""Build parabola ToM summary figures for the extrema modeller page."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from skvo_veb.components.extrema_modeller_appearance import (
    PAGE_DISPLAY_EPOCH_JD,
    PAGE_TIME_AXIS_MODE,
    PARABOLA_LINE_COLOUR,
    REVIEW_CARD_PLOT_HEIGHT,
    format_page_fit_title,
)
from skvo_veb.utils.lc_figure import (
    absolute_jd_to_plot_x,
    apply_time_xaxis_format,
    maybe_interval_observations_figure,
)
from skvo_veb.utils.parabola_tom.pipeline import ParabolaFitResult

_CURVE_POINTS = 400


def figure_from_parabola_result(
    t_obs: np.ndarray,
    y_obs: np.ndarray,
    fit: ParabolaFitResult,
    *,
    display_epoch: float = PAGE_DISPLAY_EPOCH_JD,
    invert_y: bool = False,
    y_label: str = "Magnitude",
) -> go.Figure:
    """Build a Plotly figure for one successful parabola interval fit.

    Times use the Extrema modeller page display scale (see ``page_time_label``).

    Args:
        t_obs (numpy.ndarray): Absolute JD of the interval points.
        y_obs (numpy.ndarray): Photometry in the working Mag/Flux view.
        fit (ParabolaFitResult): Successful fit (``ok`` must be true).
        display_epoch (float): Reference subtracted for the x-axis.
        invert_y (bool): Reverse the y-axis (magnitude convention).
        y_label (str): Y-axis title.

    Returns:
        plotly.graph_objects.Figure: Data, parabola, and ToM marker with σ band.

    Raises:
        ValueError: If ``fit.ok`` is false or arrays are empty.
    """
    if not fit.ok:
        raise ValueError("Cannot build a parabola figure for a failed fit")
    t_obs = np.asarray(t_obs, dtype=float)
    y_obs = np.asarray(y_obs, dtype=float)
    if t_obs.size == 0:
        raise ValueError("Cannot build a parabola figure from an empty interval")

    def _plot_x(jd_values):
        return absolute_jd_to_plot_x(jd_values, PAGE_TIME_AXIS_MODE, display_epoch)

    x = np.asarray(_plot_x(t_obs), dtype=float)
    t_min = float(np.min(t_obs))
    t_max = float(np.max(t_obs))
    t_line = np.linspace(t_min, t_max, _CURVE_POINTS)
    dt_line = t_line - float(fit.t_anchor)
    y_line = fit.c0 + fit.c1 * dt_line + fit.c2 * dt_line**2

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
    fig.add_trace(
        go.Scatter(
            x=np.asarray(_plot_x(t_line), dtype=float),
            y=y_line,
            mode="lines",
            line=dict(color=PARABOLA_LINE_COLOUR, width=2.0),
            hovertemplate="Parabola: %{y:.4f}<extra></extra>",
            name="Parabola",
        )
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
        title=dict(
            text=format_page_fit_title(
                fit.t_ext, kind="ToM", epoch=display_epoch
            ),
            font=dict(size=14),
            y=0.95,
        ),
        template="plotly_white",
        height=REVIEW_CARD_PLOT_HEIGHT,
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
    apply_time_xaxis_format(fig, phase_view=False, time_axis_mode=PAGE_TIME_AXIS_MODE)
    return fig


def figure_from_parabola_observations(
    t_obs: np.ndarray,
    y_obs: np.ndarray,
    *,
    display_epoch: float = PAGE_DISPLAY_EPOCH_JD,
    invert_y: bool = False,
    y_label: str = "Magnitude",
) -> go.Figure | None:
    """Build a points-only figure when a parabola interval fit failed.

    Args:
        t_obs (numpy.ndarray): Absolute JD of the interval points.
        y_obs (numpy.ndarray): Photometry in the working Mag/Flux view.
        display_epoch (float): Reference subtracted for the x-axis.
        invert_y (bool): Reverse the y-axis (magnitude convention).
        y_label (str): Y-axis title.

    Returns:
        plotly.graph_objects.Figure | None: Scatter of the interval, or ``None``
        when no finite points remain.
    """
    return maybe_interval_observations_figure(
        t_obs,
        y_obs,
        display_epoch=display_epoch,
        invert_y=invert_y,
        y_label=y_label,
        title="Fit failed",
        height=REVIEW_CARD_PLOT_HEIGHT,
    )
