from dash import html, dcc
import dash_bootstrap_components as dbc

external_stylesheets = [
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.3/css/all.min.css'
]

email = 'stefan.parimucha@upjs.sk'
footer = html.Footer([
    html.Hr(),
    dbc.Stack([
        html.Label('Interactive Gaia Eclipsing Binary Catalog'),
        html.Label('Pavol Jozef Šafárik University'),
        dcc.Link('contact us', title=email,
                 href=f'mailto:{email}',
                 target='_blank'
                 # , style={'float': 'right'}
                 ),
    ], direction='horizontal', gap=5),

    # dcc.Link([html.H5('Send an email')], title=email,

]),
