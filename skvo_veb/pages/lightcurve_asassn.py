import logging
import uuid

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
    dash,
    no_update,
    set_props,
)
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from skvo_veb.components import message
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import (
    apply_phot_domain_view,
    export_curvedash,
    export_file_extension,
)
from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD,
    display_epoch_offset,
    DEFAULT_EXPORT_FORMAT,
    DOMAIN_FLUX,
    DOMAIN_MAG,
    EXPORT_FORMAT_OPTIONS,
    TIME_AXIS_DATE,
    TIME_AXIS_MJD,
    is_votable_export_format,
)
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
from skvo_veb.utils.mission_config.asassn import resolve_target_identifier
from skvo_veb.utils.my_tools import (
    PipeException,
    float_pattern,
    is_like_gaia_id,
    positive_float_pattern,
    safe_float,
    sanitize_filename,
)
from skvo_veb.utils.page_session import SESSION_STORE
from skvo_veb.utils.request_asassn import load_asassn_lightcurve

register_page(
    __name__,
    name='ASAS-SN',
    order=2,
    path='/asassn',
    title='IGEBC: ASAS-SN Lightcurve',
    in_navbar=True,
)

ASASSN_PAGE_NAMESPACE = 'asassn'
DISPLAY_EPOCH_JD = DEFAULT_EPOCH_JD

