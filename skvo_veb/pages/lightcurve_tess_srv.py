# DISK_CACHE = True  # this makes sense only for a local version
import os
import re
import time

DISK_CACHE = False

import logging
logger = logging.getLogger(__name__)
from os import getenv
logging.basicConfig(filename=getenv('APP_LOG'), level=logging.INFO)

import base64
import io
from pathlib import Path

import lightkurve
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import register_page, dcc, html, callback, ctx, dash, set_props, clientside_callback
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
from skvo_veb.utils import tess_processor
from skvo_veb.utils.page_session import SESSION_STORE, table_rows_from_lk_search_dict
from dash.dependencies import Input, Output, State, ClientsideFunction
import plotly.express as px

import lightkurve as lk
from dash.exceptions import PreventUpdate
from lightkurve import LightkurveError

# Configure user data storage on the server side
import diskcache

user_cache_dir = os.getenv('USER_CACHE_DIR')
user_cache = diskcache.Cache(user_cache_dir)
# This works weirdly with apache2, it could re-import module occasionally
# user_cache.clear()  # Cleans all entries on startup.
import uuid

from skvo_veb.components import message
from skvo_veb.utils import tess_cache as cache
from skvo_veb.utils import tess_lc_search
from skvo_veb.utils import lightkurve_cache
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import volc_to_curvedash, export_curvedash, build_curvedash_title
from skvo_veb.utils.tess_lc_builder import create_lc_from_selected_rows
from skvo_veb.utils.tess_config import TESS_TIMEORIGIN as jd0_tess
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD as jd0
from skvo_veb.volightcurve import VOLightCurve
from skvo_veb.utils.my_tools import (
    safe_none,
    safe_float,
    PipeException,
    sanitize_filename,
    positive_float_pattern,
    float_pattern,
    positive_integer_pattern,
)

register_page(__name__, name='TESS curve',
              order=4,
              path='/tess_lc',
              title='TESS Lightcurve Tool',
              in_navbar=True)

label_font_size = '0.8em'
switch_label_style = {'display': 'inline-block', 'padding': '2px', 'font-size': label_font_size}
switch_label_style_vert = {'display': 'block', 'padding': '2px', 'font-size': label_font_size}
stack_wrap_style = {'marginBottom': '5px', 'flexWrap': 'wrap'}
# periodogram_option_input_style = {'width': '4em'}
periodogram_option_input_style = {'width': '100%'}
periodogram_option_label_style = {'width': '14em', 'font-size': label_font_size}

top_periods_number = 50


# but this "btjd" is not included in the original astropy.time module and appear after including lightkurve only.
# So I decided it would be safer to add this constant explicitly


