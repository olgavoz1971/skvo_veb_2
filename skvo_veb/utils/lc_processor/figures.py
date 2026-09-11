"""GP-style Plotly figures for the Lightcurve processor.

Adopted from ``auxiliary/trend/detrend_figures.py`` (same marker, font, and
margins as the GP prep plot). Do not use Discovery's ``px.scatter`` builder
here.
"""

from __future__ import annotations

import logging
import re

import numpy as np
import plotly.graph_objects as go
from plotly.colors import qualitative

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, TIME_AXIS_MJD, normalize_time_axis_mode
from skvo_veb.utils.lc_figure import (
    absolute_jd_to_plot_x,
    apply_time_xaxis_format,
    time_axis_xaxis_title,
)
from skvo_veb.utils.lc_interaction import apply_selectedpoints_to_figure, plot_x_to_jd

logger = logging.getLogger(__name__)

PLOT_TOOL_OFF = "off"
PLOT_TOOL_ADD = "add"
PLOT_TOOL_DELETE = "delete"
DELETE_KNOT_HIT_FRAC = 0.02
_SHAPE_X0_RE = re.compile(r"^shapes\[(\d+)\]\.x0$")

# Observed scatter: size 4, opacity 0.7 (same numbers as the GP prep plot).
_PHOT_MARKER = dict(size=4, color="blue", opacity=0.7, line=dict(width=0.5, color="White"))
_ERROR_STYLE = dict(
    type="data",
    visible=True,
    thickness=1,
    width=0,
    color="rgba(100, 100, 100, 0.3)",
)
_LABEL_COLORS = qualitative.Plotly
_UNMARKED_LABEL_NAMES = frozenset({"", "none", "nan", "null", "<na>", "nat"})
_PLOT_FONT = dict(
    family=(
        'Open Sans, -apple-system, BlinkMacSystemFont, "Segoe UI", '
        'Roboto, "Helvetica Neue", Arial, sans-serif'
    ),
    size=12,
    color="#000",
)
_PLOT_MARGIN = dict(l=10, r=10, t=20, b=40)
_PLOT_MARGIN_LEGEND = dict(l=10, r=140, t=20, b=40)


def graph_config(*, plot_tool: str = PLOT_TOOL_OFF, method: str | None = None) -> dict:
    """Returns the Plotly config for the current knot tool.

    Args:
        plot_tool (str): ``off``, ``add``, or ``delete``.
        method (str | None): Active smooth method id.

    Returns:
        dict: ``dcc.Graph`` config (logo off, scroll zoom on).
    """
    knots_editable = plot_tool == PLOT_TOOL_ADD and method == "spline_lsq"
    config = {
        "displaylogo": False,
        "scrollZoom": True,
        "modeBarButtonsToRemove": [],
        "editable": knots_editable,
    }
    if knots_editable:
        config["edits"] = {"shapePosition": True}
    return config


def _jd_to_plot_x(jd_values, time_axis_mode: str, display_epoch: float):
    """Maps absolute Julian Dates onto the plot x-axis.

    Args:
        jd_values: Scalar or array-like absolute JD.
        time_axis_mode (str): ``mjd`` or ``date``.
        display_epoch (float): MJD origin when the axis is MJD.

    Returns:
        Plot x coordinates (float array for MJD, datetime-like for date).
    """
    axis = normalize_time_axis_mode(time_axis_mode)
    return absolute_jd_to_plot_x(jd_values, axis, display_epoch)


def _error_y(obs_err: np.ndarray | None, show_errors: bool) -> dict | None:
    """Builds GP-style error bars when uncertainties are present and requested.

    Args:
        obs_err (numpy.ndarray | None): Uncertainties, or ``None``.
        show_errors (bool): Whether the user asked for error bars.

    Returns:
        dict | None: Plotly ``error_y`` payload, or ``None``.
    """
    if not show_errors or obs_err is None:
        return None
    err_arr = np.asarray(obs_err, dtype=float)
    if not np.any(np.isfinite(err_arr) & (err_arr > 0)):
        return None
    return {**_ERROR_STYLE, "array": err_arr}


