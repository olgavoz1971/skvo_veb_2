"""Provider-specific metadata enrichment for UPJŠ fetched lightcurves."""

from __future__ import annotations

import logging

from skvo_veb.lc_providers.upjs_ts import config
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve

logger = logging.getLogger(__name__)


def enrich_fetched_volightcurve(
    volc: VOLightCurve,
    *,
    filter_name: str,
    object_id: str | None = None,
) -> VOLightCurve:
    """Normalises title and description on a UPJŠ ``accref`` lightcurve product.

    Args:
        volc (VOLightCurve): Parsed product from ``fetch_volightcurve_from_accref``.
        filter_name (str): Passband label from the catalogue row (``ssa_bandpass``).
        object_id (str, optional): Archive object identifier for titling.

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

    base_name = meta.get("name") or meta.get("ID") or object_id
    if not base_name or not str(base_name).strip():
        raise PipeException(
            f"{config.DISPLAY_NAME}: retrieved lightcurve is missing TABLE name metadata."
        )

    title = f"{str(base_name).strip()} in {filter_label} filter"
    meta["name"] = title
    meta["lightcurve_title"] = title

    logger.debug("%s metadata enriched title=%s", config.DISPLAY_NAME, title)
    return volc
