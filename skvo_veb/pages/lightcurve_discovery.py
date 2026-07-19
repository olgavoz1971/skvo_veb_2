"""Lightcurve Discovery — multi-mission catalogue search and lightcurve workflow.

See ``docs/mission_lightcurve_providers.md`` for architecture.
Styles: ``assets/lc_discovery.css``.
"""

import logging
import uuid

import aladin_lite_react_component
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import plotly.express as px
from dash import Input, Output, State, callback, clientside_callback, ctx, dash, dcc, html, no_update, register_page, set_props
from dash.dependencies import ClientsideFunction
from dash.exceptions import PreventUpdate

from skvo_veb.components import message
from skvo_veb.logging_config import configure_logging
from skvo_veb.lc_providers.registry import list_missions
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import apply_phot_domain_view, export_curvedash, export_file_extension
from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD,
    DEFAULT_EXPORT_FORMAT,
    DOMAIN_FLUX,
    DOMAIN_MAG,
    EXPORT_FORMAT_OPTIONS,
    TIME_AXIS_DATE,
    TIME_AXIS_MJD,
    display_epoch_offset,
)
from skvo_veb.utils.lc_discovery_aladin import (
    aladin_fov_degrees,
    aladin_marker_name,
    aladin_remount_key,
    aladin_selected_star_from_row,
    aladin_target_from_metadata,
    catalog_row_from_cell_clicked,
    catalog_rows_to_aladin_stars,
    find_catalog_row_by_aladin_name,
)
from skvo_veb.utils.lc_discovery_load import (
    catalog_row_for_lc_key,
    curvedash_from_catalog_row,
    discovery_export_basename,
    mission_id_from_lc_key,
)
from skvo_veb.utils.lc_discovery_search import (
    catalog_results_header,
    catalog_rows_for_aggrid,
    run_catalog_search_for_mission,
)
from skvo_veb.utils.lc_discovery_time_bounds import parse_discovery_time_bounds
from skvo_veb.utils.lc_figure import figure_from_serialized
from skvo_veb.utils.lc_interaction import (
    apply_plot_point_selection,
    clear_plot_point_selection,
    delete_selected_rows,
)
from skvo_veb.utils.lc_session_cache import (
    generate_user_tab_id,
    has_cached_lc,
    read_serialized_lc,
    write_serialized_lc,
)
from skvo_veb.utils.my_tools import PipeException, float_pattern, positive_float_pattern, safe_float
from skvo_veb.utils.page_session import SESSION_STORE

configure_logging()

logger = logging.getLogger(__name__)

register_page(
    __name__,
    name='Lightcurve Discovery',
    order=3,
    path='/lc_discovery',
    title='IGEBC: Lightcurve Discovery',
    in_navbar=True,
)

stack_wrap_style = {'marginBottom': '5px', 'flexWrap': 'wrap'}
mission_label_style = {'display': 'block', 'padding': '2px'}
label_font_size = '0.8em'
switch_label_style_vert = {'display': 'block', 'padding': '2px', 'font-size': label_font_size}
row_class_name = 'd-flex g-2 justify-content-end align-items-end'

LC_DISCOVERY_PAGE_NAMESPACE = 'lc_discovery'
DISPLAY_EPOCH_JD = DEFAULT_EPOCH_JD

LC_DISCOVERY_CATALOG_COLUMNS = [
    {
        'field': 'distance_arcsec',
        'headerName': 'Sep (″)',
        'type': 'numericColumn',
        'sortable': True,
        'minWidth': 55,
        'maxWidth': 100,
        # 'suppressSizeToFit': True,
    },
    {
        'field': 'object_name',
        'headerName': 'Object',
        'sortable': True,
        'minWidth': 200,
    },
    {
        'field': 'filter_name',
        'headerName': 'Filter',
        'sortable': True,
        'minWidth': 80,
        # 'maxWidth': 96,
        'suppressSizeToFit': True,
    },
    {
        'field': 'ra_deg',
        'headerName': 'RA',
        'type': 'numericColumn',
        'sortable': True,
        # 'width': 88,
        'minWidth': 90,
        'suppressSizeToFit': True,
    },
    {
        'field': 'dec_deg',
        'headerName': 'Dec',
        'type': 'numericColumn',
        'sortable': True,
        # 'width': 88,
        'minWidth': 90,
        'suppressSizeToFit': True,
    },
    {
        'field': 't_min',
        'headerName': 't_min',
        'type': 'numericColumn',
        'sortable': True,
        # 'width': 68,
        'minWidth': 70,
        'suppressSizeToFit': True,
    },
    {
        'field': 't_max',
        'headerName': 't_max',
        'type': 'numericColumn',
        'sortable': True,
        # 'width': 68,
        'minWidth': 70,
        'suppressSizeToFit': True,
    },
    
    {
        'field': 'n_points',
        'headerName': 'N',
        'type': 'numericColumn',
        'sortable': True,
        'width': 52,
        'maxWidth': 60,
        'suppressSizeToFit': True,
    },
]

LC_DISCOVERY_CATALOG_DEFAULT_COL_DEF = {
    'filter': False,
    'floatingFilter': False,
    'sortable': True,
    'unSortIcon': True,
    'suppressHeaderFilterButton': True,
    'suppressHeaderMenuButton': True,
    'resizable': True,
    'wrapText': False,
    'autoHeight': False,
}

LC_DISCOVERY_RADIUS_UNIT_OPTIONS = [
    {'label': 'arcsec', 'value': 'arcsec'},
    {'label': 'arcmin', 'value': 'arcmin'},
    {'label': 'deg', 'value': 'deg'},
]

LC_DISCOVERY_TIME_FORMAT_OPTIONS = [
    {'label': 'MJD', 'value': 'mjd'},
    {'label': 'JD', 'value': 'jd'},
    {'label': 'Date', 'value': 'date'},
]

LC_DISCOVERY_TIME_MIN_PLACEHOLDER_MJD = 'Earliest MJD (optional)'
LC_DISCOVERY_TIME_MAX_PLACEHOLDER_MJD = 'Latest MJD (optional)'

_LC_DISCOVERY_CATALOG_HEADER_DEFAULT = 'Submit a query to list available lightcurves'
_LC_DISCOVERY_SEARCH_STATUS_STYLE_HIDDEN = {'display': 'none'}
_LC_DISCOVERY_SEARCH_STATUS_STYLE_VISIBLE = {'display': 'block'}
_LC_DISCOVERY_ALADIN_WIDTH = 400
_LC_DISCOVERY_ALADIN_HEIGHT = 400


def _lc_discovery_aladin_placeholder(message: str):
    """Builds the empty-state content shown before catalogue markers exist.

    Args:
        message (str): User-facing placeholder text.

    Returns:
        html.P: Placeholder element for the Aladin container.
    """
    return html.P(message, className='lc-discovery-aladin-empty text-muted mb-0')


def _build_lc_discovery_aladin_view(row_data, search_metadata):
    """Builds a fresh Aladin instance with catalogue markers applied at mount time.

    The bundled ``aladin_lite_react_component`` package only loads ``stars`` during
    its initial script load; updating the prop later is a no-op. Remounting via a
    changing React ``key`` matches the legacy query-by-coordinates page behaviour.

    Args:
        row_data (list[dict]): Current AgGrid catalogue rows.
        search_metadata (dict, optional): Serialised search outcome metadata.

    Returns:
        dash.html components: Aladin view or an empty-state placeholder.
    """
    if not row_data:
        return _lc_discovery_aladin_placeholder(
            'Submit a query to show sources on the sky map.'
        )

    stars = catalog_rows_to_aladin_stars(row_data)
    if not stars:
        return _lc_discovery_aladin_placeholder(
            'No sky coordinates are available for these catalogue rows.'
        )

    return html.Div(
        key=aladin_remount_key(search_metadata, row_data),
        children=[
            aladin_lite_react_component.AladinLiteReactComponent(
                id='lc_discovery_aladin',
                width=_LC_DISCOVERY_ALADIN_WIDTH,
                height=_LC_DISCOVERY_ALADIN_HEIGHT,
                fov=aladin_fov_degrees(search_metadata, row_data),
                target=aladin_target_from_metadata(search_metadata, row_data),
                stars=stars,
            ),
        ],
        className='lc-discovery-aladin-wrap',
    )


