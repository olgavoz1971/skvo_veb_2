#!/usr/bin/env python3
"""Standalone Dash probe: Lightcurve processor.

Run from ``auxiliary/trend``::

    ../../.venv/bin/python detrend_app.py
"""

from __future__ import annotations

import base64
import logging
import traceback
from io import BytesIO

import dash_bootstrap_components as dbc
import numpy as np
from dash import (  # noqa: E402
    ClientsideFunction,
    Dash,
    Input,
    Output,
    State,
    ctx,
    dcc,
    html,
    no_update,
)
from dash.exceptions import PreventUpdate

from paths import SPIKE_ROOT, ensure_import_paths

ensure_import_paths()

from skvo_veb.logging_config import configure_logging  # noqa: E402

configure_logging()

from skvo_veb.utils.curve_dash import CurveDash  # noqa: E402
from skvo_veb.utils.lc_bridge import (  # noqa: E402
    apply_phot_domain_view,
    export_curvedash,
    export_file_extension,
    format_user_upload_error,
    ingest_lightcurve_file,
)
from skvo_veb.utils.lc_config import (  # noqa: E402
    DEFAULT_EPOCH_JD,
    DEFAULT_EXPORT_FORMAT,
    DOMAIN_FLUX,
    DOMAIN_MAG,
    EXPORT_FORMAT_OPTIONS,
    TIME_AXIS_DATE,
    TIME_AXIS_MJD,
    absolute_jd_from_display_epoch,
    display_epoch_offset,
    normalize_time_axis_mode,
)
from skvo_veb.utils.lc_interaction import (  # noqa: E402
    apply_plot_point_selection,
    clear_plot_point_selection,
    delete_selected_rows,
    plot_x_to_jd,
)
from skvo_veb.utils.my_tools import PipeException, safe_float, sanitize_filename  # noqa: E402

from detrend_core import (  # noqa: E402
    METHOD_LABELS,
    apply_detrend_method,
    build_lsq_knot_grid,
    p_spline_interior_knots,
    resolve_break_tolerance,
)
from detrend_figures import (  # noqa: E402
    PLOT_TOOL_ADD,
    PLOT_TOOL_DELETE,
    PLOT_TOOL_OFF,
    figure_detrended,
    figure_raw_with_trend,
    extract_xaxis_range_mjd,
    graph_config,
    knot_click_edit,
    knot_hit_span_jd,
    merge_knot_drag,
)

logger = logging.getLogger(__name__)

DEFAULT_BREAK_TOLERANCE = 5.0
DEFAULT_MEDIAN_WINDOW_DAYS = 2.0
DEFAULT_N_POINTS = 301
DEFAULT_POLYORDER = 5
DEFAULT_SMOOTH_REL = 0.05
DEFAULT_N_KNOTS = 8
DEFAULT_LSQ_KNOT_GRID = "occupancy"
DEFAULT_PSPLINE_LAMBDA = 1.0e4
DEFAULT_PSPLINE_SEGMENTS = 40

ACCORDION_LC_ITEM_ID = "detrend-accordion-lc"
ACCORDION_SMOOTH_ITEM_ID = "detrend-accordion-smooth"
ACCORDION_DETREND_ITEM_ID = "detrend-accordion-detrend"
LC_EXPORT_SUFFIX = "_lc"
DETRENDED_EXPORT_SUFFIX = "_detrended"

app = Dash(
    __name__,
    assets_folder=str(SPIKE_ROOT / "assets"),
    external_stylesheets=[dbc.themes.SPACELAB],
    suppress_callback_exceptions=True,
)
server = app.server
app.title = "Lightcurve processor"


def _upload_placeholder() -> html.Span:
    """Return the empty upload filename placeholder.

    Args:
        None.

    Returns:
        dash.html.Span: Placeholder text.
    """
    return html.Span("No file loaded", className="text-muted")


def _upload_status(filename: str, *, tone: str) -> html.Div:
    """Build the upload filename chip.

    Args:
        filename (str): Original file name.
        tone (str): ``ok`` or ``error``.

    Returns:
        dash.html.Div: Status row.
    """
    colour = "text-success" if tone == "ok" else "text-danger"
    return html.Div(
        [
            html.Span(filename, className=f"detrend-upload-name-text {colour}"),
        ],
        className="detrend-upload-status",
    )


def _param_block(block_id: str, children: list, *, visible: bool) -> html.Div:
    """Wrap a method-specific parameter group.

    Args:
        block_id (str): Component id.
        children (list): Widgets.
        visible (bool): Initial visibility.

    Returns:
        dash.html.Div: Parameter block.
    """
    return html.Div(
        children,
        id=block_id,
        className="detrend-param-block detrend-sidebar-block",
        style={} if visible else {"display": "none"},
    )


def _click_help(help_id: str, title: str, body: str, *, placement: str = "right"):
    """Build a ``?`` control and popover for one widget.

    Args:
        help_id (str): Unique slug for component ids.
        title (str): Popover header; must match the control label.
        body (str): Popover body text.
        placement (str): Bootstrap popover placement.

    Returns:
        tuple: ``(button, popover)``.
    """
    btn_id = f"detrend-help-{help_id}-btn"
    pop_id = f"detrend-help-{help_id}-popover"
    button = html.Strong(
        "?",
        id=btn_id,
        role="button",
        tabIndex=0,
        className="detrend-help-btn",
        **{"aria-label": f"Help: {title}"},
    )
    popover = dbc.Popover(
        [
            dbc.PopoverHeader(title),
            dbc.PopoverBody(html.P(body, className="mb-0")),
        ],
        id=pop_id,
        target=btn_id,
        trigger="legacy",
        placement=placement,
        className="detrend-help-popover",
    )
    return button, popover


def _heading_with_help(
    label: str,
    help_id: str,
    title: str,
    body: str,
    *,
    label_class: str = "detrend-section-label",
) -> html.Div:
    """Build a section label with a ``?`` on the same row.

    Args:
        label (str): Visible heading.
        help_id (str): Unique slug.
        title (str): Popover title (same words as ``label``).
        body (str): Popover body.
        label_class (str): CSS class for the label.

    Returns:
        dash.html.Div: Heading row.
    """
    button, popover = _click_help(help_id, title, body)
    return html.Div(
        [
            html.Label(label, className=f"{label_class} mb-0"),
            html.Div(button, className="detrend-field-help"),
            popover,
        ],
        className="detrend-sidebar-heading-row",
    )


def _control_with_help(control, help_id: str, title: str, body: str) -> html.Div:
    """Put a control and a ``?`` on one row.

    Args:
        control: Dash component (typically a button).
        help_id (str): Unique slug.
        title (str): Popover title.
        body (str): Popover body.

    Returns:
        dash.html.Div: Heading row.
    """
    button, popover = _click_help(help_id, title, body)
    return html.Div(
        [control, html.Div(button, className="detrend-field-help"), popover],
        className="detrend-sidebar-heading-row",
    )


def _plot_toolbar() -> html.Div:
    """Build the observed-plot cleaning strip.

    Args:
        None.

    Returns:
        dash.html.Div: Delete / Unselect plus a ``?``.
    """
    help_btn, help_pop = _click_help(
        "plot-tools",
        "Delete selected",
        "Click or lasso on the observed plot, then Delete selected. "
        "Unselect clears the orange marks.",
        placement="bottom",
    )
    return html.Div(
        [
            html.Div(
                [
                    dbc.Button(
                        "Delete selected",
                        id="detrend-delete-selected",
                        color="secondary",
                        outline=True,
                        size="sm",
                        disabled=False,
                        className="detrend-btn-caution-outline",
                    ),
                    dbc.Button(
                        "Unselect",
                        id="detrend-unselect",
                        color="secondary",
                        outline=True,
                        size="sm",
                        disabled=False,
                    ),
                ],
                className="detrend-plot-toolbar-cluster",
            ),
            html.Div(help_btn, className="detrend-field-help"),
            help_pop,
            html.Div(id="detrend-plot-alert", className="detrend-plot-alert"),
        ],
        className="detrend-plot-toolbar",
    )


