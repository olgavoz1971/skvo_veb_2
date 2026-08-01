"""Build GP fit summary figures for the GP O-C Dash page."""

import numpy as np
import plotly.graph_objects as go

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, TIME_AXIS_MJD
from skvo_veb.utils.lc_figure import absolute_jd_to_plot_x, apply_time_xaxis_format


def figure_from_gp_result(gp_res, jd_max_guess=None, display_epoch=DEFAULT_EPOCH_JD):
    """Build a Plotly figure for one GP interval result.

    Times are shown in **MJD** (``JD - display_epoch``), matching the prep
    lightcurve interval plot. Pipeline outputs remain absolute JD.

    Args:
        gp_res (dict): Output of ``gp_peak_pipeline`` including fitted ``gp`` model.
        jd_max_guess (float, optional): Optional prior peak absolute JD for vertical marker.
        display_epoch (float): Reference subtracted for the x-axis (same as prep plot ``jd0``).

    Returns:
        plotly.graph_objects.Figure: Styled GP mean, data, and extremum markers.
    """
    def _plot_x(jd_values):
        return absolute_jd_to_plot_x(
            jd_values, TIME_AXIS_MJD, display_epoch
        )

    gp = gp_res["gp"]
    x = np.asarray(_plot_x(gp.X_train_.ravel()), dtype=float)
    y = gp.y_train_
    noise_sigma_norm = gp_res["noise_sigma_norm"]
    x_grid = np.asarray(_plot_x(gp_res["jd_grid"].ravel()), dtype=float)
    y_mean = gp_res["mean_grid"].ravel()
    y_std = gp_res["std_grid"].ravel()

    jd_peak = gp_res["jd_peak"]
    jd_peak_std = gp_res["jd_peak_std"]
    peaks_jd = np.asarray(_plot_x(gp_res["peaks_jd"]), dtype=float)
    mean_peak = gp_res["mean_peak"]
    peak_mjd = float(_plot_x(jd_peak))
    peak_std_mjd = float(jd_peak_std)

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="markers",
        marker=dict(color="black", size=6),
        error_y=dict(
            type="data", array=np.full_like(y, noise_sigma_norm),
            visible=True, thickness=1, width=2, color="gray",
        ),
        customdata=np.full_like(y, noise_sigma_norm),
        hovertemplate="Data: %{y:.3f} ± %{customdata:.3f}<extra></extra>",
        name="Data",
    ))

    fig.add_trace(go.Scatter(
        x=x_grid, y=y_mean,
        mode="lines",
        line=dict(color="rgb(31, 119, 180)", width=2),
        customdata=y_std,
        hovertemplate="GP Mean: %{y:.3f} ± %{customdata:.3f}<extra></extra>",
        name="GP mean",
    ))

    fig.add_trace(go.Scatter(
        x=np.concatenate([x_grid, x_grid[::-1]]),
        y=np.concatenate([y_mean + y_std, (y_mean - y_std)[::-1]]),
        fill="toself",
        fillcolor="rgba(31, 119, 180, 0.25)",
        line=dict(color="rgba(255,255,255,0)"),
        hoverinfo="skip",
        showlegend=False,
        name="GP ±1σ",
    ))

    fig.add_trace(go.Scatter(
        x=peaks_jd,
        y=np.full_like(peaks_jd, 0.98 * mean_peak),
        mode="markers",
        marker=dict(color="orange", size=8, opacity=0.1),
        hoverinfo="skip",
        showlegend=False,
    ))

    if jd_max_guess is not None:
        fig.add_vline(
            x=float(_plot_x(jd_max_guess)),
            line_width=1.5,
            line_dash="dot",
            line_color="green",
        )

    fig.add_vline(x=peak_mjd, line_width=2, line_dash="dash", line_color="magenta")

    fig.add_vrect(
        x0=peak_mjd - peak_std_mjd,
        x1=peak_mjd + peak_std_mjd,
        fillcolor="magenta", opacity=0.1,
        layer="below", line_width=0,
        name="±1σ range",
    )

    fig.add_vline(x=peak_mjd - peak_std_mjd, line_width=2, line_dash="dot", line_color="magenta")
    fig.add_vline(x=peak_mjd + peak_std_mjd, line_width=2, line_dash="dot", line_color="magenta")

    fig.update_layout(
        margin=dict(l=0, r=10, t=20, b=20),
        showlegend=False,
        title=dict(text=f"   Peak: {peak_mjd:.2f}", font=dict(size=14), y=0.95),
        template="plotly_white",
        height=400,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.9)",
            font_size=12,
            font_family="Rockwell",
        ),
    )
    apply_time_xaxis_format(fig, phase_view=False, time_axis_mode=TIME_AXIS_MJD)

    return fig
