import dash
from dash import html, dcc


dash.register_page(__name__)

layout = html.Div([
    html.Br(),
    html.H1("SKVO: 404 - Page not found"),
    html.Br(), html.Br(),
    dcc.Markdown('IGEBC - Interactive Gaia Eclipsing Binary Catalog is [here](/igebc)'),
], style={'textAlign': 'center'})
