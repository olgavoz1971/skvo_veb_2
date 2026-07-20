"""Provider-specific metadata enrichment for Gaia DR3 VEB fetched lightcurves."""

from __future__ import annotations

import logging

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
        raise PipeException("Gaia DR3 VEB: filter name is required for lightcurve metadata.")

    meta = volc.table.meta
    if meta is None:
        volc.table.meta = {}
        meta = volc.table.meta

    description = meta.get("description")
    if not description or not str(description).strip():
        raise PipeException(
            "Gaia DR3 VEB: retrieved lightcurve is missing TABLE description metadata."
        )

    base_name = meta.get("name") or meta.get("ID")
    if not base_name or not str(base_name).strip():
        raise PipeException(
            "Gaia DR3 VEB: retrieved lightcurve is missing TABLE name metadata."
        )

    title = f"{str(base_name).strip()} in {filter_label} filter"
    meta["name"] = title
    meta["lightcurve_title"] = title

    logger.debug(
        "Gaia DR3 VEB metadata enriched title=%s publication_id=%s",
        title,
        meta.get("bibcode") or meta.get("publication_id"),
    )
    return volc