def _point_label_name(value) -> str | None:
    """Returns a legend name for one label cell, or ``None`` if unmarked.

    Args:
        value: Raw label cell from the light-curve table.

    Returns:
        str | None: Display name, or ``None`` to leave the point unlabelled.
    """
    if value is None:
        return None
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in _UNMARKED_LABEL_NAMES:
        return None
    try:
        as_float = float(text)
    except (TypeError, ValueError):
        return text
    if np.isfinite(as_float) and as_float.is_integer():
        return str(int(as_float))
    return text


def _legend_sort_key(name: str) -> tuple:
    """Sorts legend entries numerically when the name is a number.

    Args:
        name (str): Legend text.

    Returns:
        tuple: Sort key.
    """
    try:
        return (0, int(name))
    except ValueError:
        try:
            return (0, float(name))
        except ValueError:
            return (1, name.lower())


def _apply_label_legend(fig: go.Figure, *, show: bool) -> None:
    """Places a Plotly legend outside the plotting area, or hides it.

    Args:
        fig (plotly.graph_objects.Figure): Target figure.
        show (bool): ``True`` only when more than one distinct label is present.
    """
    if not show:
        fig.update_layout(showlegend=False, margin=_PLOT_MARGIN)
        return
    fig.update_layout(
        showlegend=True,
        legend=dict(
            title_text="",
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,
            bgcolor="rgba(255,255,255,0.85)",
            borderwidth=0,
            itemsizing="constant",
        ),
        margin=_PLOT_MARGIN_LEGEND,
    )


def _add_photometry_traces(
    fig: go.Figure,
    x_mjd: np.ndarray,
    y: np.ndarray,
    obs_err: np.ndarray | None,
    *,
    labels,
    source_index: np.ndarray | None,
    show_errors: bool,
    default_name: str,
) -> bool:
    """Adds photometry markers, coloured by label when labels are present.

    Unlabelled points, and a single label type, use the GP prep marker
    (blue, opacity 0.7). A legend and the qualitative palette appear only
    when two or more label types are present. ``customdata`` holds
    ``perm_index``.

    Args:
        fig (plotly.graph_objects.Figure): Target figure.
        x_mjd: Plot x coordinates.
        y (numpy.ndarray): Photometry.
        obs_err (numpy.ndarray | None): Uncertainties.
        labels: Per-point labels, or ``None``.
        source_index (numpy.ndarray | None): Permanent indices for clicks.
        show_errors (bool): Draw error bars when uncertainties exist.
        default_name (str): Trace name for unlabelled points.

    Returns:
        bool: ``True`` if a legend should be shown.
    """
    x_arr = np.asarray(x_mjd)
    n = int(x_arr.size)
    y_arr = np.asarray(y, dtype=float)
    if y_arr.size != n:
        raise ValueError(
            f"photometry length {y_arr.size} does not match time length {n}"
        )
    src = (
        np.arange(n, dtype=int)
        if source_index is None
        else np.asarray(source_index, dtype=int)
    )
    if src.size != n:
        raise ValueError(
            f"source_index length {src.size} does not match photometry length {n}"
        )
    if labels is None:
        names = np.array([None] * n, dtype=object)
    else:
        raw = np.asarray(labels, dtype=object)
        if raw.size != n:
            raise ValueError(
                f"label length {raw.size} does not match photometry length {n}"
            )
        names = np.array([_point_label_name(v) for v in raw], dtype=object)
    marked = sorted({name for name in names if name is not None}, key=_legend_sort_key)

    def _add_group(mask: np.ndarray, color: str, name: str, in_legend: bool) -> None:
        if not np.any(mask):
            return
        err_slice = None if obs_err is None else np.asarray(obs_err)[mask]
        perm = np.asarray(src[mask], dtype=int)
        fig.add_trace(
            go.Scattergl(
                x=x_arr[mask],
                y=y_arr[mask],
                mode="markers",
                marker=dict(_PHOT_MARKER, color=color),
                error_y=_error_y(err_slice, show_errors),
                hoverinfo="none",
                customdata=np.column_stack([perm]),
                ids=perm.astype(str).tolist(),
                selected={"marker": {"color": "orange", "size": 6, "opacity": 1.0}},
                unselected={"marker": {"opacity": 0.7}},
                showlegend=in_legend,
                name=name,
            )
        )

    unmarked = np.array([name is None for name in names], dtype=bool)
    gp_color = str(_PHOT_MARKER["color"])
    _add_group(unmarked, gp_color, default_name, False)
    show_legend = len(marked) > 1
    for i, name in enumerate(marked):
        mask = np.array([item == name for item in names], dtype=bool)
        color = (
            gp_color if not show_legend else _LABEL_COLORS[i % len(_LABEL_COLORS)]
        )
        _add_group(mask, color, name, show_legend)
    return show_legend


