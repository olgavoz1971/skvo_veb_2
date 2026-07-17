"""Lightcurve Discovery — multi-mission catalogue search and lightcurve workflow.

See ``docs/mission_lightcurve_providers.md`` for architecture.
Styles: ``assets/lc_discovery.css``.
"""

import logging

import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import plotly.express as px
from dash import Input, Output, State, callback, dcc, html, register_page
from dash.exceptions import PreventUpdate

from skvo_veb.components import message
from skvo_veb.logging_config import configure_logging
from skvo_veb.lc_providers.registry import list_missions
from skvo_veb.utils.lc_discovery_search import (
    catalog_results_header,
    catalog_results_subtitle,
    catalog_rows_for_aggrid,
    run_catalog_search_for_mission,
)
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
        'field': '#',
        'headerName': '#',
        'checkboxSelection': True,
        'headerCheckboxSelection': True,
        'maxWidth': 70,
        'pinned': 'left',
    },
    {'field': 'distance_arcsec', 'headerName': 'Sep (″)', 'type': 'numericColumn', 'minWidth': 72},
    {'field': 'object_name', 'headerName': 'Object', 'minWidth': 100, 'flex': 2},
    {'field': 'filter_name', 'headerName': 'Filter', 'minWidth': 90, 'flex': 1},
    {'field': 'ra_deg', 'headerName': 'RA°', 'type': 'numericColumn', 'minWidth': 88},
    {'field': 'dec_deg', 'headerName': 'Dec°', 'type': 'numericColumn', 'minWidth': 88},
    {'field': 'n_points', 'headerName': 'N', 'type': 'numericColumn', 'maxWidth': 64},
]

