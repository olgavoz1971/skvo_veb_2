# DISK_CACHE_LOCAL = True
DISK_CACHE_LOCAL = False

import logging
from os import getenv
logging.basicConfig(filename=getenv('APP_LOG'), level=logging.INFO)

import aladin_lite_react_component
import astropy.units as u
import dash_bootstrap_components as dbc
import lightkurve
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from astropy.coordinates import SkyCoord
from astropy.table import Table
from astropy.wcs import WCS
from dash import (dcc, html, Input, Output, State, register_page, callback, clientside_callback, ctx, set_props,
                  no_update)
from dash.exceptions import PreventUpdate
from lightkurve import LightkurveError
from lightkurve.correctors import PLDCorrector
import dash_ag_grid as dag

from skvo_veb.components import message
from skvo_veb.utils import tess_cache as cache
from skvo_veb.utils import tess_processor
from skvo_veb.utils.curve_dash import CurveDash, jd0
from skvo_veb.utils.my_tools import PipeException, safe_none, log_gamma, sanitize_filename, positive_float_pattern

register_page(__name__, name='TESS cutout',
              order=3,
              path='/tess',
              title='TESS cutout Tool',
              in_navbar=True)

jd0_tess = 2457000  # btjd format. We can use the construction Time(2000, format="btjd", scale="tbd") directly,

switch_label_style = {'display': 'inline-block', 'padding': '5px'}  # In the row, otherwise 'block'
# switch_label_style = {'display': 'block', 'padding': '2px'}  # In the row, otherwise 'block'
label_font_size = '0.8em'
stack_wrap_style = {'marginBottom': '5px', 'flexWrap': 'wrap'}


