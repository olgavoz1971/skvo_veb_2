"""Unit tests for shared ``wrap_with_spinner`` (Ticket 5)."""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import html

from skvo_veb.components.loading import (
    SPINNER_STYLE_CENTERED,
    SPINNER_STYLE_COMPACT,
    wrap_with_spinner,
)


def test_wrap_with_spinner_defaults_and_compact():
    """Default wrap omits size; compact tools wrap matches TESS."""
    plain = wrap_with_spinner(html.Div(id="slot"))
    assert isinstance(plain, dbc.Spinner)
    assert "size" not in plain.to_plotly_json()["props"]
    compact = wrap_with_spinner(
        html.Div(id="tools"),
        size="sm",
        spinner_style=SPINNER_STYLE_COMPACT,
    )
    props = compact.to_plotly_json()["props"]
    assert props["size"] == "sm"
    assert props["spinner_style"] == SPINNER_STYLE_COMPACT


def test_wrap_with_spinner_centered_primary():
    """Download-row wrap uses primary colour and centred glyph style."""
    centered = wrap_with_spinner(
        [html.Div(id="a"), html.Div(id="b")],
        color="primary",
        spinner_style=SPINNER_STYLE_CENTERED,
    )
    props = centered.to_plotly_json()["props"]
    assert props["color"] == "primary"
    assert props["spinner_style"] == SPINNER_STYLE_CENTERED