def layout():
    page_layout = dbc.Container([
        html.H1('TESS Lightcurve Tool', className="text-primary text-left fs-3"),
        dbc.Tabs([
            dbc.Tab(label='Search', children=[
                dbc.Row([
                    dbc.Col([
                        dbc.Stack([
                            dbc.Label('Object', html_for='obj_name_tess_lc_srv_input', style={'width': '7em'}),
                            dcc.Input(id='obj_name_tess_lc_srv_input', persistence=True, type='search',
                                      style={'flexGrow': '1', 'width': 'auto'}),
                            dbc.Button('Resolve', id='resolve_tess_lc_srv_button', size='sm', style={'whiteSpace': 'nowrap'}),
                        ], direction='horizontal', gap=2, style={'marginBottom': '5px'}),
                        dbc.Stack([
                            dbc.Label('RA', html_for='ra_tess_lc_srv_input', style={'width': '7em'}),
                            dcc.Input(id='ra_tess_lc_srv_input', persistence=True, type='search', style={'width': '100%'}),
                        ], direction='horizontal', gap=2, style={'marginBottom': '5px'}),
                        dbc.Stack([
                            dbc.Label('DEC', html_for='dec_tess_lc_srv_input', style={'width': '7em'}),
                            dcc.Input(id='dec_tess_lc_srv_input', persistence=True, type='search', style={'width': '100%'}),
                        ], direction='horizontal', gap=2, style={'marginBottom': '5px'}),
                        dbc.Stack([
                            dbc.Label('Radius', id='radius_tess_lc_srv_lbl', html_for='radius_tess_lc_srv_input',
                                      style={'width': '7em'}),
                            dcc.Input(id='radius_tess_lc_srv_input', persistence=True, type='search',
                                      pattern=positive_float_pattern, value='', placeholder='(arcsec)',
                                      style={'width': '100%'}),
                            dbc.Tooltip('Search radius in arcseconds. If empty, center target is found.', target='radius_tess_lc_srv_lbl', placement='bottom'),
                        ], direction='horizontal', gap=2, style={'marginBottom': '10px'}),
                        dbc.Stack([
                            dbc.Button('Search', id='basic_search_tess_lc_srv_button', size="sm"),
                            dbc.Button('Cancel', id='cancel_basic_search_tess_lc_srv_button',
                                       size="sm", disabled=True),
                            dbc.Button('Clean Cache', id='clean_cache_tess_lc_srv_button', size="sm", color='danger'),
                        ], direction='horizontal', gap=2, style=stack_wrap_style),
                        dbc.Stack([
                            dcc.Upload(
                                id='upload_tess_lc_srv',
                                children=dbc.Button('Upload', size="sm"),
                                multiple=False,
                                # accept='.csv,.fits,.txt',
                                accept=','.join(f'.{ext}' for ext in CurveDash.get_extension_list()),
                            ),
                            dbc.Switch(id='switch_append_tess_lc_srv', label='Append', value=False,
                                       label_style=switch_label_style, persistence=False),
                        ], direction='horizontal', gap=2, style=stack_wrap_style),  # upload
                    ], lg=3, md=4, sm=5, xs=12,
                        style={'padding': '10px', 'background': 'Silver', 'border-radius': '5px'}),
                    # Search tools
                    dbc.Col([
                        dbc.Spinner(children=[
                            html.Div([
                                html.Div([
                                    html.H3("Search results", id="table_tess_lc_srv_header"),
                                    dbc.Stack([
                                        dbc.Button('Download curves', id='download_tess_lc_srv_button', size="sm",
                                                   className="me-2"),
                                        dbc.Button('Purge FITS & redownload', id='purge_redownload_tess_lc_srv_button',
                                                   size="sm", color='warning', className="me-2"),
                                        dbc.Button('Cancel', id='cancel_download_tess_lc_srv_button', size="sm",
                                                   disabled=True),
                                    ], direction='horizontal', gap=2)
                                ], style={
                                    'display': 'flex',
                                    'justifyContent': 'space-between',
                                    'alignItems': 'center',
                                    'width': '100%'
                                }),
                                dag.AgGrid(
                                    id="data_tess_lc_srv_table",
                                    columnDefs=[
                                        {
                                            "field": col,
                                            "headerName": col.capitalize() if col != "#" else "#",
                                            "checkboxSelection": True if col == "#" else False,
                                            "headerCheckboxSelection": True if col == "#" else False,
                                        }
                                        for col in ["#", "mission", "year", "author", "exptime", "target"]
                                    ],
                                    rowData=[],
                                    columnSize="responsiveSizeToFit",
                                    defaultColDef={"filter": True, "sortable": True, "resizable": True},
                                    dashGridOptions={
                                        "theme": "themeBalham",
                                        "rowSelection": "multiple",
                                        "suppressRowClickSelection": True,
                                        "animateRows": True,
                                        "pagination": True,
                                        "paginationPageSize": 10,
                                    },
                                    style={"height": "350px", "width": "100%"}
                                ),
                            ], id="table_tess_lc_srv_row", style={"display": "none"}),  # Search results
                            html.Div(id='div_tess_lc_srv_search_alert', style={"display": "none"}),  # Alert
                        ]),
                    ], lg=9, md=8, sm=7, xs=12),  # SearchResults Table is here
                ], style={'marginBottom': '10px'}),  # Search and SearchResults
                dbc.Spinner(children=[
                    dbc.Label(id="download_tess_lc_srv_result", children='',
                              style={"color": "green", "text-align": "center"}),
                    html.Div(id='div_tess_lc_srv_download_alert', style={"display": "none"}),  # Alert
                ], spinner_style={
                    "align-items": "center",
                    "justify-content": "center",
                }, color="primary",
                ),
            ], tab_id='tess_lc_srv_search_tab'),
            dbc.Tab(label='Plot', children=[
                dbc.Row([
                    dbc.Col([
                        html.Details([
                            html.Summary('Flux options', style={'font-size': label_font_size}),
                            # region fold_it
                            dcc.RadioItems(  # type : ignore
                                id='flux_tess_lc_srv_switch',
                                options=[   # type: ignore
                                    {'label': 'pdc_sap', 'value': 'pdcsap'},
                                    {'label': 'sap', 'value': 'sap'},
                                    {'label': 'default', 'value': 'default'},
                                ],
                                value='pdcsap',
                                labelStyle=switch_label_style,
                            ),
                            # flux type radio
                            dbc.Switch(
                                id='stitch_switch_tess_lc_srv', label='Stitch curves', value=False,
                                label_style=switch_label_style,
                                persistence=True
                            ),  # todo: add callback fired by stitch switch toggle, check it with user curve added
                            # endregion
                        ], style={'marginBottom': '5px'}),  # Flux options
                        dbc.Button('Plot Curve', id='recreate_selected_tess_lc_srv_button', size="sm",
                                   style={'width': '100%', 'marginBottom': '5px'}),
                        html.Details([
                            html.Summary('Folding', style={'font-size': label_font_size}),
                            dbc.Stack([
                                dbc.Label('Period:',
                                          style={'width': '7em', 'font-size': label_font_size}),
                                dcc.Input(id='period_tess_lc_srv_input',
                                          type='search',
                                          inputMode='numeric', persistence=False,
                                          value=None,
                                          pattern=positive_float_pattern,
                                          style={'width': '100%'}),
                            ], direction='horizontal', gap=2, style={'width': '100%', 'min-width': '5ch'}),
                            dbc.Stack([
                                dbc.Label(f'Epoch-{jd0}:', html_for='epoch_tess_lc_srv_input',
                                          style={'width': '7em', 'font-size': label_font_size}),
                                dcc.Input(id='epoch_tess_lc_srv_input', inputMode='numeric', persistence=False,
                                          value=0.0, type='search',
                                          # this particular type places "x" inside an input field
                                          pattern=float_pattern,
                                          style={'width': '100%'},
                                          ),

                            ], direction='horizontal', gap=2, style={'width': '100%', 'min-width': '5ch'}),
                            dbc.Stack([
                                dbc.Switch(id='fold_tess_lc_srv_switch', label='Fold', value=False,
                                           label_style=switch_label_style_vert,
                                           persistence=False, style={'width': '40%'}),
                                dbc.Button('Recalc Phase', id='recalc_phase_tess_lc_srv_button', size="sm",
                                           style={'width': '60%', 'marginBottom': '5px'}),
                            ], direction='horizontal', gap=2),
                            dbc.Button('Shift to min', size='sm', id='shift_epoch_btn_tess_lc_srv',
                                       style={'width': '100%'})
                        ], open=True, style={'marginBottom': '5px'}),  # Folding
                        dbc.Stack([
                            dbc.Select(
                                options=[
                                    {'label': 'VOTable (.vot)', 'value': 'votable'},
                                    {'label': 'ECSV (.ecsv)', 'value': 'ascii.ecsv'},
                                    {'label': 'ASCII Commented Header (.dat)', 'value': 'ascii.commented_header'},
                                    {'label': 'CSV (.csv)', 'value': 'csv'},
                                ],
                                value='votable',
                                id='select_tess_lc_srv_format',
                                style={'width': '40%', 'font-size': label_font_size}
                            ),
                            dbc.Button('Download', id='btn_download_tess_lc_srv', size="sm",
                                       style={'width': '60%'}),
                        ], direction='horizontal', gap=2,
                            style={'width': '100%', 'min-width': '5ch', 'marginBottom': '5px'}),
                        html.Details([
                            html.Summary('Periodogram', style={'font-size': label_font_size}),
                            dcc.RadioItems(
                                id='period_freq_tess_lc_srv_switch',
                                options=[
                                    {'label': 'Period', 'value': 'period'},
                                    {'label': 'Freq', 'value': 'frequency'},
                                ],
                                value='period',
                                persistence=True,
                                labelStyle={'display': 'row', 'padding': '4px', 'font-size': label_font_size},
                            ),  # Period / frequency switch
                            dcc.RadioItems(
                                id='method_tess_lc_srv_switch',
                                options=[
                                    {'label': ' Lomb-Scargle', 'value': 'ls'},
                                    {'label': 'BLS', 'value': 'bls'},
                                ],
                                value='ls',
                                persistence=True,
                                labelStyle={'display': 'row', 'padding': '4px', 'font-size': label_font_size},
                            ),  # Period / frequency switch
                            dbc.Stack([
                                dbc.Label('Period min:', html_for='input_periodogram_min_tess_lc_srv',
                                          style=periodogram_option_label_style),
                                dcc.Input(id='input_periodogram_min_tess_lc_srv', min=0,
                                          value=None,
                                          type='search',
                                          pattern=positive_float_pattern,
                                          style=periodogram_option_input_style),
                            ], direction='horizontal', gap=2,
                                style={'width': '100%', 'min-width': '5ch', 'marginBottom': '5px'}),
                            dbc.Stack([
                                dbc.Label('Period max:', html_for='input_periodogram_max_tess_lc_srv',
                                          style=periodogram_option_label_style),
                                dcc.Input(id='input_periodogram_max_tess_lc_srv', min=0,
                                          value=None,
                                          type='search',
                                          pattern=positive_float_pattern,
                                          style=periodogram_option_input_style),
                            ], direction='horizontal', gap=2,
                                style={'width': '100%', 'min-width': '5ch', 'marginBottom': '5px'}),
                            dbc.Collapse([
                                dbc.Stack([
                                    dbc.Label('Oversample:',
                                              style=periodogram_option_label_style),
                                    dcc.Input(id='input_periodogram_oversample_tess_lc_srv',
                                              value=1, inputMode='numeric',
                                              type='search',  # this particular type places "x" inside an input field
                                              pattern=float_pattern,
                                              style=periodogram_option_input_style),
                                ], direction='horizontal', gap=2,
                                    style={'width': '100%', 'min-width': '5ch', 'marginBottom': '5px'}),  # Oversample
                                dbc.Stack([
                                    dbc.Label('N terms:',
                                              style=periodogram_option_label_style),
                                    dcc.Input(id='input_periodogram_nterms_tess_lc_srv', value=1, min=1,
                                              type='search',
                                              pattern=positive_integer_pattern,
                                              style=periodogram_option_input_style),
                                ], direction='horizontal', gap=2,
                                    style={'width': '100%', 'min-width': '5ch', 'marginBottom': '5px'}),  # N terms
                                dbc.Stack([
                                    dbc.Label('Nyquist factor:',
                                              style=periodogram_option_label_style),
                                    dcc.Input(id='input_nyquist_factor_tess_lc_srv', value=1, min=1,
                                              type='search',
                                              pattern=positive_float_pattern,
                                              style=periodogram_option_input_style),
                                ], direction='horizontal', gap=2,
                                    style={'width': '100%', 'min-width': '5ch',
                                           'marginBottom': '5px'}),  # Nyquist Factor
                                dbc.Stack([
                                    dbc.Label('Normalization:',
                                              style=periodogram_option_label_style),
                                    dcc.RadioItems(
                                        id='pg_normalization_parameter',
                                        options=[
                                            {'label': ' Ampl', 'value': 'amplitude'},
                                            {'label': 'PSD', 'value': 'psd'},
                                        ],
                                        value='amplitude',
                                        persistence=True,
                                        labelStyle={'display': 'row', 'padding': '4px', 'font-size': label_font_size},
                                    ),  # PG Normalization parameter
                                ], direction='horizontal', gap=2,
                                    style={'width': '100%', 'min-width': '5ch', 'marginBottom': '5px'}),  # N terms
                            ], id='option_collapse_tess_lc_srv', is_open=True),  # LS options
                            dbc.Collapse([
                                dbc.Stack([
                                    dbc.Label('Duration:',
                                              style=periodogram_option_label_style),
                                    dcc.Input(id='input_periodogram_duration_tess_lc_srv', value=None, min=0,
                                              type='search',
                                              pattern=positive_float_pattern,
                                              style=periodogram_option_input_style),
                                ], direction='horizontal', gap=2,
                                    style={'width': '100%', 'min-width': '5ch', 'marginBottom': '5px'}),
                                dbc.Stack([
                                    dbc.Label('Freq factor:',
                                              style=periodogram_option_label_style),
                                    dcc.Input(id='input_pg_frequency_factor_tess_lc_srv', value=None,
                                              type='search',
                                              pattern=positive_float_pattern,
                                              style=periodogram_option_input_style),
                                ], direction='horizontal', gap=2,
                                    style={'width': '100%', 'min-width': '5ch', 'marginBottom': '5px'}),
                            ], id='periodogram_bls_option_collapse_tess_lc_srv', is_open=True),  # BLS options
                            dbc.Stack([
                                dbc.Button('Calculate', id='periodogram_tess_lc_srv_button', size="sm",
                                           style={'width': '50%'}),
                                dbc.Button('Cancel', id='cancel_periodogram_tess_lc_srv_button', size="sm",
                                           style={'width': '50%'}, disabled=True),
                            ], direction='horizontal', gap=2, style={'marginBottom': '5px'}),  # periodogram button
                            html.Div([
                                dbc.Stack([
                                    dbc.Label('Select period:',
                                              style={'marginBottom': 0, 'font-size': label_font_size}),
                                    dcc.Dropdown(
                                        id='tess_lc_srv_select_period_dropdown',
                                        options=np.arange(1, top_periods_number + 1, 1),
                                        clearable=False,
                                    ),
                                ], direction='horizontal', gap=2, style={'marginBottom': '5px'}),
                                # dbc.Button('Use Period', id='use_period_btn', size='sm')
                            ], id='tess_lc_srv_periodogram_results_row',
                                style={'display': 'none'}),  # periodogram results
                        ], style={'marginBottom': '5px'}),  # Periodogram
                    ], lg=2, md=3, sm=4, xs=12,
                        style={'padding': '10px', 'background': 'Silver', 'border-radius': '5px'}),  # Tools
                    dbc.Col([
                        html.Div(children='', id='div_tess_lc_srv_alert', style={'display': 'none'}),
                        dbc.Row([
                            dcc.Graph(id='graph_tess_lc_srv',
                                      figure=px.scatter(),
                                      config={'displaylogo': False},
                                      # style={'height': '40vh', 'width': '100%'},  # 100% of the viewport height
                                      ),
                        ]),
                        html.Div([
                            dcc.Graph(
                                id='graph_tess_lc_srv_periodogram',
                                figure=px.scatter(),
                                config={'displaylogo': False}
                            )
                        ], id='tess_lc_srv_periodogram_row', style={'display': 'none'}),
                        # ], id='tess_lc_srv_periodogram_row', style={'display': 'none'})  # periodogram

                    ], lg=10, md=9, sm=8, xs=12),  # Graph
                ], style={'marginBottom': '10px'}),
            ], tab_id='tess_lc_srv_graph_tab', id='tess_lc_srv_graph_tab', disabled=False),
        ], active_tab='tess_lc_srv_search_tab', id='tess_lc_srv_tabs', style={'marginBottom': '5px'}),
        dcc.Store(id='store_user_tab_id_tess_lc_srv', **SESSION_STORE),
        dcc.Store(id='store_tess_lightcurve_lc_srv', **SESSION_STORE),
        dcc.Store(id='store_tess_lightcurve_lc_srv_metadata', **SESSION_STORE),
        dcc.Store(id='store_tess_lc_search_result', **SESSION_STORE),
        dcc.Store(id='store_tess_periodogram_result_lc_srv', **SESSION_STORE),
        dcc.Store(id='store_resolved_coords_tess_lc_srv', **SESSION_STORE),
        dcc.Download(id='download_tess_lc_srv_lightcurve'),
    ],
        className="g-10", fluid=True, style={'display': 'flex', 'flexDirection': 'column'})
    return page_layout


