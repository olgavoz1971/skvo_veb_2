import pandas as pd
from dash import dash_table
from dash.dash_table.Format import Format, Scheme

style_data_conditional = [
    {
        'if': {'state': 'active'},  # 'active' | 'selected'
        'backgroundColor': 'bs-table-color',
        'border': 'bs-border-width' + ' bs-border-style' + ' bs-border-color',
    }
]


def table_with_link(df: pd.DataFrame, tooltips: dict | None = None, numeric_columns: dict | str = '', ident=''):
    if tooltips is None:
        tooltips = {}
    table = dash_table.DataTable(
        # https://dash.plotly.com/datatable
        # https://dash.plotly.com/datatable/style
        # https://dash.plotly.com/datatable/reference
        # css=[
        # {'selector': '.dash-cell', 'rule': 'font-size: 10px; font-family: cursive'},
        # {'selector': '.dash-table-tooltip', 'rule': 'background-color: grey; font-family: monospace; color: white'},
        # ],
        data=df.to_dict(orient='records'),
        # columns=[{'id': x, 'name': x, 'presentation': 'markdown'} for x in df.columns],
        columns=[
            # {'id': x, 'name': x, 'type': 'numeric', 'format': Format(precision=2, scheme=Scheme.fixed)}
            {'id': x, 'name': x, 'type': 'numeric', 'format': Format(precision=numeric_columns[x], scheme=Scheme.fixed)}
            if x in dict(numeric_columns)
            else {'id': x, 'name': x, 'presentation': 'markdown'}
            for x in df.columns],

        # if x == 'id' else {'id': x, 'name': x, 'type': 'text', 'presentation': 'markdown'} for x in df.columns],

        # row_selectable='single',
        tooltip_header={x: tooltips.get(x, x) for x in df.columns},
        tooltip_delay=0, tooltip_duration=None,
        page_action="native", sort_action="native", page_current=0, page_size=20,
        markdown_options={'link_target': '_self'},  # _blank opens the link in a new tab, _self - in the same
        # style_cell={"font-size": 14, 'font-family': 'courier', 'textAlign': 'left'},
        style_cell={"font-size": 14, 'textAlign': 'left'},
        cell_selectable=True,
        style_header={"font-size": 14, 'font-family': 'courier',
                      # 'font-weight': 'bold',
                      'color': '#000',
                      # 'backgroundColor': '#cacaca',
                      'backgroundColor': 'var(--bs-light)',
                      # 'border': 'var(--bs-border-width) solid var(--bs-border-color)',
                      # 'border': 'var(--bs-border-width)' + ' var(--bs-border-style)'+' var(--bs-border-color)',
                      # 'border': '1px solid #bebebe',
                      # 'textAlign': 'center'
                      'textAlign': 'left'
                      },
        # row_deletable=True,
        style_data_conditional=style_data_conditional,
        id=ident
    )
    return table


def highlite_styles(row_index: int):
    highlite_row_style = [{'if': {'row_index': row_index},
                           'color': 'red'}]     # text color
    return style_data_conditional + highlite_row_style
