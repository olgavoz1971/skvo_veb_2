"""Provider-specific metadata enrichment for Gaia DR3 (ARI) fetched lightcurves."""

from __future__ import annotations

import logging

from astropy import units as u

from skvo_veb.lc_providers.gaia_dr3_ari import config
from skvo_veb.lc_providers.shared.gaia_dr3_source_id import format_gaia_source_name
from skvo_veb.lc_providers.shared.gaia_epoch_mag_error import mag_error_from_flux_over_error
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve
from skvo_veb.volightcurve.lightcurve import PhotCal

logger = logging.getLogger(__name__)

PRIMARY_PHOT_COLUMN = "mag"
FLUX_OVER_ERROR_COLUMN = "flux_over_error"
MAG_ERR_COLUMN = "mag_err"
ARCHIVE_FLUX_ERROR_COLUMNS = ("flux_error", "flux_err")


def _attach_mag_errors_from_snr(volc: VOLightCurve) -> None:
    """Builds ``mag_err`` from ``flux_over_error`` and drops archive flux-error columns.

    Gaia ARI VOTables expose electron-per-second ``flux_error`` alongside magnitude
    photometry. Discovery uses mag-native uncertainties derived from SNR only.

    Args:
        volc (VOLightCurve): Parsed ARI product to mutate in place.

    Raises:
        PipeException: When ``flux_over_error`` is missing from the ingested table.
    """
    if FLUX_OVER_ERROR_COLUMN not in volc.table.colnames:
        raise PipeException(
            f"{config.DISPLAY_NAME}: retrieved lightcurve is missing column "
            f"'{FLUX_OVER_ERROR_COLUMN}' required for magnitude uncertainties."
        )

    snr = volc.table[FLUX_OVER_ERROR_COLUMN]
    if hasattr(snr, "value"):
        snr = snr.value
    mag_err_vals = mag_error_from_flux_over_error(snr)
    volc.table[MAG_ERR_COLUMN] = mag_err_vals * u.mag

    for column in ARCHIVE_FLUX_ERROR_COLUMNS:
        if column in volc.table.colnames:
            volc.table.remove_column(column)

    logger.debug(
        "%s attached %s from %s and removed archive flux-error columns",
        config.DISPLAY_NAME,
        MAG_ERR_COLUMN,
        FLUX_OVER_ERROR_COLUMN,
    )


def _discovery_lightcurve_title(meta: dict, *, filter_label: str) -> str:
    """Builds a canonical Discovery title from Gaia ``source_id`` and passband.

    Heidelberg ARI VOTables use verbose TABLE names such as
    ``Gaia DR3 … - G band time series``; titles for plot and export are derived
    from the ``source_id`` TABLE PARAM instead.

    Args:
        meta (dict): Parsed VOTable TABLE metadata.
        filter_label (str): Human-readable passband label from the catalogue row.

    Returns:
        str: Title such as ``Gaia DR3 4090664085620846720 in Gaia G filter``.

    Raises:
        PipeException: When ``source_id`` is missing from the archive product.
    """
    source_id = meta.get("source_id")
    if source_id is None or str(source_id).strip() == "":
        raise PipeException(
            f"{config.DISPLAY_NAME}: retrieved lightcurve is missing TABLE PARAM source_id."
        )
    object_label = format_gaia_source_name(source_id)
    return f"{object_label} in {filter_label} filter"


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

    _attach_mag_errors_from_snr(volc)

    pf_value = meta.get("pf")
    if pf_value is not None:
        try:
            meta["period"] = float(pf_value)
        except (TypeError, ValueError) as exc:
            raise PipeException(
                f"{config.DISPLAY_NAME}: TABLE PARAM pf is not a numeric period."
            ) from exc

    title = _discovery_lightcurve_title(meta, filter_label=filter_label)
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
