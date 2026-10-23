"""Calibration form helpers for the GP page (transport packet, not CurveDash).

The GP page keeps the lightcurve as an opaque transport JSON. These helpers read the
calibration from its ``meta`` block for the editor, and write the edited values back.
Suggested values are only offered in the form; nothing is stored until the user applies.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from skvo_veb.utils.lc_config import METADATA_KEY_READINESS
from skvo_veb.utils.photcal_coherence import (
    apply_photcal_form_values,
    fill_missing_photcal_form_values,
    photcal_form_values_from_storage,
)

logger = logging.getLogger(__name__)


def photcal_form_values_for_packet(transport_json: str) -> dict[str, Any]:
    """Builds the editor values for a packet, gaps filled with the suggested values.

    The packet itself is not changed. The suggested values only appear in the form,
    so the user can apply them in one step.

    Args:
        transport_json (str): Transport JSON string with a ``meta`` block.

    Returns:
        dict: Keys ``filter_name``, ``zp_flux``, ``zp_flux_unit``, ``zp_mag``,
            ``mag_sys`` and ``flux_unit``.
    """
    meta = json.loads(transport_json)["meta"]
    stored = photcal_form_values_from_storage(meta.get("photcal"), meta.get("flux_unit"))
    return fill_missing_photcal_form_values(stored)


def apply_photcal_form_to_packet(
    transport_json: str,
    *,
    filter_name: Any,
    zp_flux: Any,
    zp_flux_unit: Any,
    zp_mag: Any,
    mag_sys: Any,
    flux_unit: Any,
) -> tuple[str, list[str]]:
    """Writes edited calibration values into the packet ``meta`` block.

    The photometry arrays are not touched. The flux column unit is written only for
    a flux-domain packet. The readiness report is dropped because it no longer
    describes the packet.

    Args:
        transport_json (str): Transport JSON string with a ``meta`` block.
        filter_name: Form passband label.
        zp_flux: Form zero-point flux.
        zp_flux_unit: Form zero-point flux unit (blank means dimensionless).
        zp_mag: Form zero-point magnitude.
        mag_sys: Form magnitude system.
        flux_unit: Form flux column unit (blank means dimensionless).

    Returns:
        tuple: ``(new_transport_json, warnings)``. The warnings must be shown to the user.
    """
    packet = json.loads(transport_json)
    meta = packet["meta"]
    photcal, flux_internal, warnings = apply_photcal_form_values(
        filter_name=filter_name,
        zp_flux=zp_flux,
        zp_flux_unit=zp_flux_unit,
        zp_mag=zp_mag,
        mag_sys=mag_sys,
        flux_unit=flux_unit,
        existing_photcal=meta.get("photcal"),
    )
    meta["photcal"] = photcal
    if meta.get("active_domain") == "flux":
        meta["flux_unit"] = flux_internal
    meta.pop(METADATA_KEY_READINESS, None)
    return json.dumps(packet), warnings