row_class_name = 'd-flex g-2 justify-content-end align-items-end'
label_font_size = '0.8em'
switch_label_style_vert = {'display': 'block', 'padding': '2px', 'font-size': label_font_size}


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
            dcc.Store(id='store_user_tab_id_asassn', **SESSION_STORE),
            dcc.Store(id='store_asassn_lc_revision', **SESSION_STORE),
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
                            dbc.Col(
                                [
                                    dbc.Switch(
                                        id='mag_view_asassn_switch',
                                        label='Magnitude',
                                        value=False,
                                        persistence=False,
                                        label_style=switch_label_style_vert,
                                    ),
                                    dcc.RadioItems(
                                        id='time_axis_asassn_switch',
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
                                    ),
                                ],
                                md=2,
                                sm=4,
                            ),
                            dbc.Col(
                                [
                                    html.Details(
                                        [
                                            html.Summary('Folding', style={'font-size': label_font_size}),
                                            dbc.Stack(
                                                [
                                                    dbc.Label(
                                                        'Period:',
                                                        html_for='period_asassn_input',
                                                        style={'width': '7em', 'font-size': label_font_size},
                                                    ),
                                                    dcc.Input(
                                                        id='period_asassn_input',
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
                                                        html_for='epoch_asassn_input',
                                                        style={'width': '7em', 'font-size': label_font_size},
                                                    ),
                                                    dcc.Input(
                                                        id='epoch_asassn_input',
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
                                                        id='fold_asassn_switch',
                                                        label='Fold',
                                                        value=False,
                                                        label_style=switch_label_style_vert,
                                                        persistence=False,
                                                        style={'width': '40%'},
                                                    ),
                                                    dbc.Button(
                                                        'Recalc Phase',
                                                        id='recalc_phase_asassn_button',
                                                        size='sm',
                                                        style={'width': '60%', 'marginBottom': '5px'},
                                                    ),
                                                ],
                                                direction='horizontal',
                                                gap=2,
                                            ),
                                        ],
                                        open=True,
                                    ),
                                    html.Div(
                                        [
                                            dbc.Label(
                                                'Unable to fold; the period is unknown',
                                                id='label-fold-asassn-warning',
                                            ),
                                        ],
                                        id='div-fold-asassn-controls',
                                        style={'min-height': '30px'},
                                    ),
                                ],
                                md=4,
                                sm=12,
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
                        class_name=row_class_name,
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
    lcd = load_asassn_lightcurve(source_id=source_id, band=band, force_update=force_update)
    return lcd


def _display_epoch_value(lcd: CurveDash):
    """Returns the epoch input value relative to the display epoch.

    Args:
        lcd (CurveDash): Loaded lightcurve.

    Returns:
        float: Epoch offset for the UI input (``0.0`` when no catalogue epoch).
    """
    return display_epoch_offset(lcd.epoch, DISPLAY_EPOCH_JD)


def _bump_revision() -> str:
    """Returns a new revision token to trigger dependent callbacks.

    Returns:
        str: UUID string.
    """
    return str(uuid.uuid4())


@callback(
    output=dict(
        header=Output('h1-asassn', 'children'),
        row_content_style=Output('row-asassn-content', 'style'),
        div_alert_style=Output('div-asassn-alert', 'style'),
        alert_message=Output('div-asassn-alert', 'children'),
        fold_controls_style=Output('div-fold-asassn-controls', 'style'),
        warning_asassn_style=Output('label-fold-asassn-warning', 'style'),
        user_tab_id=Output('store_user_tab_id_asassn', 'data', allow_duplicate=True),
        revision=Output('store_asassn_lc_revision', 'data', allow_duplicate=True),
        period_val=Output('period_asassn_input', 'value', allow_duplicate=True),
        epoch_val=Output('epoch_asassn_input', 'value', allow_duplicate=True),
        mag_switch=Output('mag_view_asassn_switch', 'value', allow_duplicate=True),
    ),
    inputs=dict(
        _1=Input('input-asassn-source-id', 'n_submit'),
        _2=Input('btn-asassn-new-source', 'n_clicks'),
        _3=Input('btn-asassn-update', 'n_clicks'),
    ),
    state=dict(
        source_id=State('input-asassn-source-id', 'value'),
        band=State('select-asassn-band', 'value'),
        phase_view=State('fold_asassn_switch', 'value'),
        user_tab_id=State('store_user_tab_id_asassn', 'data'),
    ),
    running=[
        (Output('btn-asassn-update', 'disabled'), True, False),
        (Output('btn-cancel-asassn-update', 'disabled'), False, True),
        (Output('btn-asassn-new-source', 'disabled'), True, False),
    ],
    cancel=[Input('btn-cancel-asassn-update', 'n_clicks')],
    background=True,
    prevent_initial_call=True,
)
def load_new_source(_1, _2, _3, source_id, band, phase_view, user_tab_id):
    fold_controls_style = {'display': 'block', 'min-height': '30px'}
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

        period = lcd.period
        period = None if not period else round(period, 5)
        if period is None:
            fold_controls_style = {'display': 'none', 'min-height': '30px'}
            warning_asassn_style = {'display': 'block'}
            lcd.folded_view = False

        if user_tab_id is None:
            user_tab_id = generate_user_tab_id()

        write_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id, lcd.serialize())

        return dict(
            header=header_txt,
            row_content_style={'display': 'block'},
            div_alert_style={'display': 'none'},
            alert_message='',
            fold_controls_style=fold_controls_style,
            warning_asassn_style=warning_asassn_style,
            user_tab_id=user_tab_id,
            revision=_bump_revision(),
            period_val=period,
            epoch_val=_display_epoch_value(lcd),
            mag_switch=lcd.active_domain == DOMAIN_MAG,
        )
    except Exception as exc:
        logger.warning('lightcurve_asassn.load_new_source: %s', exc)
        return dict(
            header=header_txt,
            row_content_style={'display': 'none'},
            div_alert_style={'display': 'block'},
            alert_message=message.warning_alert(exc),
            fold_controls_style={'display': 'none', 'min-height': '30px'},
            warning_asassn_style={'display': 'none'},
            user_tab_id=no_update,
            revision=no_update,
            period_val=no_update,
            epoch_val=no_update,
            mag_switch=no_update,
        )


