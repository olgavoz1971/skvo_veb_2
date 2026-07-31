"""Mandatory metadata enrichment for ASAS-SN ``VOLightCurve`` products."""

from __future__ import annotations

import logging

from skvo_veb.lc_providers.asassn import config
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve

logger = logging.getLogger(__name__)


def enrich_fetched_volightcurve(
    volc: VOLightCurve,
    *,
    band_code: str,
    asas_sn_id: int | str,
) -> VOLightCurve:
    """Applies ASAS-SN pipeline metadata expected by export and ``CurveDash``.

    Args:
        volc (VOLightCurve): Parsed lightcurve from ``build_volightcurve_from_band_table``.
        band_code (str): ``g`` or ``V``.
        asas_sn_id (int or str): Sky Patrol source identifier.

    Returns:
        VOLightCurve: Same instance with normalised ``table.meta``.

    Raises:
        PipeException: When band metadata cannot be resolved.
    """
    band = config.band_spec_for_code(band_code)
    meta = volc.table.meta
    if meta is None:
        volc.table.meta = {}
        meta = volc.table.meta

    title = f"ASAS-SN {int(asas_sn_id)} {band.band_code}"
    meta["name"] = title
    meta["lightcurve_title"] = title
    meta["title"] = title
    meta["authors"] = [config.ASASSN_PIPELINE]
    meta["mission"] = config.PROVIDER_ID
    meta["band"] = band.band_code
    meta["calibration_catalog"] = band.calibration_catalog
    meta["photcal"] = config.photcal_dict_for_band(band.band_code)
    meta["asas_sn_id"] = int(asas_sn_id)

    description = meta.get("description") or meta.get("table_description")
    if not description or not str(description).strip():
        raise PipeException(
            f"{config.DISPLAY_NAME}: lightcurve is missing TABLE description after build."
        )

    logger.debug(
        "%s enriched asas_sn_id=%s band=%s n_points=%s",
        config.DISPLAY_NAME,
        asas_sn_id,
        band.band_code,
        len(volc),
    )
    return volc
