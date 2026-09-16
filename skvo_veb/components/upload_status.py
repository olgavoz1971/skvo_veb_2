"""Shared lightcurve upload chip, busy state, and ``?`` failure detail (Ticket 6).

One product pattern for GP, Processor, and later pages:

- Icon tones: ``busy`` (hourglass), ``ok``, ``error``, ``info``
- Clientside busy caption as soon as ``dcc.Upload`` contents arrive
- Failure explanation behind a ``?`` toggle (collapse starts closed)

Pages pass upload ids and detail indexes only; CSS uses ``skvo-upload-*``.
"""

from __future__ import annotations

import json
import logging
from typing import Mapping

import dash_bootstrap_components as dbc
from dash import (
    MATCH,
    Input,
    Output,
    State,
    callback,
    clientside_callback,
    dcc,
    html,
)
from dash.exceptions import PreventUpdate

logger = logging.getLogger(__name__)

# Pattern-matching ids shared by every page that uses this upload UI.
UPLOAD_DETAIL_BTN_TYPE = "skvo-upload-detail-btn"
UPLOAD_DETAIL_TYPE = "skvo-upload-detail"
UPLOAD_DETAIL_COLLAPSE_TYPE = "skvo-upload-detail-collapse"

DEFAULT_UPLOAD_STATUS_ICONS: dict[str, str] = {
    "ok": "bi-check-circle-fill text-success",
    "info": "bi-check-circle-fill text-primary",
    "error": "bi-exclamation-triangle-fill text-danger",
    "busy": "bi-hourglass-split text-secondary",
}

_FAILURE_UI_CALLBACKS_REGISTERED = False


def upload_busy_caption(filename: str | None) -> str:
    """Builds the British English busy label for an in-flight upload.

    Args:
        filename (str, optional): Original file name from ``dcc.Upload``.

    Returns:
        str: Caption such as ``Reading lightcurve.csv…``.
    """
    name = (filename or "").strip() or "file"
    return f"Reading {name}…"


def upload_placeholder() -> html.Span:
    """Idle caption shown before a file is chosen.

    Returns:
        dash.html.Span: Muted ``Drag or select`` hint.
    """
    return html.Span(
        "Drag or select",
        className="skvo-upload-name-text text-muted",
    )


def upload_status_chip(
    filename: str,
    *,
    tone: str,
    icons: Mapping[str, str] | None = None,
) -> html.Div:
    """Builds a filename (or busy) chip with a status icon.

    Args:
        filename (str): File name; for ``tone='busy'`` the busy caption is built.
        tone (str): ``ok``, ``info``, ``error``, or ``busy``.
        icons (Mapping[str, str], optional): Tone → Bootstrap Icon classes.
            Defaults to ``DEFAULT_UPLOAD_STATUS_ICONS``.

    Returns:
        dash.html.Div: Icon plus truncating label.

    Raises:
        ValueError: If ``tone`` is not present in ``icons``.
    """
    icon_map = dict(icons) if icons is not None else dict(DEFAULT_UPLOAD_STATUS_ICONS)
    if tone not in icon_map:
        raise ValueError(f"Unknown upload status tone: {tone}")

    label = upload_busy_caption(filename) if tone == "busy" else filename
    return html.Div(
        [
            html.I(
                className=f"bi {icon_map[tone]} skvo-upload-status-icon"
            ),
            html.Span(label, className="skvo-upload-name-text", title=label),
        ],
        className="skvo-upload-status",
    )


def upload_failure_detail(title: str, body: str) -> html.Div:
    """Explanatory block revealed by the ``?`` button after a failed upload.

    Args:
        title (str): Short headline, e.g. ``Lightcurve upload failed``.
        body (str): User-facing error text (may span several lines).

    Returns:
        dash.html.Div: Content for the shared detail collapse body.
    """
    return html.Div(
        [
            html.B(title),
            html.Pre(body, className="skvo-upload-detail-body"),
        ]
    )


def upload_slot(upload_id: str, button_label: str, detail_index: str) -> html.Div:
    """Builds one data-bar slot: load control, chip area, and ``?`` toggle.

    Args:
        upload_id (str): Id for the ``dcc.Upload``; chip container is
            ``<upload_id>-text``.
        button_label (str): Sentence-case button label.
        detail_index (str): ``index`` shared with the matching detail collapse.

    Returns:
        dash.html.Div: Slot ready for a data bar.
    """
    return html.Div(
        [
            dcc.Upload(
                id=upload_id,
                children=html.Div(
                    [
                        dbc.Button(
                            button_label,
                            color="secondary",
                            outline=True,
                            size="sm",
                        ),
                        html.Div(
                            upload_placeholder(),
                            id=f"{upload_id}-text",
                            className="skvo-upload-name",
                        ),
                    ],
                    className="skvo-upload-target-inner",
                ),
                className="skvo-upload-target",
                className_active="skvo-upload-target skvo-upload-target-active",
                className_reject="skvo-upload-target skvo-upload-target-reject",
            ),
            dbc.Button(
                html.I(className="bi bi-question-circle"),
                id={"type": UPLOAD_DETAIL_BTN_TYPE, "index": detail_index},
                color="link",
                size="sm",
                className="skvo-upload-detail-btn d-none",
            ),
        ],
        className="skvo-upload-slot",
    )


