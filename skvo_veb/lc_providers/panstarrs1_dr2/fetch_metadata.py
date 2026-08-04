"""Title and VO envelope enrichment for fetched Pan-STARRS1 DR2 lightcurves."""

from __future__ import annotations

import logging

from skvo_veb.lc_providers.discovery_fetch_context import DiscoveryFetchContext
from skvo_veb.lc_providers.panstarrs1_dr2 import config
from skvo_veb.lc_providers.panstarrs1_dr2.ps1_names import format_ps1_object_name
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve

logger = logging.getLogger(__name__)


def enrich_fetched_volightcurve(
    volc: VOLightCurve,
    *,
    obj_id: int,
    filter_code: str,
    object_name: str = "",
    discovery_context: DiscoveryFetchContext | None = None,
) -> VOLightCurve:
    """Applies catalogue-aware titles and export metadata.

    Args:
        volc (VOLightCurve): Product from ``build_volightcurve_from_detections``.
        obj_id (int): Pan-STARRS mean object identifier.
        filter_code (str): Filter code.
        object_name (str): IAU name from discovery when available.
        discovery_context (DiscoveryFetchContext, optional): Discovery session metadata.

    Returns:
        VOLightCurve: Same instance with updated ``table.meta``.

    Raises:
        PipeException: When required description metadata is missing.
    """
    band = config.band_spec_for_code(filter_code)
    name_bit = format_ps1_object_name(obj_id)
    if not str(object_name).strip():
        object_name = name_bit

    title = f"{name_bit} ({band.filter_name})"
    if discovery_context is not None and discovery_context.user_target:
        user_target = str(discovery_context.user_target).strip()
        if user_target and user_target != name_bit:
            title = f"{user_target} - {title}"

    meta = volc.table.meta
    if meta is None:
        volc.table.meta = {}
        meta = volc.table.meta

    description = meta.get("table_description") or meta.get("description")
    if not description or not str(description).strip():
        raise PipeException(
            f"{config.DISPLAY_NAME}: lightcurve is missing TABLE description after build."
        )

    meta["name"] = title
    meta["lightcurve_title"] = title
    meta["title"] = title
    meta["lookup_name"] = name_bit if name_bit else None
    meta["obj_id"] = int(obj_id)
    meta["filter"] = band.filter_code
    meta["mission"] = config.PROVIDER_ID
    meta["facility_name"] = config.FACILITY_NAME
    meta["instrument_name"] = config.INSTRUMENT_NAME
    meta["publication_id"] = config.PUBLICATION_BIBCODE
    meta["bibcode"] = config.PUBLICATION_BIBCODE
    meta["photcal"] = config.photcal_dict_for_band(band)

    if discovery_context is not None and discovery_context.user_target:
        meta["user_search_target"] = str(discovery_context.user_target).strip()

    logger.debug(
        "%s enriched obj_id=%s filter=%s title=%s n_points=%s",
        config.DISPLAY_NAME,
        obj_id,
        band.filter_code,
        title,
        len(volc),
    )
    return volc
