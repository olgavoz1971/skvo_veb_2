# DISK_CACHE_LOCAL = True
"""TESS Cutout Tool — Dash page for FFI/TPF pixel cutouts and user photometry.

Users download TESS pixel cutouts, define aperture masks (handmade, threshold, or
pipeline), build uncalibrated lightcurves, and export them via the shared
``lc_bridge.export_curvedash`` layer with the ``cutout`` VOTable profile.
"""

DISK_CACHE_LOCAL = False

import logging

from skvo_veb.logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)

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
from skvo_veb.utils.page_session import SESSION_STORE, table_rows_from_lk_search_dict
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD as jd0,
    DEFAULT_EXPORT_FORMAT,
    DOMAIN_FLUX,
    DOMAIN_MAG,
    EXPORT_FORMAT_OPTIONS,
    TIME_AXIS_DATE,
    TIME_AXIS_MJD,
    is_votable_export_format,
)
from skvo_veb.utils.lc_bridge import (
    export_curvedash,
    apply_phot_domain_view,
    export_file_extension,
)
from skvo_veb.utils.mission_config.tess import (
    TESS_TIMEORIGIN as jd0_tess,
    build_cutout_title,
    enrich_cutout_curvedash,
    resolve_cutout_mask_mode,
)
from skvo_veb.utils.lc_figure import build_curvedash_scatter_figure
from skvo_veb.utils.lc_interaction import (
    prepare_lcd_for_export,
    require_time_view_for_trim,
    trim_curvedash_from_selection_bounds,
)
from skvo_veb.utils.my_tools import PipeException, safe_none, log_gamma, sanitize_filename, positive_float_pattern

register_page(__name__, name='TESS cutout',
              order=3,
              path='/tess',
              title='TESS cutout Tool',
              in_navbar=True)

switch_label_style = {'display': 'inline-block', 'padding': '5px'}
label_font_size = '0.8em'
stack_wrap_style = {'marginBottom': '5px', 'flexWrap': 'wrap'}

