"""ASAS-SN Sky Patrol instrument configuration and VOTable export profile.

Per-filter passband metadata and PhotCal zero-point pairs for the ASAS-SN ``V``
(legacy APASS-calibrated) and ``g`` (REFCAT2-calibrated) bands. Flux values from
Sky Patrol are stored in millijanskys (mJy); see Kochanek et al. (2017),
2017PASP..129j4502K for V-band calibration and Jayasinghe et al. (2018),
2018MNRAS.477.3145J for g-band.
"""

from __future__ import annotations

import logging
import math

from astropy import units as u

from skvo_veb.utils.lc_config import (
    JD_TO_MJD,
    PHOTCAL_KEY_EFFECTIVE_WAVELENGTH,
    PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT,
    PHOTCAL_KEY_FILTER_IDENTIFIER,
    PHOTCAL_KEY_FILTER_NAME,
    PHOTCAL_KEY_MAG_SYS,
    PHOTCAL_KEY_ZP_FLUX,
    PHOTCAL_KEY_ZP_FLUX_UNIT,
    PHOTCAL_KEY_ZP_MAG,
    PHOTCAL_KEY_ZP_MAG_UNIT,
)
from skvo_veb.utils.my_tools import PipeException, sanitize_filename
from skvo_veb.volightcurve.time_reference import export_absolute_jd_as_time_offset

logger = logging.getLogger(__name__)

MISSION_ID = "asassn"

ASASSN_TIMESCALE = "UTC"
ASASSN_REFPOSITION = "HELIOCENTER"
ASASSN_PIPELINE = "ASAS-SN Sky Patrol"
ASASSN_FLUX_UNIT = "mJy"

AB_REFERENCE_FLUX_JY = 3631.0

ASASSN_BANDS = frozenset({"V", "g"})

ASASSN_G_FILTER_IDENTIFIER = "SLOAN/SDSS.g"
ASASSN_G_EFFECTIVE_WAVELENGTH = 467.2e-9
ASASSN_G_FILTER_NAME = "ASAS-SN g"
ASASSN_G_MAG_SYS = "AB"
ASASSN_G_CALIBRATION_CATALOG = "ATLAS REFCAT2"

ASASSN_V_FILTER_IDENTIFIER = "Generic/Johnson.V"
ASASSN_V_EFFECTIVE_WAVELENGTH = 546.8e-9
ASASSN_V_FILTER_NAME = "ASAS-SN V"
ASASSN_V_MAG_SYS = "Vega"
ASASSN_V_CALIBRATION_CATALOG = "APASS"

ASASSN_G_ZP_FLUX = AB_REFERENCE_FLUX_JY
ASASSN_G_ZP_FLUX_UNIT = "Jy"
ASASSN_G_ZP_MAG = 0.0

ASASSN_V_ZP_FLUX = 3836.3   # The ASAS-SN specific zeropoint flux, revealed by comparing provided mag and fluxes
ASASSN_V_ZP_FLUX_UNIT = "Jy"
ASASSN_V_ZP_MAG = 0.0


def normalise_band(band: str) -> str:
    """Validates and normalises an ASAS-SN filter code.

    Args:
        band (str): Photometric filter identifier (``'V'`` or ``'g'``).

    Returns:
        str: Normalised band code.

    Raises:
        PipeException: If ``band`` is not supported.
    """
    if band not in ASASSN_BANDS:
        raise PipeException(
            f"Unsupported ASAS-SN band '{band}'. Expected one of {sorted(ASASSN_BANDS)}."
        )
    return band


normalise_asassn_band = normalise_band


def calibration_catalog(band: str) -> str:
    """Returns the external catalogue used to calibrate a given ASAS-SN band.

    Args:
        band (str): Photometric filter identifier (``'V'`` or ``'g'``).

    Returns:
        str: Calibration catalogue name.
    """
    band = normalise_band(band)
    if band == "g":
        return ASASSN_G_CALIBRATION_CATALOG
    return ASASSN_V_CALIBRATION_CATALOG


asassn_calibration_catalog = calibration_catalog