# page_layout = dbc.Container([
def layout():
    res = dbc.Container([
        html.H1('TESS Cutout Tool', className="text-primary text-left fs-3"),
        dbc.Tabs([
            dbc.Tab(label='Search Sector', children=[
                dbc.Row([
                    dbc.Col([
                        dbc.Stack([
                            dbc.Label('Object', html_for='obj_name_tess_input', style={'width': '7em'}),
                            dcc.Input(id='obj_name_tess_input', persistence=True, type='search',
                                      style={'flexGrow': '1', 'width': 'auto'}),
                            dbc.Button('Resolve', id='resolve_tess_button', size='sm', style={'whiteSpace': 'nowrap'}),
                        ], direction='horizontal', gap=2, style={'marginBottom': '5px'}),
                        dbc.Stack([
                            dbc.Label('RA', html_for='ra_input', style={'width': '7em'}),
                            dcc.Input(id='ra_tess_input', persistence=True, type='search', style={'width': '100%'}),
                        ], direction='horizontal', gap=2, style={'marginBottom': '5px'}),
                        dbc.Stack([
                            dbc.Label('DEC', html_for='dec_tess_input', style={'width': '7em'}),
                            dcc.Input(id='dec_tess_input', persistence=True, type='search', style={'width': '100%'}),
                        ], direction='horizontal', gap=2, style={'marginBottom': '5px'}),
                        dbc.Stack([
                            dbc.Label('Radius', id='radius_tess_lbl', html_for='radius_tess_input',
                                      style={'width': '7em'}),
                            dcc.Input(id='radius_tess_input', persistence=True, type='search',
                                      pattern=positive_float_pattern, value=11,
                                      style={'width': '100%'}),
                            dbc.Tooltip('Search radius in arcseconds', target='radius_tess_lbl', placement='bottom'),
                        ], direction='horizontal', gap=2, style={'marginBottom': '5px'}),
                        dbc.Stack([
                            dbc.Button('Search', id='search_tess_button', size='sm'),
                            dbc.Button('Cancel', id='cancel_search_tess_button', size='sm', disabled=True),
                            dbc.Button('Clean Cache', id='clean_cache_tess_button', size='sm', color='danger'),
                        ], direction='horizontal', gap=2, style=stack_wrap_style),
                        dcc.RadioItems(
                            id='ffi_tpf_switch',
                            options=[   # type: ignore
                                {'label': 'FFI', 'value': 'ffi'},
                                {'label': 'TPF', 'value': 'tpf'}
                            ],
                            value='tpf',
                            labelStyle={'display': 'inline-block', 'padding': '5px'}),
                    ], md=3, sm=4, xs=12,
                        style={'padding': '10px', 'background': 'Silver', 'border-radius': '5px'}),  # SearchTools
                    dbc.Col([
                        dbc.Spinner(children=[
                            html.Div([
                                html.Div([
                                    html.H3("Search results", id="table_tess_header"),
                                    dbc.Stack([
                                        dbc.Label('Size', html_for='size_ffi_input',
                                                  style={'width': '7em', 'marginBottom': 0}),
                                        dcc.Input(id='size_ffi_input', type='number', min=1, value=11,
                                                  style={'width': '5em'}),
                                        dbc.Button('Download sector', id='download_sector_button', size="sm",
                                                   style={'width': '100%'}),
                                        dbc.Button('Cancel', id='cancel_download_sector_button', size="sm",
                                                   style={'width': '100%'}),
                                    ], direction='horizontal', gap=2),
                                ], style={'display': 'flex', 'justifyContent': 'space-between',
                                          'alignItems': 'center', 'width': '100%'}
                                ),
                                dag.AgGrid(
                                    id="data_tess_table",
                                    columnDefs=[{"field": col, "headerName": col.capitalize() if col != "#" else "#"} for col in
                                                ["#", "mission", "year", "author", "exptime", "target", "distance"]],
                                    rowData=[],
                                    columnSize="responsiveSizeToFit",
                                    defaultColDef={"filter": True, "sortable": True, "resizable": True},
                                    dashGridOptions={
                                        "theme": "themeBalham",
                                        "rowSelection": "single",
                                        "animateRows": True,
                                        "pagination": True,
                                        "paginationPageSize": 10,
                                    },
                                    style={"height": "250px", "width": "100%"}
                                )
                            ], id="search_results_row", style={"display": "none"}),  # Search results
                            html.Div(id='div_tess_search_alert', style={"display": "none"}),  # Alert
                        ]),
                    ], md=9, sm=8, xs=12),  # SearchResult table
                ], style={'marginBottom': '10px'}),  # Search and SearchResults
                dbc.Spinner(children=[
                    dbc.Label(id="download_sector_result", children='',
                              style={"color": "green", "text-align": "center"}),
                    html.Div(id='div_tess_download_alert', style={"display": "none"}),  # Alert
                ], spinner_style={
                    "align-items": "center",
                    "justify-content": "center",
                }, color="primary")
            ],
                    tab_id='tess_search_tab',
                    id='tess_search_tab',
                    # value='tess_search_tab'
                    ),  # Search and SearchResults Tab
            dbc.Tab(label='Plot', children=[  # The Second Tab containing the content
                # html.Div([
                dbc.Row([
                    dbc.Col([
                        dbc.Label('Cutout Tools', style={'display': 'flex', 'justify-content': 'center'}),
                        html.Details([
                            html.Summary('Plot options', style={'font-size': label_font_size}),
                            dbc.Stack([
                                dbc.Label('Scale', html_for='input_tess_gamma',
                                          style={'width': '7em', 'font-size': label_font_size}),
                                dcc.Input(id='input_tess_gamma', inputMode='numeric', persistence=True,
                                          value=1, type='number', style={'width': '100%'}),
                            ], direction='horizontal', gap=2),  # Scale
                            dbc.Checklist(options=[{'label': 'Sum', 'value': 1}], value=0, id='sum_switch',
                                          persistence=True, switch=True,
                                          style={'font-size': label_font_size}),  # style={'margin-left': 'auto'}),
                        ]),
                        dbc.Button('Plot pixel', id='replot_pixel_button', size="sm",
                                   style={'width': '100%'}),
                        html.Details([
                            html.Summary('Mask', style={'font-size': label_font_size}),
                            dcc.RadioItems(
                                id='auto_mask_switch',
                                options=[
                                    {'label': 'Auto', 'value': 1},
                                    {'label': 'Handmade', 'value': 0},
                                ],
                                value=1,
                                labelStyle=switch_label_style,
                                style={'font-size': label_font_size},
                                persistence=True
                            ),
                            dbc.Collapse(
                                dcc.RadioItems(
                                    id='mask_type_switch',
                                    options=[
                                        {'label': 'pipe', 'value': 'pipeline'},
                                        {'label': 'thresh', 'value': 'threshold'},
                                    ],
                                    value='threshold',
                                    labelStyle=switch_label_style,
                                    style={'font-size': label_font_size},
                                ),
                                id='auto_mask_collapse',
                                is_open=True,
                            ),  # select between pipline and threshold mask
                            dbc.Collapse(
                                dbc.Stack([
                                    dbc.Label('Mask thresh', html_for='thresh_input',
                                              style={'width': '7em', 'font-size': label_font_size, 'margin-bottom': 0}),
                                    dcc.Input(id='thresh_input', inputMode='numeric', persistence=True,
                                              value=1, type='number',
                                              style={'width': '100%'}),
                                ], direction='horizontal', gap=2),
                                id='auto_mask_thresh_collapse',
                                is_open=True,
                            ),  # specify an auto mask threshold here
                        ], open=True),
                    ], md=2, sm=4, style={'padding': '10px', 'background': 'Silver', 'border-radius': '5px'}),  # tools
                    dbc.Col([
                        dcc.Markdown(
                            '_**Select mask and build the lightcurve**_:\n'
                            '* Click on a star in the **Aladin** applet to mark it on the pixel image\n'
                            '* **Handmade Mask:** Click on a pixel to set/unset mask\n'
                            '* **Auto-mask:** Click on a pixel to create a threshold mask around it\n'
                            '* **Pipeline mask:** Use the mask provided by the team\n',
                            style={"font-size": 12, 'font-family': 'courier'}
                        ),
                    ], md=3, sm=8),  # Description
                    dbc.Col([
                        dcc.Graph(id='px_tess_graph',
                                  config={'displaylogo': False},
                                  style={'height': '250px'},  # 'margin': '0 auto'},
                                  # style={'height': '35vh'},
                                  # style={'height': '35vh'},
                                  # style={'height': '100%'},
                                  # style={'height': '100%', 'aspect-ratio': '1'},
                                  # style={'height': '45vh', 'aspect-ratio': '1'}),
                                  # style={'height': '40vh', 'aspect-ratio': '1'}
                                  ),
                    ], align='center', md=3, sm=6),  # pixel graph
                    dbc.Col([
                        aladin_lite_react_component.AladinLiteReactComponent(
                            id='aladin_tess',
                            width=300,
                            height=250,
                            fov=round(2 * 10) / 60,  # in degrees
                            target='02:03:54 +42:19:47',
                            # stars=stars,
                        ),
                    ], align='center', md=4, sm=6)  # aladin
                ], style={'marginBottom': '10px'}),  # align='center'),  # Px graph and Aladin
                dbc.Row([
                    dbc.Col([
                        dbc.Label('Curve Tools', style={'display': 'flex', 'justify-content': 'center'}),
                        dbc.Checklist(options=[{'label': 'Sub bkg', 'value': 1}], value=0,
                                      style={'font-size': label_font_size},
                                      id='sub_bkg_switch', persistence=True, switch=True),
                        dbc.Stack([  # I separate a Label and a Switch to have tooltip when hovering the label
                            dbc.Switch(
                                value=False,
                                style={'font-size': label_font_size},
                                id='flatten_switch', persistence=False
                            ),
                            dbc.Label('Flatten',
                                      id='flatten_switch_label',
                                      style={'font-size': label_font_size}),
                        ], direction='horizontal'),
                        dbc.Collapse([
                            dbc.Stack([
                                dbc.Label('Display:', id='flux_trend_switch_label',
                                          style={'margin-bottom': 0, 'font-size': label_font_size}),
                                dcc.RadioItems(
                                    id='flux_trend_switch',
                                    options=[
                                        {'label': 'flux', 'value': False},
                                        {'label': 'trend', 'value': True},
                                    ],
                                    value=False,
                                    labelStyle=switch_label_style,
                                    style={'font-size': label_font_size},
                                ),
                            ], direction='horizontal', gap=3, style={'alignItems': 'center'}),  # flatten switch
                            dbc.Stack([
                                dbc.Label('flatten window', id='flatten_window_lbl', html_for='flatten_window_input',
                                          style={'width': '7em', 'font-size': label_font_size, 'margin-bottom': 0}),
                                dcc.Input(id='flatten_window_input', inputMode='numeric', persistence=False,
                                          value=101, type='number', style={'width': '100%'}),
                            ], direction='horizontal', gap=2),  # Flatten window
                            dbc.Stack([
                                dbc.Label('break gap', id='flatten_break_gap_lbl', html_for='flatten_break_gap_input',
                                          style={'width': '7em', 'font-size': label_font_size, 'margin-bottom': 0}),
                                dcc.Input(id='flatten_break_gap_input', inputMode='numeric', persistence=False,
                                          value=5, type='number',
                                          style={'width': '100%'}),
                            ], direction='horizontal', gap=2),  # Flatten gap
                            dbc.Stack([
                                dbc.Label('order', id='flatten_order_lbl', html_for='flatten_order_input',
                                          style={'width': '7em', 'font-size': label_font_size, 'margin-bottom': 0}),
                                dcc.Input(id='flatten_order_input', inputMode='numeric', persistence=False,
                                          min=1, value=2, step=1, type='number',
                                          style={'width': '100%'}),
                            ], direction='horizontal', gap=2),  # Flatten order
                            # region tooltips
                            dbc.Tooltip('Toggle to display either the flattened '
                                        'light curve or the trend used for flattening',
                                        target='flux_trend_switch_label', placement='bottom'),
                            dbc.Tooltip('Switch on to remove long-term trends '
                                        'using a Savitzky–Golay filter. Choose the parameters below',
                                        target='flatten_switch_label', placement='bottom'),
                            dbc.Tooltip('Length of the filter window '
                                        '(number of data points, must be an odd positive integer). '
                                        'Controls the smoothness of trend removal',
                                        target='flatten_window_lbl', placement='bottom'),
                            dbc.Tooltip('Splits the curve if time gaps exceed break_tolerance times the median gap',
                                        target='flatten_break_gap_lbl', placement='bottom'),
                            dbc.Tooltip('Polynomial order used to fit the samples (must be less than window length)',
                                        target='flatten_order_lbl', placement='bottom'),
                            # endregion
                        ],
                            id='flatten_collapse',
                            is_open=True,
                        ),
                        dbc.Button('Plot curve', id='plot_curve_tess_button',
                                   size="sm",
                                   style={
                                       # 'marginBottom': '5px',
                                       'marginTop': '5px',
                                       # 'marginLeft': '2px', 'marginRight': '2px',
                                       'width': '100%'}),
                        html.Details([
                            html.Summary('Plot Options', style={'font-size': label_font_size}),
                            dcc.RadioItems(
                                id='star_tess_switch',
                                options=[
                                    {'label': 'Curve 1', 'value': '1'},
                                    {'label': 'Curve 2', 'value': '2'},
                                    {'label': 'Curve 3', 'value': '3'},
                                ],
                                value='1',
                                labelStyle=switch_label_style,
                                style={'font-size': label_font_size},
                            ),
                            dcc.RadioItems(
                                id='compare_switch',
                                options=[   # type: ignore
                                    {'label': 'divide', 'value': 'divide'},
                                    {'label': 'subtract', 'value': 'subtract'},
                                ],
                                value='divide',
                                labelStyle=switch_label_style,
                                style={'font-size': label_font_size},
                            ),
                            dbc.Button('Compare', id='plot_difference_button', size="sm",
                                       style={'width': '100%'})
                        ], style={'marginBottom': '5px'}),  # plot / compare  curves options
                        dbc.Button('Trim selected', id='cut_tess_button', size="sm",
                                   style={'marginBottom': '5px', 'width': '100%'}),
                        dbc.Stack([
                            dbc.Select(options=CurveDash.get_format_list(),
                                       value=CurveDash.get_format_list()[0],
                                       id='select_tess_format',
                                       style={'width': '40%', 'font-size': label_font_size}),
                            dbc.Button('Download', style={'width': '60%'}, id='btn_download_tess', size="sm"),
                        ], direction='horizontal', gap=2,
                            style={'width': '100%', 'min-width': '5ch', 'marginBottom': '5px'},
                        ),
                    ], lg=2, md=3, sm=4, xs=12,
                        style={'padding': '10px', 'background': 'Silver', 'border-radius': '5px'}),  # Light Curve Tools
                    dbc.Col([
                        html.Div(children='', id='div_tess_alert', style={'display': 'none'}),
                        dbc.Accordion([
                            dbc.AccordionItem([
                                dcc.Graph(id='curve_graph_1',
                                          figure=go.Figure().update_layout(
                                              title='',
                                              margin=dict(l=0, b=20, t=30, r=20),
                                              xaxis_title=f'time',
                                              yaxis_title=f'flux',
                                          ),
                                          config={'displaylogo': False},
                                          style={'height': '40vh'}),
                            ], title='First Light Curve', item_id='accordion_item_1'),
                            dbc.AccordionItem([
                                dcc.Graph(id='curve_graph_2',
                                          figure=go.Figure().update_layout(
                                              title='',
                                              margin=dict(l=0, b=20, t=30, r=20),
                                              xaxis_title=f'time',
                                              yaxis_title=f'flux',
                                          ),
                                          config={'displaylogo': False},
                                          style={'height': '40vh'}),
                            ], title='Second Light Curve', item_id='accordion_item_2'),
                            dbc.AccordionItem([
                                dcc.Graph(id='curve_graph_3',
                                          figure=go.Figure().update_layout(
                                              title='',
                                              margin=dict(l=0, b=20, t=30, r=20),
                                              xaxis_title=f'time',
                                              yaxis_title=f'flux',
                                          ),
                                          config={'displaylogo': False},
                                          style={'height': '40vh'}),
                            ], title='Third Light Curve', item_id='accordion_item_3'),
                        ], id='accordion_tess_lc', start_collapsed=False,
                            active_item=['accordion_item_1', 'accordion_item_2', 'accordion_item_3'],
                            always_open=True)  # Light Curves
                    ], lg=10, md=9, sm=8, xs=12),  # Light Curves Accordion

                ], style={'marginBottom': '10px'}),  # Light Curves
            ],
                    tab_id='tess_graph_tab',
                    # value='tess_graph_tab',
                    id='tess_graph_tab', disabled=True),  # Plot Tab
        ],
            active_tab='tess_search_tab',
            # value='tess_search_tab',
            id='tess_tabs', style={'marginBottom': '5px'}),
        dcc.Store(id='store_search_result'),  # things showed in the data table (the list of TESS sectors etc.)
        dcc.Store(id='store_resolved_coords'),  # store for resolved Simbad coordinates
        dcc.Store(id='store_pixel_metadata'),  # stuff for recreation the current pixel
        dcc.Store(id='mask_store'),  # mask for lightcurve calculation from cutouts
        dcc.Store(id='mask_slow_store'),  # for more complex mask operation, performed on the server side
        dcc.Store(id='mask_fast_store'),  # mask changed on client side
        dcc.Store(id='wcs_store'),  # store wcs to sync with Aladin applet
        dcc.Store(id='store_tess_cutout_lightcurve'),  # user's lightcurve is here
        dcc.Store(id='store_tess_cutout_lightcurve_metadata'),
        # extra information on lightcurve_1 (current zoom ranges)
        dcc.Store(id='lc2_store'),  # the second lightcurve is here
        dcc.Store(id='lc3_store'),  # the third lightcurve is here
        dcc.Download(id='download_tess_lightcurve'),
    ], className="g-10", fluid=True, style={'display': 'flex', 'flexDirection': 'column'})
    return res