_coord_text = tess_processor._coord_text
_has_coord = tess_processor.has_coord
_resolve_search_target = tess_processor.resolve_search_target

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
                            dbc.Button('Clean Cache', id='clean_cache_tess_button', size='sm', outline=True, color='warning'),
                        ], direction='horizontal', gap=2, style=stack_wrap_style),
                        dcc.RadioItems(
                            id='ffi_tpf_switch',
                            options=[   # type: ignore
                                {'label': 'FFI', 'value': 'ffi'},
                                {'label': 'TPF', 'value': 'tpf'}
                            ],
                            value='tpf',
                            labelStyle={'display': 'inline-block', 'padding': '5px'}),
                        dbc.Spinner(
                            children=html.Div(
                                id='div_tess_tools_alert',
                                style={'display': 'none', 'marginTop': '8px'},
                            ),
                            size='sm',
                            spinner_style={'width': '2rem', 'height': '2rem'},
                        ),
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
                                        'enableCellTextSelection': True,
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
                            html.Div(
                                [
                                    dbc.Label(
                                        'Frame',
                                        html_for='cutout_frame_slider',
                                        style={'font-size': label_font_size, 'marginBottom': '4px'},
                                    ),
                                    dcc.Slider(
                                        id='cutout_frame_slider',
                                        min=0,
                                        max=0,
                                        step=1,
                                        value=0,
                                        marks=None,
                                        tooltip={'placement': 'bottom', 'always_visible': True},
                                        disabled=True,
                                        updatemode='drag',
                                    ),
                                ],
                                id='cutout_frame_slider_row',
                                style={'display': 'none', 'marginTop': '8px'},
                            ),
                        ]),
                        dbc.Button('rePlot pixel', id='replot_pixel_button', size="sm",
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
                        dbc.Stack([
                            dbc.Switch(
                                value=False,
                                style={'font-size': label_font_size},
                                id='mag_view_cutout_switch',
                                persistence=True,
                            ),
                            dbc.Label('Magnitude',
                                      id='mag_view_cutout_switch_label',
                                      style={'font-size': label_font_size}),
                        ], direction='horizontal'),
                        dcc.RadioItems(
                            id='time_axis_cutout_switch',
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
                            dbc.Tooltip('Display photometry as magnitude instead of flux '
                                        '(applied on rePlot curve)',
                                        target='mag_view_cutout_switch_label', placement='bottom'),
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
                        dbc.Button('rePlot curve', id='plot_curve_tess_button',
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
                            dbc.Select(options=EXPORT_FORMAT_OPTIONS,
                                       value=DEFAULT_EXPORT_FORMAT,
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
                                          config={'displaylogo': False, 
                                          'scrollZoom': True,
                                          'modeBarButtonsToRemove': ['lasso2d'],
                                          },
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
                                          config={'displaylogo': False, 
                                          'scrollZoom': True,
                                          'modeBarButtonsToRemove': ['lasso2d'],
                                          },
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
                                          config={'displaylogo': False, 
                                          'scrollZoom': True,
                                          'modeBarButtonsToRemove': ['lasso2d'],
                                          },
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
        dcc.Store(id='store_search_result', **SESSION_STORE),
        dcc.Store(id='store_resolved_coords', **SESSION_STORE),
        dcc.Store(id='store_pixel_metadata', **SESSION_STORE),
        dcc.Store(id='mask_store', **SESSION_STORE),
        dcc.Store(id='mask_slow_store', **SESSION_STORE),
        dcc.Store(id='mask_fast_store', **SESSION_STORE),
        dcc.Store(id='wcs_store', **SESSION_STORE),
        dcc.Store(id='store_tess_cutout_lightcurve', **SESSION_STORE),
        dcc.Store(id='store_tess_cutout_lightcurve_metadata', **SESSION_STORE),
        dcc.Store(id='store_tess_cutout_selection_bounds', **SESSION_STORE),
        dcc.Store(id='lc2_store', **SESSION_STORE),
        dcc.Store(id='lc3_store', **SESSION_STORE),
        dcc.Download(id='download_tess_lightcurve'),
    ], className="g-10", fluid=True, style={'display': 'flex', 'flexDirection': 'column'})
    return res


if not DISK_CACHE_LOCAL and __name__ == '__main__':  # local version without diskcache
    background_callback = False
else:
    background_callback = True


# Auxiliary
def normalize(arr):
    """Min–max normalises a numeric array to the interval [0, 1].

    Args:
        arr (array-like): Input values.

    Returns:
        numpy.ndarray: Normalised array.
    """
    return (arr - arr.min()) / (arr.max() - arr.min())


def imshow_logscale(img, scale_method=None, show_colorbar=False, gamma=0.99, **kwargs):
    """Renders a 2D image with optional log scaling and linear colour-bar ticks.

    Args:
        img (array-like): Pixel values to display.
        scale_method (callable, optional): Transform applied before plotting (e.g. log gamma).
        show_colorbar (bool): Whether to attach a colour bar with physical tick labels.
        gamma (float): Gamma parameter passed to ``scale_method``.
        **kwargs: Forwarded to ``plotly.express.imshow``.

    Returns:
        plotly.graph_objects.Figure: Imshow figure with ``customdata`` holding raw flux.
    """
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
    """Builds Plotly layout shapes outlining masked pixels on the cutout image.

    Args:
        target_mask (array-like): 2D boolean aperture mask.

    Returns:
        list: Plotly shape dictionaries (cross markers per masked pixel).
    """
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
        lc_metadata=Output('store_tess_cutout_lightcurve_metadata', 'data', allow_duplicate=True),
        selection_bounds=Output('store_tess_cutout_selection_bounds', 'data', allow_duplicate=True),
        fig1=Output('curve_graph_1', 'figure', allow_duplicate=True),
        fig2=Output('curve_graph_2', 'figure', allow_duplicate=True),
        fig3=Output('curve_graph_3', 'figure', allow_duplicate=True),
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
    """Downloads the selected FFI or TPF sector cutout and opens the plot tab.

    Args:
        n_clicks: Button click count.
        selected_rows: AgGrid selected row dicts.
        pixel_di: Serialised search result store payload.
        size: FFI cutout size in pixels.

    Returns:
        dict: Callback outputs including pixel metadata and cleared lightcurve stores.
    """
    if n_clicks is None:
        raise PreventUpdate

    logger.info(f"tess_cutout.download_sector: Starting download/load operation. Requested Cutout Size: {size}")
    if selected_rows:
        row = selected_rows[0]
        logger.info(f"tess_cutout.download_sector: Selected Record Detail: Mission={row.get('mission')}, Author={row.get('author')}, Target={row.get('target')}, Exptime={row.get('exptime')}")
    else:
        logger.info("tess_cutout.download_sector: Selected Record Detail: None")

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
        pixel_metadata['n_cadences'] = int(pixel_data.shape[0])
        pixel_metadata['pipeline_mask'] = pixel_data.pipeline_mask
        output['wcs'] = dict(pixel_data.wcs.to_header())
        output['pixel_metadata'] = pixel_metadata
        output['px_graph'] = go.Figure()  # clean the widget
        output['aladin_target'] = f'{pixel_data.ra} {pixel_data.dec}'
        output['sector_results'] = 'Success. Switch to the next Tab'
        output['graph_tab_disabled'] = False
        output['active_tab'] = 'tess_graph_tab'
        set_props('div_tess_download_alert', {'children': '', 'style': {'display': 'none'}})

        empty_fig = _empty_lightcurve_figure()
        output['lc1'] = None
        output['lc2'] = None
        output['lc3'] = None
        output['lc_metadata'] = {}
        output['selection_bounds'] = None
        output['fig1'] = empty_fig
        output['fig2'] = empty_fig
        output['fig3'] = empty_fig

        logger.info(f"tess_cutout.download_sector: Success! Saved/Loaded local path: {pixel_data.path}, Target Coordinate RA DEC: {pixel_data.ra} {pixel_data.dec}, Metadata Shape: {pixel_data.shape}")

    except Exception as e:
        logger.error(f"tess_cutout.download_sector: Error during download: {e}", exc_info=True)
        logger.error(f"tess_cutout.download_sector: Failed to download sector data: {e}", exc_info=True)
        alert_message = message.warning_alert(e)
        output['sector_results'] = ''
        output['graph_tab_disabled'] = True
        set_props('div_tess_download_alert', {'children': alert_message, 'style': {'display': 'block'}})

    return output


@callback(
    Output('auto_mask_collapse', 'is_open'),
    Input('auto_mask_switch', 'value')
)
def toggle_auto_mask_collapse(auto_mask):
    """Expands automatic-mask options when auto masking is enabled."""
    return auto_mask == 1  # == auto


@callback(
    Output('auto_mask_thresh_collapse', 'is_open'),
    Input('mask_type_switch', 'value'),
    Input('auto_mask_switch', 'value')
)
def toggle_auto_mask_thresh_collapse(mask_type, auto_mask_switch_value):
    """Shows threshold controls only for automatic threshold masking."""
    return auto_mask_switch_value == 1 and mask_type == 'threshold'  # == auto


@callback(
    Output('flatten_collapse', 'is_open'),
    Input('flatten_switch', 'value')
)
def toggle_flatten_collapse(flatten_switch):
    """Expands flattening parameter controls when flattening is enabled."""
    return flatten_switch  # == flatten is on


@callback(
    output=dict(
        px_fig=Output('px_tess_graph', 'figure', allow_duplicate=True),
        mask_store_out=Output('mask_store', 'data', allow_duplicate=True),
        slider_min=Output('cutout_frame_slider', 'min'),
        slider_max=Output('cutout_frame_slider', 'max'),
        slider_value=Output('cutout_frame_slider', 'value'),
        slider_disabled=Output('cutout_frame_slider', 'disabled'),
        slider_marks=Output('cutout_frame_slider', 'marks'),
        slider_row_style=Output('cutout_frame_slider_row', 'style'),
    ),
    inputs=dict(
        replot_clicks=Input('replot_pixel_button', 'n_clicks'),
        pixel_metadata=Input('store_pixel_metadata', 'data'),
        frame_index=Input('cutout_frame_slider', 'value'),
        sum_it=Input('sum_switch', 'value'),
    ),
    state=dict(
        gamma=State('input_tess_gamma', 'value'),
        threshold=State('thresh_input', 'value'),
        mask_type=State('mask_type_switch', 'value'),
        auto_mask=State('auto_mask_switch', 'value'),
        mask_store=State('mask_store', 'data'),
    ),
    prevent_initial_call='initial_duplicate',
)
def plot_pixel(
    replot_clicks,
    pixel_metadata,
    frame_index,
    sum_it,
    gamma,
    threshold,
    mask_type,
    auto_mask,
    mask_store,
):
    """Plots the downloaded TPF/FFI cutout and initialises the aperture mask store.

    A frame slider browses individual cadences when ``Sum`` is off and the cutout
    contains more than one frame.

    Args:
        replot_clicks: Replot button click count.
        pixel_metadata (dict): Downloaded sector metadata including local file path.
        frame_index (int): Selected cadence index from the frame slider.
        sum_it: When true, sum all cadences; otherwise show the selected frame.
        gamma (float): Log-scale gamma for pixel display.
        threshold (float): Threshold for automatic mask generation.
        mask_type (str): ``pipeline`` or ``threshold`` for automatic masks.
        auto_mask: Automatic mask generation toggle.
        mask_store (list): Existing handmade mask, reused when only the frame changes.

    Returns:
        dict: Pixel figure, mask store, and frame-slider layout properties.
    """
    if not pixel_metadata or not pixel_metadata.get('path'):
        raise PreventUpdate
    if ctx.triggered_id == 'replot_pixel_button' and replot_clicks is None:
        raise PreventUpdate

    path = pixel_metadata['path']
    flux_cube, time_values = tess_processor.load_cutout_flux_cube(path)
    n_cadences = flux_cube.shape[0]
    sum_cadences = bool(sum_it)
    slider_layout = tess_processor.cutout_frame_slider_layout(n_cadences, sum_cadences)

    if ctx.triggered_id in ('store_pixel_metadata', 'replot_pixel_button'):
        frame_index = 0
    elif frame_index is None:
        frame_index = 0

    data_to_show, active_frame = tess_processor.select_cutout_display_frame(
        flux_cube,
        frame_index=int(frame_index),
        sum_cadences=sum_cadences,
    )
    px_shape = flux_cube.shape[1:]

    reuse_mask = (
        ctx.triggered_id == 'cutout_frame_slider'
        and mask_store is not None
        and len(mask_store) == px_shape[0]
        and len(mask_store[0]) == px_shape[1]
    )
    if reuse_mask:
        mask = np.array(mask_store, dtype=bool)
    else:
        mask = np.full(px_shape, False)
        if auto_mask:
            if mask_type == 'pipeline':
                mask = np.array(pixel_metadata['pipeline_mask'], dtype=bool)
            else:
                pixel_data = lightkurve.targetpixelfile.TessTargetPixelFile(path)
                mask = pixel_data.create_threshold_mask(
                    threshold=threshold,
                    reference_pixel='center',
                )

    mask_shapes = create_shapes(mask)
    show_colorbar = False
    fig = imshow_logscale(
        data_to_show,
        scale_method=log_gamma,
        color_continuous_scale='Viridis',
        origin='lower',
        show_colorbar=show_colorbar,
        gamma=gamma,
    )
    if show_colorbar:
        coloraxis_colorbar = dict(len=0.9, thickness=15)
        coloraxis_showscale = True
    else:
        coloraxis_colorbar = None
        coloraxis_showscale = False

    time_btjd = float(time_values[active_frame]) if time_values.size > active_frame else None
    fig.update_layout(
        title=dict(
            text=tess_processor.format_cutout_pixel_title(
                pixel_metadata,
                frame_index=active_frame,
                n_cadences=n_cadences,
                time_btjd=time_btjd,
                sum_cadences=sum_cadences,
            ),
            font=dict(size=12),
        ),
        coloraxis_showscale=coloraxis_showscale,
        coloraxis_colorbar=coloraxis_colorbar,
        xaxis=dict(showticklabels=False),
        yaxis=dict(showticklabels=False),
        showlegend=False,
        margin=dict(l=20, b=20, t=20, r=20),
        shapes=mask_shapes,
    )

    slider_value = active_frame if slider_layout['disabled'] is False else 0
    return dict(
        px_fig=fig,
        mask_store_out=mask.tolist(),
        slider_min=slider_layout['min'],
        slider_max=slider_layout['max'],
        slider_value=slider_value,
        slider_disabled=slider_layout['disabled'],
        slider_marks=slider_layout['marks'],
        slider_row_style=slider_layout['row_style'],
    )


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
    """Regenerates the automatic aperture mask from a pixel-graph click.

    Args:
        clickData (dict): Plotly click event with pixel coordinates.
        pixel_metadata (dict): Sector metadata including path and pipeline mask.
        mask_type (str): ``pipeline`` or ``threshold``.
        auto_mask: Automatic mask toggle; manual mode uses clientside callbacks.
        threshold (float): Flux threshold for ``threshold`` mask mode.

    Returns:
        list: Serialised 2D boolean mask for ``mask_slow_store``.
    """
    if not auto_mask:  # todo count here pipeline mask if selected and presented
        raise PreventUpdate
    if clickData is None:
        logger.debug('create_mask: nothing')
        raise PreventUpdate

    x = int(clickData['points'][0]['x'])
    y = int(clickData['points'][0]['y'])

    if mask_type == 'pipeline':
        mask = np.array(pixel_metadata['pipeline_mask'])
    else:
        path_to_pixel_data = pixel_metadata['path']
        pixel_data = lightkurve.targetpixelfile.TessTargetPixelFile(path_to_pixel_data)
        logger.debug(f'create_mask: {x}, {y}, {threshold=}')
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
    prevent_initial_call='initial_duplicate',
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


def _empty_lightcurve_figure():
    """Returns a blank Plotly figure for the cutout lightcurve graphs.

    Returns:
        plotly.graph_objects.Figure: Empty scatter layout matching the page default.
    """
    return go.Figure().update_layout(
        title='',
        margin=dict(l=0, b=20, t=30, r=20),
        xaxis_title='time',
        yaxis_title='flux',
    )


_CUTOUT_LC_STORE_ACCORDION = {
    'store_tess_cutout_lightcurve': 'accordion_item_1',
    'lc2_store': 'accordion_item_2',
    'lc3_store': 'accordion_item_3',
}


def _cutout_accordion_active_for_trigger(
    triggered_id: str | None,
    triggered_ids: set[str],
):
    """Resolve accordion ``active_item`` after a lightcurve store update.

    Opens only the accordion panel that matches the store that changed.
    Manual accordion toggles and unrelated triggers (e.g. time-axis mode) are
    left unchanged via ``no_update``.

    Args:
        triggered_id: Primary callback trigger component id.
        triggered_ids: Set of all component ids that fired in this callback.

    Returns:
        list[str] | dash.no_update: Single open accordion item id, or no update.
    """
    if triggered_id == 'time_axis_cutout_switch':
        return no_update

    lc_stores = set(_CUTOUT_LC_STORE_ACCORDION)
    if triggered_id in lc_stores:
        return [_CUTOUT_LC_STORE_ACCORDION[triggered_id]]

    lc_triggered = triggered_ids & lc_stores
    if len(lc_triggered) == 1:
        store_id = next(iter(lc_triggered))
        return [_CUTOUT_LC_STORE_ACCORDION[store_id]]

    return no_update


def create_lightcurve_figure(
    js_lightcurve: str | None,
    lc_metadata: dict = None,
    time_axis_mode: str = TIME_AXIS_MJD,
):
    """Builds a Plotly figure for one stored cutout lightcurve.

    Args:
        js_lightcurve (str): Serialised ``CurveDash`` JSON from ``dcc.Store``.
        lc_metadata (dict, optional): Optional axis range overrides from relayout events.
        time_axis_mode (str): ``mjd`` or ``date`` for the time-axis display.

    Returns:
        plotly.graph_objects.Figure: Scatter figure in MJD or calendar date coordinates.
    """
    lcd = CurveDash.from_serialized(js_lightcurve)
    return build_curvedash_scatter_figure(
        lcd,
        title=build_cutout_title(lcd),
        display_epoch=jd0,
        time_axis_mode=time_axis_mode or TIME_AXIS_MJD,
        lc_metadata=lc_metadata,
        color_by_label=False,
        phot_description=safe_none(lcd.flux_correction) or None,
    )


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
        flatten_order=State('flatten_order_input', 'value'),
        show_magnitude=State('mag_view_cutout_switch', 'value'),
        auto_mask=State('auto_mask_switch', 'value'),
        mask_type=State('mask_type_switch', 'value'),
    ),
    # endregion
    prevent_initial_call=True
)
def create_lightcurve(n_clicks, pixel_metadata, mask_list, star_number, sub_bkg,
                      flatten, show_trend, flatten_window, flatten_break_gap, flatten_order,
                      show_magnitude, auto_mask, mask_type):
    """Computes an uncalibrated cutout lightcurve and stores it in the selected slot.

    Scientific extraction is delegated to ``tess_processor.process_lightcurve_computation``.
    Metadata for export (source, mask mode, user pipeline tag) is attached via ``lc_bridge``.

    Args:
        n_clicks: Plot button click count.
        pixel_metadata (dict): Downloaded sector metadata including file path.
        mask_list (list): 2D boolean aperture mask from the pixel graph.
        star_number (str): Lightcurve slot selector (``'1'``, ``'2'``, or ``'3'``).
        sub_bkg: Background subtraction toggle.
        flatten: Flattening toggle.
        show_trend: When flattening, plot trend instead of corrected flux.
        flatten_window: Flattening window length.
        flatten_break_gap: Flattening break tolerance.
        flatten_order: Flattening polynomial order.
        show_magnitude: When true, convert photometry to magnitude before storing.
        auto_mask: Automatic mask generation toggle.
        mask_type (str): ``'pipeline'`` or ``'threshold'`` when auto mask is enabled.

    Returns:
        dict: Serialised lightcurve JSON for the chosen store output.
    """
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

        pixel_file = lightkurve.targetpixelfile.TessTargetPixelFile(path_to_pixel_data)
        ra_val = float(pixel_file.ra.value) if hasattr(pixel_file.ra, 'value') else float(pixel_file.ra)
        dec_val = float(pixel_file.dec.value) if hasattr(pixel_file.dec, 'value') else float(pixel_file.dec)

        name = label_name if label_name else pixel_metadata.get('target', '')
        sector_array = np.full_like(jd, fill_value=sector, dtype=np.uint8)
        mask_mode = resolve_cutout_mask_mode(auto_mask, mask_type)

        lcd = CurveDash(
            jd=jd + jd0_tess,
            flux=flux,
            flux_err=flux_err,
            name=name,
            label=sector_array,
            lookup_name=pixel_metadata.get('lookup_name', None),
            time_unit='d',
            timescale='tdb',
            flux_unit=flux_unit,
            flux_correction=' '.join(flux_correction),
            active_domain=DOMAIN_FLUX,
        )
        enrich_cutout_curvedash(lcd, pixel_metadata, sector, mask_mode, ra=ra_val, dec=dec_val)
        apply_phot_domain_view(lcd, bool(show_magnitude))
        jsons = lcd.serialize()


        if star_number == '1':
            output['lc1'] = jsons
        elif star_number == '2':
            output['lc2'] = jsons
        else:
            output['lc3'] = jsons
        set_props('div_tess_alert', {'children': '', 'style': {'display': 'none'}})

    except Exception as e:
        logger.warning(f'tess_cutout.plot_lightcurve: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_alert', {'children': alert_message, 'style': {'display': 'block'}})
    return output