def resolve_photcal(band: str) -> dict:
    """Builds serialisable ``metadata['photcal']`` for an ASAS-SN lightcurve band.

    Args:
        band (str): Photometric filter identifier (``'V'`` or ``'g'``).

    Returns:
        dict: PhotCal GROUP fields for CurveDash serialisation and export.
    """
    band = normalise_band(band)
    if band == "g":
        return {
            PHOTCAL_KEY_FILTER_IDENTIFIER: ASASSN_G_FILTER_IDENTIFIER,
            PHOTCAL_KEY_EFFECTIVE_WAVELENGTH: float(ASASSN_G_EFFECTIVE_WAVELENGTH),
            PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT: "m",
            PHOTCAL_KEY_FILTER_NAME: ASASSN_G_FILTER_NAME,
            PHOTCAL_KEY_ZP_FLUX: ASASSN_G_ZP_FLUX,
            PHOTCAL_KEY_ZP_FLUX_UNIT: ASASSN_G_ZP_FLUX_UNIT,
            PHOTCAL_KEY_ZP_MAG: ASASSN_G_ZP_MAG,
            PHOTCAL_KEY_ZP_MAG_UNIT: "mag",
            PHOTCAL_KEY_MAG_SYS: ASASSN_G_MAG_SYS,
        }
    return {
        PHOTCAL_KEY_FILTER_IDENTIFIER: ASASSN_V_FILTER_IDENTIFIER,
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH: float(ASASSN_V_EFFECTIVE_WAVELENGTH),
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT: "m",
        PHOTCAL_KEY_FILTER_NAME: ASASSN_V_FILTER_NAME,
        PHOTCAL_KEY_ZP_FLUX: ASASSN_V_ZP_FLUX,
        PHOTCAL_KEY_ZP_FLUX_UNIT: ASASSN_V_ZP_FLUX_UNIT,
        PHOTCAL_KEY_ZP_MAG: ASASSN_V_ZP_MAG,
        PHOTCAL_KEY_ZP_MAG_UNIT: "mag",
        PHOTCAL_KEY_MAG_SYS: ASASSN_V_MAG_SYS,
    }


resolve_asassn_photcal = resolve_photcal


def effective_wavelength_display(band: str) -> str:
    """Returns a human-readable effective wavelength string for export descriptions.

    Args:
        band (str): Photometric filter identifier (``'V'`` or ``'g'``).

    Returns:
        str: Wavelength label with unit.
    """
    band = normalise_band(band)
    wavelength_m = ASASSN_G_EFFECTIVE_WAVELENGTH if band == "g" else ASASSN_V_EFFECTIVE_WAVELENGTH
    angstrom = (wavelength_m * u.m).to_value(u.Angstrom)
    return f"{angstrom:.1f} Angstrom"


asassn_effective_wavelength_display = effective_wavelength_display


def resolve_target_identifier(lcd) -> str:
    """Returns the best human-facing target label for export and filenames.

    Prefers the user lookup name used for ASAS-SN search/cache, then ``name``,
    then Gaia ID when present. Ignores stale ``\"None\"`` strings from legacy serialisation.

    Args:
        lcd (CurveDash): ASAS-SN lightcurve container.

    Returns:
        str: Sanitisable target identifier.
    """
    meta = lcd.metadata or {}
    for candidate in (
        lcd.lookup_name,
        meta.get("lookup_name"),
        lcd.name,
        meta.get("name"),
        lcd.gaia_id,
        meta.get("gaia_id"),
    ):
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text and text.lower() != "none":
            return text
    return "unknown"


def build_votable_kwargs(lcd) -> dict:
    """Builds keyword arguments for ASAS-SN VOTable export (profile ``asassn``).

    Args:
        lcd (CurveDash): ASAS-SN lightcurve with band and photcal metadata.

    Returns:
        dict: Keyword arguments for ``write_vo_lightcurve``.
    """
    from skvo_veb.utils.lc_bridge import _photcal_group_to_votable_fields

    meta = lcd.metadata or {}
    band = lcd.band or meta.get("band") or "unknown"
    target_id = resolve_target_identifier(lcd)

    if band in ASASSN_BANDS:
        calibration = meta.get("calibration_catalog") or calibration_catalog(band)
        photcal = meta.get("photcal") or resolve_photcal(band)
        wavelength_label = effective_wavelength_display(band)
    else:
        calibration = meta.get("calibration_catalog") or "unknown"
        photcal = meta.get("photcal") or {}
        wavelength_label = "unknown"
    photcal_fields = _photcal_group_to_votable_fields(photcal, include_zero_points=True)

    desc_core = (
        f"ASAS-SN Sky Patrol lightcurve for target {target_id}. "
        f"Filter band: {band}. Effective wavelength: {wavelength_label}. "
        f"Calibrated against {calibration}. "
        f"Observation times are Heliocentric Julian Date; "
        f"``obs_time`` is Modified Julian Date (MJD = JD - {JD_TO_MJD}). "
    )

    return {
        "table_name": f"ASASSN_{sanitize_filename(str(target_id))}_{band}",
        "refposition": ASASSN_REFPOSITION,
        "timescale": ASASSN_TIMESCALE,
        "timeorigin": JD_TO_MJD,
        "votable_description": desc_core,
        "table_description": desc_core,
        "creator": ASASSN_PIPELINE,
        "ra": meta.get("ra"),
        "dec": meta.get("dec"),
        "period": meta.get("period"),
        "epoch": export_absolute_jd_as_time_offset(
            meta.get("epoch"),
            timeorigin=JD_TO_MJD,
        ),
        "binary": True,
        **photcal_fields,
    }