if not DISK_CACHE_LOCAL and __name__ == '__main__':  # local version without diskcache
    background_callback = False
else:
    background_callback = True


# Auxiliary
def normalize(arr):
    return (arr - arr.min()) / (arr.max() - arr.min())


def imshow_logscale(img, scale_method=None, show_colorbar=False, gamma=0.99, **kwargs):
    # from engineering_notation import EngNumber
    import matplotlib.ticker as ticker

    # img_true_min = img[img > 0].min()   # todo: return try here
    try:
        img_true_min = img[img > 0].min()
    except ValueError:
        img_true_min = 0
    if scale_method:
        img[img <= 0] = img_true_min
        log_data = scale_method(img, gamma=gamma)
    else:
        log_data = img
    fig = px.imshow(
        img=log_data,
        **kwargs,
    )

    if show_colorbar:
        val_min = img.min()
        val_max = img.max()
        val_range = val_max - val_min
        left = val_min
        left = left if left > 0 else img_true_min
        right = val_max + val_range / 100
        right = right if right > 0 else img_true_min
        locator = ticker.MaxNLocator(nbins=5)
        TICKS_VALS = np.array(locator.tick_values(left, right))
        TICKS_VALS[0] = left

        TICKS_VALS = TICKS_VALS[TICKS_VALS >= 0]
        TICKS_VALS[TICKS_VALS == 0] = img_true_min
        ticks_text = [f'{val:.0f}' for val in TICKS_VALS]
        # ticks_text = [f'{EngNumber(val)}' for val in TICKS_VALS]
        if scale_method is not None:
            tickvals = [scale_method(val, gamma=gamma) for val in TICKS_VALS]
        else:
            tickvals = TICKS_VALS
        fig.update_layout(
            coloraxis_colorbar=dict(
                tickvals=tickvals,
                ticktext=ticks_text,
            ),
        )
    else:
        fig.update_layout(coloraxis_showscale=False),

    fig.data[0]['customdata'] = img  # store here not-logarithmic values
    fig.data[0]['hovertemplate'] = '%{customdata:.0f}<extra></extra>'
    return fig


def create_shapes(target_mask):
    # Create a list of shapes to mark mask
    shapes = []
    for i in range(target_mask.shape[0]):
        for j in range(target_mask.shape[1]):
            if target_mask[i, j]:  # Only draw shapes for the masked pixels
                # Add red border (rectangle)
                shapes.append(
                    dict(
                        type="rect",
                        x0=j - 0.5, y0=i - 0.5,
                        x1=j + 0.5, y1=i + 0.5,
                        line=dict(color="red", width=1)
                    )
                )
                # First diagonal line (/)
                shapes.append(
                    dict(
                        type="line",
                        x0=j - 0.5, y0=i - 0.5,
                        x1=j + 0.5, y1=i + 0.5,
                        line=dict(color="red", width=1)
                    )
                )
    return shapes