@callback(
    output=dict(
        fig1=Output('curve_graph_1', 'figure', allow_duplicate=True),
        fig2=Output('curve_graph_2', 'figure', allow_duplicate=True),
        fig3=Output('curve_graph_3', 'figure', allow_duplicate=True),
        accordion_active=Output('accordion_tess_lc', 'active_item', allow_duplicate=True),
    ),
    inputs=dict(
        lc1=Input('store_tess_cutout_lightcurve', 'data'),
        lc2=Input('lc2_store', 'data'),
        lc3=Input('lc3_store', 'data'),
        time_axis_mode=Input('time_axis_cutout_switch', 'value'),
    ),
    state=dict(lc_metadata=State('store_tess_cutout_lightcurve_metadata', 'data')),
    prevent_initial_call='initial_duplicate',
)
def plot_lightcurve(lc1, lc2, lc3, time_axis_mode, lc_metadata):
    """Refreshes one or more cutout lightcurve graphs when store data changes.

    Args:
        lc1 (str): Serialised primary lightcurve JSON.
        lc2 (str): Serialised second-slot lightcurve JSON.
        lc3 (str): Serialised third-slot lightcurve JSON.
        time_axis_mode (str): ``mjd`` or ``date`` for the time-axis display.
        lc_metadata (dict): Optional axis range overrides for the primary graph.

    Returns:
        dict: Updated figures for ``curve_graph_1``–``curve_graph_3`` and accordion state.
    """
    if not ctx.triggered:
        raise PreventUpdate

    triggered_ids = {t['prop_id'].split('.')[0] for t in ctx.triggered}

    logger.debug(f"plot_lightcurve triggered: triggered_ids={triggered_ids} ctx.triggered_id={ctx.triggered_id}")

    output_keys = list(ctx.outputs_grouping.keys())
    output = {key: no_update for key in output_keys}

    try:
        axis_mode = time_axis_mode or TIME_AXIS_MJD
        if lc1:
            output['fig1'] = create_lightcurve_figure(lc1, lc_metadata, axis_mode)
        elif 'store_tess_cutout_lightcurve' in triggered_ids:
            output['fig1'] = _empty_lightcurve_figure()

        if lc2:
            output['fig2'] = create_lightcurve_figure(lc2, time_axis_mode=axis_mode)
        elif 'lc2_store' in triggered_ids:
            output['fig2'] = _empty_lightcurve_figure()

        if lc3:
            output['fig3'] = create_lightcurve_figure(lc3, time_axis_mode=axis_mode)
        elif 'lc3_store' in triggered_ids:
            output['fig3'] = _empty_lightcurve_figure()

        output['accordion_active'] = _cutout_accordion_active_for_trigger(
            ctx.triggered_id,
            triggered_ids,
        )

        if any([lc1, lc2, lc3]):
            set_props('div_tess_alert', {'children': '', 'style': {'display': 'none'}})

    except Exception as e:
        logger.warning(f'tess_cutout.plot_lightcurve: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_alert', {'children': alert_message, 'style': {'display': 'block'}})

    return output


