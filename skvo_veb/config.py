import logging
import os
from dash import DiskcacheManager, CeleryManager
import diskcache
from celery import Celery

logger = logging.getLogger(__name__)

# Keys accepted in SIMBAD_MIRROR. Values are the hostnames astroquery allows.
SIMBAD_SERVERS = {
    "cds": "simbad.cds.unistra.fr",
    "harvard": "simbad.harvard.edu",
}


class Config:
    USE_REDIS = (
        os.getenv("USE_REDIS", "false").upper() == "TRUE"
        or os.getenv("USE_REDIS", "false") == "1"
    )
    DEBUG_APP = (
        os.getenv("DEBUG_APP", "false").upper() == "TRUE"
        or os.getenv("DEBUG_APP", "false") == "1"
    )
    BEHIND_WSGI_ALIAS = (
        os.getenv("BEHIND_WSGI_ALIAS", "false").upper() == "TRUE"
        or os.getenv("BEHIND_WSGI_ALIAS", "false") == "1"
    )
    APP_LOG = os.getenv("APP_LOG")
    DISKCACHE_DIR = os.getenv("DISKCACHE_DIR")
    REDIS_BROKER = os.getenv("REDIS_BROKER")
    REDIS_BACKEND = os.getenv("REDIS_BACKEND")

    @staticmethod
    def dash_pathname_kwargs() -> dict:
        """Returns Dash URL-prefix kwargs for local run versus Apache.

        Apache ``WSGIScriptAlias /igebc`` strips ``/igebc`` before Flask sees
        the request, so production (``BEHIND_WSGI_ALIAS=true``) must set only
        ``requests_pathname_prefix``. The local Dash server has no alias, so it
        needs ``url_base_pathname`` (request and route prefixes both ``/igebc/``).

        Returns:
            dict: Keyword arguments to unpack into ``dash.Dash``.
        """
        if Config.BEHIND_WSGI_ALIAS:
            return {"requests_pathname_prefix": "/igebc/"}
        return {"url_base_pathname": "/igebc/"}

    @staticmethod
    def simbad_server() -> str:
        """Returns the astroquery SIMBAD host selected by ``SIMBAD_MIRROR``.

        Unset, blank, or ``cds`` selects the CDS mirror. ``harvard`` selects
        ``simbad.harvard.edu``. The comparison is case-insensitive.

        Returns:
            str: Hostname accepted by ``astroquery.simbad.Simbad.server``.

        Raises:
            ValueError: If ``SIMBAD_MIRROR`` is not ``cds`` or ``harvard``.
        """
        raw = os.getenv("SIMBAD_MIRROR", "cds").strip().lower() or "cds"
        try:
            return SIMBAD_SERVERS[raw]
        except KeyError:
            raise ValueError(
                f"SIMBAD_MIRROR {raw!r} is not recognised. Use 'cds' or 'harvard'."
            ) from None

    @staticmethod
    def get_background_callback_manager(server_name):
        if Config.USE_REDIS:
            celery_app = Celery(
                server_name,
                broker=Config.REDIS_BROKER,
                backend=Config.REDIS_BACKEND,
                broker_connection_retry_on_startup=True,
            )
            return CeleryManager(celery_app)
        else:
            return DiskcacheManager(diskcache.Cache(Config.DISKCACHE_DIR))


def configure_simbad_server() -> str:
    """Points the shared astroquery Simbad client at ``SIMBAD_MIRROR``.

    The assignment is on the module-level ``Simbad`` object, so later
    ``query_object`` and ``query_objectids`` calls use the same mirror.

    Returns:
        str: Hostname assigned to ``Simbad.server``.

    Raises:
        ValueError: If ``SIMBAD_MIRROR`` is not ``cds`` or ``harvard``.
    """
    from astroquery.simbad import Simbad

    host = Config.simbad_server()
    Simbad.server = host
    logger.info("SIMBAD mirror set to %s", host)
    return host