# Helper functions moved to skvo_veb/utils/tess_processor.py


@callback(
    # region
    output=dict(
        pixel_metadata=Output('store_pixel_metadata', 'data'),
        wcs=Output('wcs_store', 'data', allow_duplicate=True),
        aladin_target=Output('aladin_tess', 'target'),
        px_graph=Output('px_tess_graph', 'figure', allow_duplicate=True),
        sector_results=Output('download_sector_result', 'children'),
        graph_tab_disabled=Output('tess_graph_tab', 'disabled'),
        active_tab=Output('tess_tabs', 'active_tab'),
        # clear this stuff when loading new data.
        lc1=Output('store_tess_cutout_lightcurve', 'data', allow_duplicate=True),
        lc2=Output('lc2_store', 'data', allow_duplicate=True),
        lc3=Output('lc3_store', 'data', allow_duplicate=True),
    ),
    inputs=dict(
        n_clicks=Input('download_sector_button', 'n_clicks'),
    ),
    state=dict(
        selected_rows=State('data_tess_table', 'selectedRows'),
        pixel_di=State('store_search_result', 'data'),
        size=State('size_ffi_input', 'value')
    ),
    # endregion
    running=[(Output('download_sector_button', 'disabled'), True, False),
             (Output('cancel_download_sector_button', 'disabled'), False, True)],
    cancel=[Input('cancel_download_sector_button', 'n_clicks')],
    background=background_callback,
    prevent_initial_call=True
)
def download_sector(n_clicks, selected_rows, pixel_di, size):
    if n_clicks is None:
        raise PreventUpdate

    print(f"\n[DOWNLOAD SECTOR] Starting download/load operation...")
    print(f"  - Requested Cutout Size: {size}")
    if selected_rows:
        row = selected_rows[0]
        print(f"  - Selected Record Detail: Mission={row.get('mission')}, Author={row.get('author')}, Target={row.get('target')}, Exptime={row.get('exptime')}")
    else:
        print(f"  - Selected Record Detail: None")
    logging.info(f"tess_cutout.download_sector: Starting download/load for size={size}, selected_rows={selected_rows}")

    output_keys = list(ctx.outputs_grouping.keys())
    output = {key: no_update for key in output_keys}
    try:
        search_result_di = pixel_di.get('search_result', None)
        if not selected_rows:
            raise PipeException('Please select a row first')
        
        pixel_metadata, pixel_data = tess_processor.download_selected_pixel(selected_rows[0], search_result_di, size)

        lookup_name = pixel_di.get('lookup_name', None)  # restore user's lookup name of the object
        if not lookup_name or (lookup_name == pixel_metadata['target']):
            lookup_name = ''

        pixel_metadata['lookup_name'] = lookup_name
        pixel_metadata['path'] = pixel_data.path
        pixel_metadata['shape'] = pixel_data.shape
        pixel_metadata['pipeline_mask'] = pixel_data.pipeline_mask
        output['wcs'] = dict(pixel_data.wcs.to_header())
        output['pixel_metadata'] = pixel_metadata
        output['px_graph'] = go.Figure()  # clean the widget
        output['aladin_target'] = f'{pixel_data.ra} {pixel_data.dec}'
        output['sector_results'] = 'Success. Switch to the next Tab'
        output['graph_tab_disabled'] = False
        output['active_tab'] = 'tess_graph_tab'
        set_props('div_tess_download_alert', {'children': '', 'style': {'display': 'none'}})

        print(f"[DOWNLOAD SECTOR] Success!")
        print(f"  - Saved/Loaded local path: {pixel_data.path}")
        print(f"  - Target Coordinate RA DEC: {pixel_data.ra} {pixel_data.dec}")
        print(f"  - Metadata Shape: {pixel_data.shape}")
        logging.info(f"tess_cutout.download_sector: Success, path={pixel_data.path}, shape={pixel_data.shape}")

    except Exception as e:
        print(f"[DOWNLOAD SECTOR] Error during download: {e}")
        logging.error(f"tess_cutout.download_sector: Failed to download sector data: {e}", exc_info=True)
        alert_message = message.warning_alert(e)
        output['sector_results'] = ''
        output['graph_tab_disabled'] = True
        set_props('div_tess_download_alert', {'children': alert_message, 'style': {'display': 'block'}})

    # clear lightcurves:
    output['lc1'] = None
    output['lc2'] = None
    output['lc3'] = None
    return output


@callback(
    Output('auto_mask_collapse', 'is_open'),
    Input('auto_mask_switch', 'value')
)
def toggle_auto_mask_collapse(auto_mask):
    return auto_mask == 1  # == auto


@callback(
    Output('auto_mask_thresh_collapse', 'is_open'),
    Input('mask_type_switch', 'value'),
    Input('auto_mask_switch', 'value')
)
def toggle_auto_mask_thresh_collapse(mask_type, auto_mask_switch_value):
    return auto_mask_switch_value == 1 and mask_type == 'threshold'  # == auto


@callback(
    Output('flatten_collapse', 'is_open'),
    Input('flatten_switch', 'value')
)
def toggle_flatten_collapse(flatten_switch):
    return flatten_switch  # == flatten is on


@callback(
    [Output('px_tess_graph', 'figure', allow_duplicate=True),
     Output('mask_store', 'data', allow_duplicate=True)],
    [Input('replot_pixel_button', 'n_clicks'),
     Input('store_pixel_metadata', 'data'),
     State('input_tess_gamma', 'value'),
     State('thresh_input', 'value'),
     State('sum_switch', 'value'),
     State('mask_type_switch', 'value'),
     State('auto_mask_switch', 'value')],
    prevent_initial_call=True
)
def plot_pixel(n_clicks, pixel_metadata, gamma, threshold, sum_it, mask_type, auto_mask):
    # if ctx.triggered and ctx.triggered[0]["prop_id"] == "replot_pixel_button.n_clicks":
    if ctx.triggered_id == "replot_pixel_button":
        if n_clicks is None:
            raise PreventUpdate
    pixel_data = lightkurve.targetpixelfile.TessTargetPixelFile(pixel_metadata['path'])
    px_shape = pixel_data.shape[1:]
    mask = np.full(px_shape, False)
    if auto_mask:
        mask = (
            pixel_data.pipeline_mask if mask_type == "pipeline"
            else pixel_data.create_threshold_mask(threshold=threshold, reference_pixel="center")
        )
    mask_shapes = create_shapes(mask)

    if sum_it:
        data_to_show = np.sum(pixel_data.flux[:], axis=0)
    else:
        data_to_show = pixel_data.flux[0]  # take only the first crop

    # fig = px.imshow(data_to_show.value, color_continuous_scale='Viridis', origin='lower') fig = imshow_logscale(
    # data_to_show.value, scale_method=log_gamma, color_continuous_scale='Viridis', origin='lower')
    # print(f'{gamma=} {type(gamma)=}')
    show_colorbar = False
    fig = imshow_logscale(data_to_show.value, scale_method=log_gamma, color_continuous_scale='Viridis', origin='lower',
                          show_colorbar=show_colorbar, gamma=gamma)
    # fig.update_traces(hovertemplate="%{z:.0f}<extra></extra>", hoverinfo="z")
    if show_colorbar:
        coloraxis_colorbar = dict(len=0.9,  # Set the length (fraction of plot height, e.g., 0.5 = half the plot height)
                                  thickness=15  # Set the thickness (in pixels)
                                  )
        coloraxis_showscale = True
    else:
        coloraxis_colorbar = None
        coloraxis_showscale = False
    fig.update_layout(title=dict(
        text=f'{pixel_metadata.get("lookup_name", "")} '
             f'{pixel_metadata.get("target", "")} '
             f'{pixel_metadata.get("author", "")}',
        font=dict(size=12)
    ),
        coloraxis_showscale=coloraxis_showscale,
        coloraxis_colorbar=coloraxis_colorbar,
        xaxis=dict(showticklabels=False), yaxis=dict(showticklabels=False),
        showlegend=False, margin=dict(l=20, b=20, t=20, r=20),
        shapes=mask_shapes)

    return fig, mask.tolist()


