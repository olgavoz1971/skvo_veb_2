"""Lightcurve processor: ingest, clean, smooth, detrend, extrema, and export.

Maths stay in ``skvo_veb/utils/lc_processor/``. The working ``CurveDash``,
smooth overlay, residual, and rough extrema live in the session cache.
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
    MATCH,
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

from skvo_veb.components.message import status_alert
from skvo_veb.components.photcal_editor import photcal_editor_body, photcal_field_ids
from skvo_veb.components.upload_status import (
    register_upload_busy_clientside,
    upload_detail_collapse,
    upload_detail_id,
    upload_failure_detail,
    upload_slot,
    upload_status_chip,
)
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_export import (
    apply_export_ephemeris,
    intervals_export_download_name,
    lc_export_download_name,
    rough_toms_export_download_name,
    suggested_detrended_export_stem,
    suggested_intervals_export_stem,
    suggested_lc_export_stem,
    suggested_rough_toms_export_stem,
)
from skvo_veb.utils.lc_bridge import (
    export_curvedash,
    format_user_upload_error,
    ingest_lightcurve_file,
)
from skvo_veb.utils.photcal_coherence import (
    fill_missing_photcal_form_values,
    format_photcal_warning_message,
    inspect_curve_photcal,
    photcal_form_values_from_curvedash,
    write_photcal_form_to_curvedash,
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
    delete_rows_by_perm_indices,
    extract_display_x_range_from_selected_data,
    normalize_selected_perm_store,
    plot_x_to_jd,
)
from skvo_veb.utils.lc_processor.apply import (
    DETREND_BLOB,
    SMOOTH_BLOB,
    apply_detrend_from_smooth,
    cropped_series,
    fit_smooth_overlay,
    overlay_residual,
    overlay_trend,
    place_knot_grid,
    required_float,
    required_int,
)
from skvo_veb.utils.lc_processor.extrema import (
    EXTREMA_BLOB,
    EXTREMA_DELETE_HIT_FRAC,
    add_manual_extremum,
    extrema_xy_from_payload,
    find_extrema_from_smooth,
    remove_extremum_near_time,
    format_rough_toms_download,
)
from skvo_veb.utils.lc_processor.intervals import (
    INTERVALS_BLOB,
    REF_EXTREMA_BLOB,
    add_manual_interval,
    build_processor_interval_pick_payload,
    empty_intervals_payload,
    format_cached_intervals_download,
    generate_intervals_from_extrema,
    intervals_without_marked_ids,
    parse_uploaded_extrema_jds,
)
from skvo_veb.utils.lc_processor.config import (
    DEFAULT_BIWEIGHT_N_POINTS,
    DEFAULT_BREAK_TOLERANCE_DAYS,
    DEFAULT_INTERVAL_DELTA_DAYS,
    DEFAULT_LSQ_KNOT_GRID,
    DEFAULT_LSQ_N_KNOTS,
    DEFAULT_MEDIAN_WINDOW_DAYS,
    DEFAULT_MIN_EXTREMA_SEGMENT_POINTS,
    DEFAULT_MIN_PEAK_DISTANCE_DAYS,
    DEFAULT_PSPLINE_LAMBDA,
    DEFAULT_PSPLINE_SEGMENTS,
    DEFAULT_RP_MIN_POINTS,
    DEFAULT_RP_STEP_DAYS,
    DEFAULT_RP_WINDOW_DAYS,
    DEFAULT_SAVGOL_N_POINTS,
    DEFAULT_SAVGOL_POLYORDER,
    DEFAULT_SPLINE_SMOOTH_REL,
    MIN_EXTREMA_SEGMENT_POINTS_FLOOR,
    resolve_widget_defaults,
)
from skvo_veb.utils.lc_processor.figures import (
    PLOT_TOOL_ADD,
    PLOT_TOOL_ADD_EXT,
    PLOT_TOOL_DELETE,
    PLOT_TOOL_DELETE_EXT,
    PLOT_TOOL_OFF,
    apply_processor_zoom_store,
    empty_figure,
    extract_xaxis_range_mjd,
    figure_detrended,
    figure_raw_with_trend,
    graph_config,
    knot_click_edit,
    knot_layout_shapes,
    knot_hit_span_jd,
    merge_knot_drag,
    residual_graph_config,
)
from skvo_veb.utils.lc_processor.smooth import METHOD_LABELS
from skvo_veb.utils.lc_processor.tilt import (
    apply_local_tilt,
    copy_working_as_residual,
    residual_axis_title,
)
from skvo_veb.utils.lc_intervals import format_interval_display_pair
from skvo_veb.utils.lc_working_window import (
    WORKING_WINDOW_DISABLED,
    build_working_window_store_from_times,
    filter_plot_arrays_by_jd_window,
    jd_bounds_from_visible_plot,
    normalize_working_window,
    observation_jd_bounds_tuple,
)
from skvo_veb.utils.lc_processor.view import (
    clear_sector_labels,
    crop_curvedash_copy,
    display_mjd_to_absolute_jd,
    plot_uirevision,
    raw_labels,
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
    name="Lightcurve Processor",
    order=8,
    path="/lc_processor",
    title="Lightcurve Processor",
    in_navbar=True,
)

PAGE_NAMESPACE = "lc_processor"
ACCORDION_LC_ITEM_ID = "lc-processor-accordion-lc"
ACCORDION_SMOOTH_ITEM_ID = "lc-processor-accordion-smooth"
ACCORDION_DETREND_ITEM_ID = "lc-processor-accordion-detrend"
ACCORDION_EXTREMA_ITEM_ID = "lc-processor-accordion-extrema"
PHOTCAL_ID_PREFIX = "lc-processor-photcal"
_PHOTCAL_IDS = photcal_field_ids(PHOTCAL_ID_PREFIX)
DISPLAY_EPOCH_JD = DEFAULT_EPOCH_JD
EXTREMUM_MIN = "min"
EXTREMUM_MAX = "max"
DEFAULT_SMOOTH_METHOD = "spline_lsq"

PAGE_ABOUT_MARKDOWN = """
Load a lightcurve, inspect it, delete bad points, and export the working
series. Time crop affects the plot and Smooth only. Export lightcurve writes
the whole working series (after deletes) as ``{name}_lc``.