if not DISK_CACHE and __name__ == '__main__':  # local version without diskcache
    background_callback = False
else:
    background_callback = True


@callback(
    Output('option_collapse_tess_lc_srv', 'is_open'),
    Output('periodogram_bls_option_collapse_tess_lc_srv', 'is_open'),
    Input('method_tess_lc_srv_switch', 'value')
)
def toggle_pg_option_collapse(method):
    if method == 'ls':
        return True, False
    return False, True


@callback(
    output=dict(
        ra=Output('ra_tess_lc_srv_input', 'value', allow_duplicate=True),
        dec=Output('dec_tess_lc_srv_input', 'value', allow_duplicate=True),
        resolved_coords=Output('store_resolved_coords_tess_lc_srv', 'data'),
        alert_message=Output('div_tess_lc_srv_search_alert', 'children', allow_duplicate=True),
        alert_style=Output('div_tess_lc_srv_search_alert', 'style', allow_duplicate=True),
    ),
    inputs=dict(n_clicks=Input('resolve_tess_lc_srv_button', 'n_clicks')),
    state=dict(
        obj_name=State('obj_name_tess_lc_srv_input', 'value')
    ),
    prevent_initial_call=True
)
def resolve_coordinates_lc_srv(n_clicks, obj_name):
    if n_clicks is None:
        raise PreventUpdate

    output = {
        'ra': dash.no_update,
        'dec': dash.no_update,
        'resolved_coords': dash.no_update,
        'alert_message': '',
        'alert_style': {'display': 'none'}
    }

    if not obj_name or not obj_name.strip():
        output['alert_message'] = message.warning_alert("Please enter an object name first.")
        output['alert_style'] = {'display': 'block'}
        return output

    try:
        ra, dec = tess_processor.resolve_object_coordinates(obj_name)
        output['ra'] = ra
        output['dec'] = dec
        output['resolved_coords'] = {'obj_name': obj_name.strip(), 'ra': ra, 'dec': dec}
    except Exception as e:
        logging.warning(f"lightcurve_tess_srv.resolve_coordinates error: {e}")
        output['alert_message'] = message.warning_alert(e)
        output['alert_style'] = {'display': 'block'}

    return output


@callback(
    output=dict(
        alert_message=Output('div_tess_lc_srv_search_alert', 'children', allow_duplicate=True),
        alert_style=Output('div_tess_lc_srv_search_alert', 'style', allow_duplicate=True),
    ),
    inputs=dict(n_clicks=Input('clean_cache_tess_lc_srv_button', 'n_clicks')),
    state=dict(
        obj_name=State('obj_name_tess_lc_srv_input', 'value'),
        ra=State('ra_tess_lc_srv_input', 'value'),
        dec=State('dec_tess_lc_srv_input', 'value'),
        radius=State('radius_tess_lc_srv_input', 'value'),
        resolved_coords=State('store_resolved_coords_tess_lc_srv', 'data'),
    ),
    prevent_initial_call=True
)
def handle_clean_cache_lc_srv(n_clicks, obj_name, ra, dec, radius, resolved_coords):
    if n_clicks is None:
        raise PreventUpdate

    try:
        target, search_mode = tess_processor.resolve_search_target(obj_name, ra, dec, resolved_coords)
    except PipeException as e:
        return {
            'alert_message': message.warning_alert(e),
            'alert_style': {'display': 'block'}
        }

    try:
        rad_val = float(radius) if radius else None
    except ValueError:
        rad_val = None

    try:
        deleted_count = cache.delete_target_cache(target, radius=rad_val)
        msg_text = f"Cache cleaned successfully for '{target}'. {deleted_count} cached file(s) deleted."
        logger.info(f"handle_clean_cache_lc_srv: {msg_text}")
        return {
            'alert_message': message.info_alert(msg_text),
            'alert_style': {'display': 'block'}
        }
    except Exception as e:
        err_msg = f"Failed to clean cache for '{target}': {e}"
        logger.error(f"handle_clean_cache_lc_srv: {err_msg}", exc_info=True)
        return {
            'alert_message': message.warning_alert(err_msg),
            'alert_style': {'display': 'block'}
        }