LC_DISCOVERY_RADIUS_UNIT_OPTIONS = [
    {'label': 'arcsec', 'value': 'arcsec'},
    {'label': 'arcmin', 'value': 'arcmin'},
    {'label': 'deg', 'value': 'deg'},
]

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
    """Builds a click-triggered ``?`` control and its popover (Target field only for now).

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
                            dbc.Label(
                                'Radius',
                                html_for='lc_discovery_radius_input',
                                className='lc-discovery-field-label',
                            ),
                            dcc.Input(
                                id='lc_discovery_radius_input',
                                persistence=True,
                                type='search',
                                inputMode='numeric',
                                value='10',
                                pattern=positive_float_pattern,
                                placeholder='10',
                                className='lc-discovery-field-input',
                            ),
                            dbc.Select(
                                id='lc_discovery_radius_unit_select',
                                options=LC_DISCOVERY_RADIUS_UNIT_OPTIONS,
                                value='arcsec',
                                persistence=True,
                                className='lc-discovery-field-unit',
                            ),
                            html.Span(
                                className='lc-discovery-field-help-spacer',
                                **{'aria-hidden': 'true'},
                            ),
                        ],
                        className='lc-discovery-field-row lc-discovery-field-row-radius',
                    ),
                ],
                className='lc-discovery-field-stack',
            ),
            target_help_pop,
            _resolved_target_card(),
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
                style=stack_wrap_style,
            ),
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
                    html.Summary('Mission'),
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
    return dbc.Col(
        [
            dbc.Spinner(
                children=[
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H3(
                                        'Catalog search results',
                                        id='lc_discovery_catalog_header',
                                        className='fs-5 mb-1',
                                    ),
                                    html.P(
                                        'Submit a cone search to list available lightcurves.',
                                        id='lc_discovery_catalog_subtitle',
                                        className='text-muted mb-0',
                                    ),
                                ],
                                className='lc-discovery-catalog-header-row',
                            ),
                            html.Div(
                                dag.AgGrid(
                                    id='lc_discovery_catalog_table',
                                    columnDefs=LC_DISCOVERY_CATALOG_COLUMNS,
                                    rowData=[],
                                    columnSize='responsiveSizeToFit',
                                    defaultColDef={'filter': True, 'sortable': True, 'resizable': True},
                                    dashGridOptions={
                                        'theme': 'themeBalham',
                                        'rowSelection': 'single',
                                        'suppressRowClickSelection': False,
                                        'animateRows': True,
                                        'pagination': True,
                                        'paginationPageSize': 10,
                                        'domLayout': 'normal',
                                        'suppressHorizontalScroll': False,
                                    },
                                    style={'height': '100%', 'width': '100%'},
                                ),
                                className='lc-discovery-catalog-grid',
                            ),
                        ],
                        id='lc_discovery_catalog_row',
                    ),
                    html.Div(id='lc_discovery_search_alert', style={'display': 'none'}),
                ],
            ),
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
            dcc.Store(id='store_lc_discovery_resolved_target', **SESSION_STORE),
        ],
        className='g-10',
        fluid=True,
        style={'display': 'flex', 'flexDirection': 'column'},
    )


_LC_DISCOVERY_CATALOG_HEADER_DEFAULT = 'Catalog search results'
_LC_DISCOVERY_CATALOG_SUBTITLE_DEFAULT = (
    'Submit a query to list available lightcurves.'
)


@callback(
    Output('lc_discovery_catalog_table', 'rowData'),
    Output('lc_discovery_catalog_header', 'children'),
    Output('lc_discovery_catalog_subtitle', 'children'),
    Output('lc_discovery_object_card_markdown', 'children'),
    Output('lc_discovery_object_card', 'style'),
    Output('lc_discovery_search_alert', 'children'),
    Output('lc_discovery_search_alert', 'style'),
    Output('store_lc_discovery_catalog', 'data'),
    Output('store_lc_discovery_resolved_target', 'data'),
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
        _LC_DISCOVERY_CATALOG_SUBTITLE_DEFAULT,
        '',
        {'display': 'none'},
        None,
        {'display': 'none'},
        None,
        None,
    )


@callback(
    Output('lc_discovery_catalog_table', 'rowData', allow_duplicate=True),
    Output('lc_discovery_catalog_header', 'children', allow_duplicate=True),
    Output('lc_discovery_catalog_subtitle', 'children', allow_duplicate=True),
    Output('lc_discovery_object_card_markdown', 'children', allow_duplicate=True),
    Output('lc_discovery_object_card', 'style', allow_duplicate=True),
    Output('lc_discovery_search_alert', 'children', allow_duplicate=True),
    Output('lc_discovery_search_alert', 'style', allow_duplicate=True),
    Output('store_lc_discovery_catalog', 'data', allow_duplicate=True),
    Output('store_lc_discovery_resolved_target', 'data', allow_duplicate=True),
    Input('lc_discovery_submit_query_button', 'n_clicks'),
    State('lc_discovery_mission_switch', 'value'),
    State('lc_discovery_target_input', 'value'),
    State('lc_discovery_radius_input', 'value'),
    State('lc_discovery_radius_unit_select', 'value'),
    running=[
        (Output('lc_discovery_submit_query_button', 'disabled'), True, False),
        (Output('lc_discovery_cancel_query_button', 'disabled'), False, True),
    ],
    cancel=[Input('lc_discovery_cancel_query_button', 'n_clicks')],
    background=True,
    prevent_initial_call=True,
)
def submit_catalog_search(n_clicks, mission_id, target, radius_text, radius_unit):
    """Runs the background catalogue search for the selected mission and target.

    Args:
        n_clicks (int): Submit button click count.
        mission_id (str): Selected mission slug.
        target (str): Target field text.
        radius_text (str): Radius input value.
        radius_unit (str): Radius unit selector value.

    Returns:
        tuple: AgGrid rows, markdown card, stores, and optional alert components.
    """
    if not n_clicks:
        raise PreventUpdate

    logger.info(
        "Discovery Submit clicked mission=%r target=%r radius=%r %r.",
        mission_id,
        target,
        radius_text,
        radius_unit,
    )
    empty_alert = (None, {'display': 'none'})
    try:
        outcome = run_catalog_search_for_mission(
            mission_id,
            target,
            radius_text,
            radius_unit,
        )
    except PipeException as exc:
        logger.warning("Discovery search failed: %s", exc)
        return (
            [],
            _LC_DISCOVERY_CATALOG_HEADER_DEFAULT,
            _LC_DISCOVERY_CATALOG_SUBTITLE_DEFAULT,
            '',
            {'display': 'none'},
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
        catalog_results_subtitle(outcome),
        outcome.resolved_markdown,
        {'display': 'block'},
        *empty_alert,
        row_data,
        outcome.to_store_dict(),
    )
