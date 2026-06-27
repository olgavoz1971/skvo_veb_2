import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
from skvo_veb.utils.my_tools import timeit
# Gaia Eclipsing Binary Catalog - IGEBC
dash.register_page(__name__, name='Home',
                   order=0,
                   title='IGEBC - Interactive Gaia Eclipsing Binary Catalog',
                   description='Gaia Eclipsing Binary Catalog Main Page',
                   in_navbar=True,
                   path='/')


@timeit
def layout():
    return dbc.Container([
        dcc.Location(id='location-main'),
        html.H1('IGEBC - Interactive Gaia Eclipsing Binary Catalog', className="text-primary text-left fs-3"),
        html.Br(),
        dcc.Markdown('''
        The GAIA satellite gathered light curves of more than 2.1 million eclipsing binary stars. The basic parameters of these systems and the light curves 
        in the *G*, *Bp* and *Rp* bands have been recently published in the 3rd GAIA Data release and are available through Vizier service.
    
        *Interactive Gaia Eclipsing Binary Catalog - IGEBC* - allows user-friendly access to GAIA light curves 
        eclipsing binaries In the current version it is possible to search binaries using coordinates or 
        SIMBAD-resolved names, display their light curves in different passband and show parameters from GAIA 
        catalogues.
         
        To search an object by the name or coordinates, go to the [search page](/igebc/search)
        '''),
    ], className="g-0", fluid=True)