# download_selected_pixel moved to skvo_veb/utils/tess_processor.py


# Synchronize masks
clientside_callback(
    """
    function synchronizeMasksTriggerSlow(slowMask) {
        console.log("Synchronizing masks... Trigger = Slow");
        if (!slowMask) {
            window.dash_clientside.no_update;
        }
        return slowMask;
    }
    """,
    Output("mask_store", "data", allow_duplicate=True),
    Input("mask_slow_store", "data"),
    prevent_initial_call=True
)
clientside_callback(
    """
    function synchronizeMasksTriggerFast(fastMask) {
        if (!fastMask) {
            window.dash_clientside.no_update;
        }
        return fastMask;
    }
    """,
    Output("mask_store", "data", allow_duplicate=True),
    Input("mask_fast_store", "data"),
    prevent_initial_call=True
)


@callback(
    Output('mask_slow_store', 'data', allow_duplicate=True),
    [Input("px_tess_graph", "clickData"),
     State('store_pixel_metadata', 'data'),
     State('mask_type_switch', 'value'),
     State('auto_mask_switch', 'value'),
     State('thresh_input', 'value')],
    prevent_initial_call=True,
)
def create_mask(clickData, pixel_metadata,
                mask_type, auto_mask, threshold):
    if not auto_mask:  # todo count here pipeline mask if selected and presented
        raise PreventUpdate
    if clickData is None:
        logging.debug('create_mask: nothing')
        raise PreventUpdate

    x = int(clickData['points'][0]['x'])
    y = int(clickData['points'][0]['y'])

    if mask_type == 'pipeline':
        mask = np.array(pixel_metadata['pipeline_mask'])
    else:
        path_to_pixel_data = pixel_metadata['path']
        pixel_data = lightkurve.targetpixelfile.TessTargetPixelFile(path_to_pixel_data)
        logging.debug(f'create_mask: {x}, {y}, {threshold=}')
        mask = pixel_data.create_threshold_mask(threshold=threshold, reference_pixel=(x, y))

    return mask.tolist()


clientside_callback(
    """
    function updateFastMask(clickData, autoMask, maskList) {
        // console.log('updateFastMask', autoMask, clickData);

        if (autoMask && autoMask.length > 0) {
            console.log('updateFastMask: no_update')
            return window.dash_clientside.no_update;
        }

        if (!clickData) {
            return window.dash_clientside.no_update;
        }

        const x = Math.round(clickData.points[0].x);
        const y = Math.round(clickData.points[0].y);
        const updatedMask = [...maskList];
        updatedMask[y][x] = updatedMask[y][x] ? 0 : 1;

        return updatedMask;
    }
    """,
    Output("mask_fast_store", "data", allow_duplicate=True),
    [Input("px_tess_graph", "clickData")],
    [State("auto_mask_switch", "value"),
     State("mask_store", "data")],
    prevent_initial_call=True
)

clientside_callback(
    """
    function updateFigureWithMask(mask, fig) {
        console.log('updateFigureWithMask');

        if (!mask || !fig) {
            return window.dash_clientside.no_update;
        }
        // console.log('fig =', fig);
        // console.log('fig.layout=', fig.layout);
        
        // Recreate figure to trigger show updates
        const updatedShapes = mask.flatMap((row, rowIndex) =>
            row.map((val, colIndex) => {
                if (val) {
                    // Square
                    const rect = {
                        type: "rect",
                        x0: colIndex - 0.5,
                        x1: colIndex + 0.5,
                        y0: rowIndex - 0.5,
                        y1: rowIndex + 0.5,
                        line: {color: "red", width: 1},
                    };
                    // Diagonal
                    const line = {
                        type: "line",
                        x0: colIndex - 0.5,
                        x1: colIndex + 0.5,
                        y0: rowIndex - 0.5,
                        y1: rowIndex + 0.5,
                        line: {color: "red", width: 1},
                    };
                    return [rect, line];  // return square and diagonal
                }
                return null;
            })
        ).filter(Boolean).flat();  // flat array

        // console.log('updatedShapes=', updatedShapes);

        const newLayout = {
            ...fig.layout,
            shapes: updatedShapes,
            selections: undefined
        };

        // Copy and recreate figure to trigger rendering on the user screen
        const newFigure = {
             ...fig,
             layout: newLayout
        };

        // console.log('newLayout:', newLayout);

        return newFigure;
    }
    """,
    Output("px_tess_graph", "figure", allow_duplicate=True),
    Input("mask_store", "data"),
    State("px_tess_graph", "figure"),
    prevent_initial_call=True
)


clientside_callback(
    """
    function(relayoutData, lc_metadata) {
        if (!relayoutData) {
            return window.dash_clientside.no_update;
        }

        // Initialize metadata dictionary if null
        if (!lc_metadata) {
            lc_metadata = {};
        }

        // Reset axis ranges if autorange is triggered
        if (relayoutData['xaxis.autorange'] === true) {
            lc_metadata['xrange_left'] = null;
            lc_metadata['xrange_right'] = null;
        }
        if (relayoutData['yaxis.autorange'] === true) {
            lc_metadata['yrange_left'] = null;
            lc_metadata['yrange_right'] = null;
        }

        // Zoom: update x-axis range
        if ('xaxis.range[0]' in relayoutData && 'xaxis.range[1]' in relayoutData) {
            lc_metadata['xrange_left'] = relayoutData['xaxis.range[0]'];
            lc_metadata['xrange_right'] = relayoutData['xaxis.range[1]'];
        }

        // Zoom: update y-axis range
        if ('yaxis.range[0]' in relayoutData && 'yaxis.range[1]' in relayoutData) {
            lc_metadata['yrange_left'] = relayoutData['yaxis.range[0]'];
            lc_metadata['yrange_right'] = relayoutData['yaxis.range[1]'];
        }

        return lc_metadata;
    }
    """,
    Output('store_tess_cutout_lightcurve_metadata', 'data'),
    Input('curve_graph_1', 'relayoutData'),
    State('store_tess_cutout_lightcurve_metadata', 'data')
)


def create_lightcurve_figure(js_lightcurve: str | None, lc_metadata: dict = None):
    lcd = CurveDash.from_serialized(js_lightcurve)
    # xaxis_title = f'time, {safe_none(lcd.time_unit)}'
    xaxis_title = f'jd-{jd0}, {safe_none(lcd.time_unit)} {lcd.timescale}'
    yaxis_title = f'flux {safe_none(lcd.flux_correction)}, {safe_none(lcd.flux_unit)}'

    xrange_left = xrange_right = yrange_left = yrange_right = None
    if lc_metadata is not None:
        xrange_left = lc_metadata.get('xrange_left')
        xrange_right = lc_metadata.get('xrange_right')
        yrange_left = lc_metadata.get('yrange_left')
        yrange_right = lc_metadata.get('yrange_right')
    title = lcd.title

    fig = go.Figure()
    x = lcd.jd - jd0 if lcd.jd is not None else lcd.jd
    fig.add_trace(go.Scatter(x=x, y=lcd.flux,
                             hoverinfo='none',  # Important
                             hovertemplate=None,
                             mode='markers+lines',
                             marker=dict(color='blue', size=6, symbol='circle'),
                             line=dict(color='blue', width=1)))
    layout_kwargs = dict(
        title=title,
        showlegend=False,
        margin=dict(l=0, b=20, t=30, r=20),
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
    )
    # Set x-axis range if provided
    if xrange_left is not None and xrange_right is not None:
        layout_kwargs['xaxis'] = dict(range=[xrange_left, xrange_right])

    if yrange_left is not None and yrange_right is not None:
        layout_kwargs['yaxis'] = dict(range=[yrange_left, yrange_right])

    fig.update_layout(**layout_kwargs)

    return fig


