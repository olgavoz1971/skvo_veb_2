"""Lookup-aware metadata enrichment for fetched ZTF lightcurves."""

from __future__ import annotations

import logging

from skvo_veb.lc_providers.discovery_fetch_context import (
    DiscoveryFetchContext,
    lookup_label_from_context,
)
from skvo_veb.lc_providers.ztf import config
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve

logger = logging.getLogger(__name__)


def resolve_lookup_name_for_fetch(
    context: DiscoveryFetchContext | None,
) -> str | None:
    """Returns lookup metadata when a named Simbad cone row is close enough.

    Args:
        context (DiscoveryFetchContext, optional): Discovery session context.

    Returns:
        str or None: Lookup label or ``None`` when association does not apply.
    """
    if context is None:
        return None
    lookup = lookup_label_from_context(context)
    if lookup is None:
        return None
    if context.distance_arcsec is None:
        return None
    tau = config.effective_lookup_association_arcsec(context.radius_arcsec)
    try:
        distance = float(context.distance_arcsec)
    except (TypeError, ValueError):
        return None
    if distance > tau:
        return None
    return lookup


def enrich_fetched_volightcurve(
    volc: VOLightCurve,
    *,
    oid: int | str,
    filtercode: str,
    discovery_context: DiscoveryFetchContext | None = None,
) -> VOLightCurve:
    """Applies ZTF titles and optional lookup metadata for export and plotting.

    Args:
        volc (VOLightCurve): Parsed product from ``build_volightcurve_from_epochs``.
        oid (int or str): ZTF OID.
        filtercode (str): IRSA filter code.
        discovery_context (DiscoveryFetchContext, optional): Discovery session
            metadata for positional lookup association.

    Returns:
        VOLightCurve: Same instance with updated ``table.meta``.

    Raises:
        PipeException: When band metadata cannot be resolved.
    """
    band = config.band_spec_for_filtercode(filtercode)
    oid_int = int(oid)
    oid_label = config.format_ztf_oid_name(oid_int)
    lookup_name = resolve_lookup_name_for_fetch(discovery_context)

    meta = volc.table.meta
    if meta is None:
        volc.table.meta = {}
        meta = volc.table.meta

    if lookup_name:
        title = f"{lookup_name} - {oid_label} ({band.filter_name})"
        meta["lookup_name"] = lookup_name
    else:
        title = f"{oid_label} ({band.filter_name})"
        meta["lookup_name"] = None

    meta["name"] = title
    meta["lightcurve_title"] = title
    meta["title"] = title
    meta["ztf_oid"] = oid_int
    meta["filtercode"] = band.filtercode
    meta["mission"] = config.PROVIDER_ID
    meta["facility_name"] = config.FACILITY_NAME
    meta["instrument_name"] = config.INSTRUMENT_NAME
    meta["publication_id"] = config.PUBLICATION_BIBCODE
    meta["bibcode"] = config.PUBLICATION_BIBCODE
    meta["photcal"] = config.photcal_dict_for_filtercode(band.filtercode)

    if discovery_context is not None and discovery_context.user_target:
        meta["user_search_target"] = str(discovery_context.user_target).strip()

    description = meta.get("description") or meta.get("table_description")
    if not description or not str(description).strip():
        raise PipeException(
            f"{config.DISPLAY_NAME}: lightcurve is missing TABLE description after build."
        )

    logger.debug(
        "%s enriched oid=%s filter=%s lookup=%s n_points=%s",
        config.DISPLAY_NAME,
        oid_int,
        band.filtercode,
        lookup_name,
        len(volc),
    )
    return volc