@callback(
    output=dict(
        fig3=Output('curve_graph_3', 'figure', allow_duplicate=True),
        accordion_active=Output('accordion_tess_lc', 'active_item', allow_duplicate=True),
    ),
    inputs=dict(
        n_clicks=Input('plot_difference_button', 'n_clicks'),
    ),
    state=dict(
        jsons_1=State('store_tess_cutout_lightcurve', 'data'),
        jsons_2=State('lc2_store', 'data'),
        comparison_method=State('compare_switch', 'value'),
    ),
    prevent_initial_call=True,
)
def plot_difference(n_clicks, jsons_1, jsons_2, comparison_method):
    """Plots the difference or ratio of two stored cutout lightcurves in slot 3.

    Args:
        n_clicks: Difference plot button click count.
        jsons_1 (str): Serialised lightcurve from slot 1.
        jsons_2 (str): Serialised lightcurve from slot 2.
        comparison_method (str): ``subtract`` or ``divide``.

    Returns:
        dict: Third graph figure and accordion state.
    """
    if n_clicks is None:
        raise PreventUpdate
    fig = no_update
    accordion_active = no_update
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
        accordion_active = ['accordion_item_3']
        set_props('div_tess_alert', {'children': '', 'style': {'display': 'none'}})
    except Exception as e:
        logger.warning(f'tess_cutout.plot_difference: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_alert', {'children': alert_message, 'style': {'display': 'block'}})

    return dict(fig3=fig, accordion_active=accordion_active)