@callback(
    # region parameters
    output=dict(
        lc1=Output('store_tess_cutout_lightcurve', 'data', allow_duplicate=True),  # todo make it an Input also
        lc2=Output('lc2_store', 'data'),
        lc3=Output('lc3_store', 'data'),
        lc_metadata=Output('store_tess_cutout_lightcurve_metadata', 'data', allow_duplicate=True),
    ),
    inputs=dict(n_clicks=Input('plot_curve_tess_button', 'n_clicks')),
    state=dict(
        pixel_metadata=State('store_pixel_metadata', 'data'),
        mask_list=State('mask_store', 'data'),
        star_number=State('star_tess_switch', 'value'),
        sub_bkg=State('sub_bkg_switch', 'value'),
        flatten=State('flatten_switch', 'value'),
        show_trend=State('flux_trend_switch', 'value'),
        flatten_window=State('flatten_window_input', 'value'),
        flatten_break_gap=State('flatten_break_gap_input', 'value'),
        flatten_order=State('flatten_order_input', 'value')
    ),
    # endregion
    prevent_initial_call=True
)
def create_lightcurve(n_clicks, pixel_metadata, mask_list, star_number, sub_bkg,
                      flatten, show_trend, flatten_window, flatten_break_gap, flatten_order):
    if n_clicks is None:
        raise PreventUpdate

    output_keys = list(ctx.outputs_grouping.keys())
    output = {key: no_update for key in output_keys}
    output['lc_metadata'] = {}  # reset zoomed axis ranges

    try:
        path_to_pixel_data = pixel_metadata['path']

        jd, flux, flux_err, flux_unit, flux_correction, sector, label_name = tess_processor.process_lightcurve_computation(
            path_to_pixel_data, mask_list, sub_bkg, flatten, show_trend,
            flatten_window, flatten_break_gap, flatten_order
        )

        time_unit = 'mjd'
        name = label_name if label_name else pixel_metadata.get('target', '')

        sector_array = np.full_like(jd, fill_value=sector, dtype=np.uint8)   # mark it somehow
        lcd = CurveDash(jd=jd + jd0_tess, flux=flux, flux_err=flux_err,
                        name=name, label=sector_array, lookup_name=pixel_metadata.get('lookup_name', None),
                        time_unit=time_unit, timescale='tdb',
                        flux_unit=flux_unit, flux_correction=' '.join(flux_correction))

        title = (f'{pixel_metadata.get("pixel_type", "").upper()} '
                 f'{lcd.lookup_name} {name} '
                 f'sector:{sector} '
                 f'{pixel_metadata.get("author", "")}')

        lcd.title = title
        jsons = lcd.serialize()


        if star_number == '1':
            output['lc1'] = jsons
        elif star_number == '2':
            output['lc2'] = jsons
        else:
            output['lc3'] = jsons
        set_props('div_tess_alert', {'children': '', 'style': {'display': 'none'}})

    except Exception as e:
        logging.warning(f'tess_cutout.plot_lightcurve: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_alert', {'children': alert_message, 'style': {'display': 'block'}})
    return output


@callback(
    output=dict(
        fig1=Output('curve_graph_1', 'figure'),
        fig2=Output('curve_graph_2', 'figure'),
        fig3=Output('curve_graph_3', 'figure'),
    ),
    inputs=dict(
        lc1=Input('store_tess_cutout_lightcurve', 'data'),
        lc2=Input('lc2_store', 'data'),
        lc3=Input('lc3_store', 'data'),
    ),
    state=dict(lc_metadata=State('store_tess_cutout_lightcurve_metadata', 'data')),
    prevent_initial_call=True
)
def plot_lightcurve(lc1, lc2, lc3, lc_metadata):
    # It can happen that we enter here on all triggers at the same time:
    triggered_ids = {t['prop_id'].split('.')[0] for t in ctx.triggered}
    if not triggered_ids:
        raise PreventUpdate

    print(f'{triggered_ids=} { ctx.triggered_id=}')

    output_keys = list(ctx.outputs_grouping.keys())
    output = {key: no_update for key in output_keys}
    active_item = ['accordion_item_1']

    try:
        if 'store_tess_cutout_lightcurve' in triggered_ids:
            output['fig1'] = create_lightcurve_figure(lc1, lc_metadata)
            active_item = ['accordion_item_1'] if lc1 else []  # close an empty accordion section if lc1 id None
        if 'lc2_store' in triggered_ids:
            output['fig2'] = create_lightcurve_figure(lc2)
            active_item = ['accordion_item_2'] if lc2 else []
        if 'lc3_store' in triggered_ids:
            output['fig3'] = create_lightcurve_figure(lc3)
            active_item = ['accordion_item_3'] if lc3 else []

        set_props('div_tess_alert', {'children': '', 'style': {'display': 'none'}})
        set_props('accordion_tess_lc', {'active_item': active_item})

    except Exception as e:
        logging.warning(f'tess_cutout.plot_lightcurve: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_alert', {'children': alert_message, 'style': {'display': 'block'}})

    return output


@callback(
    Output('curve_graph_3', 'figure', allow_duplicate=True),
    [Input('plot_difference_button', 'n_clicks'),
     State('store_tess_cutout_lightcurve', 'data'),
     State('lc2_store', 'data'),
     State('compare_switch', 'value')],
    prevent_initial_call=True
)
def plot_difference(n_clicks, jsons_1, jsons_2, comparison_method):
    if n_clicks is None:
        raise PreventUpdate
    fig = no_update
    try:
        if jsons_1 is None or jsons_2 is None:
            raise PipeException('Plot both: the First and Second Light Curves first')
        lcd1 = CurveDash.from_serialized(jsons_1)
        lcd2 = CurveDash.from_serialized(jsons_2)

        # Both curves have the same jd ticks
        # search for common time pieces:
        jd_common = np.intersect1d(lcd1.jd, lcd2.jd)
        # Remember lcd.flux is pandas.Series, so indices matter, it's better to forget them (to_numpy())
        flux1_common = lcd1.flux[np.isin(lcd1.jd, jd_common)].to_numpy()
        flux2_common = lcd2.flux[np.isin(lcd2.jd, jd_common)].to_numpy()

        if comparison_method == 'divide':
            # flux = dash_lc1.flux / dash_lc2.flux
            flux = flux1_common / flux2_common
            title = 'Curve1 / Curve2'
        else:
            # flux = dash_lc1.flux - dash_lc2.flux
            flux = flux1_common - flux2_common
            title = 'Curve1 - Curve2'

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=jd_common - jd0, y=flux,
                                 hoverinfo='none',  # Important
                                 hovertemplate=None,
                                 mode='markers+lines',
                                 marker=dict(color='blue', size=6, symbol='circle'),
                                 line=dict(color='blue', width=1)))
        fig.update_layout(title=title,
                          showlegend=False,
                          margin=dict(l=0, b=20, t=30, r=20),
                          # xaxis_title=f'time, {safe_none(lcd1.time_unit)}',
                          xaxis_title=f'jd-{jd0}, {safe_none(lcd1.time_unit)} {lcd1.timescale}',
                          # xaxis_title=f'time, {safe_none(lcd1.time_unit)}',
                          yaxis_title=f'flux',
                          # xaxis={'dtick': 1000},
                          # 'showticklabels': False},# todo tune it
                          )
        active_item = ['accordion_item_3']
        set_props('div_tess_alert', {'children': '', 'style': {'display': 'none'}})
        set_props('accordion_tess_lc', {'active_item': active_item})
    except Exception as e:
        logging.warning(f'tess_cutout.plot_difference: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_alert', {'children': alert_message, 'style': {'display': 'block'}})

    return fig


