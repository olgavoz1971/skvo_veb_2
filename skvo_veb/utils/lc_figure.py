"""Shared Plotly figure builders for CurveDash lightcurves."""

from __future__ import annotations

import logging

import pandas as pd
import plotly.express as px

from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD,
    DOMAIN_MAG,
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

    timescale_label = safe_none(lcd.timescale) or 'UTC'
    jd = lcd.jd
    mode = normalize_time_axis_mode(time_axis_mode)

    if mode == TIME_AXIS_DATE:
        time_values = Time(jd, format='jd')
        x = pd.Series(time_values.datetime, index=jd.index if hasattr(jd, 'index') else None)
        return x, 'time', f'Date ({timescale_label})'

    x = jd - display_epoch if jd is not None else jd
    return x, 'mjd', f'MJD ({timescale_label})'


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
):
    """Builds an interactive scatter figure for a CurveDash lightcurve.

    Uses ``perm_index`` as ``customdata`` so clientside or server-side selection
    callbacks can mark individual points. The time view defaults to MJD
    (``jd - display_epoch``) with full numeric tick labels.

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
    if color_by_label:
        fig.update_layout(coloraxis_showscale=False)
    y_parts = [y_label]
    if phot_description:
        y_parts.append(str(phot_description))
    if phot_unit:
        y_parts.append(str(phot_unit))
    yaxis_title = ', '.join(y_parts)

    if not color_by_label:
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
    )