def _lightcurve_drawer() -> list:
    """Build the Light curve accordion body.

    Args:
        None.

    Returns:
        list: Domain, crop, ephemeris, and working-curve export widgets.
    """
    return [
        html.Div(
            [
                html.Label("Working domain", className="detrend-section-label"),
                dbc.RadioItems(
                    id="detrend-domain",
                    options=[
                        {"label": "Flux", "value": "flux"},
                        {"label": "Magnitude", "value": "mag"},
                    ],
                    value="flux",
                    inline=True,
                ),
                html.Label("Time axis", className="detrend-section-label"),
                dbc.RadioItems(
                    id="detrend-time-axis",
                    options=[
                        {"label": "MJD", "value": TIME_AXIS_MJD},
                        {"label": "Date", "value": TIME_AXIS_DATE},
                    ],
                    value=TIME_AXIS_MJD,
                    inline=True,
                ),
                dbc.Switch(
                    id="detrend-show-errors",
                    label="Show error bars",
                    value=False,
                ),
            ],
            className="detrend-sidebar-block",
        ),
        html.Div(
            [
                html.Label("Time crop (MJD)", className="detrend-section-label"),
                dbc.Input(
                    id="detrend-t-min",
                    type="number",
                    step="any",
                    placeholder="MJD min (full)",
                    size="sm",
                ),
                dbc.Input(
                    id="detrend-t-max",
                    type="number",
                    step="any",
                    placeholder="MJD max (full)",
                    size="sm",
                ),
            ],
            className="detrend-sidebar-block",
        ),
        html.Div(
            [
                _heading_with_help(
                    "Ephemeris",
                    "ephemeris",
                    "Ephemeris",
                    "Written into the exported file. Empty fields keep the "
                    "values from the upload. Folding will use the same fields.",
                ),
                dbc.InputGroup(
                    [
                        dbc.InputGroupText("P"),
                        dbc.Input(
                            id="detrend-input-period",
                            type="number",
                            placeholder="Period (days)",
                        ),
                    ],
                    size="sm",
                ),
                dbc.InputGroup(
                    [
                        dbc.InputGroupText(f"Epoch-{DEFAULT_EPOCH_JD}"),
                        dbc.Input(
                            id="detrend-input-epoch",
                            type="number",
                            placeholder="MJD offset",
                        ),
                    ],
                    size="sm",
                ),
            ],
            className="detrend-sidebar-block",
        ),
        html.Div(
            [
                _heading_with_help(
                    "Export",
                    "export-lc",
                    "Export",
                    "Time crop applies to fitting and plots. This export uses "
                    "the whole working lightcurve. The default stem gains _lc. "
                    "Format and stem are shared with the Detrend drawer.",
                ),
                dbc.Select(
                    options=EXPORT_FORMAT_OPTIONS,  # type: ignore[arg-type]
                    value=DEFAULT_EXPORT_FORMAT,
                    id="detrend-export-format",
                    size="sm",
                ),
                dbc.Input(
                    id="detrend-export-stem",
                    placeholder="lightcurve_lc",
                    type="text",
                    value="lightcurve_lc",
                    size="sm",
                ),
                dbc.Button(
                    "Export lightcurve",
                    id="detrend-download-lc-btn",
                    color="primary",
                    size="sm",
                    className="w-100",
                    disabled=True,
                ),
                html.Div(
                    id="detrend-export-feedback",
                    className="detrend-export-feedback",
                ),
            ],
            className="detrend-sidebar-block detrend-sidebar-btn-stack",
        ),
    ]

def _smooth_drawer() -> list:
    """Build the Smooth accordion body.

    Args:
        None.

    Returns:
        list: Method, parameters, knot tools, gap split, and Apply.
    """
    method_options = [
        {"label": label, "value": key} for key, label in METHOD_LABELS.items()
    ]
    return [
        html.Div(
            [
                html.Label("Method", className="detrend-section-label"),
                dbc.Select(
                    id="detrend-method",
                    options=method_options,
                    value="spline_lsq",
                    size="sm",
                ),
            ],
            className="detrend-sidebar-block",
        ),
        _param_block(
            "detrend-params-median",
            [
                html.Label("Median window (days)", className="detrend-export-sublabel"),
                dbc.Input(
                    id="detrend-median-window",
                    type="number",
                    step="any",
                    min=1e-6,
                    value=DEFAULT_MEDIAN_WINDOW_DAYS,
                    size="sm",
                ),
            ],
            visible=False,
        ),
        _param_block(
            "detrend-params-points",
            [
                html.Label("Window (points)", className="detrend-export-sublabel"),
                dbc.Input(
                    id="detrend-n-points",
                    type="number",
                    step=1,
                    min=3,
                    value=DEFAULT_N_POINTS,
                    size="sm",
                ),
                html.Label("Polynomial order", className="detrend-export-sublabel"),
                dbc.Input(
                    id="detrend-polyorder",
                    type="number",
                    step=1,
                    min=1,
                    value=DEFAULT_POLYORDER,
                    size="sm",
                ),
            ],
            visible=False,
        ),
        _param_block(
            "detrend-params-biweight",
            [
                html.Label("Window (points)", className="detrend-export-sublabel"),
                dbc.Input(
                    id="detrend-n-points-biweight",
                    type="number",
                    step=1,
                    min=1,
                    value=DEFAULT_N_POINTS,
                    size="sm",
                ),
            ],
            visible=False,
        ),
        _param_block(
            "detrend-params-smooth",
            [
                html.Label("Smoothing (relative)", className="detrend-export-sublabel"),
                dbc.Input(
                    id="detrend-smooth-rel",
                    type="number",
                    step="any",
                    min=0,
                    value=DEFAULT_SMOOTH_REL,
                    size="sm",
                ),
                html.Label("Explicit s (optional)", className="detrend-export-sublabel"),
                dbc.Input(
                    id="detrend-smooth-s",
                    type="number",
                    step="any",
                    min=0,
                    placeholder="auto from relative s",
                    size="sm",
                ),
            ],
            visible=False,
        ),
        _param_block(
            "detrend-params-lsq",
            [
                _heading_with_help(
                    "Interior knots",
                    "lsq-knots",
                    "Interior knots",
                    "Place knots builds a grid without entering edit mode. "
                    "Choose Add knot to click or drag a green line, or "
                    "Delete knot to click near one.",
                    label_class="detrend-export-sublabel",
                ),
                dbc.Input(
                    id="detrend-n-knots",
                    type="number",
                    step=1,
                    min=1,
                    value=DEFAULT_N_KNOTS,
                    size="sm",
                ),
                html.Label("Knot grid", className="detrend-export-sublabel"),
                dbc.RadioItems(
                    id="detrend-lsq-knot-grid",
                    options=[
                        {"label": "Uniform", "value": "uniform"},
                        {"label": "By occupancy", "value": "occupancy"},
                    ],
                    value=DEFAULT_LSQ_KNOT_GRID,
                    inline=True,
                ),
            ],
            visible=True,
        ),
        _param_block(
            "detrend-params-pspline",
            [
                _heading_with_help(
                    "Penalty lambda",
                    "pspline",
                    "Penalty lambda",
                    "P-spline knots are a uniform grid from the segment count.",
                    label_class="detrend-export-sublabel",
                ),
                dbc.Input(
                    id="detrend-pspline-lambda",
                    type="number",
                    step="any",
                    min=0,
                    value=DEFAULT_PSPLINE_LAMBDA,
                    size="sm",
                ),
                html.Label("Segments", className="detrend-export-sublabel"),
                dbc.Input(
                    id="detrend-pspline-nseg",
                    type="number",
                    step=1,
                    min=1,
                    value=DEFAULT_PSPLINE_SEGMENTS,
                    size="sm",
                ),
            ],
            visible=False,
        ),
        _param_block(
            "detrend-params-place-knots",
            [
                _control_with_help(
                    dbc.Button(
                        "Place knots",
                        id="detrend-place-knots",
                        color="primary",
                        size="sm",
                    ),
                    "place-knots",
                    "Place knots",
                    "Places the knot grid on the plot without fitting. "
                    "Edit LSQ knots, then Apply smooth.",
                ),
            ],
            visible=True,
        ),
        html.Div(
            [
                html.Label("Gaps", className="detrend-section-label"),
                _control_with_help(
                    dbc.Switch(
                        id="detrend-split-gaps",
                        label="Split on gaps",
                        value=True,
                    ),
                    "split-gaps",
                    "Split on gaps",
                    "When on, each smooth is fitted separately on contiguous "
                    "stretches of the light curve. A gap is a jump in time "
                    "larger than the break-tolerance threshold. When off, "
                    "the whole series is treated as one segment.",
                ),
                _heading_with_help(
                    "Break tolerance (days)",
                    "break-tol",
                    "Break tolerance (days)",
                    "Maximum allowed gap between consecutive points, in days. "
                    "Times are Julian Date, so the difference is already in "
                    "days. A new segment starts where the next point is more "
                    "than this many days later. Default 5 days.",
                    label_class="detrend-export-sublabel",
                ),
                dbc.Input(
                    id="detrend-break-tol",
                    type="number",
                    step="any",
                    min=0,
                    value=DEFAULT_BREAK_TOLERANCE,
                    size="sm",
                ),
            ],
            className="detrend-sidebar-block",
        ),
        html.Div(
            [
                dbc.Button(
                    "Apply smooth",
                    id="detrend-apply",
                    color="primary",
                    size="sm",
                    className="w-100",
                ),
                html.Div(
                    id="detrend-apply-feedback",
                    className="detrend-apply-feedback",
                ),
            ],
            className="detrend-sidebar-block detrend-sidebar-btn-stack",
        ),
        _param_block(
            "detrend-params-knot-tool",
            [
                _heading_with_help(
                    "Knot tool",
                    "knot-tool",
                    "Knot tool",
                    "Use the figure toolbar to pan, zoom, or lasso. Add knot "
                    "and Delete knot apply to the least-squares spline.",
                ),
                dbc.RadioItems(
                    id="detrend-plot-tool",
                    options=[
                        {"label": "Off", "value": PLOT_TOOL_OFF},
                        {"label": "Add knot", "value": PLOT_TOOL_ADD},
                        {"label": "Delete knot", "value": PLOT_TOOL_DELETE},
                    ],
                    value=PLOT_TOOL_OFF,
                ),
            ],
            visible=True,
        ),
    ]




