"""Multi-mission lightcurve search and fetch adapters.

Mission providers return standard catalog tables from ``search_catalog`` and
``VOLightCurve`` instances from ``fetch_lightcurve``. Dash pages convert VO
lightcurves through ``utils.lc_bridge.volc_to_curvedash`` only at the UI boundary.

See ``docs/mission_lightcurve_providers.md`` for the full contract.
"""

from skvo_veb.lc_providers.base import (
    MissionArchiveMatch,
    MissionCapabilities,
    MissionLightcurveProvider,
)
from skvo_veb.lc_providers.registry import get_provider, list_missions

__all__ = [
    "MissionArchiveMatch",
    "MissionCapabilities",
    "MissionLightcurveProvider",
    "get_provider",
    "list_missions",
]