def _apply_y_axis_direction(fig: go.Figure, *, invert_y: bool) -> None:
    """Sets magnitude vs flux y-axis direction the same way as the GP page.

    Args:
        fig (plotly.graph_objects.Figure): Target figure.
        invert_y (bool): ``True`` for magnitude, ``False`` for flux.
    """
    fig.update_yaxes(autorange="reversed" if invert_y else True)


def empty_figure(
    *,
    xaxis_title: str,
    yaxis_title: str | None = None,
    invert_y: bool = False,
    uirevision: str = "empty",
    time_axis_mode: str = TIME_AXIS_MJD,
) -> go.Figure:
    """Returns a placeholder figure before a series is drawn.

    Args:
        xaxis_title (str): Time-axis label.
        yaxis_title (str | None): Optional y-axis label.
        invert_y (bool): Reverse the y-axis for magnitudes.
        uirevision (str): Plotly ``uirevision``.
        time_axis_mode (str): ``mjd`` or ``date``.

    Returns:
        plotly.graph_objects.Figure: Empty axes.
    """
    fig = go.Figure()
    fig.update_layout(
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        template="plotly_white",
        font=_PLOT_FONT,
        margin=_PLOT_MARGIN,
        uirevision=uirevision,
        showlegend=False,
    )
    apply_time_xaxis_format(fig, phase_view=False, time_axis_mode=time_axis_mode)
    _apply_y_axis_direction(fig, invert_y=invert_y)
    return fig


def merge_knot_drag(
    knots: list[float],
    relayout_data: dict | None,
    *,
    display_epoch: float = DEFAULT_EPOCH_JD,
    time_axis_mode: str = TIME_AXIS_MJD,
) -> list[float] | None:
    """Applies shape-drag updates onto an existing knot list.

    Args:
        knots (list[float]): Current interior knot times (absolute JD).
        relayout_data (dict | None): Dash ``relayoutData`` payload.
        display_epoch (float): MJD display origin.
        time_axis_mode (str): ``mjd`` or ``date``.

    Returns:
        list[float] | None: Sorted unique knots if a drag happened; else ``None``.
    """
    if not relayout_data or not knots:
        return None
    axis = normalize_time_axis_mode(time_axis_mode)
    updates: dict[int, float] = {}
    for key, value in relayout_data.items():
        match = _SHAPE_X0_RE.match(str(key))
        if match is None:
            continue
        idx = int(match.group(1))
        try:
            updates[idx] = plot_x_to_jd(value, axis, display_epoch)
        except (TypeError, ValueError):
            continue
    if not updates:
        return None
    new_knots = list(knots)
    for idx, x_val in updates.items():
        if 0 <= idx < len(new_knots) and np.isfinite(x_val):
            new_knots[idx] = x_val
    return sorted({float(k) for k in new_knots if np.isfinite(k)})