def _detrend_drawer() -> list:
    """Build the Detrend accordion body.

    Args:
        None.

    Returns:
        list: Residual light-curve export (Apply detrend arrives in step 2).
    """
    return [
        html.Div(
            [
                _heading_with_help(
                    "Export",
                    "export-detrend",
                    "Export",
                    "Filename gains _detrended. Format and stem come from "
                    "Lightcurve. Residual is from the last Apply smooth.",
                ),
                dbc.Button(
                    "Export detrended",
                    id="detrend-download-btn",
                    color="primary",
                    size="sm",
                    className="w-100",
                    disabled=True,
                ),
                html.Div(
                    id="detrend-detrend-export-feedback",
                    className="detrend-export-feedback",
                ),
            ],
            className="detrend-sidebar-block detrend-sidebar-btn-stack",
        ),
    ]


def _sidebar() -> html.Div:
    """Build the workflow accordion sidebar.

    Args:
        None.

    Returns:
        dash.html.Div: Light curve, Smooth, and Detrend drawers.
    """
    return html.Div(
        dbc.Accordion(
            [
                dbc.AccordionItem(
                    html.Div(_lightcurve_drawer(), className="detrend-drawer-body"),
                    title="Lightcurve",
                    item_id=ACCORDION_LC_ITEM_ID,
                ),
                dbc.AccordionItem(
                    html.Div(_smooth_drawer(), className="detrend-drawer-body"),
                    title="Smooth",
                    item_id=ACCORDION_SMOOTH_ITEM_ID,
                ),
                dbc.AccordionItem(
                    html.Div(_detrend_drawer(), className="detrend-drawer-body"),
                    title="Detrend",
                    item_id=ACCORDION_DETREND_ITEM_ID,
                ),
            ],
            id="detrend-workflow-accordion",
            always_open=True,
            active_item=[ACCORDION_LC_ITEM_ID],
            className="detrend-workflow-accordion",
        ),
        className="detrend-sidebar",
    )


app.layout = dbc.Container(
    [
        dcc.Store(id="detrend-store-lc"),
        dcc.Store(id="detrend-store-result"),
        dcc.Store(id="detrend-store-knots", data=[]),
        dcc.Store(id="detrend-store-knot-pick"),
        dcc.Store(id="detrend-store-clientside"),
        dcc.Download(id="detrend-download-lc"),
        dcc.Download(id="detrend-download"),
        html.Div(
            [
                html.H1("Lightcurve processor", className="detrend-page-title"),
            ],
            className="detrend-page-header",
        ),
        html.Div(
            [
                html.Div(
                    [
                        dcc.Upload(
                            id="detrend-upload-lc",
                            children=html.Div(
                                [
                                    dbc.Button(
                                        "Load lightcurve",
                                        color="secondary",
                                        outline=True,
                                        size="sm",
                                    ),
                                    html.Div(
                                        _upload_placeholder(),
                                        id="detrend-upload-text",
                                        className="detrend-upload-name",
                                    ),
                                ],
                                className="detrend-upload-target-inner",
                            ),
                            className="detrend-upload-target",
                            className_active="detrend-upload-target detrend-upload-target-active",
                            className_reject="detrend-upload-target detrend-upload-target-reject",
                        ),
                    ],
                    className="detrend-data-slot",
                ),
                html.Div(id="detrend-upload-detail"),
            ],
            className="detrend-data-hub detrend-data-bar",
        ),
        dbc.Row(
            [
                dbc.Col(_sidebar(), width=3, className="detrend-sidebar-col"),
                dbc.Col(
                    html.Div(
                        [
                            _plot_toolbar(),
                            html.Div(
                                dcc.Graph(
                                    id="detrend-graph-raw",
                                    className="detrend-graph",
                                    config=graph_config(plot_tool=PLOT_TOOL_OFF),
                                ),
                                id="detrend-graph-raw-shell",
                                className="detrend-graph-shell",
                            ),
                            dcc.Graph(
                                id="detrend-graph-detrended",
                                className="detrend-graph",
                                config=graph_config(plot_tool=PLOT_TOOL_OFF),
                            ),
                        ],
                        className="detrend-plot-stack",
                    ),
                    width=9,
                ),
            ]
        ),
    ],
    fluid=True,
    className="detrend-page",
)


def _optional_float(value) -> float | None:
    """Parse an optional numeric widget value.

    Args:
        value: Widget contents.

    Returns:
        float | None: Parsed number, or ``None`` when empty.
    """
    if value is None or value == "":
        return None
    return float(value)


def _display_mjd_to_jd(value: float | None) -> float | None:
    """Convert a user-facing MJD crop bound to absolute Julian Date.

    Args:
        value (float | None): Display MJD (``JD - DEFAULT_EPOCH_JD``), or ``None``.

    Returns:
        float | None: Absolute JD, or ``None`` when the bound is unset.
    """
    if value is None:
        return None
    return plot_x_to_jd(value, TIME_AXIS_MJD, DEFAULT_EPOCH_JD)


def _lcd_from_store(lc_json: str, domain: str | None = None) -> CurveDash:
    """Rehydrate the working ``CurveDash`` and convert domain when requested.

    Args:
        lc_json (str): ``CurveDash.serialize()`` payload.
        domain (str | None): Requested ``mag`` or ``flux``, or ``None`` to keep
            the stored domain.

    Returns:
        CurveDash: Working light curve.

    Raises:
        ValueError: If the store is empty.
        PipeException: If domain conversion fails.
    """
    lcd = CurveDash.from_serialized(lc_json)
    if lcd.lightcurve is None or lcd.lightcurve.empty:
        raise ValueError("no lightcurve is loaded")
    if domain in (DOMAIN_FLUX, DOMAIN_MAG) and domain != lcd.active_domain:
        apply_phot_domain_view(lcd, show_magnitude=(domain == DOMAIN_MAG))
    return lcd


def _raw_labels(lcd: CurveDash) -> np.ndarray:
    """Return the label column without stringifying missing cells.

    Args:
        lcd (CurveDash): Working light curve.

    Returns:
        numpy.ndarray: Object array of raw label cells.
    """
    n = int(len(lcd.lightcurve))
    if "label" not in lcd.lightcurve.columns:
        return np.full(n, None, dtype=object)
    return lcd.lightcurve["label"].to_numpy(dtype=object)


def _timescale_refposition(lcd: CurveDash) -> tuple[str | None, str | None]:
    """Read TIMESYS labels from ``CurveDash`` metadata.

    Args:
        lcd (CurveDash): Working light curve.

    Returns:
        tuple: ``(timescale, refposition)``.
    """
    meta = lcd.metadata or {}
    envelope = meta.get("vo_envelope") or {}
    return lcd.timescale, envelope.get("refposition")


def _selected_perm_indices(lcd: CurveDash) -> list[int]:
    """Return permanent indices marked ``selected=1``.

    Args:
        lcd (CurveDash): Working light curve.

    Returns:
        list[int]: Selected ``perm_index`` values.
    """
    df = lcd.lightcurve
    if df is None or "selected" not in df.columns or "perm_index" not in df.columns:
        return []
    mask = df["selected"] == 1
    return [int(v) for v in df.loc[mask, "perm_index"].tolist()]


def _with_export_suffix(stem: str | None, suffix: str, fallback: str) -> str:
    """Append a product suffix to the shared export stem if it is missing.

    Args:
        stem (str | None): User-entered basename.
        suffix (str): Product suffix, including the leading underscore.
        fallback (str): Stem used when ``stem`` is empty.

    Returns:
        str: Stem ending in ``suffix``.
    """
    base = (stem or "").strip() or fallback
    if base.lower().endswith(suffix):
        return base
    return f"{base}{suffix}"


def _lc_export_stem(stem: str | None) -> str:
    """Build the working-lightcurve export basename.

    Args:
        stem (str | None): User-entered basename.

    Returns:
        str: Stem ending in ``_lc``.
    """
    return _with_export_suffix(stem, LC_EXPORT_SUFFIX, "lightcurve")


def _strip_lc_suffix(stem: str) -> str:
    """Remove a trailing ``_lc`` so other products do not stack suffixes.

    Args:
        stem (str): Shared export stem, possibly already ending in ``_lc``.

    Returns:
        str: Stem without a trailing ``_lc``.
    """
    base = (stem or "").strip()
    if base.lower().endswith(LC_EXPORT_SUFFIX):
        return base[: -len(LC_EXPORT_SUFFIX)]
    return base


def _detrended_export_stem(stem: str | None) -> str:
    """Build the detrended export basename from the shared stem field.

    The stem field holds the working-curve name (``_lc``). Detrended files
    use ``{base}_detrended``, not ``{base}_lc_detrended``.

    Args:
        stem (str | None): User-entered basename.

    Returns:
        str: Stem ending in ``_detrended``.
    """
    base = _strip_lc_suffix(stem or "") or "lightcurve"
    return _with_export_suffix(base, DETRENDED_EXPORT_SUFFIX, "lightcurve")


def _stem_from_upload_filename(filename: str | None) -> str:
    """Return a basename-only export stem from an uploaded file name.

    Args:
        filename (str | None): Original upload filename.

    Returns:
        str: Stem without extension, or empty when ``filename`` is missing.
    """
    if not filename:
        return ""
    return filename.rsplit(".", 1)[0]