@callback(
    output=dict(
        table_header=Output('table_tess_lc_srv_header', "children"),
        metadata=Output('store_tess_lightcurve_lc_srv_metadata', 'data'),
        search_store=Output('store_tess_lc_search_result', 'data'),
        table_data=Output("data_tess_lc_srv_table", "rowData"),
        selected_rows=Output("data_tess_lc_srv_table", "selectedRows"),
        content_style=Output("table_tess_lc_srv_row", "style"),  # to show the table and Title
        alert_message=Output('div_tess_lc_srv_search_alert', 'children', allow_duplicate=True),
        alert_style=Output('div_tess_lc_srv_search_alert', 'style', allow_duplicate=True),
        ra_out=Output('ra_tess_lc_srv_input', 'value', allow_duplicate=True),
        dec_out=Output('dec_tess_lc_srv_input', 'value', allow_duplicate=True),
        resolved_out=Output('store_resolved_coords_tess_lc_srv', 'data', allow_duplicate=True),
    ),
    inputs=dict(n_clicks=Input('basic_search_tess_lc_srv_button', 'n_clicks')),
    state=dict(
        obj_name=State('obj_name_tess_lc_srv_input', 'value'),
        ra=State('ra_tess_lc_srv_input', 'value'),
        dec=State('dec_tess_lc_srv_input', 'value'),
        radius=State('radius_tess_lc_srv_input', 'value'),
        resolved_coords=State('store_resolved_coords_tess_lc_srv', 'data'),
    ),
    running=[(Output('basic_search_tess_lc_srv_button', 'disabled'), True, False),
             (Output('cancel_basic_search_tess_lc_srv_button', 'disabled'), False, True)],
    cancel=[Input('cancel_basic_search_tess_lc_srv_button', 'n_clicks')],
    background=background_callback,
    prevent_initial_call=True
)
def basic_search(n_clicks, obj_name, ra, dec, radius, resolved_coords):
    if n_clicks is None:
        raise PreventUpdate

    output_keys = list(ctx.outputs_grouping.keys())
    output = {key: dash.no_update for key in output_keys}
    output['ra_out'] = dash.no_update
    output['dec_out'] = dash.no_update
    output['resolved_out'] = dash.no_update

    try:
        target, search_mode = tess_processor.resolve_search_target(obj_name, ra, dec, resolved_coords)
    except PipeException as e:
        output['alert_message'] = message.warning_alert(e)
        output['alert_style'] = {'display': 'block'}
        output['selected_rows'] = []
        output['content_style'] = {'display': 'none'}
        return output

    clear_stray_coords = (
        search_mode == 'object_name'
        and obj_name and str(obj_name).strip()
        and (tess_processor.has_coord(ra) or tess_processor.has_coord(dec))
    )
    if clear_stray_coords:
        output['ra_out'] = ''
        output['dec_out'] = ''
        output['resolved_out'] = None

    try:
        rad_val = float(radius) if radius else None
    except ValueError:
        output['alert_message'] = message.warning_alert("Radius must be a valid positive number.")
        output['alert_style'] = {'display': 'block'}
        output['selected_rows'] = []
        output['content_style'] = {'display': 'none'}
        return output

    try:
        logger.info(f"lightcurve_tess_srv.basic_search: Starting metadata search. mode={search_mode}, target={target!r}, radius={rad_val!r}")
        search_lcf, native_id = tess_lc_search.search_lightcurves_cached(
            target=target,
            radius=rad_val,
            search_mode=search_mode,
            resolved_coords=resolved_coords,
        )
        repr(search_lcf)  # Fill the internal '#' column if needed

        data = []
        for row in search_lcf.table:
            data.append({
                '#': row['#'],
                'mission': row['mission'],
                'year': row['year'],
                'target': row["target_name"],
                "author": row["author"],
                "exptime": row["exptime"]
            })
        if data:
            display_name = str(obj_name).strip() if obj_name and str(obj_name).strip() else target
            target_id = native_id if native_id else (data[0].get('target', '') if data else '')
            if target_id:
                target_id_str = str(target_id).strip()
                if target_id_str.isdigit():
                    target_id_str = f"TIC {target_id_str}"
                else:
                    # Replace colons with spaces so the user can easily copy and paste (e.g. "TIC:159717514" -> "TIC 159717514")
                    target_id_str = target_id_str.replace(":", " ")
                
                if display_name.lower() != target_id_str.lower():
                    display_title = f"{display_name} ({target_id_str})"
                else:
                    display_title = display_name
            else:
                display_title = display_name
            output['table_header'] = display_title
            output['metadata'] = {'lookup_name': display_name, 'native_id': native_id}
            output['search_store'] = {
                'native_id': native_id,
                'search_result': search_lcf.table.to_pandas().to_dict(),
            }
            output['table_data'] = data
            output['selected_rows'] = []  # start without any selection
            output['content_style'] = {'display': 'block'}  # show the table with search results
            output['alert_message'] = ''
            output['alert_style'] = {'display': 'none'}  # hide alert
        else:
            raise PipeException('No data found')
    except Exception as e:
        logging.warning(f'tess_lightcurve.search: {e}')
        output['selected_rows'] = []
        output['alert_message'] = message.warning_alert(e)
        output['alert_style'] = {'display': 'block'}  # show the alert
        output['content_style'] = {'display': 'none'}  # hide empty or wrong table

    return output


@callback(
    output=dict(
        table_header=Output('table_tess_lc_srv_header', "children", allow_duplicate=True),
        table_data=Output("data_tess_lc_srv_table", "rowData", allow_duplicate=True),
        content_style=Output("table_tess_lc_srv_row", "style", allow_duplicate=True),
    ),
    inputs=dict(
        search_store=Input('store_tess_lc_search_result', 'data'),
        metadata=Input('store_tess_lightcurve_lc_srv_metadata', 'data'),
    ),
    prevent_initial_call='initial_duplicate',
)
def restore_lc_srv_search_table(search_store, metadata):
    rows = table_rows_from_lk_search_dict(search_store)
    if not rows:
        raise PreventUpdate
    lookup_name = (metadata or {}).get('lookup_name', '')
    native_id = (metadata or {}).get('native_id', '')
    if native_id:
        target_id_str = str(native_id).strip().replace(':', ' ')
        if target_id_str.isdigit():
            target_id_str = f'TIC {target_id_str}'
        if lookup_name and lookup_name.lower() != target_id_str.lower():
            table_header = f'{lookup_name} ({target_id_str})'
        else:
            table_header = lookup_name or target_id_str
    else:
        table_header = lookup_name
    return {
        'table_header': table_header,
        'table_data': rows,
        'content_style': {'display': 'block'},
    }


@callback(
    Output('tess_lc_srv_graph_tab', 'disabled', allow_duplicate=True),
    Output('tess_lc_srv_tabs', 'active_tab', allow_duplicate=True),
    Input('store_user_tab_id_tess_lc_srv', 'data'),
    prevent_initial_call='initial_duplicate',
)
def restore_lc_srv_tabs(user_tab_id):
    if not user_tab_id:
        raise PreventUpdate
    user_key = _compose_user_key(user_tab_id)
    if user_cache.get(user_key, default=None) is None:
        raise PreventUpdate
    return False, 'tess_lc_srv_graph_tab'


def _compose_user_key(user_tab_id):
    return f'{user_tab_id}_data'


def extract_data_from_user_cache(user_tab_id):
    if user_tab_id is None:
        raise PipeException('Please, download light curve first')
    user_key = _compose_user_key(user_tab_id)
    user_data = user_cache.get(user_key, default=None)
    if user_data is None:  # m.b user's cache has been expired and deleted
        logging.warning(f'lightcurve_tess: extract_data_from_user_cache time={time.time()} {user_tab_id=}')
        raise PipeException('Please, download light curve. User\'s cache is empty')
    # Implement sliding expiration:
    user_cache.set(user_key, user_data, expire=86400)  # Refresh the expiration time on read
    return user_data


def plot_lc(js_lightcurve: str, phase_view: bool):
    lcd = CurveDash.from_serialized(js_lightcurve)
    title = build_curvedash_title(lcd)
    phot_unit = lcd.phot_unit
    y_column = 'mag' if lcd.active_domain == 'mag' else 'flux'
    y_label = 'magnitude' if lcd.active_domain == 'mag' else 'flux'

    if phase_view:
        x = lcd.phase
        x_column = 'phase'
        xaxis_title = 'phase'
    else:
        x = lcd.jd - jd0
        x_column = 'jd'
        xaxis_title = f'jd-{jd0}, {safe_none(lcd.time_unit)} {lcd.timescale}'

    label_series = lcd.lightcurve['label'] if lcd.lightcurve is not None else lcd.label
    df = pd.concat([x, lcd.phot, label_series, lcd.perm_index], axis=1)
    df.columns = [x_column, y_column, 'label', 'perm_index']
    fig = px.scatter(df,
                     x=x_column,
                     y=y_column,
                     color='label',
                     custom_data='perm_index')
    fig.update_traces(
        selected={'marker': {'color': 'orange', 'size': 5}},
        hoverinfo='none',  # Important
        hovertemplate=None,  # Important
        mode='markers',
        marker=dict(size=3, symbol='circle')
        # marker=dict(color='blue', size=5, symbol='circle')
    )

    fig.update_layout(
        title=title,
        # showlegend=False,
        legend_title_text='Sector',
        margin=dict(l=0, b=20, t=30, r=20),
        xaxis_title=xaxis_title,
        yaxis_title=f'{y_label}, {safe_none(phot_unit)}'
    )
    # fig = go.Figure()

    # fig.add_trace(go.Scatter(
    #     x=x, y=lcd.flux,
    #     error_y=dict(type='data', array=lcd.flux_err, visible=True),
    #     selected={'marker': {'color': 'orange', 'size': 5}},
    #     hoverinfo='none',  # Important
    #     hovertemplate=None,
    #     # mode='markers+lines',
    #     mode='markers',
    #     marker=dict(color='blue', size=6, symbol='circle'),
    #     # line=dict(color='blue', width=1)  # , dash='dash')
    # ))

    return fig


