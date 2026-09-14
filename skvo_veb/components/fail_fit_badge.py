"""Compact FAILED badge with a hover/click popover for the fit reason."""

from __future__ import annotations

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import dcc, html

from skvo_veb.components.extrema_modeller_appearance import (
    REVIEW_CARD_PLOT_HEIGHT,
    format_page_time_range,
)


def failed_fit_badge(
    *,
    title: str,
    reason: str,
    jd_min,
    jd_max,
    target_id: dict,
    placement: str = "top",
) -> list:
    """Builds a usual-size FAILED badge whose details open on hover or click.

    Uses the same ``legacy`` trigger as page ``?`` help: hover to peek, click
    to pin. A ``?`` beside FAILED hints that more detail is available. Interval
    bounds in the popover use the page display time (MJD by default).

    Args:
        title (str): Popover header, e.g. ``Parabola fit failed``.
        reason (str): Full failure message.
        jd_min: Interval start (absolute JD), if known.
        jd_max: Interval stop (absolute JD), if known.
        target_id (dict): Unique Dash id for the badge (must include a
            ``type`` and an ``index``).
        placement (str): Bootstrap popover placement (default ``top`` so the
            plot stays visible).

    Returns:
        list: Badge and popover components for the card badge row.
    """
    body_parts = []
    range_line = format_page_time_range(jd_min, jd_max)
    if range_line:
        body_parts.append(html.Div(range_line, className="gp-fail-range"))
    body_parts.append(
        html.Div(reason or "No further detail.", className="gp-fail-reason")
    )
    badge = dbc.Badge(
        ["FAILED", html.Span("", className="gp-fail-badge-hint")],
        id=target_id,
        color="danger",
        className="me-1 gp-fail-badge",
    )
    popover = dbc.Popover(
        [
            dbc.PopoverHeader(title),
            dbc.PopoverBody(body_parts),
        ],
        target=target_id,
        trigger="legacy",
        placement=placement,
        className="lc-discovery-help-popover gp-fail-popover",
    )
    return [badge, popover]


def review_card_graph(entry: dict) -> dcc.Graph:
    """Returns the card plot: interval figure, or an empty plot of the same height.

    Args:
        entry (dict): Serialised review row (success or failure).

    Returns:
        dash.dcc.Graph: Plotly graph matching successful-card layout size.
    """
    figure_json = entry.get("figure_json")
    if figure_json:
        fig = go.Figure(figure_json)
    else:
        fig = go.Figure()
        fig.update_layout(
            height=REVIEW_CARD_PLOT_HEIGHT,
            margin=dict(l=0, r=10, t=20, b=20),
            template="plotly_white",
            showlegend=False,
        )
    return dcc.Graph(figure=fig, config={"displaylogo": False})  # type: ignore[arg-type]
