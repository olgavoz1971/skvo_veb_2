"""Shared ``dbc.Spinner`` wraps for background-callback long operations.

Ticket 5: wrap reserved layout slots so a background callback that updates
an Output inside the wrap shows a spinner without jumping the page. Do not
use full-page overlays. Defaults and style constants match the TESS
reference pages.
"""

from __future__ import annotations

import logging
from typing import Any

import dash_bootstrap_components as dbc

logger = logging.getLogger(__name__)

# Compact tools-column spinner (TESS search tools alert slot).
SPINNER_STYLE_COMPACT = {"width": "2rem", "height": "2rem"}

# Download / status row spinner: centre the glyph over the slot.
SPINNER_STYLE_CENTERED = {
    "align-items": "center",
    "justify-content": "center",
}


def wrap_with_spinner(
    children: Any,
    *,
    size: str | None = None,
    color: str | None = None,
    spinner_style: dict | None = None,
    target_components: dict | None = None,
) -> dbc.Spinner:
    """Wraps layout children in a ``dbc.Spinner`` for background-job feedback.

    The spinner appears when a background callback updates an Output that is
    a descendant of ``children`` (or listed in ``target_components``). Pass
    only reserved slots (alert strip, results panel, status row) so the
    layout does not jump.

    Args:
        children: One component or a list of components to wrap.
        size (str, optional): Bootstrap spinner size (e.g. ``sm``). Omit for
            the default size used on TESS search-results panels.
        color (str, optional): Bootstrap colour (e.g. ``primary``). Omit for
            the component default.
        spinner_style (dict, optional): Inline style for the spinner glyph.
            Use ``SPINNER_STYLE_COMPACT`` or ``SPINNER_STYLE_CENTERED``.
        target_components (dict, optional): Optional ``dbc.Spinner`` map of
            component id → property names to watch. Use when a sibling Output
            must not trigger this spinner.

    Returns:
        dash_bootstrap_components.Spinner: Spinner wrapping ``children``.
    """
    kwargs: dict[str, Any] = {"children": children}
    if size is not None:
        kwargs["size"] = size
    if color is not None:
        kwargs["color"] = color
    if spinner_style is not None:
        kwargs["spinner_style"] = spinner_style
    if target_components is not None:
        kwargs["target_components"] = target_components
    return dbc.Spinner(**kwargs)