def mark_cross(fig, x, y, cross_size=0.3, line_width=2, color='cyan'):
    import copy
    new_fig = copy.deepcopy(fig)
    shapes = [
        {
            "type": "line",
            "x0": x - cross_size,
            "y0": y,
            "x1": x + cross_size,
            "y1": y,
            "line": {"color": color, "width": line_width},
        },
        {
            "type": "line",
            "x0": x,
            "y0": y - cross_size,
            "x1": x,
            "y1": y + cross_size,
            "line": {"color": color, "width": line_width},
        }
    ]

    # add mark to layout
    if "shapes" not in new_fig["layout"]:
        new_fig["layout"]["shapes"] = shapes
    else:
        new_fig["layout"]["shapes"].extend(shapes)

    return new_fig


@callback(
    [Output('ra_tess_input', 'value', allow_duplicate=True),
     Output('dec_tess_input', 'value', allow_duplicate=True),
     Output('px_tess_graph', 'figure', allow_duplicate=True)],
    [Input('aladin_tess', 'clickedCoordinates'),
     State('px_tess_graph', 'figure'),
     State('wcs_store', 'data')],
    prevent_initial_call=True
)
def mark_star(coord, fig, wcs_dict):
    if coord is None:
        logging.warning(f'mark_star: coord is None')
        raise PreventUpdate
    ra = coord.get('ra', None)
    dec = coord.get('dec', None)
    if ra is None or dec is None:
        logging.warning(f'mark_star: ra or dec is None')
        raise PreventUpdate
    # noinspection PyUnresolvedReferences
    sky_coord = SkyCoord(ra=ra * u.degree, dec=dec * u.degree, frame='icrs')
    x, y = WCS(wcs_dict).world_to_pixel(sky_coord)
    # fig = add_marker(fig, x, y, marker_symbol="diamond", color="blue", size=12)
    fig = mark_cross(fig, x, y)
    return coord.get('ra'), coord.get('dec'), fig


