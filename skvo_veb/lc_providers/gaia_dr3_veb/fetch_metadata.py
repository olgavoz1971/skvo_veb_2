"""Provider-specific metadata enrichment for Gaia DR3 VEB fetched lightcurves."""

from __future__ import annotations

import logging

from skvo_veb.lc_providers.gaia_dr3_veb import config
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve

logger = logging.getLogger(__name__)


def enrich_fetched_volightcurve(
    volc: VOLightCurve,
    *,
    filter_name: str,
) -> VOLightCurve:
    """Normalises title and description on a VEB ``accref`` lightcurve product.

    The archive TABLE ``name`` often omits the passband; this helper appends the
    filter label for plot captions and export. Description must already be present
    on the downloaded VOTable (``TABLE/DESCRIPTION``).

    Args:
        volc (VOLightCurve): Parsed product from ``fetch_volightcurve_from_accref``.
        filter_name (str): Human-readable filter label from the catalogue row.

    Returns:
        VOLightCurve: The same instance with updated ``table.meta``.

    Raises:
        PipeException: When filter name or table description is missing.
    """
    filter_label = str(filter_name or "").strip()
    if not filter_label:
        raise PipeException(
            f"{config.DISPLAY_NAME}: filter name is required for lightcurve metadata."
        )

    meta = volc.table.meta
    if meta is None:
        volc.table.meta = {}
        meta = volc.table.meta

    description = meta.get("description")
    if not description or not str(description).strip():
        raise PipeException(
            f"{config.DISPLAY_NAME}: retrieved lightcurve is missing TABLE description metadata."
        )

    base_name = meta.get("name") or meta.get("ID")
    if not base_name or not str(base_name).strip():
        raise PipeException(
            f"{config.DISPLAY_NAME}: retrieved lightcurve is missing TABLE name metadata."
        )

    title = f"{str(base_name).strip()} in {filter_label} filter"
    meta["name"] = title
    meta["lightcurve_title"] = title
    meta["facility_name"] = config.FACILITY_NAME
    meta["instrument_name"] = config.INSTRUMENT_NAME

    logger.debug(
        "%s metadata enriched title=%s publication_id=%s",
        config.DISPLAY_NAME,
        title,
        meta.get("bibcode") or meta.get("publication_id"),
    )
    return volc