def _mission_radio_options():
    """Builds mission radio options from the provider registry.

    Returns:
        list[dict]: Dash ``RadioItems`` options for registered missions.
    """
    return [
        {'label': mission.display_name, 'value': mission.mission_id}
        for mission in list_missions()
    ]


def _default_mission_id():
    """Returns the default selected mission slug for the Search tab.

    Returns:
        str: First registered mission id, or empty string when none are registered.
    """
    missions = list_missions()
    return missions[0].mission_id if missions else ''


def _click_help(help_id: str, title: str, body, *, placement: str = 'bottom'):
    """Builds a click-triggered ``?`` control and its popover.

    Args:
        help_id (str): Short slug used to build unique component ids.
        title (str): Popover header text.
        body: Popover body as a string or sequence of Dash components.
        placement (str): Bootstrap popover placement.

    Returns:
        tuple: ``(help_button, popover)`` components.
    """
    btn_id = f'lc_discovery_help_{help_id}_btn'
    pop_id = f'lc_discovery_help_{help_id}_popover'
    if not isinstance(body, (list, tuple)):
        body = [html.P(body, className='mb-0')]
    button = html.Strong(
        '?',
        id=btn_id,
        role='button',
        tabIndex=0,
        className='lc-discovery-help-btn',
        **{'aria-label': f'Help: {title}'},
    )
    popover = dbc.Popover(
        [
            dbc.PopoverHeader(title),
            dbc.PopoverBody(body),
        ],
        id=pop_id,
        target=btn_id,
        trigger='legacy',
        placement=placement,
        className='lc-discovery-help-popover',
    )
    return button, popover


def _time_bound_field_row(bound: str):
    """Builds one optional time-bound row (input, format selector, help).

    Args:
        bound (str): ``min`` or ``max`` — selects component ids and help copy.

    Returns:
        tuple: ``(field_row_div, help_popover)`` for the Search tools stack.
    """
    is_min = bound == 'min'
    input_id = f'lc_discovery_time_{bound}_input'
    format_id = f'lc_discovery_time_{bound}_format_select'
    default_placeholder = (
        LC_DISCOVERY_TIME_MIN_PLACEHOLDER_MJD
        if is_min
        else LC_DISCOVERY_TIME_MAX_PLACEHOLDER_MJD
    )
    help_title = 'Earliest time' if is_min else 'Latest time'
    help_body = [
        html.P(
            'Optional limit on the lightcurve epoch span returned by the catalogue '
            'search. Leave this field blank for an open bound.',
            className='mb-2',
        ),
        html.P(
            'Blank earliest time means no lower limit (include all data from the '
            'beginning). Blank latest time means no upper limit (include all data '
            'to the end). You may set either bound alone — for example, only a '
            'latest time returns all lightcurves earlier than that epoch.',
            className='mb-2',
        ),
        html.P(
            'Provider searches always receive these limits in MJD after conversion '
            'from the selected format below.',
            className='mb-2',
        ),
        html.P('Supported formats:', className='mb-1'),
        html.Ul(
            [
                html.Li('MJD — modified Julian date (default), e.g. 57123.45'),
                html.Li('JD — Julian date, e.g. 2457123.45'),
                html.Li('Date — calendar date (UTC), e.g. 2015-06-01'),
            ],
            className='mb-0 ps-3',
        ),
    ]
    help_btn, help_pop = _click_help(f'time_{bound}', help_title, help_body)
    field_row = html.Div(
        [
            dcc.Input(
                id=input_id,
                persistence=True,
                type='search',
                inputMode='numeric',
                placeholder=default_placeholder,
                className='lc-discovery-field-input',
            ),
            dbc.Select(
                id=format_id,
                options=LC_DISCOVERY_TIME_FORMAT_OPTIONS,
                value='mjd',
                persistence=True,
                className='lc-discovery-field-unit',
            ),
            html.Div(help_btn, className='lc-discovery-field-help'),
        ],
        className='lc-discovery-field-row lc-discovery-field-row-time',
    )
    return field_row, help_pop


def _resolved_target_card():
    """Builds the resolved-target summary card (hidden until a search resolves the target).

    Returns:
        dash_bootstrap_components.Card: Card with a Markdown body updated by search callbacks.
    """
    return dbc.Card(
        dbc.CardBody(
            dcc.Markdown(
                '',
                id='lc_discovery_object_card_markdown',
                className='lc-discovery-object-markdown mb-0',
                mathjax=True,
            ),
            className='py-2 px-3',
        ),
        id='lc_discovery_object_card',
        className='lc-discovery-object-card mb-2',
        style={'display': 'none'},
    )


def _search_tools_panel():
    """Builds the Search tab tools column (query + mission selector).

    Returns:
        dash_bootstrap_components.Col: Responsive grey tools panel.
    """
    target_help_btn, target_help_pop = _click_help(
        'target',
        'Target',
        [
            html.P(
                'Enter an object name or sky position in a form understood by '
                'Astropy (and typically Simbad). Examples:',
            ),
            html.Ul(
                [
                    html.Li('Catalogue name: V* DP Peg, TIC 123456789'),
                    html.Li('Sexagesimal: 12 34 56 +07 08 09'),
                    html.Li('Decimal degrees (ICRS): 189.23 -12.45'),
                ],
                className='mb-0 ps-3',
            ),
        ],
    )
    time_min_row, time_min_help = _time_bound_field_row('min')
    time_max_row, time_max_help = _time_bound_field_row('max')
    radius_help_btn, radius_help_pop = _click_help(
        'radius',
        'Search radius',
        [
            html.P(
                'Cone search: catalogue rows within this radius of the search '
                'centre are returned. The centre comes from Target when you enter '
                'sky coordinates (ICRS), or from Simbad when a name resolves to '
                'a position.',
                className='mb-2',
            ),
            html.P(
                'Not used when the provider matches Target directly by object name '
                'or mission archive identifier (for example, a Gaia DR3 source_id). '
                'In those cases the search goes straight to that object.',
                className='mb-0',
            ),
        ],
    )
    return dbc.Col(
        [
            html.Div(
                [
                    html.Div(
                        [
                            dbc.Label(
                                'Target',
                                html_for='lc_discovery_target_input',
                                className='lc-discovery-field-label',
                            ),
                            dcc.Input(
                                id='lc_discovery_target_input',
                                persistence=True,
                                type='search',
                                placeholder='Name or coordinates (ICRS)',
                                className='lc-discovery-field-input lc-discovery-field-input-wide',
                            ),
                            html.Div(target_help_btn, className='lc-discovery-field-help'),
                        ],
                        className='lc-discovery-field-row lc-discovery-field-row-target',
                    ),
                    html.Div(
                        [
                            dcc.Input(
                                id='lc_discovery_radius_input',
                                persistence=True,
                                type='search',
                                inputMode='numeric',
                                value='2',
                                pattern=positive_float_pattern,
                                placeholder='Search radius',
                                className='lc-discovery-field-input',
                            ),
                            dbc.Select(
                                id='lc_discovery_radius_unit_select',
                                options=LC_DISCOVERY_RADIUS_UNIT_OPTIONS,
                                value='arcsec',
                                persistence=True,
                                className='lc-discovery-field-unit',
                            ),
                            html.Div(radius_help_btn, className='lc-discovery-field-help'),
                        ],
                        className='lc-discovery-field-row lc-discovery-field-row-time',
                    ),
                    time_min_row,
                    time_max_row,
                ],
                className='lc-discovery-field-stack',
            ),
            dbc.Stack(
                [
                    dbc.Button(
                        'Submit query',
                        id='lc_discovery_submit_query_button',
                        size='sm',
                        color='primary',
                    ),
                    dbc.Button(
                        'Cancel',
                        id='lc_discovery_cancel_query_button',
                        size='sm',
                        disabled=True,
                    ),
                ],
                direction='horizontal',
                gap=2,
                className='lc-discovery-submit-actions',
            ),
            html.Div(
                '',
                id='lc_discovery_search_status',
                className='lc-discovery-search-status',
                style=_LC_DISCOVERY_SEARCH_STATUS_STYLE_HIDDEN,
            ),
            target_help_pop,
            radius_help_pop,
            time_min_help,
            time_max_help,
            _resolved_target_card(),
            html.Div(
                id='lc_discovery_search_tools_alert',
                style={'display': 'none', 'marginTop': '8px'},
            ),
            html.Hr(className='my-2'),
            html.Details(
                [
                    html.Summary('Data provider'),
                    dcc.RadioItems(
                        id='lc_discovery_mission_switch',
                        options=_mission_radio_options(),
                        value=_default_mission_id(),
                        persistence=True,
                        labelStyle=mission_label_style,
                        style={'marginTop': '8px'},
                    ),
                    html.P(
                        'Additional missions appear here as providers are registered.',
                        className='text-muted',
                        style={'marginTop': '8px', 'marginBottom': 0},
                    ),
                ],
                open=True,
            ),
        ],
        lg=3,
        md=4,
        sm=5,
        xs=12,
        style={'padding': '10px', 'background': 'Silver', 'border-radius': '5px'},
    )


