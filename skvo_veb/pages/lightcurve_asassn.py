import logging

from skvo_veb.logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)

import plotly.express as px
from dash import (
    register_page,
    html,
    dcc,
    callback,
    clientside_callback,
    ClientsideFunction,
    Input,
    Output,
    State,
    ctx,
    no_update,
    set_props,
)
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from skvo_veb.components import message
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import export_curvedash, export_file_extension
from skvo_veb.utils.lc_config import (
    DEFAULT_EXPORT_FORMAT,
    EXPORT_FORMAT_OPTIONS,
    is_votable_export_format,
)
from skvo_veb.utils.mission_config.asassn import resolve_target_identifier
from skvo_veb.utils.my_tools import is_like_gaia_id, DBException, sanitize_filename
from skvo_veb.utils.request_asassn import load_asassn_lightcurve
from skvo_veb.utils.request_gaia import decipher_source_id

register_page(
    __name__,
    name='ASAS-SN',
    order=2,
    path='/asassn',
    title='IGEBC: ASAS-SN Lightcurve',
    in_navbar=True,
)

row_class_name = 'd-flex g-2 justify-content-end align-items-end'


def layout(source_id=None, band='g'):
    if source_id is None:
        header_txt = 'Request ASAS-SN lightcurve'
    else:
        header_txt = f'ASAS-SN lightcurve\n{source_id} {band}'

    header = html.H1(
        header_txt,
        id='h1-asassn',
        className='text-primary text-left fs-3',
        style={'white-space': 'pre-wrap'},
    )
    fig = px.scatter()
    fig.update_traces(
        selected={'marker': {'color': 'orange', 'size': 10}},
        hoverinfo='none',
        hovertemplate=None,
    )
    fig.update_layout(
        xaxis={'title': 'phase', 'tickformat': '.1f'},
        yaxis_title='flux',
        margin=dict(l=0, b=20),
        dragmode='lasso',
    )

    res = dbc.Container(
        [
            dcc.Store(id='store_asassn_lightcurve'),
            html.Br(),
            header,
            html.Br(),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Stack(
                                [
                                    dcc.Markdown('Name'),
                                    dbc.Input(
                                        placeholder='type object name',
                                        value=source_id if source_id is not None else '',
                                        type='text',
                                        id='input-asassn-source-id',
                                    ),
                                ],
                                direction='horizontal',
                                gap=2,
                            ),
                        ],
                        md=5,
                    ),
                    dbc.Col(
                        [
                            dbc.Stack(
                                [
                                    dcc.Markdown('Band'),
                                    dbc.Select(
                                        options=['V', 'g'],
                                        value=band,
                                        id='select-asassn-band',
                                        style={'width': 100},
                                    ),
                                ],
                                direction='horizontal',
                                gap=2,
                            ),
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            dbc.Stack(
                                [
                                    dbc.Button(
                                        'Submit',
                                        size='md',
                                        color='primary',
                                        id='btn-asassn-new-source',
                                    ),
                                    dbc.Button(
                                        'Clear',
                                        size='md',
                                        color='light',
                                        id='btn-asassn-clear-source_id',
                                    ),
                                    dbc.Button(
                                        'Force',
                                        size='md',
                                        color='warning',
                                        outline=True,
                                        id='btn-asassn-update',
                                    ),
                                    dbc.Tooltip(
                                        'Forced updates may take some time',
                                        target='btn-asassn-update',
                                        placement='bottom',
                                    ),
                                    dbc.Button(
                                        'Cancel',
                                        size='md',
                                        disabled=True,
                                        id='btn-cancel-asassn-update',
                                    ),
                                ],
                                direction='horizontal',
                                gap=2,
                            ),
                        ],
                        md=2,
                        align='end',
                    ),
                ],
                class_name='row_class_name',
            ),
            html.Br(),
            dbc.Row(
                id='row-asassn-content',
                children=[
                    dbc.Row(
                        [
                            html.Div(
                                [
                                    dbc.Switch(
                                        id='switch-asassn-view',
                                        label='Folded view',
                                        value=True,
                                        persistence=True,
                                    ),
                                    dbc.Label(
                                        'Unable to fold; the period is unknown',
                                        id='label-switch-asassn-view-warning',
                                    ),
                                ],
                                style={'min-height': '30px'},
                            ),
                        ],
                        class_name='g-2',
                    ),
                    dbc.Row([], class_name='g-2'),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Row(
                                        [
                                            dcc.Graph(
                                                id='graph-asassn-curve',
                                                figure=fig,
                                                config={'displaylogo': False, 'scrollZoom': True},
                                            ),
                                        ],
                                        class_name='g-0',
                                    ),
                                ],
                                md=12,
                                sm=12,
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
                                            dbc.Button('Delete selected', id='btn-asassn-delete'),
                                            dbc.Button('Unselect', id='btn-asassn-unselect'),
                                        ],
                                        direction='horizontal',
                                        gap=2,
                                    ),
                                ],
                                md=6,
                                sm=12,
                            ),
                            dbc.Col(
                                [
                                    dbc.Stack(
                                        [
                                            dbc.Select(
                                                options=EXPORT_FORMAT_OPTIONS,
                                                value=DEFAULT_EXPORT_FORMAT,
                                                id='select-asassn-format',
                                            ),
                                            dbc.Button('Download', id='btn-asassn-download-lc'),
                                        ],
                                        direction='horizontal',
                                        gap=2,
                                    ),
                                ],
                                md=6,
                                sm=12,
                            ),
                        ],
                        class_name='row_class_name',
                    ),
                    dcc.Download(id='download-asassn-lc'),
                ],
                class_name='row_class_name',
                style={'display': 'none'},
            ),
            html.Div(id='div-asassn-alert', style={'display': 'none'}),
        ],
    )
    return res