@callback(
    Output('graph-asassn-curve', 'figure', allow_duplicate=True),
    Input('store_asassn_lc_revision', 'data'),
    Input('time_axis_asassn_switch', 'value'),
    State('store_user_tab_id_asassn', 'data'),
    State('fold_asassn_switch', 'value'),
    prevent_initial_call='initial_duplicate',
)
def plot_asassn_curve(_revision, time_axis_mode, user_tab_id, phase_view):
    if not user_tab_id or not has_cached_lc(ASASSN_PAGE_NAMESPACE, user_tab_id):
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id)
        fig = figure_from_serialized(
            js_lightcurve,
            phase_view=bool(phase_view),
            display_epoch=DISPLAY_EPOCH_JD,
            time_axis_mode=time_axis_mode or TIME_AXIS_MJD,
            color_by_label=False,
            dragmode='lasso',
        )
        set_props('div-asassn-alert', {'children': None, 'style': {'display': 'none'}})
        return fig
    except Exception as exc:
        logger.warning('lightcurve_asassn.plot_asassn_curve: %s', exc)
        set_props(
            'div-asassn-alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        return no_update


@callback(
    Output('store_asassn_lc_revision', 'data', allow_duplicate=True),
    Output('fold_asassn_switch', 'value', allow_duplicate=True),
    Input('recalc_phase_asassn_button', 'n_clicks'),
    Input('fold_asassn_switch', 'value'),
    State('store_user_tab_id_asassn', 'data'),
    State('period_asassn_input', 'value'),
    State('epoch_asassn_input', 'value'),
    prevent_initial_call=True,
)
def fold_or_recalculate_phase(n_clicks, phase_view, user_tab_id, period, epoch):
    if ctx.triggered_id == 'recalc_phase_asassn_button' and n_clicks is None:
        raise PreventUpdate
    try:
        epoch_value = safe_float(epoch, 0)
        period_value = safe_float(period)
        if phase_view and not period_value:
            raise PipeException('Set the period and try again')

        js_lightcurve = read_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        if lcd.lightcurve is None:
            raise PipeException('recalculate_phase: Please, download the lightcurve first')

        if period_value:
            lcd.period = period_value
            lcd.period_unit = 'd'
        if epoch_value is not None:
            lcd.epoch = epoch_value + DISPLAY_EPOCH_JD

        lcd.folded_view = bool(phase_view)
        lcd.recalc_phase()
        write_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        set_props('div-asassn-alert', {'children': None, 'style': {'display': 'none'}})
        return _bump_revision(), no_update
    except Exception as exc:
        logger.warning('lightcurve_asassn.fold_or_recalculate_phase: %s', exc)
        set_props(
            'div-asassn-alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        return no_update, False


@callback(
    Output('store_asassn_lc_revision', 'data', allow_duplicate=True),
    Output('mag_view_asassn_switch', 'value', allow_duplicate=True),
    Input('mag_view_asassn_switch', 'value'),
    State('store_user_tab_id_asassn', 'data'),
    prevent_initial_call=True,
)
def toggle_mag_view(show_magnitude, user_tab_id):
    if not user_tab_id:
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)

        desired_domain = DOMAIN_MAG if show_magnitude else DOMAIN_FLUX
        if lcd.active_domain == desired_domain:
            raise PreventUpdate

        apply_phot_domain_view(lcd, show_magnitude)
        write_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        set_props('div-asassn-alert', {'children': '', 'style': {'display': 'none'}})
        return _bump_revision(), no_update
    except PreventUpdate:
        raise
    except Exception as exc:
        logger.warning('lightcurve_asassn.toggle_mag_view: %s', exc)
        set_props(
            'div-asassn-alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        try:
            js_lightcurve = read_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id)
            lcd = CurveDash.from_serialized(js_lightcurve)
            return no_update, lcd.active_domain == DOMAIN_MAG
        except Exception:
            return no_update, False


@callback(
    Output('mag_view_asassn_switch', 'value', allow_duplicate=True),
    Input('store_asassn_lc_revision', 'data'),
    State('store_user_tab_id_asassn', 'data'),
    prevent_initial_call=True,
)
def sync_mag_view_switch(_, user_tab_id):
    if not user_tab_id:
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        return lcd.active_domain == DOMAIN_MAG
    except Exception:
        raise PreventUpdate


@callback(
    Output('store_asassn_lc_revision', 'data', allow_duplicate=True),
    Input('graph-asassn-curve', 'selectedData'),
    Input('graph-asassn-curve', 'clickData'),
    State('store_user_tab_id_asassn', 'data'),
    prevent_initial_call=True,
)
def merge_plot_selection(selected_data, click_data, user_tab_id):
    """Marks clicked or lasso-selected points in the server cache and replots."""
    if not ctx.triggered or not user_tab_id:
        raise PreventUpdate
    trigger_prop = ctx.triggered[0]['prop_id'].rsplit('.', 1)[-1]
    event_data = selected_data if trigger_prop == 'selectedData' else click_data
    if not event_data or not event_data.get('points'):
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        apply_plot_point_selection(lcd, event_data)
        write_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        return _bump_revision()
    except Exception as exc:
        logger.warning('lightcurve_asassn.merge_plot_selection: %s', exc)
        set_props(
            'div-asassn-alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        raise PreventUpdate


@callback(
    Output('store_asassn_lc_revision', 'data', allow_duplicate=True),
    Input('btn-asassn-unselect', 'n_clicks'),
    State('store_user_tab_id_asassn', 'data'),
    prevent_initial_call=True,
)
def unselect_points(n_clicks, user_tab_id):
    """Clears all ``selected`` markers in the cached lightcurve and replots."""
    if not n_clicks or not user_tab_id:
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        clear_plot_point_selection(lcd)
        write_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        set_props('div-asassn-alert', {'children': None, 'style': {'display': 'none'}})
        return _bump_revision()
    except Exception as exc:
        logger.warning('lightcurve_asassn.unselect_points: %s', exc)
        set_props(
            'div-asassn-alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        raise PreventUpdate


@callback(
    Output('store_asassn_lc_revision', 'data', allow_duplicate=True),
    Input('btn-asassn-delete', 'n_clicks'),
    State('store_user_tab_id_asassn', 'data'),
    prevent_initial_call=True,
)
def delete_selected_points(n_clicks, user_tab_id):
    """Removes rows marked ``selected=1`` from the cached lightcurve."""
    if not n_clicks or not user_tab_id:
        raise PreventUpdate
    try:
        js_lightcurve = read_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        if lcd.lightcurve is None or 'selected' not in lcd.lightcurve.columns:
            raise PipeException('Select points to delete first.')
        if not (lcd.lightcurve['selected'] == 1).any():
            set_props(
                'div-asassn-alert',
                {
                    'children': message.warning_alert('Select points to delete first.'),
                    'style': {'display': 'block'},
                },
            )
            raise PreventUpdate
        delete_selected_rows(lcd)
        if lcd.lightcurve is None or lcd.lightcurve.empty:
            raise PipeException('Cannot delete all points from the lightcurve')
        write_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id, lcd.serialize())
        set_props('div-asassn-alert', {'children': None, 'style': {'display': 'none'}})
        return _bump_revision()
    except PreventUpdate:
        raise
    except Exception as exc:
        logger.warning('lightcurve_asassn.delete_selected_points: %s', exc)
        set_props(
            'div-asassn-alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        raise PreventUpdate


clientside_callback(
    ClientsideFunction(namespace='clientside', function_name='clearInput'),
    Output('input-asassn-source-id', 'value'),
    Input('btn-asassn-clear-source_id', 'n_clicks'),
    prevent_initial_call=True,
)


@callback(
    Output('download-asassn-lc', 'data'),
    Input('btn-asassn-download-lc', 'n_clicks'),
    State('store_user_tab_id_asassn', 'data'),
    State('select-asassn-format', 'value'),
    prevent_initial_call=True,
)
def download_asassn_lc(n_clicks, user_tab_id, table_format):
    """Exports the cached ASAS-SN lightcurve through the shared bridge layer."""
    if not n_clicks or not user_tab_id:
        raise PreventUpdate

    try:
        js_lightcurve = read_serialized_lc(ASASSN_PAGE_NAMESPACE, user_tab_id)
        lcd = CurveDash.from_serialized(js_lightcurve)
        profile = 'asassn' if is_votable_export_format(table_format) else None
        file_bstring = export_curvedash(lcd, table_format, profile=profile)

        gaia_part = resolve_target_identifier(lcd)
        outfile_base = sanitize_filename(f'lc_asassn_{gaia_part}_{lcd.band}')
        ext = export_file_extension(table_format)
        outfile = f'{outfile_base}.{ext}'

        set_props('div-asassn-alert', {'children': '', 'style': {'display': 'none'}})
        return dcc.send_bytes(file_bstring, outfile)
    except Exception as exc:
        logger.warning('lightcurve_asassn.download_asassn_lc: %s', exc)
        set_props(
            'div-asassn-alert',
            {'children': message.warning_alert(exc), 'style': {'display': 'block'}},
        )
        return no_update