def _search_results_panel():
    """Builds the Search tab catalog results column.

    Returns:
        dash_bootstrap_components.Col: Responsive white results panel with AgGrid.
    """
    catalog_help_btn, catalog_help_pop = _click_help(
        'catalog_results',
        'Catalogue results',
        [
            html.P(
                'Each row is one lightcurve product you can load — typically one '
                'object in one filter passband (mission-specific splits apply, '
                'e.g. TESS sectors).',
                className='mb-2',
            ),
            html.P(
                'The layout follows IVOA Simple Spectral Access (SSA) and ObsCore '
                'ideas: one row equals one data product. You do not need to know '
                'those standards to use this page.',
                className='mb-2',
            ),
            html.P(
                'Columns t_min and t_max give the time coverage of each product in '
                'MJD (ObsCore-style names). They may be empty when the archive '
                'does not report a span.',
                className='mb-0',
            ),
        ],
    )
    return dbc.Col(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.H3(
                                                _LC_DISCOVERY_CATALOG_HEADER_DEFAULT,
                                                id='lc_discovery_catalog_header',
                                                className='fs-6 mb-0 lc-discovery-catalog-title',
                                            ),
                                            html.Div(
                                                catalog_help_btn,
                                                className='lc-discovery-field-help',
                                            ),
                                        ],
                                        className='lc-discovery-catalog-title-row',
                                    ),
                                    dbc.Stack(
                                        [
                                            dbc.Button(
                                                'Download',
                                                id='lc_discovery_fetch_button',
                                                size='sm',
                                                className='me-2',
                                            ),
                                            dbc.Button(
                                                'reDownload',
                                                id='lc_discovery_refetch_button',
                                                size='sm',
                                                outline=True,
                                                color='warning',
                                                className='me-2',
                                            ),
                                            dbc.Button(
                                                'Cancel',
                                                id='lc_discovery_cancel_fetch_button',
                                                size='sm',
                                                disabled=True,
                                            ),
                                        ],
                                        direction='horizontal',
                                        gap=2,
                                    ),
                                ],
                                style={
                                    'display': 'flex',
                                    'justifyContent': 'space-between',
                                    'alignItems': 'center',
                                    'width': '100%',
                                },
                            ),
                        ],
                        className='lc-discovery-catalog-header-row',
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                html.Div(
                                    dag.AgGrid(
                                        id='lc_discovery_catalog_table',
                                        columnDefs=LC_DISCOVERY_CATALOG_COLUMNS,
                                        rowData=[],
                                        columnSize='autoSize',
                                        defaultColDef=LC_DISCOVERY_CATALOG_DEFAULT_COL_DEF,
                                        dashGridOptions={
                                            'theme': 'themeBalham',
                                            # 'rowHeight': 22,
                                            # 'headerHeight': 24,
                                            'rowSelection': {
                                                'mode': 'singleRow',
                                                'checkboxes': False,
                                                # 'enableClickSelection': True,
                                            },
                                            'animateRows': False,
                                            'pagination': False,
                                            # 'paginationPageSize': 10,
                                            'domLayout': 'normal',
                                            'suppressHorizontalScroll': False,
                                            # 'alwaysShowHorizontalScroll': True,
                                            'enableCellTextSelection': True,
                                            # 'ensureDomOrder': True,
                                            'getRowId': {
                                                'function': 'params.data.lc_key'
                                            },
                                        },
                                        className='lc-discovery-catalog-aggrid ag-theme-balham',
                                        style={'height': '100%', 'width': '100%'},
                                    ),
                                    className='lc-discovery-catalog-grid',
                                ),
                                lg=7,
                                md=7,
                                sm=12,
                                xs=12,
                            ),
                            dbc.Col(
                                [
                                    html.Div(
                                        _lc_discovery_aladin_placeholder(
                                            'Submit a query to show sources on the sky map.'
                                        ),
                                        id='lc_discovery_aladin_container',
                                        className='lc-discovery-aladin-wrap',
                                    ),
                                    html.P(
                                        'Click a table row to highlight the object on the map, '
                                        'and vice versa.',
                                        className='lc-discovery-aladin-hint text-muted mb-0',
                                    ),
                                ],
                                lg=5,
                                md=5,
                                sm=12,
                                xs=12,
                                className='lc-discovery-aladin-col',
                            ),
                        ],
                        className='g-2 lc-discovery-catalog-body-row',
                    ),
                ],
                id='lc_discovery_catalog_row',
            ),
            html.Div(id='lc_discovery_search_alert', style={'display': 'none'}),
            dbc.Label(
                id='lc_discovery_fetch_status',
                children='',
                style={'color': 'green', 'text-align': 'center'},
            ),
            html.Div(id='lc_discovery_fetch_alert', style={'display': 'none'}),
            catalog_help_pop,
        ],
        lg=9,
        md=8,
        sm=7,
        xs=12,
    )


def _discovery_empty_figure():
    """Returns the initial empty lightcurve figure with lasso selection enabled.

    Returns:
        plotly.graph_objects.Figure: Empty scatter configured for Discovery plotting.
    """
    fig = px.scatter()
    fig.update_traces(
        selected={'marker': {'color': 'orange', 'size': 10}},
        hoverinfo='none',
        hovertemplate=None,
    )
    fig.update_layout(
        xaxis={'title': 'time', 'tickformat': '.1f'},
        yaxis_title='flux',
        margin=dict(l=48, b=48, t=24, r=16),
        dragmode='lasso',
        autosize=True,
    )
    return fig


def _display_epoch_value(lcd: CurveDash) -> float:
    """Returns the epoch input value relative to the display epoch.

    Args:
        lcd (CurveDash): Loaded lightcurve.

    Returns:
        float: Epoch offset for the UI input (``0.0`` when no catalogue epoch).
    """
    return display_epoch_offset(lcd.epoch, DISPLAY_EPOCH_JD)


def _bump_lc_revision() -> str:
    """Returns a new revision token to trigger dependent plot callbacks.

    Returns:
        str: UUID string.
    """
    return str(uuid.uuid4())


