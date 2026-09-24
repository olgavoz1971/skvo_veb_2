"""Provider-specific metadata enrichment for personal time-series lightcurves."""

from __future__ import annotations

import logging

from skvo_veb.lc_providers.personal_ts import config
from skvo_veb.lc_providers.shared.filter_zp_mag import assign_magnitude_zero_point
from skvo_veb.lc_providers.shared.photcal_error_link import (
    share_photcal_with_unlinked_errors,
)
from skvo_veb.utils.my_tools import PipeException
from volightcurve import VOLightCurve

logger = logging.getLogger(__name__)


def enrich_fetched_volightcurve(
    volc: VOLightCurve,
    *,
    filter_name: str,
    object_id: str | None = None,
) -> VOLightCurve:
    """Normalises title and description on a personal ``accref`` lightcurve product.

    Args:
        volc (VOLightCurve): Parsed product from ``fetch_volightcurve_from_accref``.
        filter_name (str): Passband label from the catalogue row (``ssa_bandpass``).
        object_id (str, optional): Personal archive object identifier for titling.

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
    assign_magnitude_zero_point(
        volc,
        display_name=config.DISPLAY_NAME,
        zp_mag_by_filter_identifier=config.ZP_MAG_BY_FILTER_IDENTIFIER,
        zp_mag_unit=config.ZP_MAG_UNIT,
    )

    logger.debug("%s metadata enriched title=%s", config.DISPLAY_NAME, title)
    share_photcal_with_unlinked_errors(volc)
    return volc