def mark_cross(fig, x, y, cross_size=0.3, line_width=2, color='cyan'):
    """Adds a cyan cross marker at pixel coordinates on a Plotly figure copy.

    Args:
        fig (dict): Serialised Plotly figure from a ``dcc.Graph`` store.
        x (float): Pixel x coordinate.
        y (float): Pixel y coordinate.
        cross_size (float): Half-length of each cross arm in pixel units.
        line_width (int): Stroke width of the cross lines.
        color (str): Line colour.

    Returns:
        dict: Deep-copied figure with cross shapes appended.
    """
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
    """Marks an Aladin click on the pixel cutout and syncs RA/Dec inputs.

    Args:
        coord (dict): Aladin ``clickedCoordinates`` with ``ra`` and ``dec``.
        fig (dict): Current pixel graph figure.
        wcs_dict (dict): FITS WCS header serialised from the cutout.

    Returns:
        tuple: ``(ra, dec, updated_figure)``.
    """
    if coord is None:
        logger.warning(f'mark_star: coord is None')
        raise PreventUpdate
    ra = coord.get('ra', None)
    dec = coord.get('dec', None)
    if ra is None or dec is None:
        logger.warning(f'mark_star: ra or dec is None')
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
        alert_message=Output('div_tess_tools_alert', 'children', allow_duplicate=True),
        alert_style=Output('div_tess_tools_alert', 'style', allow_duplicate=True),
    ),
    inputs=dict(n_clicks=Input('resolve_tess_button', 'n_clicks')),
    state=dict(
        obj_name=State('obj_name_tess_input', 'value')
    ),
    prevent_initial_call=True
)
def resolve_coordinates(n_clicks, obj_name):
    """Resolves an object name to ICRS coordinates via SIMBAD/name resolver.

    Args:
        n_clicks: Resolve button click count.
        obj_name (str): Target name entered by the user.

    Returns:
        dict: RA/Dec fields, resolved-coords store, and optional alert message.
    """
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
        logger.warning(f"tess_cutout.resolve_coordinates error: {e}")
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
        resolved_out=Output('store_resolved_coords', 'data', allow_duplicate=True),
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
    """Queries Lightkurve for available TESS FFI or TPF cutouts near the target.

    Args:
        n_clicks: Search button click count.
        pixel_type (str): ``ffi`` or ``tpf`` product type.
        obj_name (str): Optional object name.
        ra: Right ascension in degrees (optional).
        dec: Declination in degrees (optional).
        radius (float): Search cone radius for TPF queries.
        resolved_coords (dict): Cached resolver output from ``store_resolved_coords``.

    Returns:
        dict: AgGrid rows, search store payload, and UI visibility flags.
    """
    if n_clicks is None:
        raise PreventUpdate

    output_keys = list(ctx.outputs_grouping.keys())
    output = {key: no_update for key in output_keys}
    output['ra_out'] = no_update
    output['dec_out'] = no_update
    output['resolved_out'] = no_update

    try:
        target, search_mode = _resolve_search_target(obj_name, ra, dec, resolved_coords)
    except PipeException as e:
        output['alert_message'] = message.warning_alert(e)
        output['alert_style'] = {'display': 'block'}
        output['selected_rows'] = []
        output['content_style'] = {'display': 'none'}
        return output

    # Case 3: object name search without Resolve — ignore stray coordinates and clear them
    clear_stray_coords = (
        search_mode == 'object_name'
        and obj_name and str(obj_name).strip()
        and (_has_coord(ra) or _has_coord(dec))
    )
    if clear_stray_coords:
        output['ra_out'] = ''
        output['dec_out'] = ''
        output['resolved_out'] = None

    logger.info(
        f"tess_cutout.search: Starting search operation. mode={search_mode}, target={target!r}, type={pixel_type}, radius={radius}"
        f"{' (Stray coordinates ignored and cleared: RA=' + str(ra) + ', DEC=' + str(dec) + ')' if clear_stray_coords else ' (Coordinates: RA=' + str(ra) + ', DEC=' + str(dec) + ')'}"
    )

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
        display_name = str(obj_name).strip() if obj_name and str(obj_name).strip() else target
        output['table_header'] = f'{pixel_type.upper()} {display_name}'
        pixel_di = {'lookup_name': display_name, 'search_result': pixel.table.to_pandas().to_dict()}
        output['store_pixel'] = pixel_di  # Serialize Lightkurve.SearchResult to store it
        output['selected_rows'] = []  # start without any selection
        output['content_style'] = {'display': 'block'}  # show the table
        output['alert_style'] = {'display': 'none'}  # hide the alert
        output['alert_message'] = ''

        logger.info(f"tess_cutout.search: Success! Found {len(data)} matching records for {target!r}")
        for idx, row in enumerate(data):
            logger.info(f"  Record {idx+1:02d}: Mission={row['mission']}, Author={row['author']}, Target={row['target']}, Exptime={row['exptime']}")

    except Exception as e:
        logger.error(f"tess_cutout.search: Failed search for target={target!r}: {e}", exc_info=True)
        output['selected_rows'] = []
        output['alert_message'] = message.warning_alert(e)
        output['alert_style'] = {'display': 'block'}  # show the alert
        output['content_style'] = {'display': 'none'}  # hide empty or wrong table
        output['store_pixel'] = {}
    return output
    # return f'{pixel_type.upper()} {target}', data, selected_row, content_style, pixel_di, alert_message, alert_style