def _lightcurve_tools_panel():
    """Builds the Light curve tab tools panel (TESS-style left column, ASAS-SN controls).

    Returns:
        dash_bootstrap_components.Col: Responsive grey tools panel.
    """
    return dbc.Col(
        [
            dbc.Label(
                'Light curve tools',
                style={'display': 'flex', 'justify-content': 'center'},
            ),
            dbc.Button(
                'rePlot curve',
                id='lc_discovery_replot_button',
                size='sm',
                disabled=True,
                style={'width': '100%', 'marginBottom': '5px'},
            ),
            dbc.Switch(
                id='lc_discovery_mag_switch',
                label='Magnitude',
                value=False,
                label_style=switch_label_style_vert,
                persistence=False,
                style={'marginBottom': '5px', 'width': '100%'},
            ),
            dcc.RadioItems(
                id='lc_discovery_time_axis_switch',
                options=[
                    {'label': ' MJD', 'value': TIME_AXIS_MJD},
                    {'label': ' Date', 'value': TIME_AXIS_DATE},
                ],
                value=TIME_AXIS_MJD,
                persistence=True,
                labelStyle={
                    'display': 'inline-block',
                    'marginRight': '12px',
                    'font-size': label_font_size,
                },
                inputStyle={'marginRight': '4px'},
                style={'marginBottom': '5px'},
            ),
            html.Details(
                [
                    html.Summary('Folding', style={'font-size': label_font_size}),
                    dbc.Stack(
                        [
                            dbc.Label(
                                'Period:',
                                html_for='lc_discovery_period_input',
                                style={'width': '7em', 'font-size': label_font_size},
                            ),
                            dcc.Input(
                                id='lc_discovery_period_input',
                                type='search',
                                inputMode='numeric',
                                persistence=False,
                                value=None,
                                pattern=positive_float_pattern,
                                style={'width': '100%'},
                            ),
                        ],
                        direction='horizontal',
                        gap=2,
                        style={'width': '100%', 'min-width': '5ch'},
                    ),
                    dbc.Stack(
                        [
                            dbc.Label(
                                f'Epoch-{DISPLAY_EPOCH_JD}:',
                                html_for='lc_discovery_epoch_input',
                                style={'width': '7em', 'font-size': label_font_size},
                            ),
                            dcc.Input(
                                id='lc_discovery_epoch_input',
                                inputMode='numeric',
                                persistence=False,
                                value=0.0,
                                type='search',
                                pattern=float_pattern,
                                style={'width': '100%'},
                            ),
                        ],
                        direction='horizontal',
                        gap=2,
                        style={'width': '100%', 'min-width': '5ch'},
                    ),
                    dbc.Stack(
                        [
                            dbc.Switch(
                                id='lc_discovery_fold_switch',
                                label='Fold',
                                value=False,
                                label_style=switch_label_style_vert,
                                persistence=False,
                                style={'width': '40%'},
                            ),
                            dbc.Button(
                                'Recalc Phase',
                                id='lc_discovery_recalc_phase_button',
                                size='sm',
                                style={'width': '60%', 'marginBottom': '5px'},
                            ),
                        ],
                        direction='horizontal',
                        gap=2,
                    ),
                ],
                open=True,
                style={'marginBottom': '5px'},
            ),
            html.Div(
                [
                    dbc.Label(
                        'Unable to fold; the period is unknown',
                        id='lc_discovery_fold_warning_label',
                        style={'display': 'none'},
                    ),
                ],
                id='lc_discovery_fold_controls',
                style={'min-height': '30px'},
            ),
            dbc.Stack(
                [
                    dbc.Select(
                        options=EXPORT_FORMAT_OPTIONS,
                        value=DEFAULT_EXPORT_FORMAT,
                        id='lc_discovery_export_format_select',
                        style={'width': '40%', 'font-size': label_font_size},
                    ),
                    dbc.Button(
                        'Download',
                        id='lc_discovery_download_button',
                        size='sm',
                        style={'width': '60%'},
                    ),
                ],
                direction='horizontal',
                gap=2,
                style={'width': '100%', 'min-width': '5ch', 'marginBottom': '5px'},
            ),
        ],
        lg=2,
        md=3,
        sm=4,
        xs=12,
        style={'padding': '10px', 'background': 'Silver', 'border-radius': '5px'},
    )


def _lightcurve_graph_panel():
    """Builds the Light curve tab graph and interaction row.

    Returns:
        dash_bootstrap_components.Col: Responsive Plotly graph container.
    """
    return dbc.Col(
        [
            html.Div(id='lc_discovery_plot_alert', style={'display': 'none'}),
            dbc.Row(
                [
                    dcc.Graph(
                        id='lc_discovery_graph',
                        figure=_discovery_empty_figure(),
                        config={
                            'displaylogo': False,
                            'scrollZoom': True,
                            'responsive': True,
                        },
                        className='lc-discovery-graph-wrap',
                        style={'width': '100%'},
                    ),
                ],
                class_name='g-0',
            ),
            dbc.Row(
                [
                    dcc.Markdown(
                        '_**Click on a point to select it, or use Lasso or Box selector**_',
                        style={
                            'font-size': 14,
                            'font-family': 'courier',
                            'marginTop': -10,
                            'marginBottom': 10,
                        },
                    ),
                ],
                class_name=row_class_name,
            ),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Stack(
                                [
                                    dbc.Button(
                                        'Delete selected',
                                        id='lc_discovery_delete_button',
                                    ),
                                    dbc.Button(
                                        'Unselect',
                                        id='lc_discovery_unselect_button',
                                    ),
                                ],
                                direction='horizontal',
                                gap=2,
                            ),
                        ],
                        md=6,
                        sm=12,
                    ),
                ],
                class_name=row_class_name,
            ),
        ],
        lg=10,
        md=9,
        sm=8,
        xs=12,
    )


def layout():
    """Returns the Lightcurve Discovery page layout.

    Returns:
        dash_bootstrap_components.Container: Full page with Search and Light curve tabs.
    """
    return dbc.Container(
        [
            html.H1(
                'Lightcurve Discovery',
                className='text-primary text-left fs-4 fs-md-3 lc-discovery-page-title',
            ),
            html.P(
                [
                    'Cone search across archive missions, then plot and export in one workflow. ',
                    html.Span(
                        'ASAS-SN still has its dedicated page.',
                        className='d-block d-sm-inline',
                    ),
                ],
                className='text-muted lc-discovery-intro',
                style={'marginBottom': '12px'},
            ),
            dbc.Tabs(
                [
                    dbc.Tab(
                        label='Search',
                        tab_id='lc_discovery_search_tab',
                        children=[
                            dbc.Row(
                                [_search_tools_panel(), _search_results_panel()],
                                style={'marginBottom': '10px'},
                            ),
                        ],
                    ),
                    dbc.Tab(
                        label='Light curve',
                        tab_id='lc_discovery_plot_tab',
                        id='lc_discovery_plot_tab',
                        disabled=True,
                        children=[
                            dbc.Row(
                                [_lightcurve_tools_panel(), _lightcurve_graph_panel()],
                                style={'marginBottom': '10px'},
                            ),
                        ],
                    ),
                ],
                active_tab='lc_discovery_search_tab',
                id='lc_discovery_tabs',
                className='lc-discovery-tabs mb-2',
            ),
            dcc.Store(id='store_lc_discovery_user_tab_id', **SESSION_STORE),
            dcc.Store(id='store_lc_discovery_lc_revision', **SESSION_STORE),
            dcc.Store(id='store_lc_discovery_catalog', **SESSION_STORE),
            dcc.Store(id='store_lc_discovery_selected_key', **SESSION_STORE),
            dcc.Store(id='store_lc_discovery_highlight_name', **SESSION_STORE),
            dcc.Store(id='store_lc_discovery_resolved_target', **SESSION_STORE),
            dcc.Download(id='lc_discovery_download'),
        ],
        className='g-10 lc-discovery-page',
        fluid=True,
        style={'display': 'flex', 'flexDirection': 'column'},
    )


@callback(
    Output('lc_discovery_catalog_table', 'rowData'),
    Output('lc_discovery_catalog_header', 'children'),
    Output('lc_discovery_object_card_markdown', 'children'),
    Output('lc_discovery_object_card', 'style'),
    Output('lc_discovery_search_status', 'children'),
    Output('lc_discovery_search_status', 'style'),
    Output('lc_discovery_search_alert', 'children'),
    Output('lc_discovery_search_alert', 'style'),
    Output('store_lc_discovery_catalog', 'data'),
    Output('store_lc_discovery_resolved_target', 'data'),
    Output('store_lc_discovery_highlight_name', 'data'),
    Input('lc_discovery_mission_switch', 'value'),
    prevent_initial_call=True,
)
def clear_catalog_on_mission_change(_mission_id):
    """Clears search results when the mission changes; keeps the Target field text.

    Returns:
        tuple: Empty catalogue outputs and cleared stores.
    """
    return (
        [],
        _LC_DISCOVERY_CATALOG_HEADER_DEFAULT,
        '',
        {'display': 'none'},
        '',
        _LC_DISCOVERY_SEARCH_STATUS_STYLE_HIDDEN,
        None,
        {'display': 'none'},
        None,
        None,
        None,
    )