def extract_xaxis_range_mjd(relayout_data: dict | None) -> list[float] | None:
    """Reads the plot x-axis range (display MJD) from Plotly ``relayoutData``.

    Args:
        relayout_data (dict | None): Dash ``relayoutData`` payload.

    Returns:
        list[float] | None: ``[xmin, xmax]`` in display MJD; empty list on
        autorange; ``None`` when the payload has no x-range update.
    """
    if not relayout_data:
        return None
    if relayout_data.get("xaxis.autorange"):
        return []
    if "xaxis.range[0]" in relayout_data and "xaxis.range[1]" in relayout_data:
        return [
            relayout_data["xaxis.range[0]"],
            relayout_data["xaxis.range[1]"],
        ]
    rng = relayout_data.get("xaxis.range")
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        return [rng[0], rng[1]]
    return None


def knot_hit_span_jd(
    x_range_mjd: list | None,
    t_min: float,
    t_max: float,
    *,
    display_epoch: float = DEFAULT_EPOCH_JD,
    time_axis_mode: str = TIME_AXIS_MJD,
) -> float:
    """Returns the time span used for delete-knot proximity.

    Args:
        x_range_mjd (list | None): Plot x-axis ``[min, max]`` in display units.
        t_min (float): Series start (absolute JD).
        t_max (float): Series end (absolute JD).
        display_epoch (float): MJD display origin.
        time_axis_mode (str): ``mjd`` or ``date``.

    Returns:
        float: Positive span in days.
    """
    axis = normalize_time_axis_mode(time_axis_mode)
    if x_range_mjd and len(x_range_mjd) == 2:
        lo = plot_x_to_jd(x_range_mjd[0], axis, display_epoch)
        hi = plot_x_to_jd(x_range_mjd[1], axis, display_epoch)
        span = abs(float(hi) - float(lo))
        if np.isfinite(span) and span > 0:
            return span
    return max(float(t_max) - float(t_min), 1e-12)


def knot_click_edit(
    knots: list[float],
    click_x: float,
    t_min: float,
    t_max: float,
    *,
    mode: str,
    hit_span: float | None = None,
    hit_frac: float = DELETE_KNOT_HIT_FRAC,
) -> list[float]:
    """Adds or deletes an interior knot according to the click mode.

    Args:
        knots (list[float]): Current interior knot times (absolute JD).
        click_x (float): Clicked time as absolute JD.
        t_min (float): Light-curve start (absolute JD).
        t_max (float): Light-curve end (absolute JD).
        mode (str): ``add`` or ``delete``.
        hit_span (float | None): Delete proximity window (days).
        hit_frac (float): Fraction of ``hit_span`` that counts as near.

    Returns:
        list[float]: Updated sorted unique knots strictly inside the span.
    """
    x_val = float(click_x)
    current = [float(k) for k in knots if t_min < float(k) < t_max]
    if not (t_min < x_val < t_max):
        return current
    if mode == "delete":
        if not current:
            return current
        nearest = min(current, key=lambda k: abs(k - x_val))
        span = float(hit_span) if hit_span is not None else max(t_max - t_min, 1e-12)
        hit = hit_frac * max(span, 1e-12)
        if abs(nearest - x_val) > hit:
            return current
        return sorted(k for k in current if k != nearest)
    current.append(x_val)
    return sorted(set(current))


def knot_layout_shapes(
    knots: list[float] | None,
    *,
    time_axis_mode: str,
    display_epoch: float = DEFAULT_EPOCH_JD,
    editable: bool = False,
) -> list[dict]:
    """Builds Plotly layout shapes for interior knots.

    Args:
        knots (list[float] | None): Interior knot times (absolute JD).
        time_axis_mode (str): ``mjd`` or ``date``.
        display_epoch (float): MJD display origin.
        editable (bool): Whether the lines can be dragged.

    Returns:
        list[dict]: Vertical dashed lines, or an empty list.
    """
    if not knots:
        return []
    axis = normalize_time_axis_mode(time_axis_mode)
    shapes = []
    for knot in knots:
        knot_x = _jd_to_plot_x(knot, axis, display_epoch)
        shapes.append(
            dict(
                type="line",
                x0=knot_x,
                x1=knot_x,
                y0=0,
                y1=1,
                yref="paper",
                editable=bool(editable),
                line=dict(color="#2b8a3e", width=1.5, dash="dot"),
            )
        )
    return shapes


