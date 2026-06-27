import flask
from dash import Dash
from skvo_veb.config import Config

# Create Flask server instance
server = flask.Flask(__name__)

# Configure background callback manager (Celery or Diskcache based on config)
background_callback_manager = Config.get_background_callback_manager(__name__)

# Initialize Dash application with server-side page routing
app = Dash(
    __name__,
    server=server,
    use_pages=True,
    url_base_pathname='/igebc/',
    background_callback_manager=background_callback_manager,
    suppress_callback_exceptions=True
)

app.title = 'Gaia VEB lightcurves Dashboard'