@callback(
    Output('lc_discovery_catalog_table', 'rowData', allow_duplicate=True),
    Output('lc_discovery_catalog_header', 'children', allow_duplicate=True),
    Output('lc_discovery_object_card_markdown', 'children', allow_duplicate=True),
    Output('lc_discovery_object_card', 'style', allow_duplicate=True),
    Output('lc_discovery_search_status', 'children', allow_duplicate=True),
    Output('lc_discovery_search_status', 'style', allow_duplicate=True),
    Output('lc_discovery_search_alert', 'children', allow_duplicate=True),
    Output('lc_discovery_search_alert', 'style', allow_duplicate=True),
    Output('store_lc_discovery_catalog', 'data', allow_duplicate=True),
    Output('store_lc_discovery_resolved_target', 'data', allow_duplicate=True),
    Input('lc_discovery_submit_query_button', 'n_clicks'),
    State('lc_discovery_mission_switch', 'value'),
    State('lc_discovery_target_input', 'value'),
    State('lc_discovery_radius_input', 'value'),
    State('lc_discovery_radius_unit_select', 'value'),
    State('lc_discovery_time_min_input', 'value'),
    State('lc_discovery_time_min_format_select', 'value'),
    State('lc_discovery_time_max_input', 'value'),
    State('lc_discovery_time_max_format_select', 'value'),
    running=[
        (Output('lc_discovery_submit_query_button', 'disabled'), True, False),
        (Output('lc_discovery_cancel_query_button', 'disabled'), False, True),
    ],
    cancel=[Input('lc_discovery_cancel_query_button', 'n_clicks')],
    progress=[
        Output('lc_discovery_search_status', 'children'),
        Output('lc_discovery_search_status', 'style'),
    ],
    progress_default=(
        '',
        _LC_DISCOVERY_SEARCH_STATUS_STYLE_HIDDEN,
    ),
    background=True,
    prevent_initial_call=True,
)
def submit_catalog_search(
    set_progress,
    n_clicks,
    mission_id,
    target,
    radius_text,
    radius_unit,
    time_min_text,
    time_min_format,
    time_max_text,
    time_max_format,
):
    """Runs the background catalogue search for the selected mission and target.

    Args:
        n_clicks (int): Submit button click count.
        mission_id (str): Selected mission slug.
        target (str): Target field text.
        radius_text (str): Radius input value.
        radius_unit (str): Radius unit selector value.
        time_min_text (str): Earliest-time entry value.
        time_min_format (str): Earliest-time format selector value.
        time_max_text (str): Latest-time entry value.
        time_max_format (str): Latest-time format selector value.

    Returns:
        tuple: AgGrid rows, markdown card, stores, and optional alert components.
    """
    if not n_clicks:
        raise PreventUpdate

    set_props('lc_discovery_object_card', {'style': {'display': 'none'}})
    set_props('lc_discovery_object_card_markdown', {'children': ''})

    def _update_search_status(message: str) -> None:
        """Replaces the Discovery status bar with the current search step.

        Args:
            message (str): Concise status text for the active step.
        """
        set_progress((message, _LC_DISCOVERY_SEARCH_STATUS_STYLE_VISIBLE))

    logger.info(
        "Discovery Submit clicked mission=%r target=%r radius=%r %r "
        "time_min=%r (%s) time_max=%r (%s).",
        mission_id,
        target,
        radius_text,
        radius_unit,
        time_min_text,
        time_min_format,
        time_max_text,
        time_max_format,
    )
    empty_alert = (None, {'display': 'none'})
    try:
        time_bounds = parse_discovery_time_bounds(
            time_min_text,
            time_min_format,
            time_max_text,
            time_max_format,
        )
        outcome = run_catalog_search_for_mission(
            mission_id,
            target,
            radius_text,
            radius_unit,
            time_bounds=time_bounds,
            status_update=_update_search_status,
        )
    except PipeException as exc:
        logger.warning("Discovery search failed: %s", exc)
        return (
            [],
            _LC_DISCOVERY_CATALOG_HEADER_DEFAULT,
            '',
            {'display': 'none'},
            '',
            _LC_DISCOVERY_SEARCH_STATUS_STYLE_HIDDEN,
            message.warning_alert(exc),
            {'display': 'block'},
            None,
            None,
        )

    row_data = catalog_rows_for_aggrid(outcome.catalog)
    logger.info(
        "Discovery search mission=%s mode=%s rows=%s",
        mission_id,
        outcome.search_mode,
        len(row_data),
    )
    return (
        row_data,
        catalog_results_header(outcome),
        outcome.resolved_markdown,
        {'display': 'block'},
        '',
        _LC_DISCOVERY_SEARCH_STATUS_STYLE_HIDDEN,
        *empty_alert,
        row_data,
        outcome.to_store_dict(),
    )


@callback(
    Output('lc_discovery_aladin_container', 'children'),
    Output('store_lc_discovery_highlight_name', 'data', allow_duplicate=True),
    Input('store_lc_discovery_resolved_target', 'data'),
    State('lc_discovery_catalog_table', 'rowData'),
    prevent_initial_call=True,
)
def refresh_lc_discovery_aladin(search_metadata, row_data):
    """Rebuilds Aladin only when a new search completes, not on row selection.

    Args:
        search_metadata (dict, optional): Serialised search outcome metadata.
        row_data (list[dict]): Current AgGrid catalogue rows.

    Returns:
        tuple: Fresh Aladin view (or placeholder) and cleared highlight store.
    """
    return _build_lc_discovery_aladin_view(row_data, search_metadata), None


@callback(
    Output('store_lc_discovery_highlight_name', 'data', allow_duplicate=True),
    Output('store_lc_discovery_selected_key', 'data', allow_duplicate=True),
    Input('lc_discovery_catalog_table', 'cellClicked'),
    Input('lc_discovery_catalog_table', 'selectedRows'),
    Input('lc_discovery_aladin', 'selectedStar'),
    State('store_lc_discovery_highlight_name', 'data'),
    State('lc_discovery_catalog_table', 'rowData'),
    prevent_initial_call=True,
)
def update_lc_discovery_highlight_from_ui(
    cell_clicked,
    selected_rows,
    selected_star,
    current_highlight_name,
    row_data,
):
    """Records the active catalogue row from either the table or the sky map.

    A shared store avoids ping-pong callbacks that re-write ``selectedRows`` and
    ``selectedStar`` against each other (which made both the grid and Aladin blink).

    Args:
        cell_clicked (dict, optional): AgGrid ``cellClicked`` event payload.
        selected_rows (list[dict]): AgGrid selected rows.
        selected_star (dict, optional): Aladin ``selectedStar`` payload.
        current_highlight_name (str, optional): Current highlight marker name.
        row_data (list[dict]): Current AgGrid catalogue rows.

    Returns:
        tuple: Marker name and ``lc_key`` for the highlighted row.

    Raises:
        PreventUpdate: When the highlight is unchanged or cannot be resolved.
    """
    if not ctx.triggered:
        raise PreventUpdate

    triggered_prop = ctx.triggered[0]['prop_id']
    component_id, _, triggered_field = triggered_prop.partition('.')

    if component_id == 'lc_discovery_catalog_table':
        row = None
        if triggered_field == 'cellClicked':
            row = catalog_row_from_cell_clicked(cell_clicked, row_data or [])
        elif selected_rows:
            row = selected_rows[0]
        if row is None:
            raise PreventUpdate
        if row.get('ra_deg') is None or row.get('dec_deg') is None:
            raise PreventUpdate
        highlight_name = aladin_marker_name(row)
        lc_key = row.get('lc_key')
    elif component_id == 'lc_discovery_aladin':
        if not selected_star or not selected_star.get('name') or not row_data:
            raise PreventUpdate
        highlight_name = str(selected_star['name'])
        matched_row = find_catalog_row_by_aladin_name(row_data, highlight_name)
        if matched_row is None:
            raise PreventUpdate
        lc_key = matched_row.get('lc_key')
    else:
        raise PreventUpdate

    if highlight_name == current_highlight_name:
        raise PreventUpdate
    return highlight_name, lc_key