@callback(
    output=dict(
        table_header=Output("table_tess_header", "children", allow_duplicate=True),
        table_data=Output("data_tess_table", "rowData", allow_duplicate=True),
        content_style=Output("search_results_row", "style", allow_duplicate=True),
    ),
    inputs=dict(store_data=Input('store_search_result', 'data')),
    prevent_initial_call='initial_duplicate',
)
def restore_search_table(store_data):
    """Rebuilds the search results table after a browser session restore.

    Args:
        store_data (dict): Persisted ``store_search_result`` payload.

    Returns:
        dict: Table header, row data, and visibility style.
    """
    rows = table_rows_from_lk_search_dict(store_data, include_distance=True)
    if not rows:
        raise PreventUpdate
    lookup_name = store_data.get('lookup_name', '')
    return {
        'table_header': lookup_name,
        'table_data': rows,
        'content_style': {'display': 'block'},
    }


@callback(
    output=dict(
        graph_tab_disabled=Output('tess_graph_tab', 'disabled', allow_duplicate=True),
        active_tab=Output('tess_tabs', 'active_tab', allow_duplicate=True),
    ),
    inputs=dict(
        pixel_metadata=Input('store_pixel_metadata', 'data'),
        lc1=Input('store_tess_cutout_lightcurve', 'data'),
    ),
    prevent_initial_call='initial_duplicate',
)
def restore_tess_cutout_tabs(pixel_metadata, lc1):
    """Re-enables the plot tab when persisted cutout or lightcurve data exists.

    Args:
        pixel_metadata (dict): Persisted sector download metadata.
        lc1 (str): Serialised primary lightcurve, if any.

    Returns:
        dict: Graph tab disabled flag and active tab id.
    """
    if pixel_metadata and pixel_metadata.get('path'):
        return {'graph_tab_disabled': False, 'active_tab': 'tess_graph_tab'}
    if lc1:
        return {'graph_tab_disabled': False, 'active_tab': 'tess_graph_tab'}
    raise PreventUpdate


