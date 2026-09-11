"""Lightcurve processor — ingest, clean, smooth, and export a working curve.

Detrend arrives later. Maths stay in ``skvo_veb/utils/lc_processor/``.
The working ``CurveDash`` and smooth overlay live in the session cache.
"""

from __future__ import annotations

import base64
import logging
import uuid
from io import BytesIO

import numpy as np
import dash_bootstrap_components as dbc
from dash import (
    ClientsideFunction,
    Input,
    Output,
    State,
    callback,
    clientside_callback,
    ctx,
    dcc,
    html,
    no_update,
    register_page,
)
from dash.exceptions import PreventUpdate

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.gp.export import (
    apply_prep_fold_ephemeris,
    gp_lc_export_download_name,
    suggested_lc_export_stem,
)
from skvo_veb.utils.lc_bridge import (
    apply_phot_domain_view,
    export_curvedash,
    format_user_upload_error,
    ingest_lightcurve_file,
)
from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD,
    DEFAULT_EXPORT_FORMAT,
    DOMAIN_FLUX,
    DOMAIN_MAG,
    EXPORT_FORMAT_OPTIONS,
    TIME_AXIS_DATE,
    TIME_AXIS_MJD,
    display_epoch_offset,
    normalize_time_axis_mode,
)
from skvo_veb.utils.lc_figure import time_axis_xaxis_title
from skvo_veb.utils.lc_interaction import (
    apply_plot_point_selection,
    clear_plot_point_selection,
    delete_selected_rows,
    plot_x_to_jd,
)
from skvo_veb.utils.lc_processor.apply import (
    SMOOTH_BLOB,
    cropped_series,
    fit_smooth_overlay,
    overlay_trend,
    place_knot_grid,
)
from skvo_veb.utils.lc_processor.figures import (
    PLOT_TOOL_ADD,
    PLOT_TOOL_DELETE,
    PLOT_TOOL_OFF,
    empty_figure,
    extract_xaxis_range_mjd,
    figure_raw_with_trend,
    graph_config,
    knot_click_edit,
    knot_layout_shapes,
    knot_hit_span_jd,
    merge_knot_drag,
)
from skvo_veb.utils.lc_processor.smooth import METHOD_LABELS
from skvo_veb.utils.lc_processor.view import (
    crop_curvedash_copy,
    display_mjd_to_absolute_jd,
    plot_uirevision,
    raw_labels,
    selected_perm_indices,
    timescale_refposition,
)
from skvo_veb.utils.lc_session_cache import (
    clear_page_blob,
    generate_user_tab_id,
    has_cached_lc,
    read_page_blob,
    read_serialized_lc,
    write_page_blob,
    write_serialized_lc,
)
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.page_session import SESSION_STORE

logger = logging.getLogger(__name__)

register_page(
    __name__,
    name="Lightcurve processor",
    order=8,
    path="/lc_processor",
    title="IGEBC: Lightcurve processor",
    in_navbar=True,
)

PAGE_NAMESPACE = "lc_processor"
ACCORDION_LC_ITEM_ID = "lc-processor-accordion-lc"
ACCORDION_SMOOTH_ITEM_ID = "lc-processor-accordion-smooth"
DISPLAY_EPOCH_JD = DEFAULT_EPOCH_JD
DEFAULT_BREAK_TOLERANCE = 5.0
DEFAULT_MEDIAN_WINDOW_DAYS = 2.0
DEFAULT_N_POINTS = 301
DEFAULT_POLYORDER = 5
DEFAULT_SMOOTH_REL = 0.05
DEFAULT_N_KNOTS = 8
DEFAULT_LSQ_KNOT_GRID = "occupancy"
DEFAULT_PSPLINE_LAMBDA = 1.0e4
DEFAULT_PSPLINE_SEGMENTS = 40

PAGE_ABOUT_MARKDOWN = """
Load a light curve, inspect it, delete bad points, and export the working
series. Time crop affects the plot and Smooth only. Export lightcurve writes
the whole working series (after deletes) as ``{name}_lc``.

Apply smooth draws an overlay on plot 1. Residual detrend is a later drawer.
"""

def _bump_lc_revision() -> str:
    """Returns a new plot-revision token.

    Returns:
        str: UUID string.
    """
    return str(uuid.uuid4())


def _click_help(help_id: str, title: str, body: str, *, placement: str = "right"):
    """Builds a ``?`` control and popover.

    Args:
        help_id (str): Unique slug.
        title (str): Popover header; must match the control label.
        body (str): Popover body.
        placement (str): Bootstrap popover placement.

    Returns:
        tuple: ``(button, popover)``.
    """
    btn_id = f"lc-processor-help-{help_id}-btn"
    pop_id = f"lc-processor-help-{help_id}-popover"
    button = html.Strong(
        "?",
        id=btn_id,
        role="button",
        tabIndex=0,
        className="lcp-help-btn",
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
        className="lcp-help-popover",
    )
    return button, popover


def _heading_with_help(
    label: str,
    help_id: str,
    title: str,
    body: str,
    *,
    label_class: str = "lcp-section-label",
) -> html.Div:
    """Label plus ``?`` in one heading row.

    Args:
        label (str): Visible section label.
        help_id (str): Help slug.
        title (str): Popover title.
        body (str): Popover body.
        label_class (str): CSS class for the label.

    Returns:
        dash.html.Div: Heading row. The popover is a sibling in the parent block.
    """
    btn, pop = _click_help(help_id, title, body)
    return html.Div(
        [
            html.Div(
                [
                    html.Label(label, className=f"{label_class} mb-0"),
                    html.Div(btn, className="lcp-field-help"),
                ],
                className="lcp-sidebar-heading-row",
            ),
            pop,
        ]
    )


