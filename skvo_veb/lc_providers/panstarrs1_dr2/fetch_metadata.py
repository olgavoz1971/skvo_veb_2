"""Title and VO envelope enrichment for fetched Pan-STARRS1 DR2 lightcurves."""

from __future__ import annotations

import logging

from skvo_veb.lc_providers.discovery_fetch_context import (
    DiscoveryFetchContext,
    resolve_lookup_name_for_discovery_fetch,
)
from skvo_veb.lc_providers.panstarrs1_dr2 import config
from skvo_veb.lc_providers.panstarrs1_dr2.ps1_names import format_ps1_object_name
from skvo_veb.volightcurve import VOLightCurve

logger = logging.getLogger(__name__)


def enrich_fetched_volightcurve(
    volc: VOLightCurve,
    *,
    obj_id: int,
    filter_name: str,
    object_name: str = "",
    discovery_context: DiscoveryFetchContext | None = None,
) -> VOLightCurve:
    """Applies catalogue-aware titles and export metadata.

    Args:
        volc (VOLightCurve): Product from ``build_volightcurve_from_detections``.
        obj_id (int): Pan-STARRS mean object identifier.
        filter_name (str): PS1 filter ``g``, ``r``, ``i``, ``z``, or ``y``.
        object_name (str): Catalogue ``object_name`` (PS1 ``objID`` string).
        discovery_context (DiscoveryFetchContext, optional): Discovery session metadata.

    Returns:
        VOLightCurve: Same instance with updated ``table.meta``.

    Raises:
        PipeException: When required description metadata is missing.
    """
    band = config.band_spec_for_filter_name(filter_name)
    obj_label = format_ps1_object_name(obj_id)
    lookup_name = resolve_lookup_name_for_discovery_fetch(
        discovery_context,
        max_association_arcsec=config.LOOKUP_ASSOCIATION_MAX_ARCSEC,
    )

    title = f"{obj_label} filter={band.filter_name}"
    if lookup_name:
        title = f"{lookup_name} - {title}"

    description = config.detection_lightcurve_description(
        obj_id=obj_id,
        filter_name=band.filter_name,
        lookup_name=lookup_name,
    )

    meta = volc.table.meta
    if meta is None:
        volc.table.meta = {}
        meta = volc.table.meta

    meta["name"] = title
    meta["lightcurve_title"] = title
    meta["title"] = title
    meta["lookup_name"] = lookup_name
    meta["table_description"] = description
    meta["description"] = description
    meta["obj_id"] = int(obj_id)
    meta["filter"] = band.filter_name
    meta["mission"] = config.PROVIDER_ID
    meta["facility_name"] = config.FACILITY_NAME
    meta["instrument_name"] = config.INSTRUMENT_NAME
    meta["publication_id"] = config.PUBLICATION_BIBCODE
    meta["bibcode"] = config.PUBLICATION_BIBCODE
    meta["photcal"] = config.photcal_dict_for_band(band)

    if discovery_context is not None and discovery_context.user_target:
        meta["user_search_target"] = str(discovery_context.user_target).strip()

    if not str(object_name).strip():
        object_name = obj_label

    logger.debug(
        "%s enriched obj_id=%s filter=%s lookup=%s title=%s n_points=%s",
        config.DISPLAY_NAME,
        obj_id,
        band.filter_name,
        lookup_name,
        title,
        len(volc),
    )
    return volc
