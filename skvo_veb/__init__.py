from skvo_veb.logging_config import configure_logging

configure_logging()

import logging
import dash
import dash_bootstrap_components as dbc
from skvo_veb.app import app, server
from skvo_veb.config import Config
from skvo_veb.components import footer

# Define root layout
app.layout = dbc.Container([
    dbc.Row([
        dbc.NavbarSimple([
            dbc.NavItem(dbc.NavLink(page['name'], href=page['relative_path']))
            for page in dash.page_registry.values() if page.get('in_navbar', False)
        ], brand='VEB Gaia',
            color='light',
            dark=False,
            fluid=True,
            className="w-100",
        ),
    ], className="flex-grow-1"
    ),
    dash.page_container,
    dbc.Row(
        footer.footer,
    ),
], fluid=True)

# Expose celery_app for Celery worker (go_celery.sh)
celery_app = None
if Config.USE_REDIS:
    celery_app = getattr(app.background_callback_manager, 'handle', None)