Apply smooth draws an overlay on plot 1. Plot 2 is seeded by Apply
detrend (the residual) or by Copy from plot 1. Local tilt then rewrites
a stretch of plot 2. A new smooth, a domain change, or a delete clears
plot 2 and the rough-extrema marks.
"""


def _bump_lc_revision() -> str:
    """Returns a new plot-revision token.

    Returns:
        str: UUID string.
    """
    return str(uuid.uuid4())


def _processor_ui_payload(
    *,
    source_filename: str | None = None,
    method: str | None = None,
    t_min=None,
    t_max=None,
    time_axis: str | None = None,
    show_errors: bool | None = None,
    export_stem: str | None = None,
    export_format: str | None = None,
    previous: dict | None = None,
    replace_crop: bool = False,
) -> dict:
    """Builds the session UI chrome dict for the processor page.

    Tool inputs that must not live on ``CurveDash`` (method, crop, stems,
    upload filename chip) travel here. Scientific fields stay on the cached
    curve.

    Args:
        source_filename (str, optional): Original upload file name.
        method (str, optional): Smooth method id.
        t_min: Crop lower bound (MJD), or empty.
        t_max: Crop upper bound (MJD), or empty.
        time_axis (str, optional): ``mjd`` or ``date``.
        show_errors (bool, optional): Error-bar switch.
        export_stem (str, optional): Working-curve export stem.
        export_format (str, optional): Export format id.
        previous (dict, optional): Prior chrome dict to merge.
        replace_crop (bool): When ``True``, write ``t_min`` / ``t_max`` even
            if they are ``None`` (upload reset).

    Returns:
        dict: Session-storage payload for ``store-lc-processor-ui``.
    """
    base = dict(previous) if isinstance(previous, dict) else {}
    if source_filename is not None:
        base["source_filename"] = source_filename
    if method is not None:
        base["method"] = method
    if replace_crop or t_min is not None:
        base["t_min"] = t_min
    if replace_crop or t_max is not None:
        base["t_max"] = t_max
    if time_axis is not None:
        base["time_axis"] = time_axis
    if show_errors is not None:
        base["show_errors"] = bool(show_errors)
    if export_stem is not None:
        base["export_stem"] = export_stem
    if export_format is not None:
        base["export_format"] = export_format
    return base


def _ui_source_filename(ui_store) -> str | None:
    """Returns the upload file name from the session UI chrome store.

    Args:
        ui_store: ``store-lc-processor-ui`` payload.

    Returns:
        str | None: Original filename, if stored.
    """
    if not isinstance(ui_store, dict):
        return None
    name = ui_store.get("source_filename")
    if name is None or str(name).strip() == "":
        return None
    return str(name)


def _display_epoch_value(lcd: CurveDash) -> float | None:
    """Maps a cached absolute epoch to the sidebar Epoch offset.

    Args:
        lcd (CurveDash): Session-cached working curve.

    Returns:
        float | None: Display offset, or ``None`` when the curve has no epoch.
    """
    if lcd.epoch is None:
        return None
    return display_epoch_offset(lcd.epoch, DISPLAY_EPOCH_JD)


def _photcal_form_outputs(lcd: CurveDash) -> tuple:
    """Calibration editor field values from a cached ``CurveDash``.

    Args:
        lcd (CurveDash): Session-cached working curve.

    Returns:
        tuple: ``filter_name``, ``zp_flux``, ``zp_flux_unit``, ``zp_mag``,
        ``mag_sys``, ``flux_unit`` for the sidebar inputs.
    """
    vals = photcal_form_values_from_curvedash(lcd)
    return (
        vals["filter_name"],
        vals["zp_flux"],
        vals["zp_flux_unit"],
        vals["zp_mag"],
        vals["mag_sys"],
        vals["flux_unit"],
    )


def _photcal_form_outputs_from_dict(vals: dict) -> tuple:
    """Unpacks a photcal form dict into the sidebar output tuple.

    Args:
        vals (dict): Keys matching :func:`photcal_form_values_from_storage`.

    Returns:
        tuple: Same order as :func:`_photcal_form_outputs`.
    """
    return (
        vals["filter_name"],
        vals["zp_flux"],
        vals["zp_flux_unit"],
        vals["zp_mag"],
        vals["mag_sys"],
        vals["flux_unit"],
    )


def _clear_fit_blobs(user_tab_id: str) -> None:
    """Clears the overlay, residual, rough extrema, and intervals.

    Args:
        user_tab_id (str): Session cache key.
    """
    clear_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB)
    clear_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB)
    clear_page_blob(PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB)
    clear_page_blob(PAGE_NAMESPACE, user_tab_id, INTERVALS_BLOB)


def _clear_reference_extrema(user_tab_id: str) -> None:
    """Clears uploaded comparison extrema marks.

    Args:
        user_tab_id (str): Session cache key.
    """
    clear_page_blob(PAGE_NAMESPACE, user_tab_id, REF_EXTREMA_BLOB)


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


def _collapsible_drawer_section(
    index: str,
    label: str,
    help_id: str,
    help_title: str,
    help_body: str,
    body_children: list,
    *,
    start_open: bool = False,
    label_class: str = "lcp-drawer-collapse-title",
) -> html.Div:
    """Sidebar block with a chevron toggle and a closed-by-default collapse.

    The heading matches every other drawer section: one ``lcp-sidebar-heading-row``
    (chevron, label, ``?``) with the help popover as a sibling — not nested
    inside the flex row.

    Args:
        index (str): Pattern-matching index shared by toggle, icon, and collapse.
        label (str): Visible section label.
        help_id (str): Help slug for the ``?`` control.
        help_title (str): Popover title.
        help_body (str): Popover body.
        body_children (list): Controls shown when expanded.
        start_open (bool): Initial collapse state. Defaults to closed.
        label_class (str): CSS class for the collapse title. Defaults to
            ``lcp-drawer-collapse-title`` (bold). Ordinary field labels use
            ``lcp-section-label`` instead.

    Returns:
        dash.html.Div: Heading row plus ``dbc.Collapse`` body.
    """
    icon_class = "bi bi-chevron-down" if start_open else "bi bi-chevron-right"
    help_btn, help_pop = _click_help(help_id, help_title, help_body)
    return html.Div(
        [
            html.Div(
                [
                    dbc.Button(
                        html.I(
                            id={
                                "type": "lcp-drawer-collapse-icon",
                                "index": index,
                            },
                            className=icon_class,
                        ),
                        id={"type": "lcp-drawer-collapse-btn", "index": index},
                        color="link",
                        size="sm",
                        className="lcp-drawer-collapse-btn",
                    ),
                    html.Label(label, className=f"{label_class} mb-0"),
                    html.Div(help_btn, className="lcp-field-help"),
                ],
                className="lcp-sidebar-heading-row",
            ),
            help_pop,
            dbc.Collapse(
                html.Div(body_children, className="lcp-drawer-collapse-body"),
                id={"type": "lcp-drawer-collapse", "index": index},
                is_open=start_open,
            ),
        ],
        className="lcp-sidebar-block lcp-drawer-collapse-section",
    )


def _upload_status(filename: str, *, tone: str) -> html.Div:
    """Filename chip after an upload attempt (shared upload pattern).

    Args:
        filename (str): Original file name (or busy caption source).
        tone (str): ``ok``, ``error``, or ``busy``.

    Returns:
        dash.html.Div: Icon plus truncating label.
    """
    return upload_status_chip(filename, tone=tone)


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
        uirevision=f"{uirev}|empty",
        time_axis_mode=axis,
    )
    return working, residual


def _lightcurve_drawer() -> list:
    """Builds the Light curve accordion body.

    Returns:
        list: Plot, calibration, crop, ephemeris, and export widgets.
    """
    return [
        html.Div(
            [
                _control_with_help(
                    dbc.Switch(
                        id="lc-processor-points-control",
                        label="Points control",
                        value=False,
                    ),
                    "points-control",
                    "Points control",
                    """Turns on point cleaning on plot 1. Click or lasso to
                    mark points orange; Delete selected removes them from the
                    working curve; Unselect clears marks. Turns interval
                    control, knot tool, and extrema control off.""",
                ),
            ],
            className="lcp-sidebar-block",
        ),
        html.Div(
            [
                _control_with_help(
                    dbc.Button(
                        "Merge sectors",
                        id="lc-processor-merge-sectors",
                        color="primary",
                        size="sm",
                    ),
                    "merge-sectors",
                    "Merge sectors",
                    "Each distinct label (TESS sector, camera, filter) is "
                    "drawn in its own colour. Merge sectors clears those "
                    "labels so the working series is one unlabelled set. "
                    "Times and photometry are not changed.",
                ),
            ],
            className="lcp-sidebar-block",
        ),
        _collapsible_drawer_section(
            "plot",
            "Plot",
            "plot-view",
            "Plot",
            "Working domain, time axis, and whether photometry error bars "
            "are drawn on plots 1 and 2.",
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
        ), 
        _collapsible_drawer_section(
            "calibration",
            "Calibration",
            "photcal",
            "Calibration",
            "Filter label and zero points used for magnitude↔flux conversion. "
            "Filled from the uploaded lightcurve when present. Fill missing "
            "defaults only completes empty zero-point fields (never filter "
            "or overwrites file values). Apply calibration writes them into "
            "the working CurveDash (domain switch and export use that copy).",
            photcal_editor_body(PHOTCAL_ID_PREFIX),
        ),     
        _collapsible_drawer_section(
            "time-crop",
            "Time crop (MJD)",
            "time-crop",
            "Time crop (MJD)",
            "Applies to the working plot and later Smooth fits. "
            "Export lightcurve still writes the full working series.",
            [
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
        ),
        _collapsible_drawer_section(
            "ephemeris",
            "Ephemeris",
            "ephemeris",
            "Ephemeris",
            "Written into the exported file. Empty fields keep the values from "
            "the upload.",
            [
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
        ),
        _collapsible_drawer_section(
            "export-lightcurve",
            "Export",
            "export-lc",
            "Export",
            "Time crop applies to the plot only. This export writes the whole "
            "working lightcurve after deleted points. The stem field already "
            "ends in _lc.",
            [
                html.Div(
                    [
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
                    ],
                    className="lcp-sidebar-btn-stack",
                ),
            ],
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
                    value=DEFAULT_SMOOTH_METHOD,
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
                    value=DEFAULT_SAVGOL_N_POINTS,
                    size="sm",
                ),
                html.Label("Polynomial order", className="lcp-section-label"),
                dbc.Input(
                    id="lc-processor-polyorder",
                    type="number",
                    step=1,
                    min=1,
                    value=DEFAULT_SAVGOL_POLYORDER,
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
                    value=DEFAULT_BIWEIGHT_N_POINTS,
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
                    value=DEFAULT_SPLINE_SMOOTH_REL,
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
                    value=DEFAULT_LSQ_N_KNOTS,
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
            "lc-processor-params-rp",
            [
                _heading_with_help(
                    "Window (days)",
                    "rp-window",
                    "Window (days)",
                    "Full width of each sliding parabola, in days. "
                    "The fit uses points with |t − centre| ≤ window / 2. "
                    "When a period is set this starts at period / 2; "
                    "otherwise the no-period fallback is used.",
                ),
                dbc.Input(
                    id="lc-processor-rp-window",
                    type="number",
                    step="any",
                    min=1e-8,
                    value=DEFAULT_RP_WINDOW_DAYS,
                    size="sm",
                ),
                _heading_with_help(
                    "Step (days)",
                    "rp-step",
                    "Step (days)",
                    "Spacing of the native centre-grid. Apply interpolates "
                    "that grid onto the observation times. This starts at "
                    "one quarter of the window (window × 0.25).",
                ),
                dbc.Input(
                    id="lc-processor-rp-step",
                    type="number",
                    step="any",
                    min=1e-8,
                    value=DEFAULT_RP_STEP_DAYS,
                    size="sm",
                ),
                html.Label("Minimum points", className="lcp-section-label"),
                dbc.Input(
                    id="lc-processor-rp-min-points",
                    type="number",
                    step=1,
                    min=3,
                    value=DEFAULT_RP_MIN_POINTS,
                    size="sm",
                ),
                dbc.Switch(
                    id="lc-processor-rp-weights",
                    label="Weight by errors",
                    value=False,
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
                    "stretches of the lightcurve. A gap is a jump in time "
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
                    value=DEFAULT_BREAK_TOLERANCE_DAYS,
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


def _detrend_drawer() -> list:
    """Builds the Detrend accordion body.

    Returns:
        list: Seed plot 2, local tilt, and residual export.
    """
    return [
        html.Div(
            [
                _heading_with_help(
                    "Seed data",
                    "seed data",
                    "Seed data",
                    "Apply detrend writes the residual of the last overlay "
                    "(magnitudes subtract; flux divides). Copy from plot 1 "
                    "writes the cropped, cleaned series as it stands. Either "
                    "button replaces whatever is already on plot 2. Holes in "
                    "the overlay are filled inside the same night only.",
                ),
                html.Div(
                    [
                        dbc.Button(
                            "Apply detrend",
                            id="lc-processor-apply-detrend",
                            color="primary",
                            size="sm",
                            disabled=True,
                        ),
                        dbc.Button(
                            "Take",
                            id="lc-processor-copy-plot-1",
                            color="secondary",
                            outline=True,
                            size="sm",
                            disabled=True,
                        ),
                    ],
                    className="lcp-sidebar-btn-row",
                ),
            ],
            className="lcp-sidebar-block",
        ),
        html.Div(
            [
                _heading_with_help(
                    "Local tilt",
                    "local-tilt",
                    "Local tilt",
                    "Same as Remove trend on the GP page. Zoom plot 2 and "
                    "press Use visible range. Switch on Place tilt line, "
                    "click once, drag the handles, then Apply local tilt. "
                    "The line is the model; the working range is the "
                    "locality. Magnitudes subtract the line; flux divides "
                    "by it. Restore full plot 2 shows the whole seeded "
                    "series. Reload the lightcurve to undo.",
                ),
                html.Div(
                    id="lc-processor-plot2-window-status",
                    className="small text-muted",
                ),
                html.Div(
                    [
                        dbc.Button(
                            "Use visible range",
                            id="lc-processor-use-visible-range",
                            color="primary",
                            size="sm",
                            disabled=True,
                        ),
                        dbc.Button(
                            "Restore",
                            id="lc-processor-restore-plot-2",
                            color="secondary",
                            outline=True,
                            size="sm",
                            disabled=True,
                        ),
                    ],
                    className="lcp-sidebar-btn-row",
                ),
                dbc.Switch(
                    id="lc-processor-local-tilt",
                    label="Place tilt line",
                    value=False,
                    disabled=True,
                ),
                html.Div(
                    [
                        dbc.Button(
                            "Apply local tilt",
                            id="lc-processor-apply-tilt",
                            color="primary",
                            size="sm",
                        ),
                        dbc.Button(
                            "Clear tilt line",
                            id="lc-processor-clear-tilt",
                            color="secondary",
                            outline=True,
                            size="sm",
                        ),
                    ],
                    id="lc-processor-tilt-actions",
                    className="lcp-sidebar-btn-row d-none",
                ),
            ],
            className="lcp-sidebar-block",
        ),
        html.Div(
            [
                _heading_with_help(
                    "Export",
                    "export-detrend",
                    "Export",
                    "Same formats as Export lightcurve. The stem starts "
                    "from the input name and already ends in _detrended "
                    "(not _lc_detrended). Writes the current plot 2, "
                    "including any local tilts.",
                ),
                dbc.Select(
                    options=EXPORT_FORMAT_OPTIONS,  # type: ignore[arg-type]
                    value=DEFAULT_EXPORT_FORMAT,
                    id="lc-processor-detrend-export-format",
                    size="sm",
                ),
                dbc.Input(
                    id="lc-processor-detrend-export-stem",
                    placeholder="lightcurve_detrended",
                    type="text",
                    value="lightcurve_detrended",
                    size="sm",
                ),
                dbc.Button(
                    "Export detrended",
                    id="lc-processor-download-detrended-btn",
                    color="primary",
                    size="sm",
                    className="w-100",
                    disabled=True,
                ),
            ],
            className="lcp-sidebar-block lcp-sidebar-btn-stack",
        ),
    ]


def _extrema_drawer() -> list:
    """Builds the Rough extrema accordion body.

    Returns:
        list: Find-extrema, reference upload, interval, and export widgets.
    """
    return [
        _collapsible_drawer_section(
            "find-extrema",
            "Extrema",
            "find-extrema",
            "Extrema",
            """Marks minima or maxima on the last Apply-smooth overlay.
            Only finite trend samples are used; holes and gap splits are not
            joined. This is a rough finder, not a GP or MAVKA timing.""",
            [
                dbc.RadioItems(
                    id="lc-processor-extremum-kind",
                    options=[
                        {"label": "Minimum", "value": EXTREMUM_MIN},
                        {"label": "Maximum", "value": EXTREMUM_MAX},
                    ],
                    value=EXTREMUM_MIN,
                    inline=True,
                ),
                _heading_with_help(
                    "Min. peak distance (days)",
                    "min-peak-distance",
                    "Min. peak distance (days)",
                    """Minimum separation between neighbouring extrema.
                    When a period is set this starts at 0.7 × period;
                    otherwise the no-period fallback is used.""",
                ),
                dbc.Input(
                    id="lc-processor-min-peak-distance",
                    type="number",
                    step="any",
                    min=1e-8,
                    value=DEFAULT_MIN_PEAK_DISTANCE_DAYS,
                    size="sm",
                ),
                _heading_with_help(
                    "Min. points in segment",
                    "min-segment-points",
                    "Min. points in segment",
                    """A finite overlay run shorter than this is skipped.
                    A peak needs at least three samples; the default is
                    five so a one- to three-point night is not treated
                    as an extremum.""",
                ),
                dbc.Input(
                    id="lc-processor-min-segment-points",
                    type="number",
                    step=1,
                    min=MIN_EXTREMA_SEGMENT_POINTS_FLOOR,
                    value=DEFAULT_MIN_EXTREMA_SEGMENT_POINTS,
                    size="sm",
                ),
                dbc.Button(
                    "Find extrema",
                    id="lc-processor-find-extrema",
                    color="primary",
                    size="sm",
                    className="w-100",
                    disabled=True,
                ),
                _control_with_help(
                    dbc.Switch(
                        id="lc-processor-extrema-control",
                        label="Extrema control",
                        value=False,
                    ),
                    "extrema-control",
                    "Extrema control",
                    """Turns on manual add and delete of working extrema on
                    plot 1. Choose Add extremum or Delete extremum above
                    the plot (one at a time). This turns points control,
                    interval control, and knot tool off.""",
                ),
            ],
            start_open=False,
        ),

        _collapsible_drawer_section(
            "intervals-section",
            "Intervals",
            "rough-intervals",
            "Intervals",
            """Generate [t − δ, t + δ] around working (found or manually
            corrected) extrema. Interval control puts Add interval and
            Mark bands on plot 1. Export writes every surviving interval
            sorted by start.""",
            [
                dbc.Switch(
                    id="lc-processor-show-intervals",
                    label="Show intervals",
                    value=False,
                ),
                _control_with_help(
                    dbc.Switch(
                        id="lc-processor-interval-control",
                        label="Interval control",
                        value=False,
                    ),
                    "interval-control",
                    "Interval control",
                    """Turns on interval editing on plot 1. Box Select
                    becomes available in the modebar. Add interval, Mark
                    bands, Remove marked, and Clear marks appear above
                    the plot. This turns knot control and extremum
                    control off. While this is on, interval bands are
                    drawn even if Show intervals is off.""",
                ),
                _heading_with_help(
                    "Interval half-width (days)",
                    "interval-delta",
                    "Interval half-width (days)",
                    """Half-width δ for Generate intervals. When a period is set
                    this starts at period / 3; otherwise the no-period fallback is used.""",
                ),
                dbc.Input(
                    id="lc-processor-interval-delta",
                    type="number",
                    step="any",
                    min=1e-8,
                    value=DEFAULT_INTERVAL_DELTA_DAYS,
                    size="sm",
                ),
                dbc.Button(
                    "Generate intervals",
                    id="lc-processor-generate-intervals",
                    color="primary",
                    size="sm",
                    className="w-100",
                    disabled=True,
                ),
            ],
        ),
        _collapsible_drawer_section(
            "export-extrema-intervals",
            "Export",
            "export-extrema-intervals",
            "Export",
            """Export intervals or rough extrema (Times of Minima/Maxima) to a file.
            Intervals are exported as a list of [start, end] JD pairs.
            ToMs are exported as a single column of JDs with optional error.
            Both are sorted by Julian Date before export.""",
            [
                html.Label("Intervals file", className="lcp-section-label"),
                dbc.Input(
                    id="lc-processor-intervals-export-stem",
                    placeholder="lightcurve_int",
                    type="text",
                    value="lightcurve_int",
                    size="sm",
                ),
                dbc.Button(
                    "Export intervals",
                    id="lc-processor-download-intervals-btn",
                    color="primary",
                    size="sm",
                    className="w-100",
                    disabled=True,
                ),
                html.Label("ToMs file", className="lcp-section-label"),
                dbc.Input(
                    id="lc-processor-toms-export-stem",
                    placeholder="lightcurve_rough_toms",
                    type="text",
                    value="lightcurve_rough_toms",
                    size="sm",
                ),
                dbc.Button(
                    "Export ToMs",
                    id="lc-processor-download-toms-btn",
                    color="primary",
                    size="sm",
                    className="w-100",
                    disabled=True,
                ),
            ],
        ),
        _collapsible_drawer_section(
            "uploaded-extrema",
            "Upload user ToMs",
            "upload-ref-extrema",
            "Upload user ToMs",
            """First column is Julian Date; any further columns are ignored.
            Optional # JD0 = … (default 0). Marks only for comparison with
            found extrema — not used for intervals or export times.""",
            [
                html.Div(
                    [
                        dcc.Upload(
                            id="lc-processor-upload-ref-extrema",
                            children=dbc.Button(
                                "Load extrema",
                                color="secondary",
                                outline=True,
                                size="sm",
                            ),
                            className="lcp-inline-upload",
                            multiple=False,
                        ),
                        html.Span(
                            id="lc-processor-upload-ref-extrema-text",
                            className="lcp-upload-filename",
                        ),
                    ],
                    className="lcp-sidebar-btn-stack",
                ),
                dbc.Switch(
                    id="lc-processor-show-ref-extrema",
                    label="Show uploaded ToMs",
                    value=False,
                ),
            ],
        ),
    ]



def _sidebar() -> html.Div:
    """Builds the tools accordion. Plots stay outside this column.

    Returns:
        dash.html.Div: Lightcurve, Smooth, Detrend, and Rough extrema drawers.
    """
    return html.Div(
        dbc.Accordion(
            [
                dbc.AccordionItem(
                    html.Div(_lightcurve_drawer(), className="lcp-drawer-body"),
                    title="Lightcurve",
                    item_id=ACCORDION_LC_ITEM_ID,
                ),
                dbc.AccordionItem(
                    html.Div(_smooth_drawer(), className="lcp-drawer-body"),
                    title="Smooth",
                    item_id=ACCORDION_SMOOTH_ITEM_ID,
                ),
                dbc.AccordionItem(
                    html.Div(_detrend_drawer(), className="lcp-drawer-body"),
                    title="Detrend",
                    item_id=ACCORDION_DETREND_ITEM_ID,
                ),
                dbc.AccordionItem(
                    html.Div(_extrema_drawer(), className="lcp-drawer-body"),
                    title="Rough extrema",
                    item_id=ACCORDION_EXTREMA_ITEM_ID,
                ),
            ],
            id="lc-processor-accordion",
            always_open=True,
            active_item=[ACCORDION_LC_ITEM_ID],
            className="lcp-workflow-accordion",
        ),
        className="lcp-sidebar",
    )


@callback(
    Output({"type": "lcp-drawer-collapse", "index": MATCH}, "is_open"),
    Output({"type": "lcp-drawer-collapse-icon", "index": MATCH}, "className"),
    Input({"type": "lcp-drawer-collapse-btn", "index": MATCH}, "n_clicks"),
    State({"type": "lcp-drawer-collapse", "index": MATCH}, "is_open"),
    prevent_initial_call=True,
)
def toggle_lcp_drawer_section(n_clicks, is_open):
    """Opens or closes a Light curve drawer section collapse.

    Args:
        n_clicks (int | None): Clicks on the section chevron.
        is_open (bool): Current collapse state.

    Returns:
        tuple: New ``is_open`` flag and chevron icon class.
    """
    if not n_clicks:
        raise PreventUpdate
    opened = not bool(is_open)
    icon = "bi bi-chevron-down" if opened else "bi bi-chevron-right"
    return opened, icon


def _plot_toolbar() -> html.Div:
    """Mode-specific action clusters above plot 1.

    Returns:
        dash.html.Div: Points and interval toolbars (hidden until their
        drawer mode is on).
    """
    points_help_btn, points_help_pop = _click_help(
        "plot-points-tools",
        "Delete selected",
        "Click or lasso on the working plot. Orange marks stay until "
        "Unselect or Delete selected. Clicking empty space does not clear them.",
        placement="bottom",
    )
    interval_help_btn, interval_help_pop = _click_help(
        "interval-plot-tools",
        "Interval tools",
        "The plot starts in zoom. Switch the toolbar to Box Select, drag "
        "a time range, then press Add interval. To drop intervals, switch "
        "on Mark bands and click a strip, then Remove marked.",
        placement="bottom",
    )
    extrema_help_btn, extrema_help_pop = _click_help(
        "extrema-plot-tools",
        "Extrema tools",
        "Choose Add extremum or Delete extremum (one at a time), then click "
        "on plot 1. Add uses the click time as the ToM; delete removes "
        "the nearest working extremum mark.",
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
                    html.Div(points_help_btn, className="lcp-field-help"),
                    points_help_pop,
                ],
                id="lc-processor-points-toolbar",
                className="lcp-plot-toolbar-cluster d-none",
            ),
            html.Div(
                [
                    dbc.Button(
                        "Add interval",
                        id="lc-processor-add-interval",
                        color="primary",
                        size="sm",
                    ),
                    html.Div(interval_help_btn, className="lcp-field-help"),
                    interval_help_pop,
                    dbc.Switch(
                        id="lc-processor-interval-mark-bands",
                        label="Mark bands",
                        value=False,
                    ),
                    dbc.Button(
                        "Remove marked",
                        id="lc-processor-remove-marked-intervals",
                        color="primary",
                        size="sm",
                        disabled=True,
                    ),
                    dbc.Button(
                        "Clear marks",
                        id="lc-processor-clear-interval-marks",
                        color="secondary",
                        outline=True,
                        size="sm",
                        disabled=True,
                    ),
                ],
                id="lc-processor-interval-toolbar",
                className="lcp-plot-toolbar-cluster d-none",
            ),
            html.Div(
                [
                    dbc.RadioItems(
                        id="lc-processor-extrema-tool",
                        options=[
                            {
                                "label": "Add extremum",
                                "value": PLOT_TOOL_ADD_EXT,
                            },
                            {
                                "label": "Delete extremum",
                                "value": PLOT_TOOL_DELETE_EXT,
                            },
                        ],
                        value=PLOT_TOOL_OFF,
                        inline=True,
                        className="lcp-plot-toolbar-radios",
                    ),
                    html.Div(extrema_help_btn, className="lcp-field-help"),
                    extrema_help_pop,
                ],
                id="lc-processor-extrema-toolbar",
                className="lcp-plot-toolbar-cluster d-none",
            ),
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
                        html.H1("Lightcurve Processor", className="lcp-page-title"),
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
            dcc.Store(id="store-lc-processor-lc-revision", **SESSION_STORE),
            dcc.Store(id="store-lc-processor-ui", **SESSION_STORE),
            dcc.Store(id="store-lc-processor-selected-perm", data=[]),
            dcc.Store(id="store-lc-processor-zoom"),
            dcc.Store(id="store-lc-processor-knots", data=[]),
            dcc.Store(id="store-lc-processor-knot-shapes"),
            dcc.Store(id="store-lc-processor-knot-pick"),
            dcc.Store(id="store-lc-processor-extrema-pick"),
            dcc.Store(
                id="store-lc-processor-intervals",
                data=empty_intervals_payload(),
                **SESSION_STORE,
            ),
            dcc.Store(id="store-lc-processor-intervals-marked", data=[]),
            dcc.Store(id="store-lc-processor-interval-bands"),
            dcc.Store(id="store-lc-processor-interval-click"),
            dcc.Store(id="store-lc-processor-tilt-click"),
            dcc.Store(id="store-lc-processor-tilt-line"),
            dcc.Store(
                id="store-lc-processor-plot2-window",
                data=WORKING_WINDOW_DISABLED,
            ),
            dcc.Store(id="store-lc-processor-clientside"),
            dcc.Download(id="lc-processor-download-lc"),
            dcc.Download(id="lc-processor-download-detrended"),
            dcc.Download(id="lc-processor-download-intervals"),
            dcc.Download(id="lc-processor-download-toms"),
            html.Div(
                [
                    html.Div(
                        upload_slot(
                            "lc-processor-upload-lc",
                            "Load lightcurve",
                            "processor-lc",
                        ),
                        className="lcp-data-bar",
                    ),
                    upload_detail_collapse("processor-lc"),
                ],
                className="lcp-data-hub",
            ),
            dbc.Row(
                [
                    dbc.Col(_sidebar(), width=3, className="lcp-sidebar-col"),
                    dbc.Col(
                        html.Div(
                            [
                                html.Div(
                                    id="lc-processor-plot-alert",
                                    className="lcp-plot-alert",
                                ),
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
                                html.Div(
                                    dcc.Graph(
                                        id="lc-processor-graph-residual",
                                        figure=_initial_residual,
                                        className="lcp-graph",
                                        config=residual_graph_config(),
                                    ),
                                    id="lc-processor-graph-residual-shell",
                                    className="lcp-graph-shell",
                                ),
                            ],
                            className="lcp-plot-stack lcp-plot-column",
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


# Immediate busy chip while the sync ingest callback runs (Ticket 6 Option B).
register_upload_busy_clientside("lc-processor-upload-lc")


@callback(
    Output("store-lc-processor-user-tab-id", "data"),
    Output("store-lc-processor-lc-revision", "data"),
    Output("store-lc-processor-ui", "data"),
    Output("lc-processor-upload-lc-text", "children"),
    Output(upload_detail_id("processor-lc"), "children"),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Output("lc-processor-export-stem", "value"),
    Output("lc-processor-domain", "value"),
    Output("lc-processor-input-period", "value"),
    Output("lc-processor-input-epoch", "value"),
    Output(_PHOTCAL_IDS["filter_name"], "value"),
    Output(_PHOTCAL_IDS["zp_flux"], "value"),
    Output(_PHOTCAL_IDS["zp_flux_unit"], "value"),
    Output(_PHOTCAL_IDS["zp_mag"], "value"),
    Output(_PHOTCAL_IDS["mag_sys"], "value"),
    Output(_PHOTCAL_IDS["flux_unit"], "value"),
    Output("lc-processor-t-min", "value"),
    Output("lc-processor-t-max", "value"),
    Output("store-lc-processor-knots", "data"),
    Output("lc-processor-plot-tool", "value"),
    Output("lc-processor-extrema-tool", "value"),
    Output("lc-processor-extrema-control", "value"),
    Output("store-lc-processor-intervals", "data"),
    Output("store-lc-processor-intervals-marked", "data"),
    Output("lc-processor-interval-control", "value"),
    Output("lc-processor-interval-mark-bands", "value"),
    Output("lc-processor-points-control", "value"),
    Output("store-lc-processor-selected-perm", "data"),
    Output("store-lc-processor-zoom", "data"),
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
        tuple: Tab id, revision, UI chrome, upload chip, cleared overlay, stem,
        domain, ephemeris, calibration fields, crop reset, cleared selection
        and zoom stores.
    """
    if contents is None:
        raise PreventUpdate
    try:
        _content_type, content_string = contents.split(",", 1)
        decoded = base64.b64decode(content_string)
        source_name = filename or "uploaded"
        lcd = ingest_lightcurve_file(BytesIO(decoded), source_name)
        if user_tab_id is None:
            user_tab_id = generate_user_tab_id()
        write_serialized_lc(PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        _clear_fit_blobs(user_tab_id)
        _clear_reference_extrema(user_tab_id)
        native = lcd.active_domain
        domain = native if native in (DOMAIN_FLUX, DOMAIN_MAG) else DOMAIN_FLUX
        epoch_display = _display_epoch_value(lcd)
        export_stem = suggested_lc_export_stem(source_name)
        ui_payload = _processor_ui_payload(
            source_filename=source_name,
            method=DEFAULT_SMOOTH_METHOD,
            t_min=None,
            t_max=None,
            time_axis=TIME_AXIS_MJD,
            show_errors=False,
            export_stem=export_stem,
            export_format=DEFAULT_EXPORT_FORMAT,
            replace_crop=True,
        )
        logger.info(
            "Lightcurve processor loaded %s (%s points)",
            source_name,
            0 if lcd.lightcurve is None else len(lcd.lightcurve),
        )
        return (
            user_tab_id,
            _bump_lc_revision(),
            ui_payload,
            _upload_status(source_name, tone="ok"),
            None,
            None,
            export_stem,
            domain,
            lcd.period,
            epoch_display,
            *_photcal_form_outputs(lcd),
            None,
            None,
            [],
            PLOT_TOOL_OFF,
            False,
            empty_intervals_payload(),
            [],
            False,
            False,
            False,
            [],
            None,
        )
    except Exception as exc:
        logger.error("Lightcurve processor upload failed: %s", filename)
        logger.exception("Lightcurve processor upload error")
        return (
            no_update,
            no_update,
            no_update,
            _upload_status(filename or "upload", tone="error"),
            upload_failure_detail(
                "Lightcurve upload failed",
                format_user_upload_error(exc),
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
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
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


@callback(
    Output("lc-processor-domain", "value", allow_duplicate=True),
    Output("lc-processor-input-period", "value", allow_duplicate=True),
    Output("lc-processor-input-epoch", "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["filter_name"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_flux"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_flux_unit"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_mag"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["mag_sys"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["flux_unit"], "value", allow_duplicate=True),
    Input("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call="initial_duplicate",
)
def restore_processor_curve_controls(user_tab_id):
    """Refills domain, ephemeris, and calibration from the session cache.

    Args:
        user_tab_id (str, optional): Browser tab id from session storage.

    Returns:
        tuple: Working domain, period, display epoch, and photcal form fields.

    Raises:
        PreventUpdate: When there is no tab id or no cached lightcurve.
    """
    if not user_tab_id:
        raise PreventUpdate
    if not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        raise PreventUpdate
    try:
        lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
    except Exception as exc:
        logger.warning("Lightcurve processor restore curve controls failed: %s", exc)
        raise PreventUpdate from exc
    native = lcd.active_domain
    domain = native if native in (DOMAIN_FLUX, DOMAIN_MAG) else DOMAIN_FLUX
    logger.info("Lightcurve processor restored curve controls from session cache.")
    return (
        domain,
        lcd.period,
        _display_epoch_value(lcd),
        *_photcal_form_outputs(lcd),
    )


@callback(
    Output("lc-processor-upload-lc-text", "children", allow_duplicate=True),
    Output("lc-processor-export-stem", "value", allow_duplicate=True),
    Output("lc-processor-export-format", "value", allow_duplicate=True),
    Output("lc-processor-t-min", "value", allow_duplicate=True),
    Output("lc-processor-t-max", "value", allow_duplicate=True),
    Output("lc-processor-method", "value", allow_duplicate=True),
    Output("lc-processor-time-axis", "value", allow_duplicate=True),
    Output("lc-processor-show-errors", "value", allow_duplicate=True),
    Input("store-lc-processor-ui", "data"),
    prevent_initial_call="initial_duplicate",
)
def restore_processor_ui_chrome(ui_store):
    """Refills tool chrome from the session UI workspace store.

    Args:
        ui_store (dict, optional): ``store-lc-processor-ui`` payload.

    Returns:
        tuple: Upload chip, stem, format, crop, method, time axis, error bars.

    Raises:
        PreventUpdate: When the UI store is empty.
    """
    if not isinstance(ui_store, dict) or not ui_store:
        raise PreventUpdate
    source_name = _ui_source_filename(ui_store)
    chip = (
        _upload_status(source_name, tone="ok")
        if source_name
        else no_update
    )
    method = ui_store.get("method") or DEFAULT_SMOOTH_METHOD
    time_axis = ui_store.get("time_axis") or TIME_AXIS_MJD
    export_stem = ui_store.get("export_stem")
    export_format = ui_store.get("export_format") or DEFAULT_EXPORT_FORMAT
    show_errors = bool(ui_store.get("show_errors", False))
    logger.info("Lightcurve processor restored UI chrome from session store.")
    return (
        chip,
        export_stem if export_stem is not None else no_update,
        export_format,
        ui_store.get("t_min"),
        ui_store.get("t_max"),
        method,
        time_axis,
        show_errors,
    )


@callback(
    Output("store-lc-processor-ui", "data", allow_duplicate=True),
    Input("lc-processor-method", "value"),
    Input("lc-processor-t-min", "value"),
    Input("lc-processor-t-max", "value"),
    Input("lc-processor-time-axis", "value"),
    Input("lc-processor-show-errors", "value"),
    Input("lc-processor-export-stem", "value"),
    Input("lc-processor-export-format", "value"),
    State("store-lc-processor-user-tab-id", "data"),
    State("store-lc-processor-ui", "data"),
    prevent_initial_call=True,
)
def snapshot_processor_ui_chrome(
    method,
    t_min,
    t_max,
    time_axis,
    show_errors,
    export_stem,
    export_format,
    user_tab_id,
    previous_ui,
):
    """Writes tool chrome into session storage while a curve is loaded.

    Args:
        method: Smooth method id.
        t_min: Crop lower bound.
        t_max: Crop upper bound.
        time_axis: Time-axis mode.
        show_errors: Error-bar switch.
        export_stem: Working export stem.
        export_format: Export format id.
        user_tab_id: Session cache key.
        previous_ui: Prior UI chrome dict.

    Returns:
        dict: Updated UI chrome payload.

    Raises:
        PreventUpdate: When no curve is loaded yet.
    """
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        raise PreventUpdate
    updated = _processor_ui_payload(
        method=method or DEFAULT_SMOOTH_METHOD,
        t_min=t_min,
        t_max=t_max,
        time_axis=time_axis or TIME_AXIS_MJD,
        show_errors=bool(show_errors),
        export_stem=export_stem,
        export_format=export_format or DEFAULT_EXPORT_FORMAT,
        previous=previous_ui,
        replace_crop=True,
    )
    if updated == previous_ui:
        raise PreventUpdate
    return updated


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Input("lc-processor-input-period", "value"),
    Input("lc-processor-input-epoch", "value"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def sync_processor_ephemeris_to_cache(period, epoch, user_tab_id):
    """Writes sidebar period and epoch through to the cached ``CurveDash``.

    Remount restore reads these fields from disk, so typed values must not
    live only in the form widgets.

    Args:
        period: Sidebar period in days, or empty.
        epoch: Sidebar epoch as display MJD, or empty.
        user_tab_id: Session cache key.

    Returns:
        Any: ``dash.no_update`` (cache write only; plot does not depend on P/E).

    Raises:
        PreventUpdate: When there is no cache or values are unchanged.
    """
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        raise PreventUpdate
    try:
        lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
        before_period = lcd.period
        before_epoch = lcd.epoch
        apply_export_ephemeris(
            lcd, period, epoch, display_epoch=DISPLAY_EPOCH_JD
        )
        if lcd.period == before_period and lcd.epoch == before_epoch:
            raise PreventUpdate
        write_serialized_lc(PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        logger.debug(
            "Lightcurve processor wrote ephemeris to session cache (P=%s, epoch=%s)",
            lcd.period,
            lcd.epoch,
        )
        return no_update
    except PreventUpdate:
        raise
    except Exception as exc:
        logger.warning("Lightcurve processor ephemeris write-through failed: %s", exc)
        raise PreventUpdate from exc


@callback(
    Output(_PHOTCAL_IDS["filter_name"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_flux"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_flux_unit"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_mag"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["mag_sys"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["flux_unit"], "value", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input(_PHOTCAL_IDS["fill_missing"], "n_clicks"),
    State(_PHOTCAL_IDS["filter_name"], "value"),
    State(_PHOTCAL_IDS["zp_flux"], "value"),
    State(_PHOTCAL_IDS["zp_flux_unit"], "value"),
    State(_PHOTCAL_IDS["zp_mag"], "value"),
    State(_PHOTCAL_IDS["mag_sys"], "value"),
    State(_PHOTCAL_IDS["flux_unit"], "value"),
    prevent_initial_call=True,
)
def fill_processor_photcal_missing(
    n_clicks,
    filter_name,
    zp_flux,
    zp_flux_unit,
    zp_mag,
    mag_sys,
    flux_unit,
):
    """Fills empty calibration fields from application defaults only.

    Does not write the session ``CurveDash`` and does not change unit fields
    that are blank (blank remains dimensionless).

    Args:
        n_clicks: Fill-missing button clicks.
        filter_name: Current filter label form value.
        zp_flux: Current ZP flux form value.
        zp_flux_unit: Current ZP flux unit form value.
        zp_mag: Current ZP mag form value.
        mag_sys: Current magnitude system form value.
        flux_unit: Current flux column unit form value.

    Returns:
        tuple: Updated form fields and a short info alert.
    """
    if not n_clicks:
        raise PreventUpdate
    before = {
        "filter_name": filter_name if filter_name is not None else "",
        "zp_flux": zp_flux,
        "zp_flux_unit": zp_flux_unit if zp_flux_unit is not None else "",
        "zp_mag": zp_mag,
        "mag_sys": mag_sys if mag_sys is not None else "",
        "flux_unit": flux_unit if flux_unit is not None else "",
    }
    after = fill_missing_photcal_form_values(before)
    changed = any(before[k] != after[k] for k in ("zp_flux", "zp_mag", "mag_sys"))
    alert = (
        status_alert(
            "Filled missing zero points and/or magnitude system from "
            "application defaults. Unit blanks were left unchanged. "
            "Press Apply calibration to adopt into the working lightcurve.",
            "info",
        )
        if changed
        else status_alert("No missing calibration fields to fill.", "info")
    )
    return (*_photcal_form_outputs_from_dict(after), alert)


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output(_PHOTCAL_IDS["filter_name"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_flux"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_flux_unit"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_mag"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["mag_sys"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["flux_unit"], "value", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input(_PHOTCAL_IDS["apply"], "n_clicks"),
    State(_PHOTCAL_IDS["filter_name"], "value"),
    State(_PHOTCAL_IDS["zp_flux"], "value"),
    State(_PHOTCAL_IDS["zp_flux_unit"], "value"),
    State(_PHOTCAL_IDS["zp_mag"], "value"),
    State(_PHOTCAL_IDS["mag_sys"], "value"),
    State(_PHOTCAL_IDS["flux_unit"], "value"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def apply_processor_photcal(
    n_clicks,
    filter_name,
    zp_flux,
    zp_flux_unit,
    zp_mag,
    mag_sys,
    flux_unit,
    user_tab_id,
):
    """Adopts calibration editor values into the session ``CurveDash``.

    Writes ``metadata['photcal']`` and ``metadata['flux_unit']``, runs the
    shared reconcile policy, and bumps the plot revision. ZP magnitude unit
    is always ``mag``. Domain switch and export read only the cached curve.

    Args:
        n_clicks: Apply button clicks.
        filter_name: Form passband label.
        zp_flux: Form zero-point flux.
        zp_flux_unit: Form ZP flux unit.
        zp_mag: Form zero-point magnitude.
        mag_sys: Form magnitude system.
        flux_unit: Form flux column unit.
        user_tab_id: Session cache key.

    Returns:
        tuple: Revision, refreshed form fields, and optional alert.
    """
    if not n_clicks:
        raise PreventUpdate
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        return (
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            status_alert("Load a lightcurve first.", "warning"),
        )
    try:
        lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
        warnings = write_photcal_form_to_curvedash(
            lcd,
            filter_name=filter_name,
            zp_flux=zp_flux,
            zp_flux_unit=zp_flux_unit,
            zp_mag=zp_mag,
            mag_sys=mag_sys,
            flux_unit=flux_unit,
        )
        write_serialized_lc(PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        photcal_text = format_photcal_warning_message(warnings)
        alert = (
            status_alert(photcal_text, "warning")
            if photcal_text
            else status_alert("Calibration adopted into the working lightcurve.", "success")
        )
        logger.info("Lightcurve processor applied photcal to session cache")
        return (_bump_lc_revision(), *_photcal_form_outputs(lcd), alert)
    except (TypeError, ValueError) as exc:
        logger.warning("Lightcurve processor photcal apply failed: %s", exc)
        return (
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            status_alert(str(exc), "warning"),
        )
    except Exception as exc:
        logger.exception("Lightcurve processor photcal apply failed")
        return (
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            status_alert(str(exc), "warning"),
        )


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-domain", "value", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Output(_PHOTCAL_IDS["filter_name"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_flux"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_flux_unit"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["zp_mag"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["mag_sys"], "value", allow_duplicate=True),
    Output(_PHOTCAL_IDS["flux_unit"], "value", allow_duplicate=True),
    Input("lc-processor-domain", "value"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def apply_working_domain(domain, user_tab_id):
    """Writes the requested photometric domain onto the cached curve.

    Photcal is inspected without rewriting. Inappropriate calibration rejects
    the switch (radio restored) with a warning. Successful switches convert
    using photcal as stored on the session ``CurveDash`` (Apply calibration
    first if the form was edited).

    Args:
        domain (str): ``mag`` or ``flux``.
        user_tab_id: Session cache key.

    Returns:
        tuple: Revision, domain radio, optional alert, refreshed photcal fields.
    """
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        raise PreventUpdate
    try:
        lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
        if domain not in (DOMAIN_FLUX, DOMAIN_MAG) or domain == lcd.active_domain:
            raise PreventUpdate

        problems = inspect_curve_photcal(lcd)
        if problems:
            photcal_text = format_photcal_warning_message(problems)
            hint = (
                "Open Calibration collapse, correct, "
                "apply calibration, then try again"
            )
            alert_text = f"{photcal_text}\n\n{hint}" if photcal_text else hint
            return (
                no_update,
                lcd.active_domain,
                status_alert(alert_text, "warning"),
                *_photcal_form_outputs(lcd),
            )

        if domain == DOMAIN_MAG:
            lcd.convert_to_mag()
        else:
            lcd.convert_to_flux()
        write_serialized_lc(PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        _clear_fit_blobs(user_tab_id)
        return (
            _bump_lc_revision(),
            domain,
            None,
            *_photcal_form_outputs(lcd),
        )
    except PreventUpdate:
        raise
    except (PipeException, ValueError) as exc:
        logger.warning("Lightcurve processor domain change failed: %s", exc)
        cached = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
        return (
            no_update,
            cached.active_domain,
            status_alert(str(exc), "warning"),
            *_photcal_form_outputs(cached),
        )


@callback(
    Output("lc-processor-graph-working", "figure"),
    Output("lc-processor-graph-residual", "figure"),
    Output("lc-processor-plot-alert", "children"),
    Output("store-lc-processor-interval-bands", "data"),
    Input("store-lc-processor-lc-revision", "data"),
    Input("store-lc-processor-user-tab-id", "data"),
    Input("lc-processor-time-axis", "value"),
    Input("lc-processor-show-errors", "value"),
    Input("lc-processor-t-min", "value"),
    Input("lc-processor-t-max", "value"),
    Input("lc-processor-method", "value"),
    Input("store-lc-processor-plot2-window", "data"),
    Input("lc-processor-show-ref-extrema", "value"),
    Input("lc-processor-show-intervals", "value"),
    Input("lc-processor-interval-control", "value"),
    Input("store-lc-processor-intervals", "data"),
    State("store-lc-processor-knots", "data"),
    State("store-lc-processor-ui", "data"),
    State("lc-processor-upload-lc", "filename"),
    State("lc-processor-domain", "value"),
    State("store-lc-processor-zoom", "data"),
    State("store-lc-processor-intervals-marked", "data"),
)
def plot_working_and_residual(
    _revision,
    user_tab_id,
    time_axis_mode,
    show_errors,
    t_min,
    t_max,
    method,
    plot2_window,
    show_ref_extrema,
    show_intervals,
    interval_control,
    intervals_store,
    knots,
    ui_store,
    upload_filename,
    domain,
    zoom,
    marked_interval_ids,
):
    """Draws plot 1 from the cache (cropped) and plot 2 when seeded.

    Knot-tool radio and knot-list edits do not trigger this callback.
    Green lines are patched onto the existing figure so zoom is left alone.
    Orange point marks live in the client perm store, not on ``CurveDash``.
    After a rebuild that changes ``uirevision`` (delete), axis ranges are
    stamped from the zoom store when it still matches this view.

    Revision and ``user_tab_id`` are session stores so in-tab navigation
    rehydrates both and replot runs from disk (smooth / detrend / extrema
    blobs included). Mark and zoom stores stay memory-only. The interval
    list lives in ``store-lc-processor-intervals``.

    Args:
        _revision: Plot revision token.
        user_tab_id: Session cache key.
        time_axis_mode: ``mjd`` or ``date``.
        show_errors: Error-bar switch.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).
        method: Smooth method id.
        plot2_window: Plot-2 working range (Use visible range).
        show_ref_extrema: Switch; when true, draw uploaded JD as vertical lines.
        show_intervals: Switch; when true, draw interval bands (mode off).
        interval_control: Interval-control switch; when true, always draw bands.
        intervals_store: Intervals Store payload.
        knots: Current knot list.
        ui_store: Session UI chrome (source filename for ``uirevision``).
        upload_filename: Live upload component filename, if any.
        domain: Sidebar photometric domain.
        zoom: Client zoom snapshot for plot 1.
        marked_interval_ids: Interval ids marked for removal.

    Returns:
        tuple: Working figure, residual figure, ``no_update`` for the
        overlay unless plotting itself fails, and interval pick-band
        metadata for clientside marking.
    """
    filename = _ui_source_filename(ui_store) or upload_filename
    axis = normalize_time_axis_mode(time_axis_mode)
    domain_key = domain if domain in (DOMAIN_FLUX, DOMAIN_MAG) else DOMAIN_FLUX
    blank_w, blank_r = _blank_pair(
        time_axis_mode=axis, domain=domain_key, filename=filename
    )
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        return blank_w, blank_r, no_update, no_update
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
        unit = (view.phot_unit or "").strip()
        if invert_y:
            y_label = f"magnitude, {unit}" if unit else "magnitude"
        else:
            y_label = f"flux, {unit}" if unit else "flux"
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
        extrema_xy = extrema_xy_from_payload(
            read_page_blob(PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB),
            domain=view.active_domain or domain_key,
        )
        ref_jd = None
        if bool(show_ref_extrema):
            ref_payload = read_page_blob(
                PAGE_NAMESPACE, user_tab_id, REF_EXTREMA_BLOB
            )
            if ref_payload and ref_payload.get("times_jd"):
                ref_jd = [float(t) for t in ref_payload["times_jd"]]
        interval_payload = intervals_store
        draw_intervals = bool(interval_control) or bool(show_intervals)
        pick_bands = build_processor_interval_pick_payload(
            interval_payload,
            time_axis_mode=axis,
            display_epoch=DISPLAY_EPOCH_JD,
            timescale=timescale,
            enabled=draw_intervals,
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
            time_axis_mode=axis,
            break_tolerance=(
                None if payload is None else payload.get("break_tolerance")
            ),
            extrema_jd=None if extrema_xy is None else extrema_xy[0],
            extrema_y=None if extrema_xy is None else extrema_xy[1],
            ref_extrema_jd=ref_jd,
            interval_payload=interval_payload if draw_intervals else None,
            show_intervals=draw_intervals,
            marked_interval_ids=marked_interval_ids,
            horizontal_interval_select=bool(interval_control),
        )
        apply_processor_zoom_store(
            fig,
            zoom,
            time_axis_mode=axis,
            domain=view.active_domain or domain_key,
        )
        residual = empty_figure(
            xaxis_title=time_axis_xaxis_title(axis, timescale, refposition),
            yaxis_title="Residual",
            invert_y=invert_y,
            uirevision=f"{uirev}|empty",
            time_axis_mode=axis,
        )
        detrend_payload = read_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB)
        matched = overlay_residual(
            detrend_payload,
            times,
            domain=view.active_domain or domain_key,
        )
        if matched is not None:
            det_y, det_err = matched
            times_p2 = times
            labels_p2 = labels
            perm_p2 = perm
            x_range_jd = None
            window = normalize_working_window(plot2_window)
            if window is not None:
                times_p2, det_y, det_err = filter_plot_arrays_by_jd_window(
                    times,
                    det_y,
                    det_err,
                    window["jd_min"],
                    window["jd_max"],
                )
                keep = (
                    (times >= window["jd_min"])
                    & (times <= window["jd_max"])
                    & np.isfinite(times)
                )
                labels_p2 = labels[keep]
                perm_p2 = perm[keep]
                x_range_jd = (window["jd_min"], window["jd_max"])
            residual = figure_detrended(
                times_p2,
                det_y,
                det_err,
                y_label=residual_axis_title(
                    None if detrend_payload is None else detrend_payload.get("origin"),
                    invert_y=invert_y,
                    phot_unit=view.phot_unit,
                ),
                invert_y=invert_y,
                show_errors=bool(show_errors),
                uirevision=f"{uirev}|detrend|{plot2_window}",
                display_epoch=DISPLAY_EPOCH_JD,
                timescale=timescale,
                refposition=refposition,
                labels=labels_p2,
                source_index=perm_p2,
                time_axis_mode=axis,
                x_range_jd=x_range_jd,
            )
        return fig, residual, no_update, pick_bands
    except Exception as exc:
        logger.warning("Lightcurve processor plot failed: %s", exc)
        return (
            no_update,
            blank_r,
            status_alert(str(exc), "warning"),
            no_update,
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
    Input("lc-processor-merge-sectors", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def merge_working_sectors(n_clicks, user_tab_id):
    """Clears sector labels on the cached working curve.

    Args:
        n_clicks: Button clicks.
        user_tab_id: Session cache key.

    Returns:
        str: New revision token.
    """
    if not n_clicks or not user_tab_id or not has_cached_lc(
        PAGE_NAMESPACE, user_tab_id
    ):
        raise PreventUpdate
    lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
    n_cleared = clear_sector_labels(lcd)
    if n_cleared == 0:
        raise PreventUpdate
    write_serialized_lc(PAGE_NAMESPACE, user_tab_id, lcd.serialize())
    return _bump_lc_revision()


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Output("store-lc-processor-selected-perm", "data", allow_duplicate=True),
    Input("lc-processor-delete-selected", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    State("store-lc-processor-selected-perm", "data"),
    State("lc-processor-points-control", "value"),
    prevent_initial_call=True,
)
def delete_working_selected_points(
    n_clicks, user_tab_id, selected_perm, points_control
):
    """Removes client-marked rows from the cached working curve.

    Orange marks live in ``store-lc-processor-selected-perm``. The figure is
    rebuilt afterwards so the cache and Scattergl traces stay aligned.

    Args:
        n_clicks: Button clicks.
        user_tab_id: Session cache key.
        selected_perm: Client list of ``perm_index`` values.
        points_control: Points-control switch.

    Returns:
        tuple: New revision token, optional alert, and a cleared perm store.
    """
    if not n_clicks or not user_tab_id or not points_control:
        raise PreventUpdate
    try:
        marked = normalize_selected_perm_store(selected_perm)
        if not marked:
            raise PreventUpdate
        lcd = CurveDash.from_serialized(read_serialized_lc(PAGE_NAMESPACE, user_tab_id))
        n_before = 0 if lcd.lightcurve is None else len(lcd.lightcurve)
        delete_rows_by_perm_indices(lcd, marked)
        n_after = 0 if lcd.lightcurve is None else len(lcd.lightcurve)
        if n_after == n_before:
            raise PipeException("Marked points were not found in the lightcurve")
        if lcd.lightcurve is None or lcd.lightcurve.empty:
            raise PipeException("Cannot delete all points from the lightcurve")
        write_serialized_lc(PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        _clear_fit_blobs(user_tab_id)
        logger.info(
            "Lightcurve processor deleted %s selected point(s)",
            n_before - n_after,
        )
        return _bump_lc_revision(), None, []
    except PreventUpdate:
        raise
    except Exception as exc:
        logger.warning("Lightcurve processor delete failed: %s", exc)
        return no_update, status_alert(str(exc), "warning"), no_update


@callback(
    Output("lc-processor-download-lc-btn", "disabled"),
    Output("lc-processor-apply-detrend", "disabled"),
    Output("lc-processor-copy-plot-1", "disabled"),
    Output("lc-processor-download-detrended-btn", "disabled"),
    Output("lc-processor-local-tilt", "disabled"),
    Output("lc-processor-use-visible-range", "disabled"),
    Output("lc-processor-restore-plot-2", "disabled"),
    Output("lc-processor-find-extrema", "disabled"),
    Output("lc-processor-generate-intervals", "disabled"),
    Output("lc-processor-download-intervals-btn", "disabled"),
    Output("lc-processor-download-toms-btn", "disabled"),
    Input("store-lc-processor-lc-revision", "data"),
    Input("store-lc-processor-user-tab-id", "data"),
    Input("store-lc-processor-plot2-window", "data"),
    Input("store-lc-processor-intervals", "data"),
)
def gate_lightcurve_actions(_revision, user_tab_id, plot2_window, intervals_store):
    """Enables export, detrend, and extrema once the required cache blobs exist.

    Args:
        _revision: Plot revision token.
        user_tab_id: Session cache key.
        plot2_window: Plot-2 working range store.
        intervals_store: Intervals Store payload.

    Returns:
        tuple: Disabled flags for LC export, Apply detrend, Copy from
        plot 1, Export detrended, Local tilt, Use visible range,
        Restore full plot 2, Find extrema, Generate intervals, Export
        intervals, and Export times.
    """
    has_lc = bool(user_tab_id and has_cached_lc(PAGE_NAMESPACE, user_tab_id))
    has_smooth = bool(
        user_tab_id and read_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB)
    )
    has_detrend = bool(
        user_tab_id and read_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB)
    )
    extrema_payload = (
        read_page_blob(PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB)
        if user_tab_id
        else None
    )
    has_extrema = bool(extrema_payload and extrema_payload.get("hits"))
    has_intervals = bool((intervals_store or {}).get("intervals"))
    has_window = normalize_working_window(plot2_window) is not None
    return (
        not has_lc,
        not has_smooth,
        not has_lc,
        not has_detrend,
        not has_detrend,
        not has_detrend,
        not has_window,
        not has_smooth,
        not has_extrema,
        not has_intervals,
        not has_extrema,
    )


@callback(
    Output("lc-processor-detrend-export-stem", "value"),
    Output("lc-processor-intervals-export-stem", "value"),
    Output("lc-processor-toms-export-stem", "value"),
    Input("lc-processor-export-stem", "value"),
)
def sync_product_export_stems(lc_stem):
    """Derives product stems from the shared light-curve stem.

    Args:
        lc_stem: Working-curve stem, typically ending in ``_lc``.

    Returns:
        tuple: ``{base}_detrended``, ``{base}_int``, ``{base}_rough_toms``.
    """
    return (
        suggested_detrended_export_stem(lc_stem),
        suggested_intervals_export_stem(lc_stem),
        suggested_rough_toms_export_stem(lc_stem),
    )


@callback(
    Output("lc-processor-rp-window", "value"),
    Output("lc-processor-rp-step", "value"),
    Output("lc-processor-min-peak-distance", "value"),
    Output("lc-processor-interval-delta", "value"),
    Input("lc-processor-input-period", "value"),
)
def sync_period_derived_defaults(period):
    """Fills RP window, RP step, peak distance, and interval δ from the period.

    Empty or non-positive period uses the constant fallbacks. The
    numbers and formulae live in ``lc_processor.config``. Step is a
    fraction of the resolved window.

    Args:
        period: Sidebar period in days, or empty.

    Returns:
        tuple: Window, step, min. peak distance, and interval half-width (days).
    """
    return resolve_widget_defaults(period)


@callback(
    Output("lc-processor-download-lc", "data"),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
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
        apply_export_ephemeris(
            lcd, period, epoch, display_epoch=DISPLAY_EPOCH_JD
        )
        fmt = table_format or DEFAULT_EXPORT_FORMAT
        outfile = lc_export_download_name(stem, fmt)
        blob = export_curvedash(lcd, fmt)
        return dcc.send_bytes(blob, outfile), None
    except PipeException as exc:
        return no_update, status_alert(str(exc), "warning")
    except Exception as exc:
        logger.exception("Lightcurve processor export failed")
        return no_update, status_alert(str(exc), "warning")


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
    Output("lc-processor-params-rp", "style"),
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
        shown if method == "running_parabola" else hidden,
        shown if method == "spline_lsq" else hidden,
        shown if method in ("spline_lsq", "pspline") else hidden,
    )


@callback(
    Output("lc-processor-graph-working", "config"),
    Input("lc-processor-plot-tool", "value"),
    Input("lc-processor-method", "value"),
    Input("lc-processor-interval-control", "value"),
    Input("lc-processor-points-control", "value"),
)
def update_working_graph_config(
    plot_tool, method, interval_control, points_control
):
    """Updates plot config when a plot interaction mode changes.

    Args:
        plot_tool: ``off``, ``add``, or ``delete``.
        method: Active smooth method id.
        interval_control: Interval-control switch.
        points_control: Points-control switch.

    Returns:
        dict: Plotly config dictionary.
    """
    return graph_config(
        plot_tool=plot_tool or PLOT_TOOL_OFF,
        method=method,
        interval_control=bool(interval_control),
        points_control=bool(points_control),
    )


@callback(
    Output("lc-processor-plot-tool", "value", allow_duplicate=True),
    Input("lc-processor-extrema-control", "value"),
    Input("lc-processor-interval-control", "value"),
    Input("lc-processor-points-control", "value"),
    Input("lc-processor-method", "value"),
    prevent_initial_call=True,
)
def clear_knot_tool_when_exclusive(
    extrema_control, interval_control, points_control, method
):
    """Turns the knot radio off when it must not share the click.

    Hidden LSQ tools must not stay on Add/Delete knot. Another plot mode
    likewise forces the knot radio to Off.

    Args:
        extrema_control: Extrema-control switch.
        interval_control: Interval-control switch.
        points_control: Points-control switch.
        method: Active smooth method id.

    Returns:
        str: ``off``.
    """
    if method != "spline_lsq":
        return PLOT_TOOL_OFF
    if bool(extrema_control) or bool(interval_control) or bool(points_control):
        return PLOT_TOOL_OFF
    raise PreventUpdate


@callback(
    Output("lc-processor-extrema-tool", "value", allow_duplicate=True),
    Input("lc-processor-plot-tool", "value"),
    Input("lc-processor-interval-control", "value"),
    Input("lc-processor-points-control", "value"),
    prevent_initial_call=True,
)
def clear_extrema_tool_when_exclusive(
    plot_tool, interval_control, points_control
):
    """Turns the extremum plot tool off when another plot mode is on.

    Args:
        plot_tool: Knot-tool radio value.
        interval_control: Interval-control switch.
        points_control: Points-control switch.

    Returns:
        str: ``off``.
    """
    if plot_tool in (PLOT_TOOL_ADD, PLOT_TOOL_DELETE):
        return PLOT_TOOL_OFF
    if bool(interval_control) or bool(points_control):
        return PLOT_TOOL_OFF
    raise PreventUpdate


@callback(
    Output("lc-processor-extrema-control", "value", allow_duplicate=True),
    Input("lc-processor-plot-tool", "value"),
    Input("lc-processor-interval-control", "value"),
    Input("lc-processor-points-control", "value"),
    prevent_initial_call=True,
)
def clear_extrema_control_when_exclusive(
    plot_tool, interval_control, points_control
):
    """Turns extrema control off when another plot mode is on.

    Args:
        plot_tool: Knot-tool radio value.
        interval_control: Interval-control switch.
        points_control: Points-control switch.

    Returns:
        bool: ``False``.
    """
    if plot_tool in (PLOT_TOOL_ADD, PLOT_TOOL_DELETE):
        return False
    if bool(interval_control) or bool(points_control):
        return False
    raise PreventUpdate


@callback(
    Output("lc-processor-interval-control", "value", allow_duplicate=True),
    Input("lc-processor-plot-tool", "value"),
    Input("lc-processor-extrema-control", "value"),
    Input("lc-processor-points-control", "value"),
    prevent_initial_call=True,
)
def clear_interval_control_when_exclusive(
    plot_tool, extrema_control, points_control
):
    """Turns interval control off when another plot mode is on.

    Args:
        plot_tool: Knot-tool radio value.
        extrema_control: Extrema-control switch.
        points_control: Points-control switch.

    Returns:
        bool: ``False``.
    """
    if plot_tool in (PLOT_TOOL_ADD, PLOT_TOOL_DELETE):
        return False
    if bool(extrema_control) or bool(points_control):
        return False
    raise PreventUpdate


@callback(
    Output("lc-processor-points-control", "value", allow_duplicate=True),
    Input("lc-processor-plot-tool", "value"),
    Input("lc-processor-extrema-control", "value"),
    Input("lc-processor-interval-control", "value"),
    prevent_initial_call=True,
)
def clear_points_control_when_exclusive(
    plot_tool, extrema_control, interval_control
):
    """Turns points control off when another plot mode is on.

    Args:
        plot_tool: Knot-tool radio value.
        extrema_control: Extrema-control switch.
        interval_control: Interval-control switch.

    Returns:
        bool: ``False``.
    """
    if plot_tool in (PLOT_TOOL_ADD, PLOT_TOOL_DELETE):
        return False
    if bool(extrema_control) or bool(interval_control):
        return False
    raise PreventUpdate


@callback(
    Output("lc-processor-points-toolbar", "className"),
    Input("lc-processor-points-control", "value"),
)
def reflect_points_control(points_control):
    """Shows the plot-1 points cluster only while Points control is on.

    Args:
        points_control: Points-control switch.

    Returns:
        str: Toolbar cluster CSS classes.
    """
    on = bool(points_control)
    return (
        "lcp-plot-toolbar-cluster" if on else "lcp-plot-toolbar-cluster d-none"
    )


@callback(
    Output("lc-processor-interval-toolbar", "className"),
    Output("lc-processor-interval-mark-bands", "value", allow_duplicate=True),
    Input("lc-processor-interval-control", "value"),
    prevent_initial_call=True,
)
def reflect_interval_control(interval_control):
    """Shows the plot-1 interval cluster only while Interval control is on.

    Args:
        interval_control: Interval-control switch.

    Returns:
        tuple: Toolbar class name, and Mark bands off when the mode drops.
    """
    on = bool(interval_control)
    cluster = (
        "lcp-plot-toolbar-cluster" if on else "lcp-plot-toolbar-cluster d-none"
    )
    mark = False if not on else no_update
    return cluster, mark


@callback(
    Output("lc-processor-extrema-toolbar", "className"),
    Output("lc-processor-extrema-tool", "value", allow_duplicate=True),
    Input("lc-processor-extrema-control", "value"),
    prevent_initial_call=True,
)
def reflect_extrema_control(extrema_control):
    """Shows the plot-1 extremum cluster only while Extrema control is on.

    Args:
        extrema_control: Extrema-control switch.

    Returns:
        tuple: Toolbar class name and cleared plot tool when mode is off.
    """
    on = bool(extrema_control)
    cluster = (
        "lcp-plot-toolbar-cluster" if on else "lcp-plot-toolbar-cluster d-none"
    )
    tool = no_update if on else PLOT_TOOL_OFF
    return cluster, tool


@callback(
    Output("store-lc-processor-knots", "data", allow_duplicate=True),
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
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
        return no_update, no_update, status_alert(
            "Load a lightcurve first.", "warning"
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
        return no_update, no_update, status_alert(str(exc), "warning")
    had_overlay = read_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB) is not None
    had_residual = read_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB) is not None
    had_extrema = read_page_blob(PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB) is not None
    _clear_fit_blobs(user_tab_id)
    logger.info("Placed %s knots for method %s", len(placed), method)
    revision = (
        _bump_lc_revision()
        if (had_overlay or had_residual or had_extrema)
        else no_update
    )
    if not placed:
        return [], revision, status_alert(
            "No interior knots could be placed on the current segments.",
            "warning",
        )
    note = None
    if method == "spline_lsq" and len(placed) < requested:
        note = status_alert(
            f"Placed {len(placed)} of {requested} knots (limited by points per night).",
            "info",
        )
    return placed, revision, note


@callback(
    Output("store-lc-processor-knots", "data", allow_duplicate=True),
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
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
    State("lc-processor-rp-window", "value"),
    State("lc-processor-rp-step", "value"),
    State("lc-processor-rp-min-points", "value"),
    State("lc-processor-rp-weights", "value"),
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
    rp_window,
    rp_step,
    rp_min_points,
    rp_use_weights,
):
    """Fits the selected smoother and stores an overlay.

    A new overlay clears any previous residual and rough extrema. Plot 2
    stays empty until Apply detrend.

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
        rp_window: Running-parabola window (days).
        rp_step: Running-parabola centre step (days).
        rp_min_points: Minimum in-window points.
        rp_use_weights: Inverse-variance switch.

    Returns:
        tuple: Knots, revision, feedback.
    """
    if not apply_clicks:
        raise PreventUpdate
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        return no_update, no_update, status_alert(
            "Load a lightcurve first.", "warning"
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
            rp_window=rp_window,
            rp_step=rp_step,
            rp_min_points=rp_min_points,
            rp_use_weights=rp_use_weights,
        )
        write_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB, payload)
        clear_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB)
        clear_page_blob(PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB)
    except Exception as exc:
        logger.exception("Smooth fit failed")
        return no_update, no_update, status_alert(str(exc), "warning")
    return payload.get("knots") or list(knots or []), _bump_lc_revision(), None


@callback(
    Output("store-lc-processor-knots", "data", allow_duplicate=True),
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
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
    had_residual = read_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB) is not None
    had_extrema = read_page_blob(PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB) is not None
    _clear_fit_blobs(user_tab_id)
    revision = (
        _bump_lc_revision()
        if (had_overlay or had_residual or had_extrema)
        else no_update
    )
    feedback = (
        None if (had_overlay or had_residual or had_extrema) else no_update
    )
    return new_knots, revision, feedback


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("store-lc-processor-extrema-pick", "data"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-domain", "value"),
    State("lc-processor-t-min", "value"),
    State("lc-processor-t-max", "value"),
    State("lc-processor-extrema-tool", "value"),
    State("lc-processor-extremum-kind", "value"),
    State("lc-processor-min-peak-distance", "value"),
    State("lc-processor-interval-delta", "value"),
    State("lc-processor-time-axis", "value"),
    prevent_initial_call=True,
)
def edit_extrema_on_plot(
    pick,
    user_tab_id,
    domain,
    t_min,
    t_max,
    extrema_tool,
    extremum_kind,
    min_distance,
    interval_delta,
    time_axis_mode,
):
    """Adds or removes a rough extremum from a plot-area pointer pick.

    Plotly ``clickData`` only fires on an existing trace. The clientside
    pick uses Plotly ``p2d`` so a click anywhere in the axes works.

    Args:
        pick: Clientside ``{x, y, x0, x1, ts}`` in plot coordinates.
        user_tab_id: Session cache key.
        domain: Working photometric domain.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).
        extrema_tool: Extremum-tool radio value.
        extremum_kind: ``min`` or ``max``.
        min_distance: Finder separation stored on a new blob (days).
        interval_delta: Interval half-width stored on a new blob (days).
        time_axis_mode: ``mjd`` or ``date``.

    Returns:
        tuple: Revision token and optional feedback.
    """
    if extrema_tool not in (PLOT_TOOL_ADD_EXT, PLOT_TOOL_DELETE_EXT):
        raise PreventUpdate
    if not pick or pick.get("x") is None or pick.get("y") is None:
        raise PreventUpdate
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        raise PreventUpdate
    try:
        lcd = _cached_lcd(user_tab_id)
        times, _y, _e, _perm, _labels = cropped_series(lcd, t_min, t_max)
        axis = normalize_time_axis_mode(time_axis_mode)
        click_jd = plot_x_to_jd(pick["x"], axis, DISPLAY_EPOCH_JD)
        click_y = float(pick["y"])
        current = read_page_blob(PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB)
        if extrema_tool == PLOT_TOOL_ADD_EXT:
            updated = add_manual_extremum(
                current,
                jd=click_jd,
                smooth=click_y,
                kind=extremum_kind,
                domain=lcd.active_domain or domain,
                min_distance_d=required_float(min_distance, "Min. peak distance"),
                delta_time_d=required_float(interval_delta, "Interval half-width"),
            )
        else:
            vis = None
            if pick.get("x0") is not None and pick.get("x1") is not None:
                vis = [pick["x0"], pick["x1"]]
            updated = remove_extremum_near_time(
                current,
                click_jd,
                hit_span_d=knot_hit_span_jd(
                    vis, float(np.min(times)), float(np.max(times)), time_axis_mode=axis
                ),
            )
        if updated is current:
            raise PreventUpdate
        if updated is None:
            raise PreventUpdate
        write_page_blob(PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB, updated)
    except PreventUpdate:
        raise
    except Exception as exc:
        logger.exception("Manual rough-extrema edit failed")
        return no_update, status_alert(str(exc), "warning")
    n_hit = int(updated.get("n_extrema") or 0)
    return _bump_lc_revision(), status_alert(
        f"{n_hit} rough mark(s).", "info"
    )


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-upload-ref-extrema-text", "children"),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-upload-ref-extrema", "contents"),
    State("lc-processor-upload-ref-extrema", "filename"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def upload_reference_extrema(contents, filename, user_tab_id):
    """Loads uploaded comparison extrema (JD list; overlay marks only).

    Args:
        contents: ``dcc.Upload`` payload.
        filename: Original filename.
        user_tab_id: Session cache key.

    Returns:
        tuple: Revision, filename next to the load button, optional alert.
    """
    name = (filename or "").strip()
    if contents is None:
        raise PreventUpdate
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        return (
            no_update,
            name,
            status_alert(
                "Load a light curve before uploading comparison extrema.",
                "warning",
            ),
        )
    try:
        _content_type, content_string = contents.split(",", 1)
        text = base64.b64decode(content_string).decode("utf-8")
        payload = parse_uploaded_extrema_jds(text)
        write_page_blob(PAGE_NAMESPACE, user_tab_id, REF_EXTREMA_BLOB, payload)
        n_hit = len(payload["times_jd"])
        logger.info(
            "Lightcurve processor loaded %s reference extrema from %s",
            n_hit,
            filename or "upload",
        )
        return (
            _bump_lc_revision(),
            name or "uploaded",
            status_alert(f"Loaded {n_hit} uploaded extremum mark(s).", "info"),
        )
    except Exception as exc:
        logger.exception("Reference extrema upload failed")
        return (
            no_update,
            name,
            status_alert(str(exc), "warning"),
        )


@callback(
    Output("store-lc-processor-intervals", "data", allow_duplicate=True),
    Output("store-lc-processor-intervals-marked", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-generate-intervals", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-interval-delta", "value"),
    prevent_initial_call=True,
)
def generate_rough_intervals(n_clicks, user_tab_id, interval_delta):
    """Builds ``[t±δ]`` intervals around working rough extrema.

    Replaces any previous interval list (auto or manual).

    Args:
        n_clicks: Button clicks.
        user_tab_id: Session cache key.
        interval_delta: Half-width in days.

    Returns:
        tuple: Intervals Store, cleared marks, optional feedback.
    """
    if not n_clicks:
        raise PreventUpdate
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        return no_update, no_update, status_alert(
            "Load a light curve first.", "warning"
        )
    try:
        payload = generate_intervals_from_extrema(
            read_page_blob(PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB),
            delta_time_d=required_float(interval_delta, "Interval half-width"),
        )
    except Exception as exc:
        logger.exception("Generate intervals failed")
        return no_update, no_update, status_alert(str(exc), "warning")
    n_int = len(payload.get("intervals") or [])
    return payload, [], status_alert(f"Generated {n_int} interval(s).", "info")


@callback(
    Output("store-lc-processor-intervals", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-add-interval", "n_clicks"),
    State("lc-processor-graph-working", "selectedData"),
    State("store-lc-processor-intervals", "data"),
    State("lc-processor-interval-control", "value"),
    State("lc-processor-time-axis", "value"),
    prevent_initial_call=True,
)
def commit_add_interval(
    n_clicks,
    selected_data,
    intervals_store,
    interval_control,
    time_axis_mode,
):
    """Appends one interval from the current Box Select x-range.

    Args:
        n_clicks: Add interval clicks.
        selected_data: Plotly box ``selectedData``.
        intervals_store: Current intervals Store payload.
        interval_control: Interval-control switch.
        time_axis_mode: ``mjd`` or ``date``.

    Returns:
        tuple: Updated intervals Store and optional feedback.
    """
    if not n_clicks or not interval_control:
        raise PreventUpdate
    axis = normalize_time_axis_mode(time_axis_mode)
    try:
        x_range = extract_display_x_range_from_selected_data(selected_data)
        if x_range is None:
            return no_update, status_alert(
                "Select a time range with Box Select first.", "warning"
            )
        start_jd = plot_x_to_jd(x_range[0], axis, DISPLAY_EPOCH_JD)
        end_jd = plot_x_to_jd(x_range[1], axis, DISPLAY_EPOCH_JD)
        updated = add_manual_interval(
            intervals_store, start_jd=start_jd, end_jd=end_jd
        )
    except PreventUpdate:
        raise
    except Exception as exc:
        logger.exception("Add interval failed")
        return no_update, status_alert(str(exc), "warning")
    n_int = len(updated.get("intervals") or [])
    return updated, status_alert(f"{n_int} interval(s).", "info")


@callback(
    Output("store-lc-processor-intervals", "data", allow_duplicate=True),
    Output("store-lc-processor-intervals-marked", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-remove-marked-intervals", "n_clicks"),
    State("store-lc-processor-intervals", "data"),
    State("store-lc-processor-intervals-marked", "data"),
    prevent_initial_call=True,
)
def commit_remove_marked_intervals(n_clicks, intervals_store, marked_ids):
    """Removes marked intervals in one Store update (one replot).

    Args:
        n_clicks: Remove marked clicks.
        intervals_store: Current intervals Store payload.
        marked_ids: Interval ids marked on plot 1.

    Returns:
        tuple: Remaining intervals, cleared marks, optional feedback.
    """
    if not n_clicks or not marked_ids:
        raise PreventUpdate
    try:
        updated = intervals_without_marked_ids(intervals_store, marked_ids)
    except Exception as exc:
        logger.exception("Remove marked intervals failed")
        return no_update, no_update, status_alert(str(exc), "warning")
    n_int = len(updated.get("intervals") or [])
    return updated, [], status_alert(f"{n_int} interval(s).", "info")


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Output("store-lc-processor-tilt-line", "data", allow_duplicate=True),
    Output("lc-processor-local-tilt", "value", allow_duplicate=True),
    Output("store-lc-processor-plot2-window", "data", allow_duplicate=True),
    Input("lc-processor-apply-detrend", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-method", "value"),
    State("lc-processor-domain", "value"),
    State("lc-processor-t-min", "value"),
    State("lc-processor-t-max", "value"),
    prevent_initial_call=True,
)
def apply_detrend(
    n_clicks,
    user_tab_id,
    method,
    domain,
    t_min,
    t_max,
):
    """Writes the residual from the last Apply-smooth overlay onto plot 2.

    Magnitude subtracts the trend. Flux divides by the trend. Replaces
    any previous plot-2 series and clears a pending tilt line.

    Args:
        n_clicks: Apply-detrend clicks.
        user_tab_id: Session cache key.
        method: Active smooth method id.
        domain: Working photometric domain.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).

    Returns:
        tuple: Revision token, feedback, cleared tilt line, switch off.
    """
    if not n_clicks:
        raise PreventUpdate
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        return no_update, status_alert(
            "Load a lightcurve first.", "warning"
        ), no_update, no_update, no_update
    try:
        lcd = _cached_lcd(user_tab_id)
        payload = apply_detrend_from_smooth(
            lcd,
            read_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB),
            method=method,
            domain=domain,
            t_min=t_min,
            t_max=t_max,
        )
        write_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB, payload)
    except Exception as exc:
        logger.exception("Detrend failed")
        return (
            no_update,
            status_alert(str(exc), "warning"),
            no_update,
            no_update,
            no_update,
        )
    n_finite = sum(1 for v in payload["residual"] if v is not None)
    fill = payload.get("fill") or {}
    n_fill = int(fill.get("nearest", 0) + fill.get("interp", 0) + fill.get("median", 0))
    logger.info(
        "Lightcurve processor detrended %s finite point(s) (filled %s)",
        n_finite,
        n_fill,
    )
    note = status_alert(
        f"Plot 2 seeded from Apply detrend ({n_finite} point(s)).", "info"
    )
    if n_fill:
        parts = []
        if fill.get("nearest"):
            parts.append(f"{fill['nearest']} nearest trend")
        if fill.get("interp"):
            parts.append(f"{fill['interp']} local interpolant")
        if fill.get("median"):
            parts.append(f"{fill['median']} piece median")
        note = status_alert(
            "Kept every point. Filled "
            + f"{n_fill} doubtful sample(s): "
            + ", ".join(parts)
            + ".",
            "info",
        )
    return _bump_lc_revision(), note, None, False, dict(WORKING_WINDOW_DISABLED)


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Output("store-lc-processor-tilt-line", "data", allow_duplicate=True),
    Output("lc-processor-local-tilt", "value", allow_duplicate=True),
    Output("store-lc-processor-plot2-window", "data", allow_duplicate=True),
    Input("lc-processor-copy-plot-1", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-domain", "value"),
    State("lc-processor-t-min", "value"),
    State("lc-processor-t-max", "value"),
    prevent_initial_call=True,
)
def copy_plot_1_to_plot_2(n_clicks, user_tab_id, domain, t_min, t_max):
    """Copies the cropped working series onto plot 2.

    Args:
        n_clicks: Button clicks.
        user_tab_id: Session cache key.
        domain: Working photometric domain.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).

    Returns:
        tuple: Revision token, feedback, cleared tilt line, switch off.
    """
    if not n_clicks:
        raise PreventUpdate
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        return no_update, status_alert(
            "Load a lightcurve first.", "warning"
        ), no_update, no_update, no_update
    try:
        lcd = _cached_lcd(user_tab_id)
        payload = copy_working_as_residual(
            lcd, domain=domain, t_min=t_min, t_max=t_max
        )
        write_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB, payload)
    except Exception as exc:
        logger.exception("Copy from plot 1 failed")
        return (
            no_update,
            status_alert(str(exc), "warning"),
            no_update,
            no_update,
            no_update,
        )
    n_finite = sum(1 for v in payload["residual"] if v is not None)
    return (
        _bump_lc_revision(),
        status_alert(f"Copied {n_finite} point(s) from plot 1.", "info"),
        None,
        False,
        dict(WORKING_WINDOW_DISABLED),
    )


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Output("store-lc-processor-tilt-line", "data", allow_duplicate=True),
    Output("lc-processor-local-tilt", "value", allow_duplicate=True),
    Input("lc-processor-apply-tilt", "n_clicks"),
    State("store-lc-processor-tilt-line", "data"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-time-axis", "value"),
    State("store-lc-processor-plot2-window", "data"),
    prevent_initial_call=True,
)
def apply_plot_2_local_tilt(
    n_clicks, tilt_line, user_tab_id, time_axis_mode, plot2_window
):
    """Applies the dashed tilt line to the seeded plot-2 series.

    Args:
        n_clicks: Apply-local-tilt clicks.
        tilt_line: Clientside line ``{x0, y0, x1, y1, ready}``.
        user_tab_id: Session cache key.
        time_axis_mode: ``mjd`` or ``date``.
        plot2_window: Working range from Use visible range.

    Returns:
        tuple: Revision token, feedback, cleared line, switch off.
    """
    if not n_clicks:
        raise PreventUpdate
    if not tilt_line or not tilt_line.get("ready"):
        return no_update, status_alert(
            "Click plot 2 once to place a tilt line, then Apply local tilt.",
            "warning",
        ), no_update, no_update
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        raise PreventUpdate
    try:
        current = read_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB)
        updated = apply_local_tilt(
            current,
            anchor_a=(tilt_line["x0"], tilt_line["y0"]),
            anchor_b=(tilt_line["x1"], tilt_line["y1"]),
            time_axis_mode=normalize_time_axis_mode(time_axis_mode),
            display_epoch=DISPLAY_EPOCH_JD,
            jd_bounds=observation_jd_bounds_tuple(
                normalize_working_window(plot2_window)
            ),
        )
        write_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB, updated)
    except Exception as exc:
        logger.exception("Local tilt failed")
        return (
            no_update,
            status_alert(str(exc), "warning"),
            no_update,
            no_update,
        )
    n_hit = int((updated.get("tilts") or [{}])[-1].get("n_updated") or 0)
    return (
        _bump_lc_revision(),
        status_alert(f"Local tilt applied to {n_hit} point(s).", "info"),
        None,
        False,
    )


@callback(
    Output("store-lc-processor-plot2-window", "data"),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-use-visible-range", "n_clicks"),
    State("lc-processor-graph-residual", "relayoutData"),
    State("lc-processor-time-axis", "value"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def use_plot_2_visible_range(n_clicks, relayout_data, time_axis_mode, user_tab_id):
    """Locks plot 2 to the current zoom, as on the GP prep plot.

    Args:
        n_clicks: Button clicks.
        relayout_data: Plot-2 ``relayoutData``.
        time_axis_mode: ``mjd`` or ``date``.
        user_tab_id: Session cache key.

    Returns:
        tuple: Working-window store and feedback.
    """
    if not n_clicks:
        raise PreventUpdate
    payload = (
        read_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB)
        if user_tab_id
        else None
    )
    if not payload:
        return no_update, status_alert(
            "Seed plot 2 first: Apply detrend or Copy from plot 1.",
            "warning",
        )
    try:
        jd_min, jd_max = jd_bounds_from_visible_plot(
            relayout_data,
            time_axis_mode=normalize_time_axis_mode(time_axis_mode),
            display_epoch=DISPLAY_EPOCH_JD,
        )
        store_payload = build_working_window_store_from_times(
            jd_min, jd_max, np.asarray(payload["jd"], dtype=float)
        )
    except PipeException as exc:
        return no_update, status_alert(str(exc), "warning")
    if store_payload.get("enabled"):
        note = status_alert("Plot 2 now uses this time range only.", "info")
    else:
        note = status_alert(
            "Visible range covers the full plot-2 series; working range cleared.",
            "info",
        )
    return store_payload, note


@callback(
    Output("store-lc-processor-plot2-window", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-restore-plot-2", "n_clicks"),
    prevent_initial_call=True,
)
def restore_full_plot_2(n_clicks):
    """Clears the plot-2 working range.

    Args:
        n_clicks: Button clicks.

    Returns:
        tuple: Disabled working-window store and feedback.
    """
    if not n_clicks:
        raise PreventUpdate
    return (
        dict(WORKING_WINDOW_DISABLED),
        status_alert("Full plot 2 restored.", "info"),
    )


@callback(
    Output("lc-processor-plot2-window-status", "children"),
    Input("store-lc-processor-plot2-window", "data"),
    Input("lc-processor-time-axis", "value"),
)
def describe_plot_2_window(plot2_window, time_axis_mode):
    """Shows whether plot 2 uses the full series or a working range.

    Args:
        plot2_window: Working-range store.
        time_axis_mode: ``mjd`` or ``date``.

    Returns:
        str: Status sentence.
    """
    window = normalize_working_window(plot2_window)
    if window is None:
        return "Working range: full plot 2"
    start_label, end_label = format_interval_display_pair(
        window["jd_min"],
        window["jd_max"],
        time_axis_mode=normalize_time_axis_mode(time_axis_mode),
        display_epoch=DISPLAY_EPOCH_JD,
    )
    return f"Working range: {start_label} – {end_label}"


@callback(
    Output("store-lc-processor-plot2-window", "data", allow_duplicate=True),
    Input("store-lc-processor-lc-revision", "data"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def clear_plot2_window_when_empty(_revision, user_tab_id):
    """Drops the working range when plot 2 has been cleared.

    Args:
        _revision: Plot revision token.
        user_tab_id: Session cache key.

    Returns:
        dict: Disabled working-window store.
    """
    if user_tab_id and read_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB):
        raise PreventUpdate
    return dict(WORKING_WINDOW_DISABLED)


@callback(
    Output("lc-processor-graph-residual", "config"),
    Input("lc-processor-local-tilt", "value"),
)
def update_residual_graph_config(tilt_on):
    """Enables shape dragging on plot 2 while Local tilt is on.

    Args:
        tilt_on: Place-tilt-line switch.

    Returns:
        dict: Plotly config dictionary.
    """
    return residual_graph_config(tilt_on=bool(tilt_on))


@callback(
    Output("lc-processor-local-tilt", "value", allow_duplicate=True),
    Input("store-lc-processor-lc-revision", "data"),
    State("store-lc-processor-user-tab-id", "data"),
    prevent_initial_call=True,
)
def clear_local_tilt_when_plot_2_empty(_revision, user_tab_id):
    """Turns the tilt switch off when plot 2 has been cleared.

    Args:
        _revision: Plot revision token.
        user_tab_id: Session cache key.

    Returns:
        bool: ``False`` when there is no residual blob.
    """
    if user_tab_id and read_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB):
        raise PreventUpdate
    return False


@callback(
    Output("lc-processor-download-detrended", "data"),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-download-detrended-btn", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-detrend-export-format", "value"),
    State("lc-processor-detrend-export-stem", "value"),
    State("lc-processor-input-period", "value"),
    State("lc-processor-input-epoch", "value"),
    prevent_initial_call=True,
)
def download_detrended_lightcurve(
    n_clicks,
    user_tab_id,
    table_format,
    stem,
    period,
    epoch,
):
    """Exports the current plot-2 series (detrend, copy, and local tilts).

    Args:
        n_clicks: Button clicks.
        user_tab_id: Session cache key.
        table_format: Export format id.
        stem: Detrended stem (already ``_detrended`` by default).
        period: Sidebar period, or empty.
        epoch: Sidebar epoch as display MJD, or empty.

    Returns:
        tuple: Download payload and optional alert.
    """
    if not n_clicks or not user_tab_id:
        raise PreventUpdate
    payload = read_page_blob(PAGE_NAMESPACE, user_tab_id, DETREND_BLOB)
    if not payload:
        raise PreventUpdate
    try:
        lcd = _cached_lcd(user_tab_id)
        apply_export_ephemeris(
            lcd, period, epoch, display_epoch=DISPLAY_EPOCH_JD
        )
        residual_err = payload.get("residual_err")
        lcd.replace_series(
            np.asarray(payload["jd"], dtype=float),
            np.asarray(payload["residual"], dtype=float),
            None if residual_err is None else np.asarray(residual_err, dtype=float),
            domain=payload.get("domain") or lcd.active_domain,
        )
        fmt = table_format or DEFAULT_EXPORT_FORMAT
        outfile = lc_export_download_name(
            suggested_detrended_export_stem(stem), fmt
        )
        blob = export_curvedash(lcd, fmt)
        return dcc.send_bytes(blob, outfile), None
    except PipeException as exc:
        return no_update, status_alert(str(exc), "warning")
    except Exception as exc:
        logger.exception("Lightcurve processor detrend export failed")
        return no_update, status_alert(str(exc), "warning")


@callback(
    Output("store-lc-processor-lc-revision", "data", allow_duplicate=True),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-find-extrema", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-method", "value"),
    State("lc-processor-domain", "value"),
    State("lc-processor-t-min", "value"),
    State("lc-processor-t-max", "value"),
    State("lc-processor-extremum-kind", "value"),
    State("lc-processor-min-peak-distance", "value"),
    State("lc-processor-min-segment-points", "value"),
    State("lc-processor-interval-delta", "value"),
    prevent_initial_call=True,
)
def find_rough_extrema(
    n_clicks,
    user_tab_id,
    method,
    domain,
    t_min,
    t_max,
    extremum_kind,
    min_distance,
    min_segment_points,
    interval_delta,
):
    """Marks rough extrema on the last matching Apply-smooth overlay.

    Args:
        n_clicks: Find-extrema clicks.
        user_tab_id: Session cache key.
        method: Active smooth method id.
        domain: Working photometric domain.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).
        extremum_kind: ``min`` or ``max``.
        min_distance: Minimum peak separation (days).
        min_segment_points: Finite overlay samples required in a run.
        interval_delta: Interval half-width stored with the find (days).

    Returns:
        tuple: Revision token and optional feedback.
    """
    if not n_clicks:
        raise PreventUpdate
    if not user_tab_id or not has_cached_lc(PAGE_NAMESPACE, user_tab_id):
        return no_update, status_alert("Load a light curve first.", "warning")
    try:
        lcd = _cached_lcd(user_tab_id)
        times, _y, _e, _perm, _labels = cropped_series(lcd, t_min, t_max)
        payload = find_extrema_from_smooth(
            read_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB),
            times,
            domain=lcd.active_domain or domain,
            method=method,
            extremum_kind=extremum_kind,
            min_distance_d=required_float(min_distance, "Min. peak distance"),
            min_segment_points=required_int(
                min_segment_points, "Min. points in segment"
            ),
            delta_time_d=required_float(interval_delta, "Interval half-width"),
        )
        write_page_blob(PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB, payload)
    except Exception as exc:
        logger.exception("Rough extrema find failed")
        return no_update, status_alert(str(exc), "warning")
    n_hit = int(payload.get("n_extrema") or 0)
    n_skipped = int(payload.get("n_skipped_short") or 0)
    kind = payload.get("kind") or "min"
    noun = "minimum" if kind == "min" else "maximum"
    plural = "minima" if kind == "min" else "maxima"
    skip_txt = (
        f" Skipped {n_skipped} short segment(s)." if n_skipped else ""
    )
    if n_hit == 0:
        return _bump_lc_revision(), status_alert(
            f"No rough {plural} found.{skip_txt}", "warning"
        )
    median_d = payload.get("median_interval_d")
    median_txt = (
        f" Median interval {median_d:.6f} d." if median_d is not None else ""
    )
    label = noun if n_hit == 1 else plural
    return _bump_lc_revision(), status_alert(
        f"Found {n_hit} rough {label}.{median_txt}{skip_txt}", "info"
    )


@callback(
    Output("lc-processor-download-intervals", "data"),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-download-intervals-btn", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-intervals-export-stem", "value"),
    State("store-lc-processor-ui", "data"),
    State("lc-processor-upload-lc", "filename"),
    State("store-lc-processor-intervals", "data"),
    prevent_initial_call=True,
)
def download_rough_intervals(
    n_clicks, user_tab_id, stem, ui_store, upload_filename, intervals_store
):
    """Exports surviving stored intervals sorted by start JD.

    Does not regenerate from extrema; exports the interval Store as held.

    Args:
        n_clicks: Button clicks.
        user_tab_id: Session cache key.
        stem: Intervals stem (already ``_int`` by default).
        ui_store: Session UI chrome (source filename).
        upload_filename: Live upload component filename, if any.
        intervals_store: Intervals Store payload.

    Returns:
        tuple: Download payload and optional alert.
    """
    if not n_clicks or not user_tab_id:
        raise PreventUpdate
    filename = _ui_source_filename(ui_store) or upload_filename
    try:
        content = format_cached_intervals_download(
            intervals_store,
            source_file=filename,
            smooth_payload=read_page_blob(
                PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB
            ),
            extrema_payload=read_page_blob(
                PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB
            ),
        )
        outfile = intervals_export_download_name(
            suggested_intervals_export_stem(stem)
        )
        return dcc.send_string(content, outfile), None
    except Exception as exc:
        logger.exception("Lightcurve processor intervals export failed")
        return no_update, status_alert(str(exc), "warning")


@callback(
    Output("lc-processor-download-toms", "data"),
    Output("lc-processor-plot-alert", "children", allow_duplicate=True),
    Input("lc-processor-download-toms-btn", "n_clicks"),
    State("store-lc-processor-user-tab-id", "data"),
    State("lc-processor-toms-export-stem", "value"),
    State("store-lc-processor-ui", "data"),
    State("lc-processor-upload-lc", "filename"),
    prevent_initial_call=True,
)
def download_rough_toms(n_clicks, user_tab_id, stem, ui_store, upload_filename):
    """Exports compact ToM times from the last rough extrema (σ is empty).

    Args:
        n_clicks: Button clicks.
        user_tab_id: Session cache key.
        stem: Timing stem (already ``_rough_toms`` by default).
        ui_store: Session UI chrome (source filename).
        upload_filename: Live upload component filename, if any.

    Returns:
        tuple: Download payload and optional alert.
    """
    if not n_clicks or not user_tab_id:
        raise PreventUpdate
    filename = _ui_source_filename(ui_store) or upload_filename
    try:
        content = format_rough_toms_download(
            read_page_blob(PAGE_NAMESPACE, user_tab_id, EXTREMA_BLOB),
            source_file=filename,
            smooth_payload=read_page_blob(PAGE_NAMESPACE, user_tab_id, SMOOTH_BLOB),
        )
        outfile = rough_toms_export_download_name(
            suggested_rough_toms_export_stem(stem)
        )
        return dcc.send_string(content, outfile), None
    except Exception as exc:
        logger.exception("Lightcurve processor rough ToM export failed")
        return no_update, status_alert(str(exc), "warning")


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
    ClientsideFunction(namespace="lcpSelect", function_name="bindGraph"),
    Output("store-lc-processor-clientside", "data", allow_duplicate=True),
    Input("lc-processor-graph-working", "figure"),
    Input("store-lc-processor-selected-perm", "data"),
    Input("lc-processor-plot-tool", "value"),
    Input("lc-processor-extrema-tool", "value"),
    Input("lc-processor-interval-control", "value"),
    Input("lc-processor-interval-mark-bands", "value"),
    Input("lc-processor-points-control", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpSelect", function_name="mergeSelection"),
    Output("store-lc-processor-selected-perm", "data", allow_duplicate=True),
    Input("lc-processor-graph-working", "selectedData"),
    Input("lc-processor-graph-working", "clickData"),
    State("store-lc-processor-selected-perm", "data"),
    State("lc-processor-plot-tool", "value"),
    State("lc-processor-extrema-tool", "value"),
    State("lc-processor-interval-control", "value"),
    State("lc-processor-interval-mark-bands", "value"),
    State("lc-processor-points-control", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpSelect", function_name="clearSelection"),
    Output("store-lc-processor-selected-perm", "data", allow_duplicate=True),
    Input("lc-processor-unselect", "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpSelect", function_name="captureZoom"),
    Output("store-lc-processor-zoom", "data", allow_duplicate=True),
    Input("lc-processor-graph-working", "relayoutData"),
    State("store-lc-processor-zoom", "data"),
    State("lc-processor-time-axis", "value"),
    State("lc-processor-domain", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpSelect", function_name="invalidateZoom"),
    Output("store-lc-processor-zoom", "data", allow_duplicate=True),
    Input("lc-processor-time-axis", "value"),
    Input("lc-processor-domain", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpKnot", function_name="applyShapes"),
    Output("store-lc-processor-clientside", "data", allow_duplicate=True),
    Input("store-lc-processor-knot-shapes", "data"),
    State("lc-processor-plot-tool", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpExtrema", function_name="bindGraph"),
    Output("store-lc-processor-clientside", "data", allow_duplicate=True),
    Input("lc-processor-graph-working", "figure"),
    Input("lc-processor-extrema-tool", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpInterval", function_name="bindGraph"),
    Output("store-lc-processor-clientside", "data", allow_duplicate=True),
    Input("lc-processor-graph-working", "figure"),
    Input("lc-processor-interval-control", "value"),
    Input("lc-processor-interval-mark-bands", "value"),
    Input("store-lc-processor-interval-bands", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpInterval", function_name="toggleMarks"),
    Output("store-lc-processor-intervals-marked", "data", allow_duplicate=True),
    Input("store-lc-processor-interval-click", "data"),
    State("store-lc-processor-intervals-marked", "data"),
    State("store-lc-processor-interval-bands", "data"),
    State("lc-processor-interval-mark-bands", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpInterval", function_name="clearMarks"),
    Output("store-lc-processor-intervals-marked", "data", allow_duplicate=True),
    Input("lc-processor-clear-interval-marks", "n_clicks"),
    State("store-lc-processor-interval-bands", "data"),
    State("store-lc-processor-intervals-marked", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpInterval", function_name="reflectMarkedCount"),
    Output("lc-processor-remove-marked-intervals", "disabled"),
    Output("lc-processor-clear-interval-marks", "disabled"),
    Input("store-lc-processor-intervals-marked", "data"),
)

clientside_callback(
    ClientsideFunction(namespace="lcpTilt", function_name="applyMode"),
    Output("lc-processor-tilt-actions", "className"),
    Input("lc-processor-local-tilt", "value"),
)

clientside_callback(
    ClientsideFunction(namespace="lcpTilt", function_name="bindGraph"),
    Output("store-lc-processor-clientside", "data", allow_duplicate=True),
    Input("lc-processor-graph-residual", "figure"),
    Input("lc-processor-local-tilt", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpTilt", function_name="processClick"),
    Output("store-lc-processor-tilt-line", "data"),
    Input("store-lc-processor-tilt-click", "data"),
    State("lc-processor-local-tilt", "value"),
    State("store-lc-processor-tilt-line", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpTilt", function_name="clearLine"),
    Output("store-lc-processor-tilt-line", "data", allow_duplicate=True),
    Input("lc-processor-clear-tilt", "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="lcpTilt", function_name="restoreLine"),
    Output("store-lc-processor-clientside", "data", allow_duplicate=True),
    Input("lc-processor-graph-residual", "figure"),
    Input("store-lc-processor-tilt-line", "data"),
    State("lc-processor-local-tilt", "value"),
    prevent_initial_call=True,
)