def _control_with_help(control, help_id: str, title: str, body: str) -> html.Div:
    """Puts a control and a ``?`` on one row.

    Args:
        control: Dash component (typically a button or switch).
        help_id (str): Unique slug.
        title (str): Popover title.
        body (str): Popover body.

    Returns:
        dash.html.Div: Heading row.
    """
    btn, pop = _click_help(help_id, title, body)
    return html.Div(
        [control, html.Div(btn, className="lcp-field-help"), pop],
        className="lcp-sidebar-heading-row",
    )


def _param_block(block_id: str, children: list, *, visible: bool) -> html.Div:
    """Wraps a method-specific parameter group.

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
        className="lcp-param-block lcp-sidebar-block",
        style={} if visible else {"display": "none"},
    )


def _upload_placeholder() -> html.Span:
    """Idle caption before a file is chosen.

    Returns:
        dash.html.Span: Muted placeholder.
    """
    return html.Span("Drag or select", className="lcp-upload-name-text text-muted")


def _upload_status(filename: str, *, tone: str) -> html.Div:
    """Filename chip after an upload attempt.

    Args:
        filename (str): Original file name.
        tone (str): ``ok`` or ``error``.

    Returns:
        dash.html.Div: Status row.
    """
    colour = "text-success" if tone == "ok" else "text-danger"
    return html.Div(
        [html.Span(filename, className=f"lcp-upload-name-text {colour}")],
        className="lcp-upload-status",
    )


def _blank_pair(*, time_axis_mode: str, domain: str, filename: str | None = None):
    """Empty working and residual axes (GP font and margins).

    Args:
        time_axis_mode (str): ``mjd`` or ``date``.
        domain (str): ``mag`` or ``flux``.
        filename (str | None): Upload name for ``uirevision``.

    Returns:
        tuple: Working figure, residual figure.
    """
    axis = normalize_time_axis_mode(time_axis_mode)
    invert_y = domain == DOMAIN_MAG
    uirev = plot_uirevision(None, filename, domain, axis)
    x_title = time_axis_xaxis_title(axis)
    working = empty_figure(
        xaxis_title=x_title,
        yaxis_title="Photometry",
        invert_y=invert_y,
        uirevision=uirev,
        time_axis_mode=axis,
    )
    residual = empty_figure(
        xaxis_title=x_title,
        yaxis_title="Residual",
        invert_y=invert_y,
        uirevision=uirev,
        time_axis_mode=axis,
    )
    return working, residual


def _lightcurve_drawer() -> list:
    """Builds the Light curve accordion body.

    Returns:
        list: Domain, crop, ephemeris, and export widgets.
    """
    export_help = _heading_with_help(
        "Export",
        "export-lc",
        "Export",
        "Time crop applies to the plot only. This export writes the whole "
        "working light curve after deleted points. The stem field already "
        "ends in _lc.",
    )
    ephemeris_help = _heading_with_help(
        "Ephemeris",
        "ephemeris",
        "Ephemeris",
        "Written into the exported file. Empty fields keep the values from "
        "the upload.",
    )
    return [
        html.Div(
            [
                html.Label("Working domain", className="lcp-section-label"),
                dbc.RadioItems(
                    id="lc-processor-domain",
                    options=[
                        {"label": "Flux", "value": DOMAIN_FLUX},
                        {"label": "Magnitude", "value": DOMAIN_MAG},
                    ],
                    value=DOMAIN_FLUX,
                    inline=True,
                ),
                html.Label("Time axis", className="lcp-section-label"),
                dbc.RadioItems(
                    id="lc-processor-time-axis",
                    options=[
                        {"label": "MJD", "value": TIME_AXIS_MJD},
                        {"label": "Date", "value": TIME_AXIS_DATE},
                    ],
                    value=TIME_AXIS_MJD,
                    inline=True,
                ),
                dbc.Switch(
                    id="lc-processor-show-errors",
                    label="Show error bars",
                    value=False,
                ),
            ],
            className="lcp-sidebar-block",
        ),
        html.Div(
            [
                _heading_with_help(
                    "Time crop (MJD)",
                    "time-crop",
                    "Time crop (MJD)",
                    "Applies to the working plot and later Smooth fits. "
                    "Export lightcurve still writes the full working series.",
                ),
                dbc.Input(
                    id="lc-processor-t-min",
                    type="number",
                    step="any",
                    placeholder="MJD min (full)",
                    size="sm",
                ),
                dbc.Input(
                    id="lc-processor-t-max",
                    type="number",
                    step="any",
                    placeholder="MJD max (full)",
                    size="sm",
                ),
            ],
            className="lcp-sidebar-block",
        ),
        html.Div(
            [
                ephemeris_help,
                dbc.InputGroup(
                    [
                        dbc.InputGroupText("P"),
                        dbc.Input(
                            id="lc-processor-input-period",
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
                            id="lc-processor-input-epoch",
                            type="number",
                            placeholder="MJD offset",
                        ),
                    ],
                    size="sm",
                ),
            ],
            className="lcp-sidebar-block",
        ),
        html.Div(
            [
                export_help,
                dbc.Select(
                    options=EXPORT_FORMAT_OPTIONS,  # type: ignore[arg-type]
                    value=DEFAULT_EXPORT_FORMAT,
                    id="lc-processor-export-format",
                    size="sm",
                ),
                dbc.Input(
                    id="lc-processor-export-stem",
                    placeholder="lightcurve_lc",
                    type="text",
                    value="lightcurve_lc",
                    size="sm",
                ),
                dbc.Button(
                    "Export lightcurve",
                    id="lc-processor-download-lc-btn",
                    color="primary",
                    size="sm",
                    className="w-100",
                    disabled=True,
                ),
                html.Div(id="lc-processor-export-feedback", className="lcp-export-feedback"),
            ],
            className="lcp-sidebar-block lcp-sidebar-btn-stack",
        ),
    ]


def _smooth_drawer() -> list:
    """Builds the Smooth accordion body.

    Returns:
        list: Method, parameters, knot tools, gap split, and Apply.
    """
    method_options = [
        {"label": label, "value": key} for key, label in METHOD_LABELS.items()
    ]
    return [
        html.Div(
            [
                html.Label("Method", className="lcp-section-label"),
                dbc.Select(
                    id="lc-processor-method",
                    options=method_options,
                    value="spline_lsq",
                    size="sm",
                ),
            ],
            className="lcp-sidebar-block",
        ),
        _param_block(
            "lc-processor-params-median",
            [
                html.Label("Median window (days)", className="lcp-section-label"),
                dbc.Input(
                    id="lc-processor-median-window",
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
            "lc-processor-params-points",
            [
                html.Label("Window (points)", className="lcp-section-label"),
                dbc.Input(
                    id="lc-processor-n-points",
                    type="number",
                    step=1,
                    min=3,
                    value=DEFAULT_N_POINTS,
                    size="sm",
                ),
                html.Label("Polynomial order", className="lcp-section-label"),
                dbc.Input(
                    id="lc-processor-polyorder",
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
            "lc-processor-params-biweight",
            [
                html.Label("Window (points)", className="lcp-section-label"),
                dbc.Input(
                    id="lc-processor-n-points-biweight",
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
            "lc-processor-params-smooth",
            [
                html.Label("Smoothing (relative)", className="lcp-section-label"),
                dbc.Input(
                    id="lc-processor-smooth-rel",
                    type="number",
                    step="any",
                    min=0,
                    value=DEFAULT_SMOOTH_REL,
                    size="sm",
                ),
                html.Label("Explicit s (optional)", className="lcp-section-label"),
                dbc.Input(
                    id="lc-processor-smooth-s",
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
            "lc-processor-params-lsq",
            [
                _heading_with_help(
                    "Interior knots",
                    "lsq-knots",
                    "Interior knots",
                    "Place knots builds a grid without entering edit mode. "
                    "Choose Add knot to click or drag a green line, or "
                    "Delete knot to click near one.",
                ),
                dbc.Input(
                    id="lc-processor-n-knots",
                    type="number",
                    step=1,
                    min=1,
                    value=DEFAULT_N_KNOTS,
                    size="sm",
                ),
                html.Label("Knot grid", className="lcp-section-label"),
                dbc.RadioItems(
                    id="lc-processor-lsq-knot-grid",
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
            "lc-processor-params-pspline",
            [
                _heading_with_help(
                    "Penalty lambda",
                    "pspline",
                    "Penalty lambda",
                    "P-spline knots are a uniform grid from the segment count.",
                ),
                dbc.Input(
                    id="lc-processor-pspline-lambda",
                    type="number",
                    step="any",
                    min=0,
                    value=DEFAULT_PSPLINE_LAMBDA,
                    size="sm",
                ),
                html.Label("Segments", className="lcp-section-label"),
                dbc.Input(
                    id="lc-processor-pspline-nseg",
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
            "lc-processor-params-place-knots",
            [
                _control_with_help(
                    dbc.Button(
                        "Place knots",
                        id="lc-processor-place-knots",
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
                html.Label("Gaps", className="lcp-section-label"),
                _control_with_help(
                    dbc.Switch(
                        id="lc-processor-split-gaps",
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
                ),
                dbc.Input(
                    id="lc-processor-break-tol",
                    type="number",
                    step="any",
                    min=0,
                    value=DEFAULT_BREAK_TOLERANCE,
                    size="sm",
                ),
            ],
            className="lcp-sidebar-block",
        ),
        html.Div(
            [
                dbc.Button(
                    "Apply smooth",
                    id="lc-processor-apply-smooth",
                    color="primary",
                    size="sm",
                    className="w-100",
                ),
                html.Div(
                    id="lc-processor-apply-feedback",
                    className="lcp-apply-feedback",
                ),
            ],
            className="lcp-sidebar-block lcp-sidebar-btn-stack",
        ),
        _param_block(
            "lc-processor-params-knot-tool",
            [
                _heading_with_help(
                    "Knot tool",
                    "knot-tool",
                    "Knot tool",
                    "Use the figure toolbar to pan, zoom, or lasso. Add knot "
                    "and Delete knot apply to the least-squares spline.",
                ),
                dbc.RadioItems(
                    id="lc-processor-plot-tool",
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


def _sidebar() -> html.Div:
    """Builds the tools accordion. Plots stay outside this column.

    Returns:
        dash.html.Div: Light curve and Smooth drawers.
    """
    return html.Div(
        dbc.Accordion(
            [
                dbc.AccordionItem(
                    html.Div(_lightcurve_drawer(), className="lcp-drawer-body"),
                    title="Light curve",
                    item_id=ACCORDION_LC_ITEM_ID,
                ),
                dbc.AccordionItem(
                    html.Div(_smooth_drawer(), className="lcp-drawer-body"),
                    title="Smooth",
                    item_id=ACCORDION_SMOOTH_ITEM_ID,
                ),
            ],
            id="lc-processor-accordion",
            always_open=True,
            active_item=[ACCORDION_LC_ITEM_ID],
            className="lcp-workflow-accordion",
        ),
        className="lcp-sidebar",
    )


def _plot_toolbar() -> html.Div:
    """Cleaning strip above plot 1.

    Returns:
        dash.html.Div: Delete / Unselect plus help.
    """
    help_btn, help_pop = _click_help(
        "plot-tools",
        "Delete selected",
        "Click or lasso on the working plot, then Delete selected. "
        "Unselect clears the orange marks.",
        placement="bottom",
    )
    return html.Div(
        [
            html.Div(
                [
                    dbc.Button(
                        "Delete selected",
                        id="lc-processor-delete-selected",
                        color="secondary",
                        outline=True,
                        size="sm",
                        className="lcp-btn-caution-outline",
                    ),
                    dbc.Button(
                        "Unselect",
                        id="lc-processor-unselect",
                        color="secondary",
                        outline=True,
                        size="sm",
                    ),
                ],
                className="lcp-plot-toolbar-cluster",
            ),
            html.Div(help_btn, className="lcp-field-help"),
            help_pop,
            html.Div(id="lc-processor-plot-alert", className="lcp-plot-alert"),
        ],
        className="lcp-plot-toolbar",
    )


def layout():
    """Builds the Lightcurve processor page.

    Returns:
        dash_bootstrap_components.Container: Page layout.
    """
    _initial_working, _initial_residual = _blank_pair(
        time_axis_mode=TIME_AXIS_MJD,
        domain=DOMAIN_FLUX,
    )
    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        html.H1("Lightcurve processor", className="lcp-page-title"),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.Button(
                            [
                                html.I(className="bi bi-question-circle me-2"),
                                "About",
                            ],
                            id="lc-processor-open-help",
                            color="secondary",
                            outline=True,
                            className="lcp-page-about-btn",
                        ),
                        width="auto",
                        className="ms-auto d-flex align-items-center",
                    ),
                ],
                className="lcp-page-header align-items-center",
            ),
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("About")),
                    dbc.ModalBody(dcc.Markdown(PAGE_ABOUT_MARKDOWN)),
                    dbc.ModalFooter(
                        dbc.Button(
                            "Close",
                            id="lc-processor-close-help",
                            color="secondary",
                            size="sm",
                            className="ms-auto",
                        )
                    ),
                ],
                id="lc-processor-help-modal",
                size="lg",
                is_open=False,
            ),
            dcc.Store(id="store-lc-processor-user-tab-id", **SESSION_STORE),
            dcc.Store(id="store-lc-processor-lc-revision"),
            dcc.Store(id="store-lc-processor-knots", data=[]),
            dcc.Store(id="store-lc-processor-knot-shapes"),
            dcc.Store(id="store-lc-processor-knot-pick"),
            dcc.Store(id="store-lc-processor-clientside"),
            dcc.Download(id="lc-processor-download-lc"),
            html.Div(
                [
                    html.Div(
                        dcc.Upload(
                            id="lc-processor-upload-lc",
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
                                        id="lc-processor-upload-text",
                                        className="lcp-upload-name",
                                    ),
                                ],
                                className="lcp-upload-target-inner",
                            ),
                            className="lcp-upload-target",
                            className_active="lcp-upload-target lcp-upload-target-active",
                            className_reject="lcp-upload-target lcp-upload-target-reject",
                        ),
                        className="lcp-data-slot",
                    ),
                    html.Div(id="lc-processor-upload-detail", className="lcp-upload-detail"),
                ],
                className="lcp-data-hub",
            ),
            dbc.Row(
                [
                    dbc.Col(_sidebar(), width=3, className="lcp-sidebar-col"),
                    dbc.Col(
                        html.Div(
                            [
                                _plot_toolbar(),
                                html.Div(
                                    dcc.Graph(
                                        id="lc-processor-graph-working",
                                        figure=_initial_working,
                                        className="lcp-graph",
                                        config=graph_config(),
                                    ),
                                    id="lc-processor-graph-working-shell",
                                    className="lcp-graph-shell",
                                ),
                                dcc.Graph(
                                    id="lc-processor-graph-residual",
                                    figure=_initial_residual,
                                    className="lcp-graph",
                                    config=graph_config(),
                                ),
                            ],
                            className="lcp-plot-stack",
                        ),
                        width=9,
                    ),
                ]
            ),
        ],
        fluid=True,
        className="lcp-page",
    )


@callback(
    Output("lc-processor-help-modal", "is_open"),
    Input("lc-processor-open-help", "n_clicks"),
    Input("lc-processor-close-help", "n_clicks"),
    State("lc-processor-help-modal", "is_open"),
    prevent_initial_call=True,
)
def toggle_about(open_clicks, close_clicks, is_open):
    """Opens or closes the page About modal.

    Args:
        open_clicks: About button clicks.
        close_clicks: Close button clicks.
        is_open (bool): Current modal state.

    Returns:
        bool: Toggled open state.
    """
    if not open_clicks and not close_clicks:
        raise PreventUpdate
    return not is_open


@callback(
    Output("store-lc-processor-user-tab-id", "data"),
    Output("store-lc-processor-lc-revision", "data"),
    Output("lc-processor-upload-text", "children"),
    Output("lc-processor-upload-detail", "children"),
    Output("lc-processor-export-stem", "value"),
    Output("lc-processor-domain", "value"),
    Output("lc-processor-input-period", "value"),
    Output("lc-processor-input-epoch", "value"),
    Output("lc-processor-t-min", "value"),
    Output("lc-processor-t-max", "value"),
    Output("store-lc-processor-knots", "data"),
    Output("lc-processor-plot-tool", "value"),
    Input("lc-processor-upload-lc", "contents"),
    State("lc-processor-upload-lc", "filename"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def upload_lightcurve(contents, filename, user_tab_id):
    """Ingests a file into the session cache.

    Args:
        contents: ``dcc.Upload`` payload.
        filename: Original filename.
        user_tab_id: Existing tab id, if any.

    Returns:
        tuple: Tab id, revision, upload chip, stem, domain, ephemeris, crop reset.
    """
    if contents is None:
        raise PreventUpdate
    try:
        _content_type, content_string = contents.split(",", 1)
        decoded = base64.b64decode(content_string)
        lcd = ingest_lightcurve_file(BytesIO(decoded), filename or "uploaded")
        if user_tab_id is None:
            user_tab_id = generate_user_tab_id()
        write_serialized_lc(PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        clear_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB)
        native = lcd.active_domain
        domain = native if native in (DOMAIN_FLUX, DOMAIN_MAG) else DOMAIN_FLUX
        epoch_display = (
            display_epoch_offset(lcd.epoch, DISPLAY_EPOCH_JD)
            if lcd.epoch is not None
            else None
        )
        logger.info(
            "Lightcurve processor loaded %s (%s points)",
            filename,
            0 if lcd.lightcurve is None else len(lcd.lightcurve),
        )
        return (
            user_tab_id,
            _bump_lc_revision(),
            _upload_status(filename or "uploaded file", tone="ok"),
            None,
            suggested_lc_export_stem(filename),
            domain,
            lcd.period,
            epoch_display,
            None,
            None,
            [],
            PLOT_TOOL_OFF,
        )
    except Exception as exc:
        logger.error("Lightcurve processor upload failed: %s", filename)
        logger.exception("Lightcurve processor upload error")
        return (
            no_update,
            no_update,
            _upload_status(filename or "upload", tone="error"),
            format_user_upload_error(exc),
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
        )


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-domain", "value", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-domain", "value"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def apply_working_domain(domain, user_tab_id):
    """Writes the requested photometric domain onto the cached curve.

    A failed conversion restores the radio to the cached domain.

    Args:
        domain (str): ``mag`` or ``flux``.
        user_tab_id: Session cache key.

    Returns:
        tuple: Revision token, domain radio value, optional alert.
    """
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        raise PreventUpdate
    try:
        lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
        if domain not in (DOMAIN_FLUX, DOMAIN_MAG) or domain == lcd.active_domain:
            raise PreventUpdate
        apply_phot_domain_view(lcd, show_magnitude=(domain == DOMAIN_MAG))
        write_serialized_lc(PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        clear_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB)
        return _bump_lc_revision(), domain, None
    except PreventUpdate:
        raise
    except (PipeException, ValueError) as exc:
        logger.warning("Lightcurve processor domain change failed: %s", exc)
        cached = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
        return (
            no_update,
            cached.active_domain,
            dbc.Alert(str(exc), color="warning", className="py-2 mb-0"),
        )


@callback(
    Output("lc-processor-graph-working", "figure"),
    Output("lc-processor-graph-residual", "figure"),
    Output("lc-processor-plot-alert", "children"),
    Input("store-lc-processor-lc-revision", "data"),
    Input("lc-processor-time-axis", "value"),
    Input("lc-processor-show-errors", "value"),
    Input("lc-processor-t-min", "value"),
    Input("lc-processor-t-max", "value"),
    Input("lc-processor-method", "value"),
    State("store-lc-processor-knots", "data"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-upload-lc", "filename"),
    State("lc-processor-domain", "value"),
)
def plot_working_and_residual(
    _revision,
    time_axis_mode,
    show_errors,
    t_min,
    t_max,
    method,
    knots,
    user_tab_id,
    filename,
    domain,
):
    """Draws plot 1 from the cache (cropped) and keeps plot 2 empty.

    Knot-tool radio and knot-list edits do not trigger this callback.
    Green lines are patched onto the existing figure so zoom is left alone.

    Args:
        _revision: Plot revision token.
        time_axis_mode: ``mjd`` or ``date``.
        show_errors: Error-bar switch.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).
        method: Smooth method id.
        knots: Current knot list.
        user_tab_id: Session cache key.
        filename: Upload name for ``uirevision``.
        domain: Sidebar photometric domain.

    Returns:
        tuple: Working figure, residual figure, optional alert.
    """
    axis = normalize_time_axis_mode(time_axis_mode)
    domain_key = domain if domain in (DOMAIN_FLUX, DOMAIN_MAG) else DOMAIN_FLUX
    blank_w, blank_r = _blank_pair(
        time_axis_mode=axis, domain=domain_key, filename=filename
    )
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        return blank_w, blank_r, None
    try:
        lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
        view = crop_curvedash_copy(
            lcd,
            display_mjd_to_absolute_jd(t_min),
            display_mjd_to_absolute_jd(t_max),
        )
        times = np.asarray(view.jd, dtype=float)
        values = np.asarray(view.phot, dtype=float)
        err = None if view.phot_err is None else np.asarray(view.phot_err, dtype=float)
        perm = np.asarray(view.perm_index, dtype=int)
        labels = raw_labels(view)
        invert_y = view.active_domain == DOMAIN_MAG
        y_label = "Magnitude" if invert_y else "Flux"
        timescale, refposition = timescale_refposition(view)
        uirev = plot_uirevision(lcd, filename, view.active_domain or domain_key, axis)
        payload = read_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB)
        trend = overlay_trend(
            payload,
            times,
            domain=view.active_domain or domain_key,
            method=method,
        )
        plot_knots = (
            [float(k) for k in (knots or [])]
            if method in ("spline_lsq", "pspline")
            else None
        )
        fig = figure_raw_with_trend(
            times,
            values,
            err,
            trend,
            y_label=y_label,
            invert_y=invert_y,
            show_errors=bool(show_errors),
            uirevision=uirev,
            knots=plot_knots,
            knots_editable=False,
            display_epoch=DISPLAY_EPOCH_JD,
            timescale=timescale,
            refposition=refposition,
            labels=labels,
            source_index=perm,
            selected_perm_indices=selected_perm_indices(lcd),
            time_axis_mode=axis,
        )
        residual = empty_figure(
            xaxis_title=time_axis_xaxis_title(axis, timescale, refposition),
            yaxis_title="Residual",
            invert_y=invert_y,
            uirevision=uirev,
            time_axis_mode=axis,
        )
        return fig, residual, None
    except Exception as exc:
        logger.warning("Lightcurve processor plot failed: %s", exc)
        return (
            no_update,
            blank_r,
            dbc.Alert(str(exc), color="warning", className="py-2 mb-0"),
        )


@callback(
    Output("store-lc-processor-knot-shapes", "data"),
    Input("store-lc-processor-knots", "data"),
    Input("lc-processor-method", "value"),
    Input("lc-processor-time-axis", "value"),
)
def publish_knot_shapes(knots, method, time_axis_mode):
    """Publishes knot lines for a clientside ``Plotly.relayout``.

    The working ``figure`` property is not written here, so zoom is not reset.

    Args:
        knots: Interior knot times (absolute JD).
        method: Smooth method id.
        time_axis_mode: ``mjd`` or ``date``.

    Returns:
        list: Plotly shape dicts, or an empty list.
    """
    if method not in ("spline_lsq", "pspline"):
        return []
    return knot_layout_shapes(
        knots,
        time_axis_mode=normalize_time_axis_mode(time_axis_mode),
        display_epoch=DISPLAY_EPOCH_JD,
        editable=False,
    )


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Input("lc-processor-graph-working", "selectedData"),
    Input("lc-processor-graph-working", "clickData"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-plot-tool", "value"),
    prevent_initial_call=True,
)
def merge_working_selection(selected_data, click_data, user_tab_id, plot_tool):
    """Marks clicked or lassoed points on the cached curve.

    Args:
        selected_data: Plotly box/lasso payload.
        click_data: Plotly click payload.
        user_tab_id: Session cache key.
        plot_tool: Knot tool; add/delete consume clicks instead.

    Returns:
        str: New revision token.
    """
    if plot_tool in (PLOT_TOOL_ADD, PLOT_TOOL_DELETE):
        raise PreventUpdate
    if not ctx.triggered or not user_tab_id or not has_cached_lc(
        PAGE_NAMESPACE, user_tab_id
    ):
        raise PreventUpdate
    trigger_prop = ctx.triggered[0]["prop_id"].rsplit(".", 1)[-1]
    event = selected_data if trigger_prop == "selectedData" else click_data
    if not event or not event.get("points"):
        raise PreventUpdate
    try:
        lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
        apply_plot_point_selection(lcd, event, allow_point_index_fallback=False)
        write_serialized_lc(PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        return _bump_lc_revision()
    except Exception as exc:
        logger.warning("Lightcurve processor selection failed: %s", exc)
        raise PreventUpdate


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Input("lc-processor-unselect", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def unselect_working_points(n_clicks, user_tab_id):
    """Clears orange selection marks.

    Args:
        n_clicks: Button clicks.
        user_tab_id: Session cache key.

    Returns:
        str: New revision token.
    """
    if not n_clicks or not user_tab_id:
        raise PreventUpdate
    lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
    clear_plot_point_selection(lcd)
    write_serialized_lc(PAGE_NAMESPACE, user_tab_id, lcd.serialize())
    return _bump_lc_revision()


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-delete-selected", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def delete_working_selected_points(n_clicks, user_tab_id):
    """Removes selected rows from the cached working curve.

    Args:
        n_clicks: Button clicks.
        user_tab_id: Session cache key.

    Returns:
        tuple: New revision token and optional alert.
    """
    if not n_clicks or not user_tab_id:
        raise PreventUpdate
    try:
        lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
        marked = selected_perm_indices(lcd)
        if not marked:
            raise PreventUpdate
        delete_selected_rows(lcd)
        if lcd.lightcurve is None or lcd.lightcurve.empty:
            raise PipeException("Cannot delete all points from the lightcurve")
        write_serialized_lc(PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        clear_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB)
        logger.info("Lightcurve processor deleted %s selected point(s)", len(marked))
        return _bump_lc_revision(), None
    except PreventUpdate:
        raise
    except Exception as exc:
        logger.warning("Lightcurve processor delete failed: %s", exc)
        return no_update, dbc.Alert(str(exc), color="warning", className="py-2 mb-0")


@callback(
    Output("lc-processor-download-lc-btn", "disabled"),
    Input("store-lc-processor-lc-revision", "data"),
    State("store-lc-processor-user-tab-id", "data"),
)
def gate_lightcurve_export(_revision, user_tab_id):
    """Enables export once a working curve is cached.

    Args:
        _revision: Plot revision token.
        user_tab_id: Session cache key.

    Returns:
        bool: ``True`` when the button must stay disabled.
    """
    return not (user_tab_id and has_cached_lc(PAGE_NAMESPACE, user_tab_id))


@callback(
    Output("lc-processor-download-lc", "data"),
    Output("lc-processor-export-feedback", "children"),
    Input("lc-processor-download-lc-btn", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-export-format", "value"),
    State("lc-processor-export-stem", "value"),
    State("lc-processor-input-period", "value"),
    State("lc-processor-input-epoch", "value"),
    prevent_initial_call=True,
)
def download_working_lightcurve(
    n_clicks,
    user_tab_id,
    table_format,
    stem,
    period,
    epoch,
):
    """Exports the full cached working curve (crop is ignored).

    Args:
        n_clicks: Button clicks.
        user_tab_id: Session cache key.
        table_format: Export format id.
        stem: User stem (already ``_lc`` by default).
        period: Sidebar period, or empty.
        epoch: Sidebar epoch as display MJD, or empty.

    Returns:
        tuple: Download payload and optional alert.
    """
    if not n_clicks or not user_tab_id:
        raise PreventUpdate
    try:
        lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
        apply_prep_fold_ephemeris(
            lcd, period, epoch, display_epoch=DISPLAY_EPOCH_JD
        )
        fmt = table_format or DEFAULT_EXPORT_FORMAT
        outfile = gp_lc_export_download_name(stem, fmt)
        blob = export_curvedash(lcd, fmt)
        return dcc.send_bytes(blob, outfile), None
    except PipeException as exc:
        return no_update, dbc.Alert(str(exc), color="warning", className="py-2 mb-0")
    except Exception as exc:
        logger.exception("Lightcurve processor export failed")
        return no_update, dbc.Alert(str(exc), color="danger", className="py-2 mb-0")


def _cached_lcd(user_tab_id) -> CurveDash:
    """Loads the working curve from the session cache.

    Args:
        user_tab_id: Session cache key.

    Returns:
        CurveDash: Cached working curve.
    """
    return CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))


@callback(
    Output("lc-processor-params-median", "style"),
    Output("lc-processor-params-points", "style"),
    Output("lc-processor-params-biweight", "style"),
    Output("lc-processor-params-smooth", "style"),
    Output("lc-processor-params-lsq", "style"),
    Output("lc-processor-params-pspline", "style"),
    Output("lc-processor-params-knot-tool", "style"),
    Output("lc-processor-params-place-knots", "style"),
    Input("lc-processor-method", "value"),
)
def toggle_method_params(method: str):
    """Shows the parameter block that belongs to the selected method.

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