def figure_raw_with_trend(
    times: np.ndarray | None,
    observed: np.ndarray | None,
    obs_err: np.ndarray | None,
    trend: np.ndarray | None,
    *,
    y_label: str,
    invert_y: bool,
    show_errors: bool,
    uirevision: str,
    knots: list[float] | None = None,
    knots_editable: bool = False,
    display_epoch: float = DEFAULT_EPOCH_JD,
    timescale: str | None = None,
    refposition: str | None = None,
    labels=None,
    source_index: np.ndarray | None = None,
    selected_perm_indices=None,
    time_axis_mode: str = TIME_AXIS_MJD,
) -> go.Figure:
    """Builds the observed (plus optional trend) figure.

    ``times`` and ``knots`` remain absolute JD.

    Args:
        times (numpy.ndarray | None): Observation times (absolute JD).
        observed (numpy.ndarray | None): Observed photometry.
        obs_err (numpy.ndarray | None): Uncertainties, or ``None``.
        trend (numpy.ndarray | None): Fitted trend, or ``None``.
        y_label (str): Y-axis label.
        invert_y (bool): Invert the y-axis (magnitudes only).
        show_errors (bool): Draw error bars when uncertainties exist.
        uirevision (str): Plotly ``uirevision`` so zoom survives updates.
        knots (list[float] | None): Interior knot times (absolute JD).
        knots_editable (bool): Draw knots as draggable vertical shapes.
        display_epoch (float): MJD display origin.
        timescale (str | None): TIMESYS timescale for the axis suffix.
        refposition (str | None): TIMESYS refposition for the axis suffix.
        labels: Optional per-point group labels.
        source_index (numpy.ndarray | None): Permanent indices for clicks.
        selected_perm_indices: Permanent indices marked ``selected=1``.
        time_axis_mode (str): ``mjd`` or ``date``.

    Returns:
        plotly.graph_objects.Figure: Working photometry plot.
    """
    axis = normalize_time_axis_mode(time_axis_mode)
    xaxis_title = time_axis_xaxis_title(axis, timescale, refposition)
    if times is None or observed is None:
        return empty_figure(
            xaxis_title=xaxis_title,
            yaxis_title=y_label,
            invert_y=invert_y,
            uirevision=uirevision,
            time_axis_mode=axis,
        )

    x_plot = _jd_to_plot_x(times, axis, display_epoch)
    y_obs = np.asarray(observed, dtype=float)
    fig = go.Figure()
    show_legend = _add_photometry_traces(
        fig,
        x_plot,
        y_obs,
        obs_err,
        labels=labels,
        source_index=source_index,
        show_errors=show_errors,
        default_name="observed",
    )
    if trend is not None:
        fig.add_trace(
            go.Scattergl(
                x=x_plot,
                y=np.asarray(trend, dtype=float),
                mode="lines",
                showlegend=False,
                name="trend",
                hoverinfo="skip",
                line=dict(color="#c92a2a", width=2),
            )
        )
    shapes = knot_layout_shapes(
        knots,
        time_axis_mode=axis,
        display_epoch=display_epoch,
        editable=knots_editable,
    )
    fig.update_layout(
        xaxis_title=xaxis_title,
        yaxis_title=y_label,
        template="plotly_white",
        font=_PLOT_FONT,
        margin=_PLOT_MARGIN,
        uirevision=uirevision,
        shapes=shapes,
        dragmode="zoom",
        clickmode="event+select",
        hovermode="closest",
    )
    _apply_label_legend(fig, show=show_legend)
    apply_time_xaxis_format(fig, phase_view=False, time_axis_mode=axis)
    _apply_y_axis_direction(fig, invert_y=invert_y)
    apply_selectedpoints_to_figure(fig, selected_perm_indices)
    return fig