@callback(
    Output('lc_discovery_aladin', 'selectedStar', allow_duplicate=True),
    Input('store_lc_discovery_highlight_name', 'data'),
    State('lc_discovery_catalog_table', 'rowData'),
    State('lc_discovery_aladin', 'selectedStar'),
    prevent_initial_call=True,
)
def sync_lc_discovery_highlight_to_aladin(highlight_name, row_data, current_star):
    """Highlights an Aladin marker when the shared store changes from a table click.

    Map clicks are already handled inside the Aladin component; this callback runs
    only for table-driven highlight changes.

    Args:
        highlight_name (str, optional): Shared marker name from the highlight store.
        row_data (list[dict]): Current AgGrid catalogue rows.
        current_star (dict, optional): Current Aladin ``selectedStar`` payload.

    Returns:
        dict: Updated Aladin ``selectedStar`` payload.

    Raises:
        PreventUpdate: When the map already shows the requested marker.
    """
    if not highlight_name or not row_data:
        raise PreventUpdate
    if current_star and current_star.get('name') == highlight_name:
        raise PreventUpdate

    matched_row = find_catalog_row_by_aladin_name(row_data, highlight_name)
    if matched_row is None:
        raise PreventUpdate
    return aladin_selected_star_from_row(matched_row)


clientside_callback(
    ClientsideFunction(
        namespace='clientside',
        function_name='lcDiscoveryMinTimePlaceholder',
    ),
    Output('lc_discovery_time_min_input', 'placeholder'),
    Input('lc_discovery_time_min_format_select', 'value'),
)

clientside_callback(
    ClientsideFunction(
        namespace='clientside',
        function_name='lcDiscoveryMaxTimePlaceholder',
    ),
    Output('lc_discovery_time_max_input', 'placeholder'),
    Input('lc_discovery_time_max_format_select', 'value'),
)

clientside_callback(
    ClientsideFunction(
        namespace='clientside',
        function_name='lcDiscoveryCatalogHighlightRules',
    ),
    Output('lc_discovery_catalog_table', 'dashGridOptions'),
    Input('store_lc_discovery_highlight_name', 'data'),
    prevent_initial_call=True,
)


@callback(
    Output('lc_discovery_plot_tab', 'disabled'),
    Input('lc_discovery_catalog_table', 'rowData'),
)
def toggle_lc_discovery_plot_tab(row_data):
    """Enables the Light curve tab once a search returns catalogue rows.

    Args:
        row_data (list[dict]): Current AgGrid catalogue rows.

    Returns:
        bool: ``True`` to keep the tab disabled when the catalogue is empty.
    """
    return not row_data


@callback(
    Output('lc_discovery_fetch_button', 'disabled'),
    Output('lc_discovery_refetch_button', 'disabled'),
    Input('store_lc_discovery_selected_key', 'data'),
)
def toggle_lc_discovery_fetch_buttons(lc_key):
    """Enables catalogue fetch buttons when a row is highlighted.

    Args:
        lc_key (str, optional): Serialised fetch handle for the selected row.

    Returns:
        tuple: ``(download_disabled, redownload_disabled)`` flags.
    """
    disabled = not lc_key
    return disabled, disabled


@callback(
    Output('lc_discovery_replot_button', 'disabled'),
    Input('store_lc_discovery_lc_revision', 'data'),
    State('store_lc_discovery_user_tab_id', 'data'),
)
def toggle_lc_discovery_replot_button(_revision, user_tab_id):
    """Enables rePlot once a lightcurve is cached for this session.

    Args:
        _revision (str, optional): Plot revision token (dependency only).
        user_tab_id (str, optional): Session cache key.

    Returns:
        bool: ``True`` while no cached lightcurve exists.
    """
    if not user_tab_id or not has_cached_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id):
        return True
    return False


@callback(
    output=dict(
        plot_alert_style=Output('lc_discovery_plot_alert', 'style', allow_duplicate=True),
        plot_alert_message=Output('lc_discovery_plot_alert', 'children', allow_duplicate=True),
        fold_controls_style=Output('lc_discovery_fold_controls', 'style', allow_duplicate=True),
        fold_warning_style=Output('lc_discovery_fold_warning_label', 'style', allow_duplicate=True),
        user_tab_id=Output('store_lc_discovery_user_tab_id', 'data', allow_duplicate=True),
        revision=Output('store_lc_discovery_lc_revision', 'data', allow_duplicate=True),
        period_val=Output('lc_discovery_period_input', 'value', allow_duplicate=True),
        epoch_val=Output('lc_discovery_epoch_input', 'value', allow_duplicate=True),
        mag_switch=Output('lc_discovery_mag_switch', 'value', allow_duplicate=True),
        fold_switch=Output('lc_discovery_fold_switch', 'value', allow_duplicate=True),
        fetch_status=Output('lc_discovery_fetch_status', 'children', allow_duplicate=True),
        fetch_alert_message=Output('lc_discovery_fetch_alert', 'children', allow_duplicate=True),
        fetch_alert_style=Output('lc_discovery_fetch_alert', 'style', allow_duplicate=True),
        plot_tab_disabled=Output('lc_discovery_plot_tab', 'disabled', allow_duplicate=True),
        active_tab=Output('lc_discovery_tabs', 'active_tab', allow_duplicate=True),
    ),
    inputs=dict(
        download_clicks=Input('lc_discovery_fetch_button', 'n_clicks'),
        redownload_clicks=Input('lc_discovery_refetch_button', 'n_clicks'),
    ),
    state=dict(
        mission_id=State('lc_discovery_mission_switch', 'value'),
        lc_key=State('store_lc_discovery_selected_key', 'data'),
        row_data=State('lc_discovery_catalog_table', 'rowData'),
        phase_view=State('lc_discovery_fold_switch', 'value'),
        user_tab_id=State('store_lc_discovery_user_tab_id', 'data'),
    ),
    running=[
        (Output('lc_discovery_fetch_button', 'disabled'), True, False),
        (Output('lc_discovery_refetch_button', 'disabled'), True, False),
        (Output('lc_discovery_cancel_fetch_button', 'disabled'), False, True),
    ],
    cancel=[Input('lc_discovery_cancel_fetch_button', 'n_clicks')],
    background=True,
    prevent_initial_call=True,
)
def fetch_lc_discovery_lightcurve(
    download_clicks,
    redownload_clicks,
    mission_id,
    lc_key,
    row_data,
    phase_view,
    user_tab_id,
):
    """Fetches the highlighted catalogue row via the mission provider (background job).

    Uses ``provider.fetch_lightcurve`` → ``volc_to_curvedash`` with no shared
    archive fetch cache (deferred). The resulting ``CurveDash`` is held in the
    existing per-session plot store for interactive tools.

    Args:
        download_clicks (int): Download button click count.
        redownload_clicks (int): reDownload button click count.
        mission_id (str): Selected mission slug from the UI.
        lc_key (str): Serialised fetch handle for the selected row.
        row_data (list[dict]): Current AgGrid catalogue rows.
        phase_view (bool): Current fold switch state.
        user_tab_id (str, optional): Session plot-store key.

    Returns:
        dict: Updated stores, fold controls, tab state, and status messages.
    """
    if not ctx.triggered_id or not lc_key:
        raise PreventUpdate

    force_refresh = ctx.triggered_id == 'lc_discovery_refetch_button'
    catalog_row = catalog_row_for_lc_key(row_data, lc_key)
    if catalog_row is None:
        return dict(
            plot_alert_style={'display': 'none'},
            plot_alert_message='',
            fold_controls_style={'display': 'none', 'min-height': '30px'},
            fold_warning_style={'display': 'none'},
            user_tab_id=no_update,
            revision=no_update,
            period_val=no_update,
            epoch_val=no_update,
            mag_switch=no_update,
            fold_switch=no_update,
            fetch_status='',
            fetch_alert_message=message.warning_alert(
                'Selected row is no longer in the catalogue table.'
            ),
            fetch_alert_style={'display': 'block'},
            plot_tab_disabled=no_update,
            active_tab=no_update,
        )

    if mission_id and mission_id_from_lc_key(lc_key) != mission_id:
        return dict(
            plot_alert_style={'display': 'none'},
            plot_alert_message='',
            fold_controls_style={'display': 'none', 'min-height': '30px'},
            fold_warning_style={'display': 'none'},
            user_tab_id=no_update,
            revision=no_update,
            period_val=no_update,
            epoch_val=no_update,
            mag_switch=no_update,
            fold_switch=no_update,
            fetch_status='',
            fetch_alert_message=message.warning_alert(
                'Selected row does not match the current mission.'
            ),
            fetch_alert_style={'display': 'block'},
            plot_tab_disabled=no_update,
            active_tab=no_update,
        )

    fold_controls_style = {'display': 'block', 'min-height': '30px'}
    fold_warning_style = {'display': 'none'}

    try:
        lcd = curvedash_from_catalog_row(catalog_row, force_refresh=force_refresh)
        if lcd.lightcurve is not None:
            lcd.lightcurve.dropna(subset=['flux'], inplace=True)
        lcd.folded_view = bool(phase_view)

        period = lcd.period
        period = None if not period else round(period, 5)
        if period is None:
            fold_controls_style = {'display': 'none', 'min-height': '30px'}
            fold_warning_style = {'display': 'block'}
            lcd.folded_view = False

        if user_tab_id is None:
            user_tab_id = generate_user_tab_id()

        write_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id, lcd.serialize())

        object_label = catalog_row.get('object_name') or 'object'
        filter_label = catalog_row.get('filter_name') or ''
        status_line = f'Loaded {object_label}'
        if filter_label:
            status_line = f'{status_line} ({filter_label})'
        if force_refresh:
            status_line = f'reDownload complete — {status_line}'

        return dict(
            plot_alert_style={'display': 'none'},
            plot_alert_message='',
            fold_controls_style=fold_controls_style,
            fold_warning_style=fold_warning_style,
            user_tab_id=user_tab_id,
            revision=_bump_lc_revision(),
            period_val=period,
            epoch_val=_display_epoch_value(lcd),
            mag_switch=lcd.active_domain == DOMAIN_MAG,
            fold_switch=lcd.folded_view,
            fetch_status=status_line,
            fetch_alert_message=message.info_alert(f'{status_line}. Switch to the Light curve tab.'),
            fetch_alert_style={'display': 'block'},
            plot_tab_disabled=False,
            active_tab='lc_discovery_plot_tab',
        )
    except Exception as exc:
        logger.warning('lightcurve_discovery.fetch_lc_discovery_lightcurve: %s', exc)
        return dict(
            plot_alert_style={'display': 'none'},
            plot_alert_message='',
            fold_controls_style={'display': 'none', 'min-height': '30px'},
            fold_warning_style={'display': 'none'},
            user_tab_id=no_update,
            revision=no_update,
            period_val=no_update,
            epoch_val=no_update,
            mag_switch=no_update,
            fold_switch=no_update,
            fetch_status='',
            fetch_alert_message=message.warning_alert(exc),
            fetch_alert_style={'display': 'block'},
            plot_tab_disabled=no_update,
            active_tab=no_update,
        )