@callback(
    Output("lc-processor-graph-working", "config"),
    Input("lc-processor-plot-tool", "value"),
    Input("lc-processor-method", "value"),
)
def update_working_graph_config(plot_tool, method):
    """Updates plot config when the knot tool changes.

    Args:
        plot_tool: ``off``, ``add``, or ``delete``.
        method: Active smooth method id.

    Returns:
        dict: Plotly config dictionary.
    """
    return graph_config(plot_tool=plot_tool or PLOT_TOOL_OFF, method=method)


@callback(
    Output("store-lc-processor-knots", "data", allow_duplicate=True),
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-apply-feedback", "children"),
    Input("lc-processor-place-knots", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-method", "value"),
    State("lc-processor-split-gaps", "value"),
    State("lc-processor-break-tol", "value"),
    State("lc-processor-t-min", "value"),
    State("lc-processor-t-max", "value"),
    State("lc-processor-n-knots", "value"),
    State("lc-processor-lsq-knot-grid", "value"),
    State("lc-processor-pspline-nseg", "value"),
    prevent_initial_call=True,
)
def place_knots(
    n_clicks,
    user_tab_id,
    method,
    split_gaps,
    break_tol,
    t_min,
    t_max,
    n_knots,
    knot_grid_mode,
    n_segments,
):
    """Draws the knot grid on the working plot without fitting.

    Args:
        n_clicks: Place-knots clicks.
        user_tab_id: Session cache key.
        method: Method id.
        split_gaps: Gap-split switch.
        break_tol: Maximum gap in days.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).
        n_knots: Requested LSQ knot count.
        knot_grid_mode: ``uniform`` or ``occupancy``.
        n_segments: P-spline segment count.

    Returns:
        tuple: Knots, revision, optional status.
    """
    if not n_clicks:
        raise PreventUpdate
    if method not in ("spline_lsq", "pspline"):
        raise PreventUpdate
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        return no_update, no_update, dbc.Alert(
            "Load a light curve first.",
            color="warning",
            className="py-2 mb-0",
        )
    try:
        lcd = _cached_lcd(user_tab_id)
        times, _y, _e, _perm, _labels = cropped_series(lcd, t_min, t_max)
        placed, requested = place_knot_grid(
            times,
            method=method,
            split_gaps=bool(split_gaps),
            break_tol=break_tol,
            n_knots=n_knots,
            knot_grid_mode=knot_grid_mode,
            n_segments=n_segments,
        )
    except Exception as exc:
        logger.exception("Could not place knots")
        return no_update, no_update, dbc.Alert(
            str(exc), color="danger", className="py-2 mb-0"
        )
    had_overlay = read_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB) is not None
    clear_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB)
    logger.info("Placed %s knots for method %s", len(placed), method)
    revision = _bump_lc_revision() if had_overlay else no_update
    if not placed:
        return [], revision, dbc.Alert(
            "No interior knots could be placed on the current segments.",
            color="warning",
            className="py-2 mb-0",
        )
    note = None
    if method == "spline_lsq" and len(placed) < requested:
        note = dbc.Alert(
            f"Placed {len(placed)} of {requested} knots (limited by points per night).",
            color="info",
            className="py-2 mb-0",
        )
    return placed, revision, note