def _export_download_name(stem: str | None, table_format: str, *, fallback: str) -> str:
    """Resolve a browser download filename for a light-curve export.

    Args:
        stem (str | None): User-entered basename or full filename.
        table_format (str): Export format identifier from ``EXPORT_FORMAT_OPTIONS``.
        fallback (str): Stem used when ``stem`` is empty.

    Returns:
        str: Sanitised filename with an extension when the stem has none.
    """
    raw = (stem or fallback).strip()
    safe = sanitize_filename(raw)
    if "." in safe:
        return safe
    ext = export_file_extension(table_format)
    return f"{safe}.{ext}"


def _apply_export_ephemeris(
    lcd,
    period,
    epoch_display,
    *,
    display_epoch: float = DEFAULT_EPOCH_JD,
):
    """Write sidebar P / Epoch onto a ``CurveDash`` before export.

    Empty widgets leave ingest-time metadata unchanged.

    Args:
        lcd: ``CurveDash`` rebuilt from the page store.
        period: Sidebar period in days, or empty.
        epoch_display: Sidebar epoch as MJD offset (``JD - display_epoch``).
        display_epoch (float): Same offset as the plot and Epoch field.

    Returns:
        CurveDash: The same instance, mutated in place.
    """
    period_val = safe_float(period)
    if period_val is not None and period_val > 0:
        lcd.period = period_val
        lcd.period_unit = "d"
        logger.debug("Export period set from sidebar: %s d", period_val)

    epoch_abs = absolute_jd_from_display_epoch(epoch_display, display_epoch)
    if epoch_abs is not None:
        lcd.epoch = epoch_abs
        logger.debug("Export epoch set from sidebar: JD %s", epoch_abs)
    return lcd


def _plot_uirevision(
    lcd: CurveDash | None,
    filename: str | None,
    domain: str,
    time_axis_mode: str,
) -> str:
    """Return Plotly ``uirevision`` so zoom is kept without a zoom store.

    Same contract as Discovery: the token changes when the working series
    identity or the view (domain, MJD / Date) changes. Selection flags are
    not included, so marking points does not rezoom. Delete changes the
    row count or JD span, so Plotly autoranges and drops stale orange marks.

    Args:
        lcd (CurveDash | None): Working light curve, or ``None`` when empty.
        filename (str | None): Upload name.
        domain (str): ``mag`` or ``flux``.
        time_axis_mode (str): ``mjd`` or ``date``.

    Returns:
        str: Revision token for both plots.
    """
    axis = normalize_time_axis_mode(time_axis_mode)
    name = ""
    data = "n=0"
    if lcd is not None and lcd.lightcurve is not None and not lcd.lightcurve.empty:
        jd = lcd.lightcurve["jd"]
        data = f"n={len(lcd.lightcurve)}|{float(jd.min()):.8f}|{float(jd.max()):.8f}"
        meta = lcd.metadata or {}
        name = meta.get("lookup_name") or meta.get("name") or ""
    return f"{filename or 'lc'}|{name}|{domain}|x={axis}|{data}"


def _fit_overlay(result, times: np.ndarray, domain: str, method: str):
    """Return trend and residual arrays when they match the working series.

    The fit store is an overlay, not a second light curve. If the payload is
    missing, for another domain or method, or a different length, it is ignored.

    Args:
        result: Fit payload from ``detrend-store-result``, or ``None``.
        times (numpy.ndarray): Working-series Julian Dates (after crop).
        domain (str): Working photometric domain.
        method (str): Active smooth method.

    Returns:
        tuple: ``(trend, detrended, det_err)``, each ``None`` when unused.
    """
    if not result:
        return None, None, None
    if result.get("domain") != domain or result.get("method") != method:
        return None, None, None
    trend = np.asarray(result["trend"], dtype=float)
    n = int(np.asarray(times).size)
    if trend.size != n:
        logger.warning(
            "Ignoring stale fit overlay (%s points) on working series (%s points)",
            trend.size,
            n,
        )
        return None, None, None
    return (
        trend,
        np.asarray(result["detrended"], dtype=float),
        np.asarray(result["det_err"], dtype=float),
    )


