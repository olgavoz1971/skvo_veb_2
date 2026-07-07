"""Shared Plotly figure builders for CurveDash lightcurves."""

from __future__ import annotations

import logging

import pandas as pd
import plotly.express as px

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, DOMAIN_MAG
from skvo_veb.utils.my_tools import safe_none

logger = logging.getLogger(__name__)


def build_curvedash_scatter_figure(
    lcd,
    title: str,
    display_epoch: float = DEFAULT_EPOCH_JD,
    phase_view: bool = False,
    lc_metadata: dict | None = None,
    color_by_label: bool = True,
    phot_description: str | None = None,
):
    """Builds an interactive scatter figure for a CurveDash lightcurve.

    Uses ``perm_index`` as ``customdata`` so clientside or server-side selection
    callbacks can mark individual points. Time view subtracts ``display_epoch``
    from absolute JD for the x-axis.

    Args:
        lcd (CurveDash): Application lightcurve instance.
        title (str): Figure title text.
        display_epoch (float): JD offset subtracted for the time-axis display.
        phase_view (bool): When true, plot ``phase`` instead of time.
        lc_metadata (dict, optional): Cached axis range overrides.
        color_by_label (bool): Colour markers by the ``label`` (sector) column.
        phot_description (str, optional): Extra photometry descriptor for the y-axis
            (e.g. cutout ``flux_correction`` text).

    Returns:
        plotly.graph_objects.Figure: Scatter figure ready for ``dcc.Graph``.
    """
    y_column = 'phot'
    y_label = 'magnitude' if lcd.active_domain == DOMAIN_MAG else 'flux'
    phot_unit = lcd.phot_unit
    is_magnitude = lcd.active_domain == DOMAIN_MAG

    if phase_view:
        x = lcd.phase
        x_column = 'phase'
        xaxis_title = 'phase'
    else:
        x = lcd.jd - display_epoch if lcd.jd is not None else lcd.jd
        x_column = 'jd'
        xaxis_title = f'jd-{display_epoch}, {safe_none(lcd.time_unit)} {lcd.timescale}'

    label_series = lcd.lightcurve['label'] if lcd.lightcurve is not None else lcd.label
    df = pd.concat([x, lcd.phot, label_series, lcd.perm_index], axis=1)
    df.columns = [x_column, y_column, 'label', 'perm_index']

    scatter_kwargs = dict(
        x=x_column,
        y=y_column,
        custom_data='perm_index',
        hover_data=None,
    )
    if color_by_label:
        scatter_kwargs['color'] = 'label'

    fig = px.scatter(df, render_mode='webgl', **scatter_kwargs)
    fig.update_traces(
        selected={'marker': {'color': 'orange', 'size': 6}},
        unselected={'marker': {'opacity': 0.85}},
        hoverinfo='none',
        hovertemplate=None,
        mode='markers',
        marker=dict(size=4, symbol='circle'),
    )
    y_parts = [y_label]
    if phot_description:
        y_parts.append(str(phot_description))
    if phot_unit:
        y_parts.append(str(phot_unit))
    yaxis_title = ', '.join(y_parts)

    fig.update_layout(
        title=title,
        legend_title_text='Sector' if color_by_label else None,
        showlegend=color_by_label,
        margin=dict(l=0, b=20, t=30, r=20),
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        dragmode='zoom',
    )

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
