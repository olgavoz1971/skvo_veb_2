"""Provider-specific metadata enrichment for Gaia DR3 (ARI) fetched lightcurves."""

from __future__ import annotations

import logging

from skvo_veb.lc_providers.gaia_dr3_ari import config
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve
from skvo_veb.volightcurve.lightcurve import PhotCal

logger = logging.getLogger(__name__)

PRIMARY_PHOT_COLUMN = "mag"


def enrich_fetched_volightcurve(
    volc: VOLightCurve,
    *,
    filter_name: str,
) -> VOLightCurve:
    """Applies Gaia DR3 (ARI) metadata supplements on a single-band product.

    The archive omits ``zeroPointReferenceMagnitude`` in ``photcal`` GROUPs; this
    helper writes the provider-configured reference magnitude onto the ``mag``
    column calibration. TABLE PARAM ``pf`` is copied to ``period`` when present.

    Args:
        volc (VOLightCurve): Parsed product from ``fetch_volightcurve_from_access_url``.
        filter_name (str): Human-readable filter label from the catalogue row.

    Returns:
        VOLightCurve: The same instance with updated metadata.

    Raises:
        PipeException: When mandatory metadata or photcal linkage is missing.
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

    photdm = volc.photdms.get(PRIMARY_PHOT_COLUMN)
    if photdm is None or photdm.photcal is None:
        raise PipeException(
            f"{config.DISPLAY_NAME}: photcal metadata for column '{PRIMARY_PHOT_COLUMN}' "
            "is missing on the downloaded product."
        )
    if photdm.photcal.zp_flux is None:
        raise PipeException(
            f"{config.DISPLAY_NAME}: zeroPointFlux is missing from the archive photcal GROUP."
        )

    existing_photcal = photdm.photcal
    photdm.photcal = PhotCal(
        zp_flux=existing_photcal.zp_flux,
        zp_mag=config.GAIA_ARI_ZERO_POINT_REFERENCE_MAGNITUDE,
        zp_mag_unit="mag",
        mag_sys=existing_photcal.mag_sys,
    )

    pf_value = meta.get("pf")
    if pf_value is not None:
        try:
            meta["period"] = float(pf_value)
        except (TypeError, ValueError) as exc:
            raise PipeException(
                f"{config.DISPLAY_NAME}: TABLE PARAM pf is not a numeric period."
            ) from exc

    title = f"{str(base_name).strip()} in {filter_label} filter"
    meta["name"] = title
    meta["lightcurve_title"] = title

    logger.debug(
        "%s metadata enriched title=%s period=%s zp_mag=%s",
        config.DISPLAY_NAME,
        title,
        meta.get("period"),
        config.GAIA_ARI_ZERO_POINT_REFERENCE_MAGNITUDE,
    )
    return volc