def _crop_series(
    times: np.ndarray,
    values: np.ndarray,
    errors: np.ndarray | None,
    t_min: float | None,
    t_max: float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Apply inclusive absolute-JD bounds.

    Args:
        times (numpy.ndarray): Absolute Julian Dates.
        values (numpy.ndarray): Photometry.
        errors (numpy.ndarray | None): Uncertainties.
        t_min (float | None): Lower bound (absolute JD).
        t_max (float | None): Upper bound (absolute JD).

    Returns:
        tuple: Cropped ``(times, values, errors)``.

    Raises:
        ValueError: If the crop is empty or inverted.
    """
    keep = np.ones(times.shape, dtype=bool)
    if t_min is not None:
        keep &= times >= t_min
    if t_max is not None:
        keep &= times <= t_max
    if t_min is not None and t_max is not None and t_min > t_max:
        raise ValueError("t min must be <= t max")
    if not np.any(keep):
        raise ValueError("no points remain in the requested time crop")
    err = None if errors is None else errors[keep]
    return times[keep], values[keep], err


def _loaded_arrays(
    lc_json: str,
    domain: str,
    t_min: float | None,
    t_max: float | None,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray | None,
    str,
    bool,
    str | None,
    str | None,
    np.ndarray,
    np.ndarray,
]:
    """Rehydrate, convert domain, and crop the working ``CurveDash``.

    Crop widgets are display MJD (same scale as the GP page). Arrays returned
    here keep absolute Julian Date. The stored curve itself is not cropped.

    Args:
        lc_json (str): ``CurveDash.serialize()`` payload.
        domain (str): ``mag`` or ``flux``.
        t_min (float | None): Optional crop start (display MJD).
        t_max (float | None): Optional crop end (display MJD).

    Returns:
        tuple: ``(jd, y, err, y_label, is_mag, timescale, refposition,
        perm_index, labels)``.
    """
    lcd = _lcd_from_store(lc_json, domain)
    if lcd.jd is None or lcd.phot is None:
        raise ValueError("stored CurveDash has no photometry")
    times = np.asarray(lcd.jd, dtype=float)
    values = np.asarray(lcd.phot, dtype=float)
    err = None if lcd.phot_err is None else np.asarray(lcd.phot_err, dtype=float)
    perm = np.asarray(lcd.perm_index, dtype=int)
    labels = _raw_labels(lcd)
    n = int(times.size)
    if perm.size != n or labels.size != n or values.size != n:
        raise ValueError("CurveDash photometry columns have unequal length")
    tmin_jd = _display_mjd_to_jd(t_min)
    tmax_jd = _display_mjd_to_jd(t_max)
    crop = np.ones(times.shape, dtype=bool)
    if tmin_jd is not None:
        crop &= times >= tmin_jd
    if tmax_jd is not None:
        crop &= times <= tmax_jd
    if tmin_jd is not None and tmax_jd is not None and tmin_jd > tmax_jd:
        raise ValueError("t min must be <= t max")
    if not np.any(crop):
        raise ValueError("no points remain in the requested time crop")
    times = times[crop]
    values = values[crop]
    perm = perm[crop]
    labels = labels[crop]
    err = None if err is None else err[crop]
    is_mag = lcd.active_domain == DOMAIN_MAG
    timescale, refposition = _timescale_refposition(lcd)
    y_label = "Magnitude" if is_mag else "Flux"
    return (
        times,
        values,
        err,
        y_label,
        is_mag,
        timescale,
        refposition,
        perm,
        labels,
    )


def _series_to_store(
    times: np.ndarray,
    observed: np.ndarray,
    obs_err: np.ndarray | None,
    trend: np.ndarray,
    detrended: np.ndarray,
    det_err: np.ndarray,
    *,
    domain: str,
    method: str,
    knots: list[float],
    source_index: np.ndarray,
    labels: np.ndarray,
) -> dict:
    """Pack fit arrays for ``dcc.Store``.

    Args:
        times (numpy.ndarray): JD.
        observed (numpy.ndarray): Observed photometry.
        obs_err (numpy.ndarray | None): Uncertainties.
        trend (numpy.ndarray): Trend.
        detrended (numpy.ndarray): Residual.
        det_err (numpy.ndarray): Residual uncertainties.
        domain (str): Working domain.
        method (str): Method id.
        knots (list[float]): Knot times used (LSQ) or displayed (P-spline).
        source_index (numpy.ndarray): Permanent indices of the fitted rows.
        labels (numpy.ndarray): Per-point group labels.

    Returns:
        dict: JSON-safe payload.
    """
    err_list = None if obs_err is None else np.asarray(obs_err, dtype=float).tolist()
    n = int(np.asarray(times).size)
    src_arr = np.asarray(source_index, dtype=int)
    raw_labels = np.asarray(labels, dtype=object)
    if src_arr.size != n or raw_labels.size != n:
        raise ValueError("source_index and labels must match the fitted series length")
    label_list = []
    for v in raw_labels:
        if v is None:
            label_list.append(None)
        elif hasattr(v, "item"):
            label_list.append(v.item())
        else:
            label_list.append(v)
    return {
        "jd": np.asarray(times, dtype=float).tolist(),
        "y": np.asarray(observed, dtype=float).tolist(),
        "err": err_list,
        "trend": np.asarray(trend, dtype=float).tolist(),
        "detrended": np.asarray(detrended, dtype=float).tolist(),
        "det_err": np.asarray(det_err, dtype=float).tolist(),
        "domain": domain,
        "method": method,
        "knots": [float(k) for k in knots],
        "source_index": src_arr.tolist(),
        "labels": label_list,
    }


def _fit_from_widgets(
    lc_json: str,
    *,
    method: str,
    domain: str,
    split_gaps: bool,
    break_tol: float | None,
    t_min: float | None,
    t_max: float | None,
    median_window: float | None,
    n_points: int | None,
    n_points_biweight: int | None,
    polyorder: int | None,
    smooth_rel: float | None,
    smooth_s: float | None,
    knots: list[float],
    n_knots: int | None,
    knot_grid_mode: str,
    penalty_lambda: float | None,
    n_segments: int | None,
) -> dict:
    """Run the selected method with current widget values.

    Args:
        lc_json (str): ``CurveDash.serialize()`` payload.
        method (str): Method id.
        domain (str): Working domain.
        split_gaps (bool): Split on cadence gaps.
        break_tol (float | None): Maximum gap in days.
        t_min (float | None): Crop start (display MJD).
        t_max (float | None): Crop end (display MJD).
        median_window (float | None): Median window in days.
        n_points (int | None): SG / Lightkurve window.
        n_points_biweight (int | None): Biweight window.
        polyorder (int | None): Polynomial order.
        smooth_rel (float | None): Relative smoothing ``s``.
        smooth_s (float | None): Explicit smoothing ``s``.
        knots (list[float]): Current LSQ knots.
        n_knots (int | None): Requested knot count if knots are empty.
        knot_grid_mode (str): ``uniform`` or ``occupancy`` for an empty LSQ grid.
        penalty_lambda (float | None): P-spline lambda.
        n_segments (int | None): P-spline segments.

    Returns:
        dict: Store payload from ``_series_to_store``.
    """
    times, values, err, _ylabel, _is_mag, _ts, _ref, source, labels = _loaded_arrays(
        lc_json, domain, t_min, t_max
    )
    gap = resolve_break_tolerance(bool(split_gaps), float(break_tol or DEFAULT_BREAK_TOLERANCE))
    use_knots = [float(k) for k in knots]
    if method == "spline_lsq" and not use_knots:
        n_use = int(n_knots or DEFAULT_N_KNOTS)
        use_knots = build_lsq_knot_grid(
            times,
            n_use,
            mode=knot_grid_mode or DEFAULT_LSQ_KNOT_GRID,
            break_tolerance=gap,
        ).tolist()

    point_window = int(n_points or DEFAULT_N_POINTS)
    if method == "biweight":
        point_window = int(n_points_biweight or DEFAULT_N_POINTS)

    display_knots = use_knots
    if method == "pspline":
        display_knots = p_spline_interior_knots(
            times, int(n_segments or DEFAULT_PSPLINE_SEGMENTS)
        ).tolist()
    elif method != "spline_lsq":
        display_knots = []

    trend, detrended, det_err = apply_detrend_method(
        times,
        values,
        err,
        method=method,
        mode=domain,  # type: ignore[arg-type]
        break_tolerance=gap,
        median_window_days=float(median_window or DEFAULT_MEDIAN_WINDOW_DAYS),
        n_points=point_window,
        polyorder=int(polyorder or DEFAULT_POLYORDER),
        smoothing_s=smooth_s,
        smoothing_rel=float(smooth_rel if smooth_rel is not None else DEFAULT_SMOOTH_REL),
        knots=np.asarray(use_knots, dtype=float),
        penalty_lambda=float(
            penalty_lambda if penalty_lambda is not None else DEFAULT_PSPLINE_LAMBDA
        ),
        n_segments=int(n_segments or DEFAULT_PSPLINE_SEGMENTS),
    )
    return _series_to_store(
        times,
        values,
        err,
        trend,
        detrended,
        det_err,
        domain=domain,
        method=method,
        knots=display_knots,
        source_index=source,
        labels=labels,
    )


@app.callback(
    Output("detrend-params-median", "style"),
    Output("detrend-params-points", "style"),
    Output("detrend-params-biweight", "style"),
    Output("detrend-params-smooth", "style"),
    Output("detrend-params-lsq", "style"),
    Output("detrend-params-pspline", "style"),
    Output("detrend-params-knot-tool", "style"),
    Output("detrend-params-place-knots", "style"),
    Input("detrend-method", "value"),
)
def toggle_method_params(method: str):
    """Show the parameter block that belongs to the selected method.

    Args:
        method (str): Method id.

    Returns:
        tuple: Display styles for each parameter block.
    """
    hidden = {"display": "none"}
    shown = {}
    return (
        shown if method == "median" else hidden,
        shown if method in ("savgol", "lightkurve") else hidden,
        shown if method == "biweight" else hidden,
        shown if method == "spline_smooth" else hidden,
        shown if method == "spline_lsq" else hidden,
        shown if method == "pspline" else hidden,
        shown if method == "spline_lsq" else hidden,
        shown if method in ("spline_lsq", "pspline") else hidden,
    )


@app.callback(
    Output("detrend-store-lc", "data"),
    Output("detrend-upload-text", "children"),
    Output("detrend-upload-detail", "children"),
    Output("detrend-store-result", "data", allow_duplicate=True),
    Output("detrend-store-knots", "data", allow_duplicate=True),
    Output("detrend-export-stem", "value"),
    Output("detrend-domain", "value"),
    Output("detrend-plot-tool", "value"),
    Output("detrend-input-period", "value"),
    Output("detrend-input-epoch", "value"),
    Output("detrend-t-min", "value"),
    Output("detrend-t-max", "value"),
    Input("detrend-upload-lc", "contents"),
    State("detrend-upload-lc", "filename"),
    prevent_initial_call=True,
)
def upload_lightcurve(contents, filename):
    """Ingest a light curve into a working ``CurveDash``.

    Args:
        contents: ``dcc.Upload`` payload.
        filename: Original filename.

    Returns:
        tuple: Store, status, detail, cleared fit state, export stem, domain,
        plot tool, and ephemeris widgets prefilled from the file.
    """
    if contents is None:
        raise PreventUpdate
    try:
        _content_type, content_string = contents.split(",", 1)
        decoded = base64.b64decode(content_string)
        lcd = ingest_lightcurve_file(BytesIO(decoded), filename or "uploaded")
        native = lcd.active_domain
        epoch_abs = lcd.epoch
        epoch_display = (
            display_epoch_offset(epoch_abs, DEFAULT_EPOCH_JD)
            if epoch_abs is not None
            else None
        )
        stem = _stem_from_upload_filename(filename)
        export_stem = _lc_export_stem(stem or "lightcurve")
        logger.info(
            "Loaded %s (%s points)",
            filename,
            0 if lcd.lightcurve is None else len(lcd.lightcurve),
        )
        return (
            lcd.serialize(),
            _upload_status(filename or "uploaded file", tone="ok"),
            None,
            None,
            [],
            export_stem,
            native if native in (DOMAIN_FLUX, DOMAIN_MAG) else DOMAIN_FLUX,
            PLOT_TOOL_OFF,
            lcd.period,
            epoch_display,
            None,
            None,
        )
    except Exception as exc:
        logger.error("Upload failed: %s", filename)
        logger.error(traceback.format_exc())
        return (
            no_update,
            _upload_status(filename or "upload", tone="error"),
            html.Div(
                html.Div(
                    format_user_upload_error(exc),
                    className="detrend-upload-detail-body",
                ),
                className="detrend-upload-detail",
            ),
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
        )


@app.callback(
    Output("detrend-store-result", "data", allow_duplicate=True),
    Output("detrend-store-knots", "data", allow_duplicate=True),
    Output("detrend-apply-feedback", "children", allow_duplicate=True),
    Input("detrend-place-knots", "n_clicks"),
    State("detrend-store-lc", "data"),
    State("detrend-method", "value"),
    State("detrend-domain", "value"),
    State("detrend-split-gaps", "value"),
    State("detrend-break-tol", "value"),
    State("detrend-t-min", "value"),
    State("detrend-t-max", "value"),
    State("detrend-n-knots", "value"),
    State("detrend-lsq-knot-grid", "value"),
    State("detrend-pspline-nseg", "value"),
    prevent_initial_call=True,
)
def place_knots(
    n_clicks,
    lc_json,
    method,
    domain,
    split_gaps,
    break_tol,
    t_min,
    t_max,
    n_knots,
    knot_grid_mode,
    n_segments,
):
    """Draw the knot grid on the observed plot without fitting a trend.

    Args:
        n_clicks: Place-knots clicks.
        lc_json: Stored ``CurveDash`` JSON.
        method: Method id.
        domain: Working domain.
        split_gaps: Gap-split switch.
        break_tol: Maximum gap in days.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).
        n_knots: Requested LSQ knot count.
        knot_grid_mode: ``uniform`` or ``occupancy``.
        n_segments: P-spline segment count.

    Returns:
        tuple: Cleared fit, new knots, optional status.
    """
    if not n_clicks:
        raise PreventUpdate
    if method not in ("spline_lsq", "pspline"):
        raise PreventUpdate
    if not lc_json:
        return no_update, no_update, dbc.Alert(
            "Load a light curve first.",
            color="warning",
            className="py-2 small mb-0",
        )
    try:
        times, _y, _e, _lab, _is_mag, _ts, _ref, _src, _labels = _loaded_arrays(
            lc_json,
            domain,
            _optional_float(t_min),
            _optional_float(t_max),
        )
        gap = resolve_break_tolerance(
            bool(split_gaps), float(break_tol or DEFAULT_BREAK_TOLERANCE)
        )
        if method == "pspline":
            placed = p_spline_interior_knots(
                times, int(n_segments or DEFAULT_PSPLINE_SEGMENTS)
            ).tolist()
            requested = int(n_segments or DEFAULT_PSPLINE_SEGMENTS)
        else:
            requested = int(n_knots or DEFAULT_N_KNOTS)
            placed = build_lsq_knot_grid(
                times,
                requested,
                mode=knot_grid_mode or DEFAULT_LSQ_KNOT_GRID,
                break_tolerance=gap,
            ).tolist()
    except Exception as exc:
        logger.exception("Could not place knots")
        return no_update, no_update, dbc.Alert(
            str(exc), color="danger", className="py-2 small mb-0"
        )
    logger.info("Placed %s knots for method %s", len(placed), method)
    if not placed:
        return None, [], dbc.Alert(
            "No interior knots could be placed on the current segments.",
            color="warning",
            className="py-2 small mb-0",
        )
    note = None
    if method == "spline_lsq" and len(placed) < requested:
        note = dbc.Alert(
            f"Placed {len(placed)} of {requested} knots (limited by points per night).",
            color="info",
            className="py-2 small mb-0",
        )
    return None, placed, note


@app.callback(
    Output("detrend-store-result", "data", allow_duplicate=True),
    Output("detrend-store-knots", "data", allow_duplicate=True),
    Output("detrend-apply-feedback", "children", allow_duplicate=True),
    Input("detrend-apply", "n_clicks"),
    State("detrend-store-lc", "data"),
    State("detrend-method", "value"),
    State("detrend-domain", "value"),
    State("detrend-split-gaps", "value"),
    State("detrend-break-tol", "value"),
    State("detrend-t-min", "value"),
    State("detrend-t-max", "value"),
    State("detrend-median-window", "value"),
    State("detrend-n-points", "value"),
    State("detrend-n-points-biweight", "value"),
    State("detrend-polyorder", "value"),
    State("detrend-smooth-rel", "value"),
    State("detrend-smooth-s", "value"),
    State("detrend-store-knots", "data"),
    State("detrend-n-knots", "value"),
    State("detrend-lsq-knot-grid", "value"),
    State("detrend-pspline-lambda", "value"),
    State("detrend-pspline-nseg", "value"),
    prevent_initial_call=True,
)
def apply_trend(
    apply_clicks,
    lc_json,
    method,
    domain,
    split_gaps,
    break_tol,
    t_min,
    t_max,
    median_window,
    n_points,
    n_points_biweight,
    polyorder,
    smooth_rel,
    smooth_s,
    knots,
    n_knots,
    knot_grid_mode,
    penalty_lambda,
    n_segments,
):
    """Fit the selected trend.

    Args:
        apply_clicks: Apply-button clicks.
        lc_json: Stored ``CurveDash`` JSON.
        method: Method id.
        domain: Working domain.
        split_gaps: Gap-split switch.
        break_tol: Maximum gap in days.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).
        median_window: Median window (days).
        n_points: SG / Lightkurve window.
        n_points_biweight: Biweight window.
        polyorder: Polynomial order.
        smooth_rel: Relative smoothing.
        smooth_s: Explicit smoothing ``s``.
        knots: Current knot list.
        n_knots: Requested knot count.
        knot_grid_mode: LSQ grid mode if knots are still empty.
        penalty_lambda: P-spline lambda.
        n_segments: P-spline segments.

    Returns:
        tuple: Result store, knot store, feedback.
    """
    if not apply_clicks:
        raise PreventUpdate
    if not lc_json:
        return no_update, no_update, dbc.Alert(
            "Load a light curve first.",
            color="warning",
            className="py-2 small mb-0",
        )
    try:
        payload = _fit_from_widgets(
            lc_json,
            method=method,
            domain=domain,
            split_gaps=bool(split_gaps),
            break_tol=_optional_float(break_tol),
            t_min=_optional_float(t_min),
            t_max=_optional_float(t_max),
            median_window=_optional_float(median_window),
            n_points=int(n_points) if n_points else None,
            n_points_biweight=int(n_points_biweight) if n_points_biweight else None,
            polyorder=int(polyorder) if polyorder else None,
            smooth_rel=_optional_float(smooth_rel),
            smooth_s=_optional_float(smooth_s),
            knots=list(knots or []),
            n_knots=int(n_knots) if n_knots else None,
            knot_grid_mode=knot_grid_mode or DEFAULT_LSQ_KNOT_GRID,
            penalty_lambda=_optional_float(penalty_lambda),
            n_segments=int(n_segments) if n_segments else None,
        )
    except Exception as exc:
        logger.exception("Detrend fit failed")
        return no_update, no_update, dbc.Alert(
            str(exc), color="danger", className="py-2 small mb-0"
        )
    out_knots = payload.get("knots") or list(knots or [])
    return payload, out_knots, None


@app.callback(
    Output("detrend-store-result", "data", allow_duplicate=True),
    Output("detrend-store-knots", "data", allow_duplicate=True),
    Output("detrend-apply-feedback", "children", allow_duplicate=True),
    Input("detrend-graph-raw", "clickData"),
    Input("detrend-graph-raw", "relayoutData"),
    Input("detrend-store-knot-pick", "data"),
    State("detrend-store-lc", "data"),
    State("detrend-store-knots", "data"),
    State("detrend-method", "value"),
    State("detrend-domain", "value"),
    State("detrend-split-gaps", "value"),
    State("detrend-break-tol", "value"),
    State("detrend-t-min", "value"),
    State("detrend-t-max", "value"),
    State("detrend-median-window", "value"),
    State("detrend-n-points", "value"),
    State("detrend-n-points-biweight", "value"),
    State("detrend-polyorder", "value"),
    State("detrend-smooth-rel", "value"),
    State("detrend-smooth-s", "value"),
    State("detrend-n-knots", "value"),
    State("detrend-plot-tool", "value"),
    State("detrend-pspline-lambda", "value"),
    State("detrend-pspline-nseg", "value"),
    State("detrend-store-result", "data"),
    State("detrend-time-axis", "value"),
    prevent_initial_call=True,
)
def edit_knots_on_plot(
    click_data,
    relayout_data,
    knot_pick,
    lc_json,
    knots,
    method,
    domain,
    split_gaps,
    break_tol,
    t_min,
    t_max,
    median_window,
    n_points,
    n_points_biweight,
    polyorder,
    smooth_rel,
    smooth_s,
    n_knots,
    plot_tool,
    penalty_lambda,
    n_segments,
    result,
    time_axis_mode,
):
    """Add, remove, or drag LSQ knots on the observed plot.

    Args:
        click_data: Plotly ``clickData`` (add-knot on photometry).
        relayout_data: Plotly ``relayoutData`` (drag in add mode).
        knot_pick: Clientside pointer pick in delete mode (plot x in MJD).
        lc_json: Stored ``CurveDash`` JSON.
        knots: Current knot list.
        method: Method id.
        domain: Working domain.
        split_gaps: Gap-split switch.
        break_tol: Maximum gap in days.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).
        median_window: Median window.
        n_points: SG window.
        n_points_biweight: Biweight window.
        polyorder: Polynomial order.
        smooth_rel: Relative smoothing.
        smooth_s: Explicit ``s``.
        n_knots: Knot count widget.
        plot_tool: Active plot tool.
        penalty_lambda: P-spline lambda.
        n_segments: P-spline segments.
        result: Current fit payload, if any.
        time_axis_mode: ``mjd`` or ``date``.

    Returns:
        tuple: Updated result, knots, feedback.
    """
    if method != "spline_lsq" or not lc_json:
        raise PreventUpdate
    tool = plot_tool or PLOT_TOOL_OFF
    axis = normalize_time_axis_mode(time_axis_mode)
    triggered = ctx.triggered_id
    current = [float(k) for k in (knots or [])]
    new_knots = None
    if triggered == "detrend-store-knot-pick":
        if tool != PLOT_TOOL_DELETE or not knot_pick:
            raise PreventUpdate
        times, _y, _e, _lab, _is_mag, _ts, _ref, _src, _labels = _loaded_arrays(
            lc_json,
            domain,
            _optional_float(t_min),
            _optional_float(t_max),
        )
        t0 = float(np.min(times))
        t1 = float(np.max(times))
        click_jd = plot_x_to_jd(knot_pick["x"], axis, DEFAULT_EPOCH_JD)
        vis = None
        if knot_pick.get("x0") is not None and knot_pick.get("x1") is not None:
            vis = [knot_pick["x0"], knot_pick["x1"]]
        elif relayout_data:
            vis = extract_xaxis_range_mjd(relayout_data)
        new_knots = knot_click_edit(
            current,
            click_jd,
            t0,
            t1,
            mode="delete",
            hit_span=knot_hit_span_jd(
                vis,
                t0,
                t1,
                time_axis_mode=axis,
            ),
        )
        if new_knots == current:
            raise PreventUpdate
    elif triggered == "detrend-graph-raw" and ctx.triggered:
        prop = ctx.triggered[0].get("prop_id", "")
        if prop.endswith("clickData") and click_data:
            if tool != PLOT_TOOL_ADD:
                raise PreventUpdate
            point = click_data["points"][0]
            click_jd = plot_x_to_jd(point["x"], axis, DEFAULT_EPOCH_JD)
            times, _y, _e, _lab, _is_mag, _ts, _ref, _src, _labels = _loaded_arrays(
                lc_json,
                domain,
                _optional_float(t_min),
                _optional_float(t_max),
            )
            t0 = float(np.min(times))
            t1 = float(np.max(times))
            new_knots = knot_click_edit(
                current,
                click_jd,
                t0,
                t1,
                mode="add",
            )
            if new_knots == current:
                raise PreventUpdate
        elif prop.endswith("relayoutData"):
            if tool != PLOT_TOOL_ADD:
                raise PreventUpdate
            new_knots = merge_knot_drag(
                current,
                relayout_data,
                time_axis_mode=axis,
            )

    if new_knots is None:
        raise PreventUpdate
    if not result:
        return None, new_knots, None
    try:
        payload = _fit_from_widgets(
            lc_json,
            method=method,
            domain=domain,
            split_gaps=bool(split_gaps),
            break_tol=_optional_float(break_tol),
            t_min=_optional_float(t_min),
            t_max=_optional_float(t_max),
            median_window=_optional_float(median_window),
            n_points=int(n_points) if n_points else None,
            n_points_biweight=int(n_points_biweight) if n_points_biweight else None,
            polyorder=int(polyorder) if polyorder else None,
            smooth_rel=_optional_float(smooth_rel),
            smooth_s=_optional_float(smooth_s),
            knots=new_knots,
            n_knots=int(n_knots) if n_knots else None,
            knot_grid_mode=DEFAULT_LSQ_KNOT_GRID,
            penalty_lambda=_optional_float(penalty_lambda),
            n_segments=int(n_segments) if n_segments else None,
        )
    except Exception as exc:
        logger.exception("Knot edit refit failed")
        return no_update, no_update, dbc.Alert(
            str(exc), color="danger", className="py-2 small mb-0"
        )
    return payload, payload.get("knots") or new_knots, None


@app.callback(
    Output("detrend-store-lc", "data", allow_duplicate=True),
    Output("detrend-store-result", "data", allow_duplicate=True),
    Output("detrend-apply-feedback", "children", allow_duplicate=True),
    Output("detrend-domain", "value", allow_duplicate=True),
    Input("detrend-domain", "value"),
    Input("detrend-store-lc", "data"),
    prevent_initial_call=True,
)
def sync_working_domain(domain, lc_json):
    """Convert the stored ``CurveDash`` when the working-domain radio changes.

    Args:
        domain: Requested ``mag`` or ``flux``.
        lc_json: Stored ``CurveDash`` JSON.

    Returns:
        tuple: Updated store, cleared fit, optional alert, domain (reverted on
        failure).
    """
    if not lc_json or domain not in (DOMAIN_FLUX, DOMAIN_MAG):
        raise PreventUpdate
    if ctx.triggered_id != "detrend-domain":
        raise PreventUpdate
    lcd = CurveDash.from_serialized(lc_json)
    if lcd.lightcurve is None or lcd.lightcurve.empty:
        raise PreventUpdate
    if lcd.active_domain == domain:
        raise PreventUpdate
    try:
        apply_phot_domain_view(lcd, show_magnitude=(domain == DOMAIN_MAG))
    except Exception as exc:
        logger.warning("Detrend domain conversion failed: %s", exc)
        return (
            no_update,
            no_update,
            dbc.Alert(str(exc), color="danger", className="py-2 small mb-0"),
            lcd.active_domain,
        )
    logger.info("Converted working light curve to %s", domain)
    return lcd.serialize(), None, None, no_update


@app.callback(
    Output("detrend-store-lc", "data", allow_duplicate=True),
    Output("detrend-plot-alert", "children", allow_duplicate=True),
    Input("detrend-graph-raw", "selectedData"),
    Input("detrend-graph-raw", "clickData"),
    State("detrend-plot-tool", "value"),
    State("detrend-store-lc", "data"),
    prevent_initial_call=True,
)
def merge_observed_plot_selection(selected_data, click_data, plot_tool, lc_json):
    """Mark clicked or lasso-selected points on the working ``CurveDash``.

    Selection is only active on the observed plot. Add knot / Delete knot
    consume clicks instead.

    Args:
        selected_data: Plotly lasso/box payload.
        click_data: Plotly click payload.
        plot_tool: Active knot tool.
        lc_json: Stored ``CurveDash`` JSON.

    Returns:
        tuple: Updated store and optional alert.
    """
    if plot_tool in (PLOT_TOOL_ADD, PLOT_TOOL_DELETE) or not lc_json or not ctx.triggered:
        raise PreventUpdate
    trigger_prop = ctx.triggered[0]["prop_id"].rsplit(".", 1)[-1]
    event_data = selected_data if trigger_prop == "selectedData" else click_data
    if not event_data or not event_data.get("points"):
        raise PreventUpdate
    try:
        lcd = _lcd_from_store(lc_json)
        apply_plot_point_selection(lcd, event_data)
        n_marked = len(_selected_perm_indices(lcd))
        logger.info("Marked %s point(s) on the working light curve", n_marked)
        return lcd.serialize(), None
    except Exception as exc:
        logger.warning("Detrend point selection failed: %s", exc)
        return no_update, dbc.Alert(str(exc), color="warning", className="py-2 small mb-0")


@app.callback(
    Output("detrend-store-lc", "data", allow_duplicate=True),
    Output("detrend-plot-alert", "children", allow_duplicate=True),
    Output("detrend-graph-raw", "selectedData", allow_duplicate=True),
    Input("detrend-unselect", "n_clicks"),
    State("detrend-store-lc", "data"),
    prevent_initial_call=True,
)
def unselect_observed_points(n_clicks, lc_json):
    """Clear all ``selected`` markers on the working light curve.

    Same helpers as Discovery: ``clear_plot_point_selection`` then redraw.
    ``selectedData`` is cleared so Plotly drops the native lasso highlight.

    Args:
        n_clicks: Unselect-button clicks.
        lc_json: Stored ``CurveDash`` JSON.

    Returns:
        tuple: Updated store, optional alert, cleared graph selection.
    """
    if not n_clicks or not lc_json:
        raise PreventUpdate
    try:
        lcd = _lcd_from_store(lc_json)
        clear_plot_point_selection(lcd)
        logger.info("Cleared selected marks on the working light curve")
        return lcd.serialize(), None, None
    except Exception as exc:
        logger.warning("Detrend unselect failed: %s", exc)
        return no_update, dbc.Alert(
            str(exc), color="warning", className="py-2 small mb-0"
        ), no_update


@app.callback(
    Output("detrend-store-lc", "data", allow_duplicate=True),
    Output("detrend-store-result", "data", allow_duplicate=True),
    Output("detrend-plot-alert", "children", allow_duplicate=True),
    Output("detrend-graph-raw", "selectedData", allow_duplicate=True),
    Input("detrend-delete-selected", "n_clicks"),
    State("detrend-store-lc", "data"),
    prevent_initial_call=True,
)
def delete_observed_selected_points(n_clicks, lc_json):
    """Permanently remove rows marked ``selected=1``.

    Same helpers as Discovery: ``delete_selected_rows`` on the working
    ``CurveDash``.

    Args:
        n_clicks: Delete-button clicks.
        lc_json: Stored ``CurveDash`` JSON.

    Returns:
        tuple: Updated store, cleared fit, optional alert, cleared graph
        selection.
    """
    if not n_clicks or not lc_json:
        raise PreventUpdate
    try:
        lcd = _lcd_from_store(lc_json)
        if lcd.lightcurve is None or "selected" not in lcd.lightcurve.columns:
            raise PipeException("Select points to delete first.")
        if not (lcd.lightcurve["selected"] == 1).any():
            return no_update, no_update, dbc.Alert(
                "Select points to delete first.",
                color="warning",
                className="py-2 small mb-0",
            ), no_update
        delete_selected_rows(lcd)
        if lcd.lightcurve is None or lcd.lightcurve.empty:
            raise PipeException("Cannot delete all points from the light curve.")
        logger.info("Deleted selected points; %s remain", len(lcd.lightcurve))
        return lcd.serialize(), None, None, None
    except PipeException as exc:
        logger.warning("Detrend delete failed: %s", exc)
        return no_update, no_update, dbc.Alert(
            str(exc), color="warning", className="py-2 small mb-0"
        ), no_update
    except Exception as exc:
        logger.exception("Detrend delete failed")
        return no_update, no_update, dbc.Alert(
            str(exc), color="danger", className="py-2 small mb-0"
        ), no_update


@app.callback(
    Output("detrend-graph-raw", "figure"),
    Output("detrend-graph-detrended", "figure"),
    Input("detrend-store-lc", "data"),
    Input("detrend-store-result", "data"),
    Input("detrend-store-knots", "data"),
    Input("detrend-domain", "value"),
    Input("detrend-show-errors", "value"),
    Input("detrend-method", "value"),
    Input("detrend-t-min", "value"),
    Input("detrend-t-max", "value"),
    Input("detrend-time-axis", "value"),
    State("detrend-upload-lc", "filename"),
)
def update_figures(
    lc_json,
    result,
    knots,
    domain,
    show_errors,
    method,
    t_min,
    t_max,
    time_axis_mode,
    filename,
):
    """Redraw both plots from the working ``CurveDash`` and optional fit overlay.

    The figure is a disposable view. Zoom is kept only by Plotly
    ``uirevision``. Knot-tool changes do not trigger this callback.

    Args:
        lc_json: ``CurveDash.serialize()`` payload.
        result: Fit overlay payload, or ``None``.
        knots: Knot list.
        domain: Working domain.
        show_errors: Error-bar switch.
        method: Method id.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).
        time_axis_mode: ``mjd`` or ``date``.
        filename: Upload name for ``uirevision``.

    Returns:
        tuple: Raw figure, residual figure.
    """
    invert_y = domain == DOMAIN_MAG
    axis = normalize_time_axis_mode(time_axis_mode)
    fig_kwargs = dict(display_epoch=DEFAULT_EPOCH_JD, time_axis_mode=axis)
    if not lc_json:
        uirev = _plot_uirevision(None, filename, domain, axis)
        return (
            figure_raw_with_trend(
                None, None, None, None,
                y_label="Photometry", invert_y=invert_y, show_errors=False,
                knots=None, knots_editable=False,
                uirevision=uirev,
                **fig_kwargs,
            ),
            figure_detrended(
                None, None, None,
                y_label="Detrended", invert_y=invert_y, show_errors=False,
                uirevision=uirev,
                **fig_kwargs,
            ),
        )

    lcd = _lcd_from_store(lc_json, domain)
    times, values, err, y_label, invert_y, timescale, refposition, source, labels = (
        _loaded_arrays(
            lc_json, domain, _optional_float(t_min), _optional_float(t_max)
        )
    )
    selected_perm = _selected_perm_indices(lcd)
    uirev = _plot_uirevision(lcd, filename, domain, axis)
    logger.info("Plotting %s (%s points)", filename, int(np.asarray(times).size))
    fig_kwargs.update(timescale=timescale, refposition=refposition)
    trend, detrended, det_err = _fit_overlay(result, times, domain, method)
    plot_knots = (
        [float(k) for k in (knots or [])]
        if method in ("spline_lsq", "pspline")
        else None
    )
    n = int(np.asarray(times).size)
    if int(np.asarray(labels).size) != n:
        raise ValueError(
            f"label length {np.asarray(labels).size} does not match "
            f"photometry length {n}"
        )
    if int(np.asarray(source).size) != n:
        raise ValueError(
            f"source_index length {np.asarray(source).size} does not match "
            f"photometry length {n}"
        )

    det_ylabel = "Δmag (obs − trend)" if invert_y else "flux / trend"
    return (
        figure_raw_with_trend(
            times,
            values,
            err,
            trend,
            y_label=y_label,
            invert_y=invert_y,
            show_errors=bool(show_errors),
            knots=plot_knots,
            knots_editable=False,
            uirevision=uirev,
            labels=labels,
            source_index=source,
            selected_perm_indices=selected_perm,
            **fig_kwargs,
        ),
        figure_detrended(
            times if detrended is not None else None,
            detrended,
            det_err,
            y_label=det_ylabel,
            invert_y=invert_y,
            show_errors=bool(show_errors),
            uirevision=uirev,
            labels=labels if detrended is not None else None,
            source_index=source if detrended is not None else None,
            **fig_kwargs,
        ),
    )


@app.callback(
    Output("detrend-graph-raw", "config"),
    Input("detrend-plot-tool", "value"),
    Input("detrend-method", "value"),
)
def update_raw_graph_config(plot_tool, method):
    """Update plot config when the knot tool changes, without rebuilding traces.

    Args:
        plot_tool: ``off``, ``add``, or ``delete``.
        method: Active detrend method id.

    Returns:
        dict: Plotly config dictionary.
    """
    return graph_config(plot_tool=plot_tool or PLOT_TOOL_OFF, method=method)


@app.callback(
    Output("detrend-download-lc-btn", "disabled"),
    Input("detrend-store-lc", "data"),
)
def gate_lightcurve_download(lc_json):
    """Enable the working-curve download after a file is loaded.

    Args:
        lc_json: Stored ``CurveDash`` JSON.

    Returns:
        bool: Disabled flag.
    """
    return not bool(lc_json)


@app.callback(
    Output("detrend-download-btn", "disabled"),
    Input("detrend-store-result", "data"),
)
def gate_download(result):
    """Enable detrended download only after a successful fit.

    Args:
        result: Fit payload.

    Returns:
        bool: Disabled flag.
    """
    return not bool(result)


@app.callback(
    Output("detrend-download-lc", "data"),
    Output("detrend-export-feedback", "children"),
    Input("detrend-download-lc-btn", "n_clicks"),
    State("detrend-store-lc", "data"),
    State("detrend-export-format", "value"),
    State("detrend-export-stem", "value"),
    State("detrend-input-period", "value"),
    State("detrend-input-epoch", "value"),
    prevent_initial_call=True,
)
def download_working_lightcurve(n_clicks, lc_json, table_format, stem, period, epoch):
    """Export the whole working ``CurveDash`` (deletes kept, crop ignored).

    Args:
        n_clicks: Export button clicks.
        lc_json: Stored ``CurveDash`` JSON.
        table_format: Export format id.
        stem: Download basename.
        period: Sidebar period in days, or empty.
        epoch: Sidebar epoch as MJD offset, or empty.

    Returns:
        tuple: Export payload and optional alert.
    """
    if not n_clicks or not lc_json:
        raise PreventUpdate
    fmt = table_format or DEFAULT_EXPORT_FORMAT
    try:
        lcd = _lcd_from_store(lc_json)
        _apply_export_ephemeris(
            lcd,
            period,
            epoch,
            display_epoch=DEFAULT_EPOCH_JD,
        )
        file_bytes = export_curvedash(lcd, fmt)
        outfile = _export_download_name(
            _lc_export_stem(stem), fmt, fallback="lightcurve_lc"
        )
        return dcc.send_bytes(file_bytes, outfile), None
    except PipeException as exc:
        logger.warning("Working light-curve export failed: %s", exc)
        return no_update, dbc.Alert(str(exc), color="warning", className="py-2 small mb-0")
    except Exception as exc:
        logger.exception("Working light-curve export failed")
        return no_update, dbc.Alert(
            f"Could not export light curve: {exc}",
            color="danger",
            className="py-2 small mb-0",
        )


@app.callback(
    Output("detrend-download", "data"),
    Output("detrend-detrend-export-feedback", "children"),
    Input("detrend-download-btn", "n_clicks"),
    State("detrend-store-result", "data"),
    State("detrend-store-lc", "data"),
    State("detrend-export-format", "value"),
    State("detrend-export-stem", "value"),
    State("detrend-input-period", "value"),
    State("detrend-input-epoch", "value"),
    prevent_initial_call=True,
)
def download_detrended(
    n_clicks, result, lc_json, table_format, stem, period, epoch
):
    """Export the detrended series as a light curve.

    Rehydrates the working ``CurveDash``, applies sidebar P / Epoch (empty
    fields keep ingest values), then replaces only the time-photometry series
    with the fitted residual.

    Args:
        n_clicks: Export button clicks.
        result: Fit payload; ``jd`` is absolute Julian Date (not display MJD).
        lc_json: Working ``CurveDash`` JSON.
        table_format: Export format id.
        stem: Download basename.
        period: Sidebar period in days, or empty.
        epoch: Sidebar epoch as MJD offset, or empty.

    Returns:
        tuple: Export payload and optional alert.
    """
    if not n_clicks or not result or not lc_json:
        raise PreventUpdate
    fmt = table_format or DEFAULT_EXPORT_FORMAT
    try:
        lcd = _lcd_from_store(lc_json)
        _apply_export_ephemeris(
            lcd,
            period,
            epoch,
            display_epoch=DEFAULT_EPOCH_JD,
        )
        domain = result.get("domain") or lcd.active_domain
        lcd.replace_series(
            np.asarray(result["jd"], dtype=float),
            np.asarray(result["detrended"], dtype=float),
            np.asarray(result["det_err"], dtype=float),
            domain=domain,
        )
        file_bytes = export_curvedash(lcd, fmt)
        outfile = _export_download_name(
            _detrended_export_stem(stem), fmt, fallback="lightcurve_detrended"
        )
        return dcc.send_bytes(file_bytes, outfile), None
    except PipeException as exc:
        logger.warning("Detrend export failed: %s", exc)
        return no_update, dbc.Alert(str(exc), color="warning", className="py-2 small mb-0")
    except Exception as exc:
        logger.exception("Detrend export failed")
        return no_update, dbc.Alert(
            f"Could not export light curve: {exc}",
            color="danger",
            className="py-2 small mb-0",
        )


app.clientside_callback(
    ClientsideFunction(namespace="detrendKnot", function_name="applyDeleteMode"),
    Output("detrend-graph-raw-shell", "className"),
    Input("detrend-plot-tool", "value"),
)

app.clientside_callback(
    ClientsideFunction(namespace="detrendKnot", function_name="bindGraph"),
    Output("detrend-store-clientside", "data"),
    Input("detrend-graph-raw", "figure"),
    State("detrend-plot-tool", "value"),
    prevent_initial_call=True,
)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8052)
