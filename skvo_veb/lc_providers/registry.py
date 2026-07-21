"""Mission provider registry for Lightcurve Discovery."""

from __future__ import annotations

import logging

from skvo_veb.lc_providers.base import MissionDescriptor, MissionLightcurveProvider
from skvo_veb.lc_providers.gaia_debug import GaiaDr3Provider
from skvo_veb.lc_providers.gaia_dr3_veb import GaiaDr3VebProvider
from skvo_veb.lc_providers.ogle_ocvs import OgleOcvsProvider
from skvo_veb.lc_providers.personal_ts import PersonalTsProvider
from skvo_veb.lc_providers.upjs_ts import UpjsTsProvider
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, MissionLightcurveProvider] = {
    GaiaDr3Provider.mission_id: GaiaDr3Provider(),
    GaiaDr3VebProvider.mission_id: GaiaDr3VebProvider(),
    OgleOcvsProvider.mission_id: OgleOcvsProvider(),
    PersonalTsProvider.mission_id: PersonalTsProvider(),
    UpjsTsProvider.mission_id: UpjsTsProvider(),
}


def get_provider(mission_id: str) -> MissionLightcurveProvider:
    """Returns a registered mission provider instance.

    Args:
        mission_id (str): Mission slug from the UI or catalog ``lc_key``.

    Returns:
        MissionLightcurveProvider: Provider for the requested mission.

    Raises:
        PipeException: If ``mission_id`` is unknown.
    """
    provider = PROVIDERS.get(mission_id)
    if provider is None:
        known = ", ".join(sorted(PROVIDERS)) or "(none)"
        raise PipeException(f"Unknown mission '{mission_id}'. Registered missions: {known}.")
    return provider


def list_missions() -> list[MissionDescriptor]:
    """Lists registered missions for UI selectors.

    Returns:
        list[MissionDescriptor]: Sorted mission metadata entries.
    """
    return sorted(
        (provider.descriptor() for provider in PROVIDERS.values()),
        key=lambda item: item.display_name.lower(),
    )
