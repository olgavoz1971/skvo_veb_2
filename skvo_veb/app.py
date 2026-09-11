import flask
from dash import Dash
from skvo_veb.config import Config

# Create Flask server instance
server = flask.Flask(__name__)

# Configure background callback manager (Celery or Diskcache based on config)
background_callback_manager = Config.get_background_callback_manager(__name__)

# Initialize Dash application with server-side page routing.
# URL prefixes: Config.dash_pathname_kwargs() (BEHIND_WSGI_ALIAS in .env).
app = Dash(
    __name__,
    server=server,
    use_pages=True,
    background_callback_manager=background_callback_manager,
    suppress_callback_exceptions=True,
    **Config.dash_pathname_kwargs(),
)

app.title = 'Gaia VEB lightcurves Dashboard'