def _load_lightcurve(source_id: str, band: str, force_update=False) -> CurveDash:
    """Loads an ASAS-SN lightcurve by Gaia ID or common name.

    Args:
        source_id (str): Gaia DR3 id or object name.
        band (str): Photometric filter (``'V'`` or ``'g'``).
        force_update (bool): When true, bypass the local pickle cache.

    Returns:
        CurveDash: Deserialised ASAS-SN lightcurve.
    """
    # try:
    #     gaia_id = decipher_source_id(source_id)
    #     lcd = load_asassn_lightcurve(gaia_id=gaia_id, band=band, force_update=force_update)
    # except DBException:
    #     logger.info('Gaia lookup failed for %s; querying ASAS-SN by name', source_id)
    #     print('Hmmmm..., ok, let\'s try to query directly by the name')
    #     lcd = load_asassn_lightcurve(source_id=source_id, band=band, force_update=force_update)
    # Let's try simple way, may be we will ad simbad resolver if needed
    lcd = load_asassn_lightcurve(source_id=source_id, band=band, force_update=force_update)
    return lcd


# @callback(
#     Output('store_asassn_lightcurve', 'data', allow_duplicate=True),
#     Input('graph-asassn-curve', 'selectedData'),
#     Input('graph-asassn-curve', 'clickData'),
#     State('store_asassn_lightcurve', 'data'),
#     prevent_initial_call=True)
# def test_tmp(_1, _2, js):
#     import json
#     t = json.loads(js)
#     print(t['metadata'])
#     return js


@callback(
    output=dict(
        header=Output('h1-asassn', 'children'),
        row_content_style=Output('row-asassn-content', 'style'),
        div_alert_style=Output('div-asassn-alert', 'style'),
        alert_message=Output('div-asassn-alert', 'children'),
        switch_asassn_style=Output('switch-asassn-view', 'style'),
        warning_asassn_style=Output('label-switch-asassn-view-warning', 'style'),
        lc=Output('store_asassn_lightcurve', 'data'),
    ),
    inputs=dict(
        _1=Input('input-asassn-source-id', 'n_submit'),
        _2=Input('btn-asassn-new-source', 'n_clicks'),
        _3=Input('btn-asassn-update', 'n_clicks'),
    ),
    state=dict(
        source_id=State('input-asassn-source-id', 'value'),
        band=State('select-asassn-band', 'value'),
        phase_view=State('switch-asassn-view', 'value'),
    ),
    running=[(Output('btn-asassn-update', 'disabled'), True, False),
             (Output('btn-cancel-asassn-update', 'disabled'), False, True),
             (Output('btn-asassn-new-source', 'disabled'), True, False)],
    cancel=[Input('btn-cancel-asassn-update', 'n_clicks')],
    background=True,
    prevent_initial_call=True
)
def load_new_source(_1, _2, _3, source_id, band, phase_view):
    # folded_view = 1 if phase_view else 0
    switch_asassn_style = {'display': 'block'}
    warning_asassn_style = {'display': 'none'}

    if source_id is None or source_id == '':
        raise PreventUpdate
    title = 'ASAS-SN lightcurve'
    prefix = 'GAIA DR3' if is_like_gaia_id(source_id) else ''
    header_txt = html.Span([f'{title} {prefix} {source_id}  ', html.Em(band)])
    try:
        force_update = ctx.triggered_id == 'btn-asassn-update'
        logger.info(
            'Load source data from ASAS-SN db: source_id=%s band=%s force_update=%s',
            source_id,
            band,
            force_update,
        )
        lcd = _load_lightcurve(source_id, band=band, force_update=force_update)
        lcd.lightcurve.dropna(subset=['flux'], inplace=True)
        lcd.folded_view = phase_view

        # jdict = handler.load_lightcurve(source_id, band, catalogue, force_update)
        period = lcd.period
        period = None if not period else round(period, 5)
        epoch = lcd.epoch
        period_unit = lcd.period_unit
        content_style = {'display': 'block'}
        alert_style = {'display': 'none'}
        alert_message = ''
        # if period:
        #     header_txt += f' P={period}'
        # if period_unit:
        #     header_txt += f' {period_unit}'
        if period is None:
            switch_asassn_style = {'display': 'none'}
            warning_asassn_style = {'display': 'block'}
            lcd.folded_view = 0

        lc = lcd.serialize()

    except Exception as e:
        logger.warning('lightcurve_asassn.load_new_source: %s', e)
        content_style = {'display': 'none'}
        alert_style = {'display': 'block'}
        alert_message = message.warning_alert(e)
        lc = no_update

    output = dict(header=header_txt, row_content_style=content_style,
                  div_alert_style=alert_style, alert_message=alert_message,
                  switch_asassn_style=switch_asassn_style,
                  warning_asassn_style=warning_asassn_style,
                  lc=lc)
    return output


