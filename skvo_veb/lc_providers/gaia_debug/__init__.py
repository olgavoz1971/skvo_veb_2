"""Gaia DR3 debug lightcurve provider (synthetic catalogue for UI development)."""

from skvo_veb.lc_providers.gaia_debug.debug_catalog import AA_AND, AB_AND, V433_AQL
from skvo_veb.lc_providers.gaia_debug.provider import GaiaDr3DebugProvider, GaiaDr3Provider

__all__ = [
    "AA_AND",
    "AB_AND",
    "GaiaDr3DebugProvider",
    "GaiaDr3Provider",
    "V433_AQL",
]