@callback(
    output=dict(
        ra=Output('ra_tess_input', 'value', allow_duplicate=True),
        dec=Output('dec_tess_input', 'value', allow_duplicate=True),
        resolved_coords=Output('store_resolved_coords', 'data'),
        alert_message=Output('div_tess_search_alert', 'children', allow_duplicate=True),
        alert_style=Output('div_tess_search_alert', 'style', allow_duplicate=True),
    ),
    inputs=dict(n_clicks=Input('resolve_tess_button', 'n_clicks')),
    state=dict(
        obj_name=State('obj_name_tess_input', 'value')
    ),
    prevent_initial_call=True
)
def resolve_coordinates(n_clicks, obj_name):
    if n_clicks is None:
        raise PreventUpdate

    output = {
        'ra': no_update,
        'dec': no_update,
        'resolved_coords': no_update,
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
        logging.warning(f"tess_cutout.resolve_coordinates error: {e}")
        output['alert_message'] = message.warning_alert(e)
        output['alert_style'] = {'display': 'block'}

    return output


@callback(
    # region
    output=dict(
        table_header=Output("table_tess_header", "children"),
        table_data=Output("data_tess_table", "rowData"),
        selected_rows=Output("data_tess_table", "selectedRows"),
        content_style=Output("search_results_row", "style"),  # show the table and Title
        store_pixel=Output('store_search_result', 'data'),
        alert_message=Output('div_tess_search_alert', 'children', allow_duplicate=True),
        alert_style=Output('div_tess_search_alert', 'style', allow_duplicate=True),
        ra_out=Output('ra_tess_input', 'value', allow_duplicate=True),
        dec_out=Output('dec_tess_input', 'value', allow_duplicate=True),
    ),
    inputs=dict(n_clicks=Input('search_tess_button', 'n_clicks')),
    state=dict(
        pixel_type=State('ffi_tpf_switch', 'value'),
        obj_name=State('obj_name_tess_input', 'value'),
        ra=State('ra_tess_input', 'value'),
        dec=State('dec_tess_input', 'value'),
        radius=State('radius_tess_input', 'value'),
        resolved_coords=State('store_resolved_coords', 'data'),
    ),
    # endregion
    running=[(Output('search_tess_button', 'disabled'), True, False),
             (Output('cancel_search_tess_button', 'disabled'), False, True),
             (Output('download_sector_result', 'children'),
              'I\'m working... Please wait', 'Press Download to get the lightcurve')],
    cancel=[Input('cancel_search_tess_button', 'n_clicks')],
    background=background_callback,
    prevent_initial_call=True
)
def search(n_clicks, pixel_type, obj_name, ra, dec, radius, resolved_coords):
    if n_clicks is None:
        raise PreventUpdate

    output_keys = list(ctx.outputs_grouping.keys())
    output = {key: no_update for key in output_keys}
    output['ra_out'] = no_update
    output['dec_out'] = no_update

    clean_coords = False
    if obj_name and obj_name.strip():
        target = obj_name.strip()
        if (ra and ra.strip()) or (dec and dec.strip()):
            if resolved_coords:
                stored_obj = resolved_coords.get('obj_name', '')
                stored_ra = resolved_coords.get('ra', '')
                stored_dec = resolved_coords.get('dec', '')
                if (stored_obj == target and 
                    (not ra or ra.strip() == stored_ra) and 
                    (not dec or dec.strip() == stored_dec)):
                    pass
                else:
                    clean_coords = True
            else:
                clean_coords = True
    else:
        if (not ra or not ra.strip()) and (not dec or not dec.strip()):
            output['alert_message'] = message.warning_alert("Please enter an object name or RA/DEC coordinates.")
            output['alert_style'] = {'display': 'block'}
            output['selected_rows'] = []
            output['content_style'] = {'display': 'none'}
            return output
        target = f'{ra} {dec}'

    if clean_coords:
        output['ra_out'] = ""
        output['dec_out'] = ""

    print(f"\n[SEARCH SECTOR] Starting search operation...")
    print(f"  - Pixel Type: {pixel_type!r}")
    print(f"  - Object Name: {obj_name!r}")
    print(f"  - Coordinates: RA={ra!r}, DEC={dec!r}")
    print(f"  - Resolved Target Name: {target!r}")
    print(f"  - Radius: {radius!r}")
    logging.info(f"tess_cutout.search: Starting search operation for target={target!r}, type={pixel_type}, radius={radius}")

    try:
        if pixel_type == 'ffi':
            pixel = tess_processor.get_ffi(target=target)
        else:
            pixel = tess_processor.get_tpf(target, radius=radius)

        data = []
        if len(pixel) == 0:
            raise PipeException('No data found')
        for row in pixel.table:
            data.append({
                '#': row['#'],
                'mission': row['mission'],
                'year': row['year'],
                'target': row["target_name"],
                "author": row["author"],
                "exptime": row["exptime"],
                "distance": row["distance"]
            })
        if data:
            output['table_data'] = data
        else:
            raise PipeException('Empty data')
        output['table_header'] = f'{pixel_type.upper()} {target}'
        pixel_di = {'lookup_name': f'{target}', 'search_result': pixel.table.to_pandas().to_dict()}
        output['store_pixel'] = pixel_di  # Serialize Lightkurve.SearchResult to store it
        output['selected_rows'] = [data[0]] if data else []  # select the first row by default
        output['content_style'] = {'display': 'block'}  # show the table
        output['alert_style'] = {'display': 'none'}  # hide the alert
        output['alert_message'] = ''

        print(f"[SEARCH SECTOR] Success! Found {len(data)} matching records for {target!r}")
        for idx, row in enumerate(data):
            print(f"  Record {idx+1:02d}: Mission={row['mission']}, Author={row['author']}, Target={row['target']}, Exptime={row['exptime']}")
        logging.info(f"tess_cutout.search: Success, found {len(data)} records for {target!r}")

    except Exception as e:
        print(f"[SEARCH SECTOR] Error during search for {target!r}: {e}")
        logging.error(f"tess_cutout.search: Failed search for target={target!r}: {e}", exc_info=True)
        output['selected_rows'] = []
        output['alert_message'] = message.warning_alert(e)
        output['alert_style'] = {'display': 'block'}  # show the alert
        output['content_style'] = {'display': 'none'}  # hide empty or wrong table
        output['store_pixel'] = {}
    return output
    # return f'{pixel_type.upper()} {target}', data, selected_row, content_style, pixel_di, alert_message, alert_style


@callback(
    output=dict(
        alert_message=Output('div_tess_search_alert', 'children', allow_duplicate=True),
        alert_style=Output('div_tess_search_alert', 'style', allow_duplicate=True),
    ),
    inputs=dict(n_clicks=Input('clean_cache_tess_button', 'n_clicks')),
    state=dict(
        obj_name=State('obj_name_tess_input', 'value'),
        ra=State('ra_tess_input', 'value'),
        dec=State('dec_tess_input', 'value'),
        radius=State('radius_tess_input', 'value'),
    ),
    prevent_initial_call=True
)
def handle_clean_cache(n_clicks, obj_name, ra, dec, radius):
    if n_clicks is None:
        raise PreventUpdate

    if obj_name and obj_name.strip():
        target = obj_name.strip()
    elif ra and dec:
        target = f"{ra.strip()} {dec.strip()}"
    else:
        return {
            'alert_message': message.warning_alert("Please enter an object name or RA/DEC coordinates first to clean their cache."),
            'alert_style': {'display': 'block'}
        }

    try:
        rad_val = float(radius) if radius else 11.0
    except ValueError:
        rad_val = 11.0

    try:
        deleted_count = cache.delete_target_cache(target, radius=rad_val)
        msg_text = f"Cache cleaned successfully for '{target}'. {deleted_count} cached file(s) deleted."
        print(f"[CLEAN CACHE] {msg_text}")
        logging.info(f"handle_clean_cache: {msg_text}")
        return {
            'alert_message': message.info_alert(msg_text),
            'alert_style': {'display': 'block'}
        }
    except Exception as e:
        err_msg = f"Failed to clean cache for '{target}': {e}"
        print(f"[CLEAN CACHE] Error: {err_msg}")
        logging.error(f"handle_clean_cache: {err_msg}", exc_info=True)
        return {
            'alert_message': message.warning_alert(err_msg),
            'alert_style': {'display': 'block'}
        }


@callback(Output('download_tess_lightcurve', 'data'),  # ------ Download -----
          Input('btn_download_tess', 'n_clicks'),
          State('store_tess_cutout_lightcurve', 'data'),
          # State('store_tess_cutout_curve_metadata', 'data'),
          State('select_tess_format', 'value'),
          State('curve_graph_1', 'relayoutData'),
          prevent_initial_call=True)
def download_tess_lightcurve(n_clicks, js_lightcurve, table_format, relayout_data):
    """
    Downloads the light curve to the user's computer, storing only 'what I see on the screen',
    so the zoom action cuts out a light curve piece along the time axis.
    Add metadata to the Table.metadata
    """
    if not n_clicks:
        raise PreventUpdate
    if js_lightcurve is None:
        raise PreventUpdate
    try:
        lcd = CurveDash.from_serialized(js_lightcurve)
        # Cut out the light curve, bound it by the visible area along a time axis:
        if relayout_data and 'xaxis.range[0]' in relayout_data and 'xaxis.range[1]' in relayout_data:
            left_border = relayout_data['xaxis.range[0]']
            right_border = relayout_data['xaxis.range[1]']
            lcd.keep(left_border, right_border)
        # bstring is "bytes"
        file_bstring = lcd.download(table_format)  # todo: here add table metadata with the lookup name

        outfile_base = f'lc_tess_' + sanitize_filename(lcd.title)

        ext = lcd.get_file_extension(table_format)
        outfile = f'{outfile_base}.{ext}'

        ret = dcc.send_bytes(file_bstring, outfile)
        set_props('div_tess_alert', {'children': '', 'style': {'display': 'none'}})

    except Exception as e:
        logging.warning(f'tess_cutout.download_tess_lightcurve: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_alert', {'children': alert_message, 'style': {'display': 'block'}})
        ret = no_update

    return ret


@callback(Output('store_tess_cutout_lightcurve', 'data', allow_duplicate=True),
          [Input('cut_tess_button', 'n_clicks'),
           # Input('keep_tess_button', 'n_clicks'),
           State('curve_graph_1', 'selectedData'),
           State('store_tess_cutout_lightcurve', 'data')],
          prevent_initial_call=True,
          )
# def handle_selection(_1, _2, selected_data, js_lightcurve):
def handle_selection(_1, selected_data, js_lightcurve):
    """
    Remove a selected piece of lightcurve
    Can be applied only to lightcurve 1
    """
    # if _1 is None and _2 is None:
    if _1 is None:
        raise PreventUpdate
    if selected_data is None or js_lightcurve is None:
        raise PreventUpdate
    if 'range' not in selected_data:
        raise PreventUpdate
    if 'x' not in selected_data['range']:
        raise PreventUpdate
    left_border, right_border = selected_data['range']['x']
    try:
        lcd = CurveDash.from_serialized(js_lightcurve)
        lcd.cut(left_border+jd0, right_border+jd0)
        # if ctx.triggered_id == 'cut_tess_button':
        #     lcd.cut(left_border, right_border)
        # else:
        #     lcd.keep(left_border, right_border)
        set_props('div_tess_alert', {'children': '', 'style': {'display': 'none'}})
        return lcd.serialize()
    except Exception as e:
        logging.warning(f'tess_cutout.handle_selection: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_alert', {'children': alert_message, 'style': {'display': 'block'}})
        return no_update  # If I raise PreventUpdate here, set_props will not really set props; I


if __name__ == '__main__':  # So this is a local version
    from dash import Dash

    if DISK_CACHE_LOCAL:
        # Background callback management:
        import diskcache
        from dash import DiskcacheManager
        from pathlib import Path

        diskcache_dir = Path('diskcache')
        diskcache_dir.mkdir(exist_ok=True)
        background_callback_manager = DiskcacheManager(diskcache.Cache(diskcache_dir.name))
    else:
        background_callback_manager = None

    app = Dash(__name__,
               background_callback_manager=background_callback_manager,
               external_stylesheets=[dbc.themes.BOOTSTRAP])

    app.layout = layout()
    # app.run_server(debug=True, port=8050)
    app.run(debug=True, port=8050)