# @callback(
#     Output('store_tess_lightcurve_lc_srv', 'data', allow_duplicate=True),
#     Input('fold_tess_lc_srv_switch', 'value'),
#     State('store_tess_lightcurve_lc_srv', 'data'),
#     State('period_tess_lc_srv_input', 'value'),
#     prevent_initial_call=True
# )
# def fold(fold_lc, js_lightcurve: str, period):
#     period_unit = 'd'
#     # if n_clicks is None:
#     #     raise PreventUpdate
#     lcd = CurveDash.from_serialized(js_lightcurve)
#     lcd.folded_view = fold_lc
#     lcd.period = period
#     lcd.period_unit = period_unit
#     return lcd.serialize()


@callback(
    output=dict(lc=Output('store_tess_lightcurve_lc_srv', 'data', allow_duplicate=True)),  # dummy
    inputs=dict(n_clicks=Input('recreate_selected_tess_lc_srv_button', 'n_clicks'), ),
    state=dict(
        user_tab_id=State('store_user_tab_id_tess_lc_srv', 'data'),
        selected_rows=State('data_tess_lc_srv_table', 'selectedRows'),
        table_data=State('data_tess_lc_srv_table', 'data'),
        stitch=State('stitch_switch_tess_lc_srv', 'value'),
        flux_method=State('flux_tess_lc_srv_switch', 'value'),
        metadata=State('store_tess_lightcurve_lc_srv_metadata', 'data'),
        search_store=State('store_tess_lc_search_result', 'data'),
        phase_view=State('fold_tess_lc_srv_switch', 'value'),
        period=State('period_tess_lc_srv_input', 'value'),
        epoch=State('epoch_tess_lc_srv_input', 'value')
    ),
    prevent_initial_call=True
)
def replot_selected_curves(n_clicks, user_tab_id, selected_rows, table_data, stitch, flux_method, metadata,
                           search_store, phase_view, period, epoch):
    if n_clicks is None:
        raise PreventUpdate
    try:
        epoch = safe_float(epoch, 0)
        period = safe_float(period)
        epoch = epoch + jd0 if epoch else epoch
        lc = create_lc_from_selected_rows(selected_rows, table_data, stitch, flux_method, metadata,
                                          phase_view, period, epoch, search_store=search_store)
        # write it to server user cache
        write_user_data_to_cache(lc, user_tab_id)

        set_props('div_tess_lc_srv_alert', {'children': None, 'style': {'display': 'none'}})
        output = {'lc': str(uuid.uuid4())}  # trigger dependent callbacks
        return output

    except Exception as e:
        logging.warning(f'lightcurve_tess.replot_selected_curves: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_lc_srv_alert', {'children': alert_message, 'style': {'display': 'block'}})
        return dash.no_update


@callback(
    Output('store_tess_lightcurve_lc_srv', 'data', allow_duplicate=True),  # dummy
    Output('epoch_tess_lc_srv_input', 'value', allow_duplicate=True),
    Input('shift_epoch_btn_tess_lc_srv', 'n_clicks'),
    State('store_user_tab_id_tess_lc_srv', 'data'),
    # State('store_tess_lightcurve_lc_srv', 'data'),  # dummy
    State('period_tess_lc_srv_input', 'value'),
    State('epoch_tess_lc_srv_input', 'value'),
    prevent_initial_call=True)
