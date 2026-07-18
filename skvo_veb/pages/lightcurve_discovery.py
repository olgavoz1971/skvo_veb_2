"""Lightcurve Discovery — multi-mission catalogue search and lightcurve workflow.

See ``docs/mission_lightcurve_providers.md`` for architecture.
Styles: ``assets/lc_discovery.css``.
"""

import logging

import aladin_lite_react_component
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import plotly.express as px
from dash import Input, Output, State, callback, clientside_callback, ctx, dcc, html, register_page, set_props
from dash.dependencies import ClientsideFunction
from dash.exceptions import PreventUpdate

from skvo_veb.components import message
from skvo_veb.logging_config import configure_logging
from skvo_veb.lc_providers.registry import list_missions
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
from skvo_veb.utils.lc_discovery_search import (
    catalog_results_header,
    catalog_rows_for_aggrid,
    run_catalog_search_for_mission,
)
from skvo_veb.utils.lc_discovery_time_bounds import parse_discovery_time_bounds
from skvo_veb.utils.my_tools import PipeException, positive_float_pattern
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

_LC_DISCOVERY_CATALOG_HEADER_DEFAULT = 'Submit a query to list available lightcurves.'
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
            dbc.Spinner(
                children=html.Div(
                    id='lc_discovery_search_tools_alert',
                    style={'display': 'none', 'marginTop': '8px'},
                ),
                size='sm',
                spinner_style={'width': '2rem', 'height': '2rem'},
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
                                                    'rowHeight': 22,
                                                    'headerHeight': 24,
                                                    'rowSelection': {
                                                        'mode': 'singleRow',
                                                        'checkboxes': False,
                                                        'enableClickSelection': True,
                                                    },
                                                    'animateRows': False,
                                                    'pagination': True,
                                                    'paginationPageSize': 10,
                                                    'domLayout': 'normal',
                                                    'suppressHorizontalScroll': False,
                                                    'alwaysShowHorizontalScroll': True,
                                                    'enableCellTextSelection': True,
                                                    'ensureDomOrder': True,
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
                ],
            ),
            catalog_help_pop,
        ],
        lg=9,
        md=8,
        sm=7,
        xs=12,
    )


def _lightcurve_tools_panel():
    """Builds the Light curve tab tools placeholder.

    Returns:
        dash_bootstrap_components.Col: Responsive grey tools panel.
    """
    return dbc.Col(
        [
            dbc.Label(
                'Light curve tools',
                style={'display': 'flex', 'justify-content': 'center'},
            ),
            html.P(
                'Select a row in the Search tab, then load a lightcurve here.',
                className='text-muted',
                style={'marginTop': '8px'},
            ),
            dbc.Button(
                'Load selected',
                id='lc_discovery_load_button',
                size='sm',
                color='primary',
                disabled=True,
                style={'width': '100%', 'marginBottom': '5px'},
            ),
            dbc.Button(
                'rePlot curve',
                id='lc_discovery_replot_button',
                size='sm',
                disabled=True,
                style={'width': '100%', 'marginBottom': '5px'},
            ),
        ],
        lg=2,
        md=3,
        sm=4,
        xs=12,
        style={'padding': '10px', 'background': 'Silver', 'border-radius': '5px'},
    )


def _lightcurve_graph_panel():
    """Builds the Light curve tab graph placeholder.

    Returns:
        dash_bootstrap_components.Col: Responsive Plotly graph container.
    """
    empty_fig = px.scatter()
    empty_fig.update_layout(
        title='',
        margin=dict(l=48, b=48, t=24, r=16),
        xaxis_title='time',
        yaxis_title='flux',
        autosize=True,
    )
    return dbc.Col(
        [
            html.Div(id='lc_discovery_plot_alert', style={'display': 'none'}),
            dcc.Graph(
                id='lc_discovery_graph',
                figure=empty_fig,
                config={
                    'displaylogo': False,
                    'scrollZoom': True,
                    'responsive': True,
                    'modeBarButtonsToRemove': ['lasso2d'],
                },
                className='lc-discovery-graph-wrap',
                style={'width': '100%'},
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
            dcc.Store(id='store_lc_discovery_catalog', **SESSION_STORE),
            dcc.Store(id='store_lc_discovery_selected_key', **SESSION_STORE),
            dcc.Store(id='store_lc_discovery_highlight_name', **SESSION_STORE),
            dcc.Store(id='store_lc_discovery_resolved_target', **SESSION_STORE),
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