@callback(
    output=dict(
        alert_message=Output('div_tess_tools_alert', 'children', allow_duplicate=True),
        alert_style=Output('div_tess_tools_alert', 'style', allow_duplicate=True),
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
    """Deletes server-side TESS cache files for the current search target.

    Args:
        n_clicks: Clean-cache button click count.
        obj_name (str): Object name, if provided.
        ra: Right ascension in degrees (optional).
        dec: Declination in degrees (optional).
        radius (float): Cache key search radius for coordinate targets.

    Returns:
        dict: Success or error alert for the search panel.
    """
    if n_clicks is None:
        raise PreventUpdate

    if obj_name and str(obj_name).strip():
        target = str(obj_name).strip()
    elif _has_coord(ra) and _has_coord(dec):
        target = f"{_coord_text(ra)} {_coord_text(dec)}"
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
        logger.info(f"handle_clean_cache: {msg_text}")
        return {
            'alert_message': message.info_alert(msg_text),
            'alert_style': {'display': 'block'}
        }
    except Exception as e:
        err_msg = f"Failed to clean cache for '{target}': {e}"
        logger.error(f"handle_clean_cache: {err_msg}", exc_info=True)
        return {
            'alert_message': message.warning_alert(err_msg),
            'alert_style': {'display': 'block'}
        }


# Capture box-select x-axis bounds locally (~16 bytes). Full selectedData stays in the browser.
clientside_callback(
    """
    function(selectedData, timeAxisMode) {
        if (!selectedData || !selectedData.range || !selectedData.range.x) {
            return window.dash_clientside.no_update;
        }
        const x = selectedData.range.x;
        const a = x[0];
        const b = x[1];
        let xmin;
        let xmax;
        if (typeof a === 'string' || typeof b === 'string') {
            xmin = a < b ? a : b;
            xmax = a < b ? b : a;
        } else {
            xmin = Math.min(a, b);
            xmax = Math.max(a, b);
        }
        const mode = timeAxisMode || ((typeof a === 'string' || typeof b === 'string') ? 'date' : 'mjd');
        return {xmin: xmin, xmax: xmax, time_axis_mode: mode};
    }
    """,
    Output('store_tess_cutout_selection_bounds', 'data'),
    Input('curve_graph_1', 'selectedData'),
    State('time_axis_cutout_switch', 'value'),
    prevent_initial_call=True,
)


@callback(
    Output('store_tess_cutout_selection_bounds', 'data', allow_duplicate=True),
    Input('time_axis_cutout_switch', 'value'),
    prevent_initial_call=True,
)
def clear_cutout_selection_bounds_on_time_axis_change(_time_axis_mode):
    """Clears stale box bounds when the user switches MJD/Date display."""
    return None


@callback(Output('download_tess_lightcurve', 'data'),  # ------ Download -----
          Input('btn_download_tess', 'n_clicks'),
          State('store_tess_cutout_lightcurve', 'data'),
          State('select_tess_format', 'value'),
          State('curve_graph_1', 'relayoutData'),
          State('store_tess_cutout_selection_bounds', 'data'),
          State('store_tess_cutout_lightcurve_metadata', 'data'),
          State('time_axis_cutout_switch', 'value'),
          prevent_initial_call=True)
def download_tess_lightcurve(n_clicks, js_lightcurve, table_format, relayout_data,
                             selection_bounds, lc_metadata, time_axis_mode):
    """Exports the primary cutout lightcurve, clipped to the active selection or zoom.

    VOTable export uses the ``cutout`` profile (uncalibrated; no PhotCal zero points).
    The on-screen store retains any prior trims; export further limits output to the
    stored box-selection bounds, or otherwise the visible time axis.

    Args:
        n_clicks: Download button click count.
        js_lightcurve (str): Serialised primary lightcurve store data.
        table_format (str): Target file format identifier.
        relayout_data (dict): Plotly relayout data for optional zoom clipping.
        selection_bounds (dict): ``{xmin, xmax}`` from clientside box-select capture.
        lc_metadata (dict): Cached axis ranges from relayout events.

    Returns:
        dict or no_update: ``dcc.send_bytes`` payload for the Download component.
    """
    if not n_clicks:
        raise PreventUpdate
    if js_lightcurve is None:
        raise PreventUpdate
    try:
        lcd = CurveDash.from_serialized(js_lightcurve)
        lcd = prepare_lcd_for_export(
            lcd,
            selection_bounds=selection_bounds,
            relayout_data=relayout_data,
            lc_metadata=lc_metadata,
            display_epoch=jd0,
            time_axis_mode=time_axis_mode or TIME_AXIS_MJD,
        )

        profile = 'cutout' if is_votable_export_format(table_format) else None
        file_bstring = export_curvedash(lcd, table_format, profile=profile)

        outfile_base = 'lc_tess_' + sanitize_filename(build_cutout_title(lcd))
        ext = export_file_extension(table_format)
        outfile = f'{outfile_base}.{ext}'

        ret = dcc.send_bytes(file_bstring, outfile)
        set_props('div_tess_alert', {'children': '', 'style': {'display': 'none'}})

    except Exception as e:
        logger.warning(f'tess_cutout.download_tess_lightcurve: {e}')
        alert_message = message.warning_alert(e)
        set_props('div_tess_alert', {'children': alert_message, 'style': {'display': 'block'}})
        ret = no_update

    return ret


# Trim lightcurves stored on the client within the boundaries defined by box-selection.
@callback(
    Output('store_tess_cutout_lightcurve', 'data', allow_duplicate=True),
    Output('store_tess_cutout_selection_bounds', 'data', allow_duplicate=True),
    Output('curve_graph_1', 'selectedData', allow_duplicate=True),
    Input('cut_tess_button', 'n_clicks'),
    State('store_tess_cutout_selection_bounds', 'data'),
    State('store_tess_cutout_lightcurve', 'data'),
    State('time_axis_cutout_switch', 'value'),
    prevent_initial_call=True,
)
def trim_cutout_lightcurve(n_clicks, selection_bounds, js_lightcurve, time_axis_mode):
    """Removes the boxed time interval from the primary cutout lightcurve store."""
    if not n_clicks or not js_lightcurve:
        raise PreventUpdate
    try:
        lcd = CurveDash.from_serialized(js_lightcurve)
        trim_curvedash_from_selection_bounds(
            lcd,
            selection_bounds,
            display_epoch=jd0,
            time_axis_mode=time_axis_mode or TIME_AXIS_MJD,
        )
        set_props('div_tess_alert', {'children': '', 'style': {'display': 'none'}})
        return lcd.serialize(), None, None
    except Exception as exc:
        logger.warning('tess_cutout.trim_cutout_lightcurve: %s', exc)
        alert_message = message.warning_alert(exc)
        set_props('div_tess_alert', {'children': alert_message, 'style': {'display': 'block'}})
        return no_update, no_update, no_update


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
