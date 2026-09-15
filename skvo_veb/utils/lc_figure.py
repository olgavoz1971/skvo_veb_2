"""Shared Plotly figure builders for CurveDash lightcurves."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD,
    DOMAIN_MAG,
    METADATA_KEY_VO_ENVELOPE,
    TIME_AXIS_DATE,
    TIME_AXIS_MJD,
    normalize_time_axis_mode,
)
from skvo_veb.utils.lc_interaction import (
    apply_selectedpoints_to_figure,
    normalize_selected_perm_store,
    trace_selected_indices,
    trace_selected_indices_from_column,
)
from skvo_veb.utils.my_tools import safe_none

logger = logging.getLogger(__name__)

MJD_X_TICKFORMAT = '.2f'
DATE_X_TICKFORMAT = '%Y-%m-%d'
DATE_X_HOVERFORMAT = '%Y-%m-%d %H:%M'


def format_timesys_axis_suffix(
    timescale: str | None = None,
    refposition: str | None = None,
) -> str:
    """Builds a parenthetical TIMESYS annotation for plot axis titles.

    Args:
        timescale (str, optional): ``TIMESYS/@timescale`` (for example ``TCB``).
        refposition (str, optional): ``TIMESYS/@refposition`` (for example ``BARYCENTER``).

    Returns:
        str: ``" (TCB, BARYCENTER)"`` or ``""`` when no metadata is available.
    """
    parts = []
    if timescale:
        parts.append(str(timescale).strip().upper())
    if refposition:
        parts.append(str(refposition).strip().upper())
    if not parts:
        return ""
    return f" ({', '.join(parts)})"


def _astropy_scale_for_timesys(timescale: str | None) -> str | None:
    """Maps VOTable ``TIMESYS/@timescale`` to an Astropy ``Time`` scale when supported.

    Args:
        timescale (str, optional): TIMESYS timescale string from ingest.

    Returns:
        str or None: Lower-case Astropy scale, or ``None`` when unsupported/absent.
    """
    if not timescale:
        return None
    scale = str(timescale).strip().lower()
    if scale in ("hjd", "bjd"):
        return None
    return scale


def time_axis_xaxis_title(
    time_axis_mode: str,
    timescale: str | None = None,
    refposition: str | None = None,
    *,
    numeric_scale_label: str | None = None,
) -> str:
    """Returns the unfolded time-axis title for a lightcurve plot.

    Args:
        time_axis_mode (str): ``mjd`` or ``date``.
        timescale (str, optional): Ingested ``TIMESYS/@timescale``; never invented.
        refposition (str, optional): Ingested ``TIMESYS/@refposition``.
        numeric_scale_label (str, optional): Caption for the numeric axis
            (``MJD``, ``JD``, ``JD-2450000``). Defaults to ``MJD``.

    Returns:
        str: Axis title matching ``_build_time_axis`` (no default timescale).
    """
    suffix = format_timesys_axis_suffix(timescale, refposition)
    mode = normalize_time_axis_mode(time_axis_mode)
    if mode == TIME_AXIS_DATE:
        return f"Date{suffix}" if suffix else "Date"
    scale = numeric_scale_label or "MJD"
    return f"{scale}{suffix}" if suffix else scale


def absolute_jd_to_plot_x(
    jd_values,
    time_axis_mode: str,
    display_epoch: float = DEFAULT_EPOCH_JD,
    *,
    timescale: str | None = None,
):
    """Maps absolute Julian Date(s) to Plotly x coordinates for the active axis mode.

    Args:
        jd_values: Scalar or array-like absolute JD.
        time_axis_mode (str): ``mjd`` or ``date``.
        display_epoch (float): Reference subtracted in MJD mode.
        timescale (str, optional): ``TIMESYS/@timescale`` for calendar-date plotting.

    Returns:
        float, numpy.ndarray, or list: Plot x values (MJD offset or datetimes).
    """
    from astropy.time import Time

    mode = normalize_time_axis_mode(time_axis_mode)
    scalar = np.isscalar(jd_values) or (
        isinstance(jd_values, (float, int)) and not hasattr(jd_values, '__len__')
    )
    arr = np.atleast_1d(np.asarray(jd_values, dtype=float))
    if mode == TIME_AXIS_DATE:
        scale = _astropy_scale_for_timesys(timescale)
        if scale:
            converted = Time(arr, format="jd", scale=scale).datetime
        else:
            converted = Time(arr, format="jd").datetime
        if scalar and len(converted) == 1:
            return converted[0]
        return list(converted)
    out = arr - float(display_epoch)
    if scalar and out.size == 1:
        return float(out[0])
    return out


def interval_observations_figure(
    t_obs: np.ndarray,
    y_obs: np.ndarray,
    *,
    display_epoch: float = DEFAULT_EPOCH_JD,
    invert_y: bool = False,
    y_label: str | None = None,
    title: str = "Fit failed",
    height: int = 400,
) -> go.Figure:
    """Build a points-only MJD figure for an interval (no model or ToM).

    Args:
        t_obs (numpy.ndarray): Absolute Julian Dates (finite points only).
        y_obs (numpy.ndarray): Photometry aligned with ``t_obs``.
        display_epoch (float): Reference subtracted for the x-axis.
        invert_y (bool): Reverse the y-axis (magnitude convention).
        y_label (str | None): Y-axis title; omitted when empty.
        title (str): Figure title (failure cards use ``Fit failed``).
        height (int): Plotly layout height in pixels.

    Returns:
        plotly.graph_objects.Figure: Scatter of the interval photometry.

    Raises:
        ValueError: If ``t_obs`` is empty or lengths differ.
    """
    t_obs = np.asarray(t_obs, dtype=float)
    y_obs = np.asarray(y_obs, dtype=float)
    if t_obs.shape != y_obs.shape:
        raise ValueError(
            f"t_obs and y_obs length mismatch: {t_obs.size} vs {y_obs.size}"
        )
    if t_obs.size == 0:
        raise ValueError("Cannot plot an empty interval")

    x = np.asarray(
        absolute_jd_to_plot_x(t_obs, TIME_AXIS_MJD, display_epoch),
        dtype=float,
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
    layout = dict(
        margin=dict(l=0, r=10, t=20, b=20),
        showlegend=False,
        title=dict(text=f"   {title}", font=dict(size=14), y=0.95),
        template="plotly_white",
        height=height,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.9)",
            font_size=12,
            font_family="Rockwell",
        ),
    )
    if y_label:
        layout["yaxis_title"] = y_label
    fig.update_layout(**layout)
    if invert_y:
        fig.update_yaxes(autorange="reversed")
    apply_time_xaxis_format(fig, phase_view=False, time_axis_mode=TIME_AXIS_MJD)
    return fig


def maybe_interval_observations_figure(
    t_obs: np.ndarray,
    y_obs: np.ndarray,
    *,
    display_epoch: float = DEFAULT_EPOCH_JD,
    invert_y: bool = False,
    y_label: str | None = None,
    title: str = "Fit failed",
    height: int = 400,
) -> go.Figure | None:
    """Returns a points-only figure, or ``None`` when no finite samples remain.

    Args:
        t_obs (numpy.ndarray): Absolute Julian Dates.
        y_obs (numpy.ndarray): Photometry aligned with ``t_obs``.
        display_epoch (float): Reference subtracted for the x-axis.
        invert_y (bool): Reverse the y-axis (magnitude convention).
        y_label (str | None): Y-axis title; omitted when empty.
        title (str): Figure title.
        height (int): Plotly layout height in pixels.

    Returns:
        plotly.graph_objects.Figure | None: Scatter plot, or ``None`` if empty.

    Raises:
        ValueError: If the arrays have different lengths.
    """
    t_obs = np.asarray(t_obs, dtype=float)
    y_obs = np.asarray(y_obs, dtype=float)
    if t_obs.shape != y_obs.shape:
        raise ValueError(
            f"t_obs and y_obs length mismatch: {t_obs.size} vs {y_obs.size}"
        )
    finite = np.isfinite(t_obs) & np.isfinite(y_obs)
    t_obs = t_obs[finite]
    y_obs = y_obs[finite]
    if t_obs.size == 0:
        return None
    return interval_observations_figure(
        t_obs,
        y_obs,
        display_epoch=display_epoch,
        invert_y=invert_y,
        y_label=y_label,
        title=title,
        height=height,
    )


def apply_time_xaxis_format(fig, *, phase_view: bool, time_axis_mode: str) -> None:
    """Applies variable-star-friendly x-axis tick formatting (public wrapper).

    Args:
        fig (plotly.graph_objects.Figure): Target figure.
        phase_view (bool): Whether the x-axis shows phase.
        time_axis_mode (str): ``mjd`` or ``date`` when not in phase view.
    """
    _apply_time_xaxis_format(fig, phase_view=phase_view, time_axis_mode=time_axis_mode)


def _build_time_axis(lcd, display_epoch: float, time_axis_mode: str):
    """Builds x-axis values and label for the unfolded time view.

    Args:
        lcd (CurveDash): Application lightcurve instance.
        display_epoch (float): JD offset for MJD display (``JD_TO_MJD``).
        time_axis_mode (str): ``mjd`` or ``date``.

    Returns:
        tuple: ``(x_series, x_column, xaxis_title)``.
    """
    from astropy.time import Time

    timescale_label = safe_none(lcd.timescale)
    envelope = (lcd.metadata or {}).get(METADATA_KEY_VO_ENVELOPE) or {}
    refposition = envelope.get("refposition")
    suffix = format_timesys_axis_suffix(timescale_label, refposition)
    jd = lcd.jd
    mode = normalize_time_axis_mode(time_axis_mode)

    if mode == TIME_AXIS_DATE:
        scale = _astropy_scale_for_timesys(timescale_label)
        if scale:
            time_values = Time(jd, format="jd", scale=scale)
        else:
            time_values = Time(jd, format="jd")
        x = pd.Series(time_values.datetime, index=jd.index if hasattr(jd, 'index') else None)
        title = f"Date{suffix}" if suffix else "Date"
        return x, 'time', title

    x = jd - display_epoch if jd is not None else jd
    title = f"MJD{suffix}" if suffix else "MJD"
    return x, 'mjd', title


def _apply_time_xaxis_format(fig, *, phase_view: bool, time_axis_mode: str) -> None:
    """Applies variable-star-friendly x-axis tick formatting.

    Args:
        fig (plotly.graph_objects.Figure): Target figure.
        phase_view (bool): Whether the x-axis shows phase.
        time_axis_mode (str): ``mjd`` or ``date`` when not in phase view.
    """
    if phase_view:
        fig.update_xaxes(tickformat='.3f', exponentformat='none')
        return

    if normalize_time_axis_mode(time_axis_mode) == TIME_AXIS_DATE:
        fig.update_xaxes(
            type='date',
            tickformat=DATE_X_TICKFORMAT,
            hoverformat=DATE_X_HOVERFORMAT,
            exponentformat='none',
        )
        return

    fig.update_xaxes(tickformat=MJD_X_TICKFORMAT, exponentformat='none')


def _format_sector_legend_labels(label_series: pd.Series) -> pd.Series:
    """Formats sector ids as discrete legend labels (e.g. ``Sector 56``).

    Args:
        label_series (pandas.Series): Raw sector/group column from a lightcurve table.

    Returns:
        pandas.Series: String labels suitable for categorical colouring in Plotly.
    """
    def _one_label(value) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return 'Sector ?'
        try:
            return f'Sector {int(value)}'
        except (TypeError, ValueError):
            text = str(value).strip()
            if text.lower().startswith('sector'):
                return text
            return f'Sector {text}' if text else 'Sector ?'

    return label_series.map(_one_label)


def _sector_legend_sort_key(label: str) -> tuple:
    """Sort key so legend entries follow numeric sector order.

    Args:
        label (str): Legend label such as ``Sector 56``.

    Returns:
        tuple: Sort key for ``sorted(..., key=...)``.
    """
    parts = str(label).split()
    if len(parts) >= 2 and parts[-1].lstrip('-').isdigit():
        return (0, int(parts[-1]))
    return (1, str(label))


def _data_uirevision_token(lcd) -> str:
    """Builds a token that changes when lightcurve rows or time span change.

    Plotly preserves box/lasso ``selectedpoints`` while ``uirevision`` is unchanged.
    Including observation count and JD limits clears stale orange highlights after
    trim or delete without resetting zoom on unrelated view toggles.

    Args:
        lcd (CurveDash): Application lightcurve instance.

    Returns:
        str: Compact data fingerprint for ``uirevision``.
    """
    df = lcd.lightcurve
    if df is None or df.empty:
        return 'n=0'
    jd = df['jd']
    return f'n={len(df)}|{float(jd.min()):.8f}|{float(jd.max()):.8f}'


def _uirevision_key(lcd, phase_view: bool, time_axis_mode: str = TIME_AXIS_MJD) -> str:
    """Builds a Plotly ``uirevision`` token for view-changing replots.

    Args:
        lcd (CurveDash): Application lightcurve instance.
        phase_view (bool): Whether the x-axis shows phase.
        time_axis_mode (str): ``mjd`` or ``date`` for the time-axis display.

    Returns:
        str: Stable revision key for the current view mode and data extent.
    """
    metadata = lcd.metadata or {}
    mission = metadata.get('mission', '')
    name = metadata.get('lookup_name') or metadata.get('name') or ''
    band = metadata.get('band', '')
    domain = lcd.active_domain or ''
    axis_mode = normalize_time_axis_mode(time_axis_mode)
    data_token = _data_uirevision_token(lcd)
    return (
        f'{mission}|{name}|{band}|{domain}|phase={int(bool(phase_view))}'
        f'|x={axis_mode}|{data_token}'
    )


def _assign_perm_ids_on_traces(fig) -> None:
    """Sets Scattergl ``ids`` from perm_index ``customdata``.

    WebGL events often drop ``customdata`` but keep ``id``. Traces without
    customdata (overlays) are left unchanged.

    Args:
        fig: Plotly figure whose photometry traces carry perm_index customdata.

    Raises:
        ValueError: If a customdata row is missing a perm_index value.
    """
    for trace in fig.data:
        custom = getattr(trace, 'customdata', None)
        if custom is None:
            continue
        ids = []
        for value in custom:
            raw = value[0] if isinstance(value, (list, tuple, np.ndarray)) else value
            if raw is None or (isinstance(raw, float) and np.isnan(raw)):
                raise ValueError('Scatter trace customdata is missing perm_index')
            ids.append(str(int(np.asarray(raw).item())))
        trace.ids = ids


def build_curvedash_scatter_figure(
    lcd,
    title: str,
    display_epoch: float = DEFAULT_EPOCH_JD,
    phase_view: bool = False,
    time_axis_mode: str = TIME_AXIS_MJD,
    lc_metadata: dict | None = None,
    color_by_label: bool = True,
    phot_description: str | None = None,
    selected_perm_indices=None,
    dragmode: str = 'zoom',
    show_error_bars: bool = False,
    highlight_from_selected_column: bool = True,
):
    """Builds an interactive scatter figure for a CurveDash lightcurve.

    Uses ``perm_index`` as ``customdata`` and ``ids`` so clientside or
    server-side selection callbacks can mark individual points. The time view
    defaults to MJD (``jd - display_epoch``) with full numeric tick labels.

    Args:
        lcd (CurveDash): Application lightcurve instance.
        title (str): Figure title text.
        display_epoch (float): JD offset subtracted for the MJD time-axis display.
        phase_view (bool): When true, plot ``phase`` instead of time.
        time_axis_mode (str): ``mjd`` or ``date`` when plotting against time.
        lc_metadata (dict, optional): Cached axis range overrides.
        color_by_label (bool): Colour markers by the ``label`` (sector) column.
        phot_description (str, optional): Extra photometry descriptor for the y-axis
            (e.g. cutout ``flux_correction`` text).
        selected_perm_indices: Optional iterable of ``perm_index`` values to highlight.
        dragmode (str): Plotly drag mode (``zoom``, ``lasso``, ``select``, etc.).
        show_error_bars (bool): Draw ``phot_err`` when the figure is a single
            trace (no sector colouring).
        highlight_from_selected_column (bool): When true (default), restore
            orange marks from ``CurveDash.selected``. Discovery client marks
            leave this false so a rebuild does not re-paint the column.

    Returns:
        plotly.graph_objects.Figure: Scatter figure ready for ``dcc.Graph``.
    """
    selected_perm_indices = normalize_selected_perm_store(selected_perm_indices)
    y_column = 'phot'
    y_label = 'magnitude' if lcd.active_domain == DOMAIN_MAG else 'flux'
    phot_unit = lcd.phot_unit
    is_magnitude = lcd.active_domain == DOMAIN_MAG
    axis_mode = normalize_time_axis_mode(time_axis_mode)

    if phase_view:
        x = lcd.phase
        x_column = 'phase'
        xaxis_title = 'phase'
    else:
        x, x_column, xaxis_title = _build_time_axis(lcd, display_epoch, axis_mode)

    label_series = lcd.lightcurve['label'] if lcd.lightcurve is not None else lcd.label
    legend_labels = _format_sector_legend_labels(label_series) if color_by_label else label_series
    df = pd.concat([x, lcd.phot, legend_labels, lcd.perm_index], axis=1)
    df.columns = [x_column, y_column, 'label', 'perm_index']

    scatter_kwargs = dict(
        x=x_column,
        y=y_column,
        custom_data='perm_index',
        hover_data=None,
    )
    if color_by_label:
        scatter_kwargs['color'] = 'label'
        scatter_kwargs['category_orders'] = {
            'label': sorted(df['label'].unique(), key=_sector_legend_sort_key),
        }

    fig = px.scatter(df, render_mode='webgl', **scatter_kwargs)
    fig.update_traces(
        selected={'marker': {'color': 'orange', 'size': 6}},
        unselected={'marker': {'opacity': 0.85}},
        hoverinfo='none',
        hovertemplate=None,
        mode='markers',
        marker=dict(size=4, symbol='circle'),
    )
    _assign_perm_ids_on_traces(fig)
    if show_error_bars and not color_by_label and lcd.phot_err is not None:
        fig.update_traces(
            error_y=dict(
                type='data',
                array=np.asarray(lcd.phot_err, dtype=float),
                visible=True,
                thickness=1,
                width=0,
                color='rgba(100, 100, 100, 0.3)',
            )
        )
    if color_by_label:
        fig.update_layout(coloraxis_showscale=False)
    y_parts = [y_label]
    if phot_description:
        y_parts.append(str(phot_description))
    if phot_unit:
        y_parts.append(str(phot_unit))
    yaxis_title = ', '.join(y_parts)

    if highlight_from_selected_column and not color_by_label:
        indices = trace_selected_indices_from_column(lcd)
        if not indices and selected_perm_indices:
            indices = trace_selected_indices(lcd, selected_perm_indices)
        fig.update_traces(selectedpoints=indices)
    else:
        apply_selectedpoints_to_figure(fig, selected_perm_indices)

    fig.update_layout(
        title=title,
        legend_title_text='Sector' if color_by_label else None,
        showlegend=color_by_label,
        margin=dict(l=0, b=20, t=30, r=20),
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        dragmode=dragmode,
        uirevision=_uirevision_key(lcd, phase_view, axis_mode),
    )
    if not highlight_from_selected_column:
        fig.update_layout(clickmode='event+select')

    _apply_time_xaxis_format(fig, phase_view=phase_view, time_axis_mode=axis_mode)

    if is_magnitude:
        fig.update_yaxes(autorange='reversed')

    if lc_metadata is not None:
        xrange_left = lc_metadata.get('xrange_left')
        xrange_right = lc_metadata.get('xrange_right')
        yrange_left = lc_metadata.get('yrange_left')
        yrange_right = lc_metadata.get('yrange_right')
        if xrange_left is not None and xrange_right is not None:
            fig.update_xaxes(range=[xrange_left, xrange_right])
        if yrange_left is not None and yrange_right is not None:
            if is_magnitude:
                fig.update_yaxes(range=[max(yrange_left, yrange_right), min(yrange_left, yrange_right)])
            else:
                fig.update_yaxes(range=[yrange_left, yrange_right])

    return fig


def figure_from_serialized(
    js_lightcurve: str,
    *,
    phase_view: bool = False,
    display_epoch: float = DEFAULT_EPOCH_JD,
    time_axis_mode: str = TIME_AXIS_MJD,
    selected_perm_indices=None,
    color_by_label: bool = True,
    phot_description: str | None = None,
    lc_metadata: dict | None = None,
    dragmode: str = 'zoom',
    show_error_bars: bool = False,
    highlight_from_selected_column: bool = True,
):
    """Builds a scatter figure from a serialised ``CurveDash`` payload.

    Args:
        js_lightcurve (str): JSON string from ``CurveDash.serialize()``.
        phase_view (bool): Plot phase on the x-axis when true.
        display_epoch (float): JD offset for the MJD time-axis display.
        time_axis_mode (str): ``mjd`` or ``date`` when plotting against time.
        selected_perm_indices: Optional iterable of highlighted ``perm_index`` values.
        color_by_label (bool): Colour markers by sector ``label`` column.
        phot_description (str, optional): Extra y-axis descriptor text.
        lc_metadata (dict, optional): Cached axis range overrides.
        dragmode (str): Plotly drag mode for the graph.
        show_error_bars (bool): Draw ``phot_err`` on a single-trace figure.
        highlight_from_selected_column (bool): Restore marks from
            ``CurveDash.selected`` when true.

    Returns:
        plotly.graph_objects.Figure: Scatter figure ready for ``dcc.Graph``.
    """
    from skvo_veb.utils.curve_dash import CurveDash
    from skvo_veb.utils.lc_bridge import build_curvedash_title

    lcd = CurveDash.from_serialized(js_lightcurve)
    return build_curvedash_scatter_figure(
        lcd,
        title=build_curvedash_title(lcd),
        display_epoch=display_epoch,
        phase_view=phase_view,
        time_axis_mode=time_axis_mode,
        lc_metadata=lc_metadata,
        color_by_label=color_by_label,
        phot_description=phot_description,
        selected_perm_indices=selected_perm_indices,
        dragmode=dragmode,
        show_error_bars=show_error_bars,
        highlight_from_selected_column=highlight_from_selected_column,
    )