@callback(
    Output("store-lc-processor-knots", "data", allow_duplicate=True),
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-apply-feedback", "children", allow_duplicate=True),
    Input("lc-processor-apply-smooth", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-method", "value"),
    State("lc-processor-domain", "value"),
    State("lc-processor-split-gaps", "value"),
    State("lc-processor-break-tol", "value"),
    State("lc-processor-t-min", "value"),
    State("lc-processor-t-max", "value"),
    State("lc-processor-median-window", "value"),
    State("lc-processor-n-points", "value"),
    State("lc-processor-n-points-biweight", "value"),
    State("lc-processor-polyorder", "value"),
    State("lc-processor-smooth-rel", "value"),
    State("lc-processor-smooth-s", "value"),
    State("store-lc-processor-knots", "data"),
    State("lc-processor-n-knots", "value"),
    State("lc-processor-lsq-knot-grid", "value"),
    State("lc-processor-pspline-lambda", "value"),
    State("lc-processor-pspline-nseg", "value"),
    prevent_initial_call=True,
)
def apply_smooth(
    apply_clicks,
    user_tab_id,
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
    """Fits the selected smoother and stores an overlay (plot 2 stays empty).

    Args:
        apply_clicks: Apply-button clicks.
        user_tab_id: Session cache key.
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
        knot_grid_mode: LSQ grid mode.
        penalty_lambda: P-spline lambda.
        n_segments: P-spline segments.

    Returns:
        tuple: Knots, revision, feedback.
    """
    if not apply_clicks:
        raise PreventUpdate
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        return no_update, no_update, dbc.Alert(
            "Load a light curve first.",
            color="warning",
            className="py-2 mb-0",
        )
    try:
        lcd = _cached_lcd(user_tab_id)
        payload = fit_smooth_overlay(
            lcd,
            method=method,
            domain=domain,
            split_gaps=bool(split_gaps),
            break_tol=break_tol,
            t_min=t_min,
            t_max=t_max,
            median_window=median_window,
            n_points=n_points,
            n_points_biweight=n_points_biweight,
            polyorder=polyorder,
            smooth_rel=smooth_rel,
            smooth_s=smooth_s,
            knots=list(knots or []),
            n_knots=n_knots,
            knot_grid_mode=knot_grid_mode,
            penalty_lambda=penalty_lambda,
            n_segments=n_segments,
        )
        write_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB, payload)
    except Exception as exc:
        logger.exception("Smooth fit failed")
        return no_update, no_update, dbc.Alert(
            str(exc), color="danger", className="py-2 mb-0"
        )
    return payload.get("knots") or list(knots or []), _bump_lc_revision(), None


@callback(
    Output("store-lc-processor-knots", "data", allow_duplicate=True),
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-apply-feedback", "children", allow_duplicate=True),
    Input("lc-processor-graph-working", "clickData"),
    Input("lc-processor-graph-working", "relayoutData"),
    Input("store-lc-processor-knot-pick", "data"),
    State("store-lc-processor-user-tab-id", "data"),
    State("store-lc-processor-knots", "data"),
    State("lc-processor-method", "value"),
    State("lc-processor-t-min", "value"),
    State("lc-processor-t-max", "value"),
    State("lc-processor-plot-tool", "value"),
    State("lc-processor-time-axis", "value"),
    prevent_initial_call=True,
)
def edit_knots_on_plot(
    click_data,
    relayout_data,
    knot_pick,
    user_tab_id,
    knots,
    method,
    t_min,
    t_max,
    plot_tool,
    time_axis_mode,
):
    """Adds, removes, or drags LSQ knots. Does not refit until Apply smooth.

    Args:
        click_data: Plotly ``clickData``.
        relayout_data: Plotly ``relayoutData``.
        knot_pick: Clientside pointer pick in delete mode.
        user_tab_id: Session cache key.
        knots: Current knot list.
        method: Method id.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).
        plot_tool: Active knot tool.
        time_axis_mode: ``mjd`` or ``date``.

    Returns:
        tuple: Knots, revision, feedback.
    """
    if method != "spline_lsq" or not user_tab_id or not has_cached_lc(
        PAGE_NAMESPACE, user_tab_id
    ):
        raise PreventUpdate
    tool = plot_tool or PLOT_TOOL_OFF
    axis = normalize_time_axis_mode(time_axis_mode)
    triggered = ctx.triggered_id
    current = [float(k) for k in (knots or [])]
    new_knots = None
    lcd = _cached_lcd(user_tab_id)
    times, _y, _e, _perm, _labels = cropped_series(lcd, t_min, t_max)
    t0 = float(np.min(times))
    t1 = float(np.max(times))
    if triggered == "store-lc-processor-knot-pick":
        if tool != PLOT_TOOL_DELETE or not knot_pick:
            raise PreventUpdate
        click_jd = plot_x_to_jd(knot_pick["x"], axis, DISPLAY_EPOCH_JD)
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
            hit_span=knot_hit_span_jd(vis, t0, t1, time_axis_mode=axis),
        )
        if new_knots == current:
            raise PreventUpdate
    elif triggered == "lc-processor-graph-working" and ctx.triggered:
        prop = ctx.triggered[0].get("prop_id", "")
        if prop.endswith("clickData") and click_data:
            if tool != PLOT_TOOL_ADD:
                raise PreventUpdate
            point = click_data["points"][0]
            click_jd = plot_x_to_jd(point["x"], axis, DISPLAY_EPOCH_JD)
            new_knots = knot_click_edit(current, click_jd, t0, t1, mode="add")
            if new_knots == current:
                raise PreventUpdate
        elif prop.endswith("relayoutData"):
            if tool != PLOT_TOOL_ADD:
                raise PreventUpdate
            new_knots = merge_knot_drag(current, relayout_data, time_axis_mode=axis)
    if new_knots is None:
        raise PreventUpdate
    had_overlay = read_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB) is not None
    clear_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB)
    revision = _bump_lc_revision() if had_overlay else no_update
    return new_knots, revision, None


clientside_callback(
    ClientsideFunction(namespace="lcpKnot", function_name="applyDeleteMode"),
    Output("lc-processor-graph-working-shell", "className"),
    Input("lc-processor-plot-tool", "value"),
)

clientside_callback(
    ClientsideFunction(namespace="lcpKnot", function_name="bindGraph"),
    Output("store-lc-processor-clientside", "data"),
    Input("lc-processor-graph-working", "figure"),
    State("lc-processor-plot-tool", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpKnot", function_name="applyShapes"),
    Output("store-lc-processor-clientside", "data", allow_duplicate=True),
    Input("store-lc-processor-knot-shapes", "data"),
    State("lc-processor-plot-tool", "value"),
    prevent_initial_call=True,
)