@callback(
    output=dict(
        revision=Output('store_lc_discovery_lc_revision', 'data', allow_duplicate=True),
    ),
    inputs=dict(replot_clicks=Input('lc_discovery_replot_button', 'n_clicks')),
    state=dict(user_tab_id=State('store_lc_discovery_user_tab_id', 'data')),
    prevent_initial_call=True,
)
def replot_lc_discovery_lightcurve(replot_clicks, user_tab_id):
    """Refreshes the plot from the in-session ``CurveDash`` without re-fetching.

    Args:
        replot_clicks (int): rePlot button click count.
        user_tab_id (str, optional): Session plot-store key.

    Returns:
        dict: New plot revision token.

    Raises:
        PreventUpdate: When no cached lightcurve exists.
    """
    if not replot_clicks or not user_tab_id:
        raise PreventUpdate
    if not has_cached_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id):
        raise PreventUpdate
    set_props('lc_discovery_plot_alert', {'children': None, 'style': {'display': 'none'}})
    return dict(revision=_bump_lc_revision())


@callback(
    Output('lc_discovery_graph', 'figure', allow_duplicate=True),
    Input('store_lc_discovery_lc_revision', 'data'),
    Input('lc_discovery_time_axis_switch', 'value'),
    State('store_lc_discovery_user_tab_id', 'data'),
    State('lc_discovery_fold_switch', 'value'),
    prevent_initial_call='initial_duplicate',
)
def plot_lc_discovery_curve(_revision, time_axis_mode, user_tab_id, phase_view):
    """Builds the Discovery lightcurve figure from the session cache.

    Args:
        _revision (str, optional): Plot revision token.
        time_axis_mode (str): MJD or calendar date axis mode.
        user_tab_id (str, optional): Session cache key.
        phase_view (bool): Whether to show folded phases.

    Returns:
        dict: Plotly figure dictionary.

    Raises:
        PreventUpdate: When no cached lightcurve is available.
    """
    if not user_tab_id or not has_cached_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id):
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id)
        fig = figure_from_serialized(
            js_lightcurve,
            phase_view=bool(phase_view),
            display_epoch=DISPLAY_EPOCH_JD,
            time_axis_mode=time_axis_mode or TIME_AXIS_MJD,
            color_by_label=False,
            dragmode='lasso',
        )
        set_props('lc_discovery_plot_alert', {'children': None, 'style': {'display': 'none'}})
        return fig
    except Exception as exc:
        logger.warning('lightcurve_discovery.plot_lc_discovery_curve: %s', exc)
        set_props(
            'lc_discovery_plot_alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        return no_update


@callback(
    Output('store_lc_discovery_lc_revision', 'data', allow_duplicate=True),
    Output('lc_discovery_fold_switch', 'value', allow_duplicate=True),
    Input('lc_discovery_recalc_phase_button', 'n_clicks'),
    Input('lc_discovery_fold_switch', 'value'),
    State('store_lc_discovery_user_tab_id', 'data'),
    State('lc_discovery_period_input', 'value'),
    State('lc_discovery_epoch_input', 'value'),
    prevent_initial_call=True,
)
def fold_or_recalculate_lc_discovery_phase(n_clicks, phase_view, user_tab_id, period, epoch):
    """Folds or recalculates phase for the cached Discovery lightcurve.

    Args:
        n_clicks (int): Recalc Phase button click count.
        phase_view (bool): Fold switch state.
        user_tab_id (str, optional): Session cache key.
        period (str, optional): Period input value.
        epoch (str, optional): Epoch input value relative to ``DISPLAY_EPOCH_JD``.

    Returns:
        tuple: New revision token and optional updated fold switch value.

    Raises:
        PreventUpdate: When inputs are invalid or unchanged.
    """
    if ctx.triggered_id == 'lc_discovery_recalc_phase_button' and n_clicks is None:
        raise PreventUpdate
    try:
        epoch_value = safe_float(epoch, 0)
        period_value = safe_float(period)
        if phase_view and not period_value:
            raise PipeException('Set the period and try again')

        js_lightcurve = read_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        if lcd.lightcurve is None:
            raise PipeException('recalculate_phase: Please, load a lightcurve first')

        if period_value:
            lcd.period = period_value
            lcd.period_unit = 'd'
        if epoch_value is not None:
            lcd.epoch = epoch_value + DISPLAY_EPOCH_JD

        lcd.folded_view = bool(phase_view)
        lcd.recalc_phase()
        write_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        set_props('lc_discovery_plot_alert', {'children': None, 'style': {'display': 'none'}})
        return _bump_lc_revision(), no_update
    except Exception as exc:
        logger.warning('lightcurve_discovery.fold_or_recalculate_lc_discovery_phase: %s', exc)
        set_props(
            'lc_discovery_plot_alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        return no_update, False


@callback(
    Output('store_lc_discovery_lc_revision', 'data', allow_duplicate=True),
    Output('lc_discovery_mag_switch', 'value', allow_duplicate=True),
    Input('lc_discovery_mag_switch', 'value'),
    State('store_lc_discovery_user_tab_id', 'data'),
    prevent_initial_call=True,
)
def toggle_lc_discovery_mag_view(show_magnitude, user_tab_id):
    """Switches the cached lightcurve between flux and magnitude domains.

    Args:
        show_magnitude (bool): Mag switch state.
        user_tab_id (str, optional): Session cache key.

    Returns:
        tuple: New revision token and optional corrected switch value.

    Raises:
        PreventUpdate: When no domain change is required.
    """
    if not user_tab_id:
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)

        desired_domain = DOMAIN_MAG if show_magnitude else DOMAIN_FLUX
        if lcd.active_domain == desired_domain:
            raise PreventUpdate

        apply_phot_domain_view(lcd, show_magnitude)
        write_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        set_props('lc_discovery_plot_alert', {'children': '', 'style': {'display': 'none'}})
        return _bump_lc_revision(), no_update
    except PreventUpdate:
        raise
    except Exception as exc:
        logger.warning('lightcurve_discovery.toggle_lc_discovery_mag_view: %s', exc)
        set_props(
            'lc_discovery_plot_alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        try:
            js_lightcurve = read_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id)
            lcd = CurveDash.from_serialized(js_lightcurve)
            return no_update, lcd.active_domain == DOMAIN_MAG
        except Exception:
            return no_update, False


@callback(
    Output('lc_discovery_mag_switch', 'value', allow_duplicate=True),
    Input('store_lc_discovery_lc_revision', 'data'),
    State('store_lc_discovery_user_tab_id', 'data'),
    prevent_initial_call=True,
)
def sync_lc_discovery_mag_switch(_, user_tab_id):
    """Keeps the magnitude switch aligned with the cached active domain.

    Args:
        _ (str, optional): Plot revision token (dependency only).
        user_tab_id (str, optional): Session cache key.

    Returns:
        bool: Whether magnitude view is active.

    Raises:
        PreventUpdate: When no cache entry exists.
    """
    if not user_tab_id:
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        return lcd.active_domain == DOMAIN_MAG
    except Exception:
        raise PreventUpdate


@callback(
    Output('store_lc_discovery_lc_revision', 'data', allow_duplicate=True),
    Input('lc_discovery_graph', 'selectedData'),
    Input('lc_discovery_graph', 'clickData'),
    State('store_lc_discovery_user_tab_id', 'data'),
    prevent_initial_call=True,
)
def merge_lc_discovery_plot_selection(selected_data, click_data, user_tab_id):
    """Marks clicked or lasso-selected points in the server cache and replots.

    Args:
        selected_data (dict, optional): Plotly lasso/box selection payload.
        click_data (dict, optional): Plotly click payload.
        user_tab_id (str, optional): Session cache key.

    Returns:
        str: New revision token.

    Raises:
        PreventUpdate: When the event carries no usable points.
    """
    if not ctx.triggered or not user_tab_id:
        raise PreventUpdate
    trigger_prop = ctx.triggered[0]['prop_id'].rsplit('.', 1)[-1]
    event_data = selected_data if trigger_prop == 'selectedData' else click_data
    if not event_data or not event_data.get('points'):
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        apply_plot_point_selection(lcd, event_data)
        write_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        return _bump_lc_revision()
    except Exception as exc:
        logger.warning('lightcurve_discovery.merge_lc_discovery_plot_selection: %s', exc)
        set_props(
            'lc_discovery_plot_alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        raise PreventUpdate


@callback(
    Output('store_lc_discovery_lc_revision', 'data', allow_duplicate=True),
    Input('lc_discovery_unselect_button', 'n_clicks'),
    State('store_lc_discovery_user_tab_id', 'data'),
    prevent_initial_call=True,
)
def unselect_lc_discovery_points(n_clicks, user_tab_id):
    """Clears all ``selected`` markers in the cached lightcurve and replots.

    Args:
        n_clicks (int): Unselect button click count.
        user_tab_id (str, optional): Session cache key.

    Returns:
        str: New revision token.

    Raises:
        PreventUpdate: When the button was not clicked or no cache exists.
    """
    if not n_clicks or not user_tab_id:
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        clear_plot_point_selection(lcd)
        write_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        set_props('lc_discovery_plot_alert', {'children': None, 'style': {'display': 'none'}})
        return _bump_lc_revision()
    except Exception as exc:
        logger.warning('lightcurve_discovery.unselect_lc_discovery_points: %s', exc)
        set_props(
            'lc_discovery_plot_alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        raise PreventUpdate


@callback(
    Output('store_lc_discovery_lc_revision', 'data', allow_duplicate=True),
    Input('lc_discovery_delete_button', 'n_clicks'),
    State('store_lc_discovery_user_tab_id', 'data'),
    prevent_initial_call=True,
)
def delete_lc_discovery_selected_points(n_clicks, user_tab_id):
    """Removes rows marked ``selected=1`` from the cached lightcurve.

    Args:
        n_clicks (int): Delete button click count.
        user_tab_id (str, optional): Session cache key.

    Returns:
        str: New revision token.

    Raises:
        PreventUpdate: When nothing is selected or deletion would empty the curve.
    """
    if not n_clicks or not user_tab_id:
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        if lcd.lightcurve is None or 'selected' not in lcd.lightcurve.columns:
            raise PipeException('Select points to delete first.')
        if not (lcd.lightcurve['selected'] == 1).any():
            set_props(
                'lc_discovery_plot_alert',
                {
                    'children': message.warning_alert('Select points to delete first.'),
                    'style': {'display': 'block'},
                },
            )
            raise PreventUpdate
        delete_selected_rows(lcd)
        if lcd.lightcurve is None or lcd.lightcurve.empty:
            raise PipeException('Cannot delete all points from the lightcurve')
        write_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        set_props('lc_discovery_plot_alert', {'children': None, 'style': {'display': 'none'}})
        return _bump_lc_revision()
    except PreventUpdate:
        raise
    except Exception as exc:
        logger.warning('lightcurve_discovery.delete_lc_discovery_selected_points: %s', exc)
        set_props(
            'lc_discovery_plot_alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        raise PreventUpdate


@callback(
    Output('lc_discovery_download', 'data'),
    Input('lc_discovery_download_button', 'n_clicks'),
    State('store_lc_discovery_user_tab_id', 'data'),
    State('lc_discovery_export_format_select', 'value'),
    prevent_initial_call=True,
)
def download_lc_discovery_lightcurve(n_clicks, user_tab_id, table_format):
    """Exports the cached Discovery lightcurve via mission-blind bridge export.

    VOTable kwargs are rebuilt from ``CurveDash`` metadata ingested at fetch time.
    Legacy mission export profiles are not used on this page.

    Args:
        n_clicks (int): Download button click count.
        user_tab_id (str, optional): Session plot-store key.
        table_format (str): Selected export format.

    Returns:
        dict | dash.no_update: Dash download payload.

    Raises:
        PreventUpdate: When the button was not clicked or no cache exists.
    """
    if not n_clicks or not user_tab_id:
        raise PreventUpdate

    try:
        js_lightcurve = read_serialized_lc(LC_DISCOVERY_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        file_bstring = export_curvedash(lcd, table_format)

        outfile_base = discovery_export_basename(lcd)
        ext = export_file_extension(table_format)
        outfile = f'{outfile_base}.{ext}'

        set_props('lc_discovery_plot_alert', {'children': '', 'style': {'display': 'none'}})
        return dcc.send_bytes(file_bstring, outfile)
    except Exception as exc:
        logger.warning('lightcurve_discovery.download_lc_discovery_lightcurve: %s', exc)
        set_props(
            'lc_discovery_plot_alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        return no_update