def upload_detail_collapse(detail_index: str) -> dbc.Collapse:
    """Full-width collapse holding the failure explanation for one slot.

    Args:
        detail_index (str): ``index`` shared with the slot's ``?`` button.

    Returns:
        dash_bootstrap_components.Collapse: Closed collapse with an empty body.
    """
    return dbc.Collapse(
        html.Div(
            id={"type": UPLOAD_DETAIL_TYPE, "index": detail_index},
            className="skvo-upload-detail",
        ),
        id={"type": UPLOAD_DETAIL_COLLAPSE_TYPE, "index": detail_index},
        is_open=False,
    )


def upload_detail_id(detail_index: str) -> dict:
    """Builds the pattern id for a slot's failure-detail body.

    Args:
        detail_index (str): Slot index (e.g. ``lc``, ``intervals``).

    Returns:
        dict: Dash pattern-matching component id.
    """
    return {"type": UPLOAD_DETAIL_TYPE, "index": detail_index}


def register_upload_busy_clientside(upload_id: str, chip_id: str | None = None) -> None:
    """Registers the clientside busy chip for one ``dcc.Upload`` control.

    Args:
        upload_id (str): Id of the ``dcc.Upload`` component.
        chip_id (str, optional): Chip container id; defaults to
            ``<upload_id>-text``.
    """
    target_chip = chip_id or f"{upload_id}-text"
    name_js = json.dumps("skvo-upload-name-text")
    status_js = json.dumps("skvo-upload-status")
    icon_wrap_js = json.dumps("skvo-upload-status-icon")
    busy_icon_js = json.dumps(DEFAULT_UPLOAD_STATUS_ICONS["busy"])

    clientside_callback(
        f"""
        function(contents, filename) {{
            return window.dash_clientside.skvoUpload.buildBusyChip(
                contents,
                filename,
                {name_js},
                {status_js},
                {icon_wrap_js},
                {busy_icon_js},
                true
            );
        }}
        """,
        Output(target_chip, "children", allow_duplicate=True),
        Input(upload_id, "contents"),
        State(upload_id, "filename"),
        prevent_initial_call=True,
    )
    logger.debug(
        "Registered upload busy clientside upload_id=%s chip_id=%s",
        upload_id,
        target_chip,
    )


def register_upload_failure_ui_callbacks() -> None:
    """Registers shared ``?`` show/hide and toggle callbacks (once per process)."""
    global _FAILURE_UI_CALLBACKS_REGISTERED
    if _FAILURE_UI_CALLBACKS_REGISTERED:
        return

    @callback(
        Output({"type": UPLOAD_DETAIL_BTN_TYPE, "index": MATCH}, "className"),
        Output({"type": UPLOAD_DETAIL_COLLAPSE_TYPE, "index": MATCH}, "is_open"),
        Input({"type": UPLOAD_DETAIL_TYPE, "index": MATCH}, "children"),
    )
    def _reflect_upload_failure_detail(detail):
        """Shows the ``?`` only while a slot has an explanation to give.

        Args:
            detail: Children of the detail container (``None`` when clear).

        Returns:
            tuple: Button class name and collapse open state (always starts
            closed after a new detail write).
        """
        base = "skvo-upload-detail-btn"
        return (base if detail else f"{base} d-none"), False

    @callback(
        Output(
            {"type": UPLOAD_DETAIL_COLLAPSE_TYPE, "index": MATCH},
            "is_open",
            allow_duplicate=True,
        ),
        Input({"type": UPLOAD_DETAIL_BTN_TYPE, "index": MATCH}, "n_clicks"),
        State({"type": UPLOAD_DETAIL_COLLAPSE_TYPE, "index": MATCH}, "is_open"),
        prevent_initial_call=True,
    )
    def _toggle_upload_failure_detail(n_clicks, is_open):
        """Expands or hides the failure explanation.

        Args:
            n_clicks (int | None): Clicks on the slot's ``?`` button.
            is_open (bool): Current collapse state.

        Returns:
            bool: Requested collapse state.
        """
        if not n_clicks:
            raise PreventUpdate
        return not is_open

    _FAILURE_UI_CALLBACKS_REGISTERED = True
    logger.debug("Registered shared upload failure UI callbacks")


# Importing this module registers the ``?`` callbacks once for all pages.
register_upload_failure_ui_callbacks()