clientside_callback(
    ClientsideFunction(
        namespace='clientside',
        function_name='updateFoldedView'
    ),
    Output('store_asassn_lightcurve', 'data', allow_duplicate=True),
    Input('switch-asassn-view', 'value'),
    State('store_asassn_lightcurve', 'data'),
    prevent_initial_call=True
)

clientside_callback(
    ClientsideFunction(
        namespace='clientside',
        function_name='selectData'
    ),
    Output('store_asassn_lightcurve', 'data', allow_duplicate=True),
    Input('graph-asassn-curve', 'selectedData'),
    Input('graph-asassn-curve', 'clickData'),
    State('store_asassn_lightcurve', 'data'),
    prevent_initial_call=True
)
# todo: I suspect this function -- selectData --  in rounding gaia_id, therefore we loose part of gaia_id
# Try to make gaia_id string (not an integer as it is)
# todo: Check how JavaScript keeps long jd tails

clientside_callback(
    ClientsideFunction(
        namespace='clientside',
        function_name='plotLightcurveFromStore'
    ),
    Output('graph-asassn-curve', 'figure'),
    Input('store_asassn_lightcurve', 'data'),
    State('graph-asassn-curve', 'figure'),
    prevent_initial_call=True
)

clientside_callback(
    ClientsideFunction(
        namespace='clientside',
        function_name='unselectData'
    ),
    Output('store_asassn_lightcurve', 'data', allow_duplicate=True),
    Input('btn-asassn-unselect', 'n_clicks'),
    State('store_asassn_lightcurve', 'data'),
    prevent_initial_call=True
)

clientside_callback(
    ClientsideFunction(
        namespace='clientside',
        function_name='deleteSelected'
    ),
    Output('store_asassn_lightcurve', 'data', allow_duplicate=True),
    Input('btn-asassn-delete', 'n_clicks'),
    State('store_asassn_lightcurve', 'data'),
    prevent_initial_call=True
)

clientside_callback(
    ClientsideFunction(
        namespace='clientside',
        function_name='clearInput'
    ),
    Output('input-asassn-source-id', 'value'),
    Input('btn-asassn-clear-source_id', 'n_clicks'),
    prevent_initial_call=True
)


@callback(Output('download-asassn-lc', 'data'),  # ------ Download -----
          Input('btn-asassn-download-lc', 'n_clicks'),
          State('store_asassn_lightcurve', 'data'),
          State('select-asassn-format', 'value'),
          prevent_initial_call=True)
def download_asassn_lc(n_clicks, js_lightcurve, table_format):
    """Exports the stored ASAS-SN lightcurve through the shared bridge layer."""
    if not n_clicks or js_lightcurve is None:
        raise PreventUpdate

    try:
        lcd = CurveDash.from_serialized(js_lightcurve)
        profile = 'asassn' if is_votable_export_format(table_format) else None
        file_bstring = export_curvedash(lcd, table_format, profile=profile)

        gaia_part = resolve_target_identifier(lcd)
        outfile_base = sanitize_filename(f'lc_asassn_{gaia_part}_{lcd.band}')
        ext = export_file_extension(table_format)
        outfile = f'{outfile_base}.{ext}'

        set_props('div-asassn-alert', {'children': '', 'style': {'display': 'none'}})
        return dcc.send_bytes(file_bstring, outfile)
    except Exception as e:
        logger.warning('lightcurve_asassn.download_asassn_lc: %s', e)
        set_props(
            'div-asassn-alert',
            {'children': message.warning_alert(e), 'style': {'display': 'block'}},
        )
        return no_update