def shift_to_minimum(n_clicks, user_tab_id, period, epoch):
    if n_clicks is None:
        raise PreventUpdate
    try:
        period = safe_float(period)
        epoch = safe_float(epoch, 0)
        if period is None:
            raise PipeException('Set the period and try again')
        if epoch is None:
            epoch = 0
        js_lightcurve = extract_data_from_user_cache(user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        if lcd.lightcurve is None:
            raise PipeException('shift_to_minimum: Please, download curves first')
        lcd.period = period
        lcd.epoch = epoch + jd0
        # phi_min = lcd.find_phase_of_min_simple()
        phi_min = lcd.find_phase_of_min_gauss()
        logging.debug(f'{phi_min=}')
        new_epoch = lcd.shift_epoch(phi_min)
        lcd.epoch = new_epoch
        lcd.recalc_phase()
        set_props('div_tess_lc_srv_alert', {'children': None, 'style': {'display': 'none'}})
        write_user_data_to_cache(lcd.serialize(), user_tab_id)
        dummy_lc = str(uuid.uuid4())  # trigger dependent callbacks; return a string → JSON-serializable
        return dummy_lc, new_epoch - jd0
    except Exception as e:
        logging.warning(f'lightcurve_tess.shift_to_minimum: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_lc_srv_alert', {'children': alert_message, 'style': {'display': 'block'}})
        return dash.no_update, dash.no_update


# @callback(Output('fold_tess_lc_srv_switch', 'value'),
#           Input('fold_tess_lc_srv_switch', 'value'),
#           State('period_tess_lc_srv_input', 'value'),
#           State('epoch_tess_lc_srv_input', 'value'),
#           prevent_initial_call=True
#           )
# def fold(phase_view, period, epoch):
#     if not phase_view:
#         return dash.no_update
#     try:
#         epoch = safe_float(epoch, 0)
#         period = safe_float(period)
#         if phase_view and not period:
#             raise PipeException('Set the period and try again')
#         return dash.no_update
#     except Exception as e:
#         logging.warning(f'lightcurve_tess.fold: {e}')
#         alert_message = message.warning_alert(e)
#         set_props('div_tess_lc_srv_alert', {'children': alert_message, 'style': {'display': 'block'}})
#         return False


# Switch between folded and time view. Recalculate phases if needed
# todo: think about restoring this functionality, but bear in mind, that this callback is fired by set_props()
# @callback([Output('store_tess_lightcurve_lc_srv', 'data', allow_duplicate=True),  # dummy
#            Output('fold_tess_lc_srv_switch', 'value')],
#           Input('fold_tess_lc_srv_switch', 'value'),
#           State('store_tess_lightcurve_lc_srv', 'data'),
#           State('period_tess_lc_srv_input', 'value'),
#           State('epoch_tess_lc_srv_input', 'value'),
#           prevent_initial_call=True
#           )
# def fold(phase_view, js_lightcurve, period, epoch):
#     pass
#     try:
#         epoch = safe_float(epoch, 0)
#         period = safe_float(period)
#         if phase_view and not period:
#             raise PipeException('Set the period and try again')
#         lcd = CurveDash.from_serialized(js_lightcurve)
#         if lcd.lightcurve is None:
#             raise PipeException('fold: Please, download curves first')
#         if phase_view:
#             lcd.period = period
#             period_unit = 'd'
#             lcd.period_unit = period_unit
#             if epoch:
#                 lcd.epoch = epoch + jd0
#             lcd.recalc_phase()
#         lcd.folded_view = phase_view
#         set_props('div_tess_lc_srv_alert', {'children': None, 'style': {'display': 'none'}})
#         return lcd.serialize(), dash.no_update
#     except Exception as e:
#         logging.warning(f'lightcurve_tess.fold: {e}')
#         alert_message = message.warning_alert(e)
#         set_props('div_tess_lc_srv_alert', {'children': alert_message, 'style': {'display': 'block'}})
#         return dash.no_update, False

# fold it here


@callback(
    [Output('store_tess_lightcurve_lc_srv', 'data', allow_duplicate=True),  # dummy
     Output('fold_tess_lc_srv_switch', 'value')],
    [Input('recalc_phase_tess_lc_srv_button', 'n_clicks'),
     Input('fold_tess_lc_srv_switch', 'value')],
    [State('store_user_tab_id_tess_lc_srv', 'data'),
     State('period_tess_lc_srv_input', 'value'),
     State('epoch_tess_lc_srv_input', 'value')],
    prevent_initial_call=True)
def fold_or_recalculate_phase(n_clicks, phase_view, user_tab_id, period, epoch):
    # todo: rewrite it on the client side ???
    if ctx.triggered_id == 'recalc_phase_tess_lc_srv_button' and n_clicks is None:
        raise PreventUpdate
    # if ctx.triggered_id == 'fold_tess_lc_srv_switch' and not phase_view:
    #     raise PreventUpdate
    try:
        epoch = safe_float(epoch, 0)
        period = safe_float(period)
        if phase_view and not period:
            raise PipeException('Set the period and try again')
        js_lightcurve = extract_data_from_user_cache(user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        if lcd.lightcurve is None:
            raise PipeException('recalculate_phase: Please, download curves first')
        if period:
            lcd.period = period
            period_unit = 'd'
            lcd.period_unit = period_unit
        if epoch:
            lcd.epoch = epoch + jd0

        lcd.recalc_phase()
        dummy_lc = str(uuid.uuid4())  # trigger dependent callbacks; return a string → JSON-serializable
        write_user_data_to_cache(lcd.serialize(), user_tab_id)
        set_props('div_tess_lc_srv_alert', {'children': None, 'style': {'display': 'none'}})
        return dummy_lc, dash.no_update
    except Exception as e:
        logging.warning(f'lightcurve_tess.recalculate_phase: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_lc_srv_alert', {'children': alert_message, 'style': {'display': 'block'}})
        return dash.no_update, False


@callback(Output('graph_tess_lc_srv', 'figure', allow_duplicate=True),
          Input('store_tess_lightcurve_lc_srv', 'data'),
          Input('store_user_tab_id_tess_lc_srv', 'data'),
          State('fold_tess_lc_srv_switch', 'value'),
          prevent_initial_call='initial_duplicate',
          )
def plot_tess_curve(_, user_tab_id, phase_view):
    if not user_tab_id:
        raise PreventUpdate
    user_key = _compose_user_key(user_tab_id)
    if user_cache.get(user_key, default=None) is None:
        raise PreventUpdate
    try:
        js_lightcurve = extract_data_from_user_cache(user_tab_id)
        fig = plot_lc(js_lightcurve, phase_view)
        set_props('div_tess_lc_srv_alert', {'children': None, 'style': {'display': 'none'}})
        return fig
    except Exception as e:
        logging.warning(f'lightcurve_tess.plot_tess_curve: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_lc_srv_alert', {'children': alert_message, 'style': {'display': 'block'}})
        return dash.no_update


@callback(
    output=dict(
        pg_fig=Output('graph_tess_lc_srv_periodogram', 'figure'),
        pg_row_style=Output('tess_lc_srv_periodogram_row', 'style'),
        periodogram_result_store=Output('store_tess_periodogram_result_lc_srv', 'data'),
        results_row_style=Output('tess_lc_srv_periodogram_results_row', 'style'),
    ),
    inputs=dict(n_clicks=Input('periodogram_tess_lc_srv_button', 'n_clicks')),
    state=dict(
        # js_lightcurve=State('store_tess_lightcurve_lc_srv', 'data'),
        user_tab_id=State('store_user_tab_id_tess_lc_srv', 'data'),
        period_freq=State('period_freq_tess_lc_srv_switch', 'value'),
        method=State('method_tess_lc_srv_switch', 'value'),
        nterms=State('input_periodogram_nterms_tess_lc_srv', 'value'),
        oversample=State('input_periodogram_oversample_tess_lc_srv', 'value'),
        p_min=State('input_periodogram_min_tess_lc_srv', 'value'),
        p_max=State('input_periodogram_max_tess_lc_srv', 'value'),
        duration=State('input_periodogram_duration_tess_lc_srv', 'value'),
        nyquist_factor=State('input_nyquist_factor_tess_lc_srv', 'value'),
        normalization=State('pg_normalization_parameter', 'value'),
        frequency_factor=State('input_pg_frequency_factor_tess_lc_srv', 'value')
    ),
    background=background_callback,
    running=[(Output('periodogram_tess_lc_srv_button', 'disabled'), True, False),
             (Output('cancel_periodogram_tess_lc_srv_button', 'disabled'), False, True)],
    cancel=[Input('cancel_periodogram_tess_lc_srv_button', 'n_clicks')],
    prevent_initial_call=True)
def periodogram(n_clicks, user_tab_id, period_freq, method, nterms, oversample,
                p_min, p_max, duration, nyquist_factor, normalization, frequency_factor):
    import warnings
    from scipy.signal import find_peaks

    if not n_clicks:
        raise PreventUpdate

    output_keys = list(ctx.outputs_grouping.keys())
    output = {key: dash.no_update for key in output_keys}

    try:
        lcd = CurveDash.from_serialized(extract_data_from_user_cache(user_tab_id))
        if lcd.lightcurve is None:
            raise PipeException('periodogram: Please, download curves first')
        if lcd.active_domain != 'flux' or lcd.flux is None:
            raise PipeException(
                'Periodogram requires flux-domain data. Convert the lightcurve to flux first.'
            )
        kurve = lightkurve.LightCurve(time=lcd.jd, flux=lcd.flux, flux_err=lcd.flux_err)

        if method == 'ls':
            kwargs = dict(method=method, oversample_factor=safe_float(oversample, None),
                          minimum_period=safe_float(p_min, None),
                          maximum_period=safe_float(p_max, None),
                          nterms=safe_float(nterms, 1),
                          nyquist_factor=safe_float(nyquist_factor, 1),
                          normalization=normalization
                          )
        else:  # BLS
            try:
                # The set of the transit durations (in days) that will be considered.
                # Default to `[0.05, 0.10, 0.15, 0.20, 0.25, 0.33]` if not specified
                duration_list = [float(x.strip()) for x in duration.split(',')]
            except Exception as e:
                logging.warning(f'Periodogram: {str(e)}')
                duration_list = None
            if duration_list is None:
                kwargs = dict(method=method,
                              minimum_period=safe_float(p_min, None),
                              maximum_period=safe_float(p_max, None),
                              frequency_factor=safe_float(frequency_factor, 10))
            else:
                kwargs = dict(method=method,
                              minimum_period=safe_float(p_min, None),
                              maximum_period=safe_float(p_max, None),
                              frequency_factor=safe_float(frequency_factor, 10),
                              duration=duration_list)
        # Turn specified warnings into exceptions. It's pretty useful when working with the lightkurve module
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', RuntimeWarning)
                pg = kurve.to_periodogram(**kwargs)  # Will raise an exception on divide-by-zero
                # Extract top 5 periods:
                distance = max(len(pg.power) // 100, 1)
                peaks, _ = find_peaks(pg.power, distance=distance)
                sorted_peaks = peaks[np.argsort(pg.power[peaks])[::-1]]
                top_periods = pg.period[sorted_peaks[:top_periods_number]].value
                output['periodogram_result_store'] = top_periods
        except RuntimeWarning as e:
            raise PipeException(f'Periodogram computation failed: {str(e)}')
        if period_freq == 'frequency':
            x = pg.frequency
            xaxis_title = 'Frequency, 1/d'
            xaxis_type = 'linear'
        else:
            x = pg.period
            xaxis_title = 'Period, d'
            xaxis_type = 'log'

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=x, y=pg.power,
            # hoverinfo='none',  # Important
            hovertemplate='%{x:.4f}<extra></extra>',
            # %{x:.4f}: x-format; <extra></extra>: removes the default trace info
            mode='lines',
            # mode='markers',
            # marker=dict(color='blue', size=6, symbol='circle'),
            line=dict(color='blue', width=1)  # , dash='dash')
        ))

        title = f'Periodogram {lcd.lookup_name} {lcd.name}'
        fig.update_layout(
            title=title,
            showlegend=False,
            margin=dict(l=0, b=20, t=30, r=20),
            xaxis_type=xaxis_type,
            xaxis_title=xaxis_title,
            yaxis_title='Power'
        )
        output['pg_fig'] = fig
        output['pg_row_style'] = {'display': 'block'}
        output['results_row_style'] = {'display': 'block'}
        set_props('div_tess_lc_srv_alert', {'children': None, 'style': {'display': 'none'}})
    except Exception as e:
        logging.warning(f'lightcurve_tess.periodogram: {e}')
        output['results_row_style'] = {'display': 'none'}
        output['pg_row_style'] = {'display': 'none'}
        alert_message = message.warning_alert(e)
        set_props('div_tess_lc_srv_alert', {'children': alert_message, 'style': {'display': 'block'}})

    return output


# ----------- The clientside part ---------

# Plot light curve
# clientside_callback(
#     ClientsideFunction(
#         namespace='clientside',
#         function_name='plotLightcurveFromStore'
#     ),
#     Output('graph_tess_lc_srv', 'figure'),
#     Input('store_tess_lightcurve_lc_srv', 'data'),
#     State('graph_tess_lc_srv', 'figure'),
#     prevent_initial_call=True
# )

# # Switch between folded and time view. All phases have been recalculated already
# clientside_callback(
#     ClientsideFunction(
#         namespace='clientside',
#         function_name='updateFoldedView'
#     ),
#     Output('store_tess_lightcurve_lc_srv', 'data', allow_duplicate=True),
#     Input('fold_tess_lc_srv_switch', 'value'),
#     State('store_tess_lightcurve_lc_srv', 'data'),
#     prevent_initial_call=True
# )

# Mark data as selected
clientside_callback(
    ClientsideFunction(
        namespace='clientside',
        function_name='selectData'
    ),
    Output('store_tess_lightcurve_lc_srv', 'data', allow_duplicate=True),
    Input('graph_tess_lc_srv', 'selectedData'),
    Input('graph_tess_lc_srv', 'clickData'),
    State('store_tess_lightcurve_lc_srv', 'data'),
    prevent_initial_call=True
)


# Unmark data
# clientside_callback(
#     ClientsideFunction(
#         namespace='clientside',
#         function_name='unselectData'
#     ),
#     Output('store_tess_lightcurve_lc_srv', 'data', allow_duplicate=True),
#     Input('btn_tess_unselect', 'n_clicks'),
#     State('store_tess_lightcurve_lc_srv', 'data'),
#     prevent_initial_call=True
# )


# Delete selected points
# clientside_callback(
#     ClientsideFunction(
#         namespace='clientside',
#         function_name='deleteSelected'
#     ),
#     Output('store_tess_lightcurve_lc_srv', 'data', allow_duplicate=True),
#     Input('btn_tess_delete', 'n_clicks'),
#     State('store_tess_lightcurve_lc_srv', 'data'),
#     prevent_initial_call=True
# )


def write_user_data_to_cache(user_data, user_tab_id):
    user_key = _compose_user_key(user_tab_id)
    user_cache.set(user_key, user_data,
                   expire=86400)  # in seconds todo: check and change it
    logging.info(f'lightcurve_tess: write_user_data_to_cache time={time.time()}')


def generate_user_tab_id():
    user_tab_id = str(uuid.uuid4())  # Generate a unique tab_id
    logging.info(f'Generated new tab_id: {user_tab_id}')
    return user_tab_id


@callback(
    output=dict(
        message_results=Output('download_tess_lc_srv_result', 'children', allow_duplicate=True),
        alert_message=Output('div_tess_lc_srv_search_alert', 'children', allow_duplicate=True),
        alert_style=Output('div_tess_lc_srv_search_alert', 'style', allow_duplicate=True),
    ),
    inputs=dict(n_clicks=Input('purge_redownload_tess_lc_srv_button', 'n_clicks')),
    state=dict(
        selected_rows=State('data_tess_lc_srv_table', 'selectedRows'),
        search_store=State('store_tess_lc_search_result', 'data'),
    ),
    running=[(Output('purge_redownload_tess_lc_srv_button', 'disabled'), True, False)],
    background=background_callback,
    prevent_initial_call=True,
)
def purge_redownload_selected_rows(n_clicks, selected_rows, search_store):
    if n_clicks is None:
        raise PreventUpdate

    if not selected_rows:
        return {
            'message_results': '',
            'alert_message': message.warning_alert('Select at least one table row to purge and redownload.'),
            'alert_style': {'display': 'block'},
        }

    try:
        search_result = tess_lc_search.restore_search_result(search_store)
        summaries = []
        for row in selected_rows:
            row_idx = row['#']
            was_purged, lc = lightkurve_cache.purge_and_redownload_row(search_result, row_idx)
            label = getattr(lc, 'LABEL', None) or f'sector {getattr(lc, "SECTOR", "?")}'
            action = 'purged and redownloaded' if was_purged else 'redownloaded (no local cache file found)'
            summaries.append(f'Row {row_idx}: {action} — {label}')
            logger.info(f"purge_redownload_selected_rows: Completed row {row_idx}: {action}")

        msg = 'Fresh MAST download completed:\n' + '\n'.join(summaries)
        logging.info(f'purge_redownload_selected_rows: {msg}')
        return {
            'message_results': msg,
            'alert_message': message.info_alert(msg),
            'alert_style': {'display': 'block'},
        }
    except Exception as exc:
        logging.error(f'purge_redownload_selected_rows failed: {exc}', exc_info=True)
        return {
            'message_results': '',
            'alert_message': message.warning_alert(exc),
            'alert_style': {'display': 'block'},
        }


@callback(
    output=dict(
        user_tab_id=Output('store_user_tab_id_tess_lc_srv', 'data'),
        lightcurve=Output('store_tess_lightcurve_lc_srv', 'data', allow_duplicate=True),  # dummy Storage
        message_results=Output('download_tess_lc_srv_result', 'children'),
        graph_tab_disabled=Output('tess_lc_srv_graph_tab', 'disabled'),
        active_tab=Output('tess_lc_srv_tabs', 'active_tab'),
        periodogram_results_row_style=Output('tess_lc_srv_periodogram_results_row', 'style', allow_duplicate=True),
        pg_row_style=Output('tess_lc_srv_periodogram_row', 'style', allow_duplicate=True),
    ),
    inputs=dict(n_clicks=Input('download_tess_lc_srv_button', 'n_clicks')),
    state=dict(
        user_tab_id=State('store_user_tab_id_tess_lc_srv', 'data'),
        selected_rows=State('data_tess_lc_srv_table', 'selectedRows'),
        table_data=State('data_tess_lc_srv_table', 'data'),
        stitch=State('stitch_switch_tess_lc_srv', 'value'),
        flux_method=State('flux_tess_lc_srv_switch', 'value'),
        metadata=State('store_tess_lightcurve_lc_srv_metadata', 'data'),
        search_store=State('store_tess_lc_search_result', 'data'),
        phase_view=State('fold_tess_lc_srv_switch', 'value'),
    ),
    background=background_callback,
    running=[(Output('download_tess_lc_srv_button', 'disabled'), True, False),
             (Output('cancel_download_tess_lc_srv_button', 'disabled'), False, True)],
    cancel=[Input('cancel_download_tess_lc_srv_button', 'n_clicks')],
    prevent_initial_call=True)
def download_tess_lc_srv_curve(n_clicks, user_tab_id, selected_rows, table_data, stitch, flux_method, metadata,
                               search_store, phase_view):
    """
    This method checks for the presence of light curves in the local cache.
    If any are missing, it downloads the absent light curves from the remote database.
    Note: unlike other methods handling TESS lightcurves, this one is specifically designed to accommodate long
    waiting times. It includes user feedback mechanisms, such as a spinner, and robust error handling for server
    connectivity issues.
    In contrast, other methods rely on the local cache to ensure faster response times.
    """
    if n_clicks is None:
        raise PreventUpdate

    output_keys = list(ctx.outputs_grouping.keys())
    output = {key: dash.no_update for key in output_keys}

    if user_tab_id is None:  # If there's no tab_id, generate a new one
        user_tab_id = generate_user_tab_id()
        output['user_tab_id'] = user_tab_id

    # Clean Periodogram stuff
    output['periodogram_results_row_style'] = {'display': 'none'}
    output['pg_row_style'] = {'display': 'none'}
    try:
        # Store the loaded light curve into dcc.Store
        # Store a loaded light curve on the server side in the DiskCache instead
        write_user_data_to_cache(
            create_lc_from_selected_rows(
                selected_rows, table_data, stitch, flux_method, metadata, search_store=search_store
            ),
            user_tab_id,
        )
        # Return a new UUID to ensure the dcc.Store value always changes.
        # This triggers dependent callbacks even if no other data is updated.
        output['lightcurve'] = str(uuid.uuid4())  # returns a string → JSON-serializable
        # output['lightcurve'] = create_lc_from_selected_rows(selected_rows, table_data, stitch, flux_method, metadata)

        output['graph_tab_disabled'] = False
        output['active_tab'] = 'tess_lc_srv_graph_tab'
        output['message_results'] = 'Success, switch to the next Tab'
        set_props('div_tess_lc_srv_download_alert', {'children': '', 'style': {'display': 'none'}})
    except Exception as e:
        logging.warning(f'lightcurve_tess.download_tess_curve {e}')
        alert_message = message.warning_alert(e)
        output['graph_tab_disabled'] = True
        output['message_results'] = ''
        set_props('div_tess_lc_srv_download_alert', {'children': alert_message, 'style': {'display': 'block'}})
    if phase_view:
        set_props('fold_tess_lc_srv_switch', {'value': False})  # this triggers callbacks, hanging on the switch
    return output


@callback(Output('download_tess_lc_srv_lightcurve', 'data'),  # ------ Download -----
          Input('btn_download_tess_lc_srv', 'n_clicks'),
          State('store_user_tab_id_tess_lc_srv', 'data'),
          State('select_tess_lc_srv_format', 'value'),
          prevent_initial_call=True)
def download_to_user_tess_lc_srv_lightcurve(n_clicks, user_tab_id, table_format):
    """Downloads a light curve to the user's computer via the lc_bridge export layer."""
    if not n_clicks:
        raise PreventUpdate

    try:
        js_lightcurve = extract_data_from_user_cache(user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        profile = 'tess' if table_format == 'votable' else None
        file_bstring = export_curvedash(lcd, table_format, profile=profile)

        outfile_base = f'lc_tess_' + sanitize_filename(lcd.title)
        ext = CurveDash.get_file_extension(table_format)
        outfile = f'{outfile_base}.{ext}'

        ret = dcc.send_bytes(file_bstring, outfile)
        set_props('div_tess_lc_srv_alert', {'children': '', 'style': {'display': 'none'}})

    except Exception as e:
        logging.warning(f'tess_lc.download_to_user_tess_lc_srv_lightcurve: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_lc_srv_alert', {'children': alert_message, 'style': {'display': 'block'}})
        ret = dash.no_update

    return ret


# @callback(Output('period_tess_lc_srv_input', 'value', allow_duplicate=True),
#           Input('use_period1_btn', 'n_clicks'),
#           State('period1_res', 'children'),
#           prevent_initial_call=True)
# def use_period1(n_clicks, period_str):
#     if not n_clicks:
#         raise PreventUpdate
#     try:
#         period = float(period_str)
#     except ValueError:
#         logging.warning(f'lightcurve_tess.use_period1: {period_str} could not be converted into the float')
#         period = None
#     return period


# @callback(Output('period_tess_lc_srv_input', 'value', allow_duplicate=True),
#           Input('use_period2_btn', 'n_clicks'),
#           State('period2_res', 'children'),
#           prevent_initial_call=True)
# def use_period2(n_clicks, period_str):
#     if not n_clicks:
#         raise PreventUpdate
#     try:
#         period = float(period_str)
#     except ValueError:
#         logging.warning(f'lightcurve_tess.use_period2: {period_str} could not be converted into the float')
#         period = None
#     return period


# Input('use_period_btn', 'n_clicks'),
# State('tess_lc_srv_select_period_dropdown', 'value'),

@callback(Output('period_tess_lc_srv_input', 'value', allow_duplicate=True),
          Input('tess_lc_srv_select_period_dropdown', 'value'),
          State('store_tess_periodogram_result_lc_srv', 'data'),
          prevent_initial_call=True)
def use_period(period_number, period_list):
    # if not n_clicks:
    #     raise PreventUpdate
    try:
        return period_list[period_number - 1]
    except Exception as e:
        raise PipeException(f'lightcurve_tess: use_period: {str(e)}')


# @callback(Output('period_tess_lc_srv_input', 'value', allow_duplicate=True),
#           Input('use_period1_btn', 'n_clicks'),
#           State('store_tess_periodogram_result_lc_srv', 'data'),
#           prevent_initial_call=True)
# def use_period(n_clicks, period):
#     if not n_clicks:
#         raise PreventUpdate
#     try:
#         return period
#     except ValueError:
#         logging.warning(f'lightcurve_tess.use_period: {period} could not be converted into the float')
#         return None
#
#
# @callback(Output('period_tess_lc_srv_input', 'value', allow_duplicate=True),
#           Input('use_period2_btn', 'n_clicks'),
#           State('store_tess_periodogram_result_lc_srv', 'data'),
#           prevent_initial_call=True)
# def use_period2(n_clicks, period):
#     if not n_clicks:
#         raise PreventUpdate
#     try:
#         return 2 * period
#     except ValueError:
#         logging.warning(f'lightcurve_tess.use_period2: {period} could not be converted into the float')
#         return None
#
#
# @callback(Output('period_tess_lc_srv_input', 'value', allow_duplicate=True),
#           Input('use_period4_btn', 'n_clicks'),
#           State('store_tess_periodogram_result_lc_srv', 'data'),
#           prevent_initial_call=True)
# def use_period4(n_clicks, period):
#     if not n_clicks:
#         raise PreventUpdate
#     try:
#         return 4 * period
#         # period = float(period)
#     except ValueError:
#         logging.warning(f'lightcurve_tess.use_period4: {period} could not be converted into the float')
#         # period = None
#         return None
#     # return 4 * period


# clientside_callback(
#     ClientsideFunction(
#         namespace='clientside',
#         function_name='clearInput'
#     ),
#     Output('period_tess_lc_srv_input', 'value'),
#     Input('clear_period_btn', 'n_clicks'),
#     prevent_initial_call=True
# )


# clientside_callback(
#     ClientsideFunction(
#         namespace='clientside',
#         function_name='clearInput'
#     ),
#     Output('epoch_tess_lc_srv_input', 'value'),
#     Input('clear_epoch_btn', 'n_clicks'),
#     prevent_initial_call=True
# )


@callback(
    output=dict(
        user_tab_id=Output('store_user_tab_id_tess_lc_srv', 'data', allow_duplicate=True),
        lightcurve=Output('store_tess_lightcurve_lc_srv', 'data', allow_duplicate=True),  # dummy
        message_results=Output('download_tess_lc_srv_result', 'children', allow_duplicate=True),
        graph_tab_disabled=Output('tess_lc_srv_graph_tab', 'disabled', allow_duplicate=True),
        active_tab=Output('tess_lc_srv_tabs', 'active_tab', allow_duplicate=True),
        period_val=Output('period_tess_lc_srv_input', 'value', allow_duplicate=True),
        epoch_val=Output('epoch_tess_lc_srv_input', 'value', allow_duplicate=True),
    ),
    inputs=dict(contents=Input('upload_tess_lc_srv', 'contents')),
    state=dict(
        filename=State('upload_tess_lc_srv', 'filename'),
        append=State('switch_append_tess_lc_srv', 'value'),
        js_lightcurve=State('store_tess_lightcurve_lc_srv', 'data'),
        phase_view=State('fold_tess_lc_srv_switch', 'value'),
        user_tab_id=State('store_user_tab_id_tess_lc_srv', 'data'),
    ),
    prevent_initial_call=True)
def handle_upload(contents, filename, append, js_lightcurve, phase_view, user_tab_id):
    output_keys = list(ctx.outputs_grouping.keys())
    output = {key: dash.no_update for key in output_keys}
    if contents is None:
        raise PreventUpdate
    try:
        extension = Path(filename).suffix[1:]
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)

        file_obj = io.BytesIO(decoded)

        # 1. Ingest standard Virtual Observatory lightcurve using the scientific core
        volc = VOLightCurve(file_obj)

        # 2. Delegate all parsing, column mapping, and physical conversions to the backend lc_bridge utility
        lcd = volc_to_curvedash(volc, filename)

        # 3. Handle append state and serialization
        try:
            if append and user_tab_id:
                lcd_stored = CurveDash.from_serialized(extract_data_from_user_cache(user_tab_id))

                if lcd_stored.lightcurve is None:
                    logging.warning('lightcurve_tess: handle upload: no stored lightcurves found')
                    lc = lcd.serialize()
                else:
                    lcd_stored.append(lcd)
                    lc = lcd_stored.serialize()
            else:
                lc = lcd.serialize()
        except Exception as e:
            raise PipeException(f'lightcurve_tess: handle_upload: problem extracting stored lightcurve {e}')

        # 4. Save to server-side cache and update UI targets
        if user_tab_id is None:
            user_tab_id = generate_user_tab_id()
            output['user_tab_id'] = user_tab_id
        write_user_data_to_cache(lc, user_tab_id)
        output['lightcurve'] = str(uuid.uuid4())
        output['graph_tab_disabled'] = False
        output['active_tab'] = 'tess_lc_srv_graph_tab'
        output['message_results'] = 'Success, switch to the next Tab'
        
        period = lcd.metadata.get('period')
        epoch = lcd.metadata.get('epoch')
        output['period_val'] = period if period is not None else dash.no_update
        output['epoch_val'] = epoch if epoch is not None else dash.no_update
        set_props('div_tess_lc_srv_download_alert', {'children': '', 'style': {'display': 'none'}})
    except Exception as e:
        logging.warning(f'lightcurve_tess.handle_upload {e}')
        alert_message = message.warning_alert(e)
        output['graph_tab_disabled'] = True
        output['message_results'] = ''
        set_props('div_tess_lc_srv_download_alert', {'children': alert_message, 'style': {'display': 'block'}})
    if phase_view:
        set_props('fold_tess_lc_srv_switch', {'value': False})
    return output


if __name__ == '__main__':  # So this is a local version
    from dash import Dash

    if DISK_CACHE:
        # Background callback management:
        import diskcache
        from dash import DiskcacheManager

        # from pathlib import Path

        diskcache_dir = Path('diskcache')
        diskcache_dir.mkdir(exist_ok=True)
        background_callback_manager = DiskcacheManager(diskcache.Cache(diskcache_dir.name))
    else:
        background_callback_manager = None

    app = Dash(__name__,
               background_callback_manager=background_callback_manager,
               external_stylesheets=[dbc.themes.BOOTSTRAP])

    app.layout = layout()
    app.run(debug=True, port=8051)
# else:
#     register_page(__name__, name='TESS curve',
#                   order=4,
#                   path='/igebc/tess_lc',
#                   title='TESS Lightcurve Tool',
#                   in_navbar=True)
#
#
#     def layout():
#         return page_layout
