"""ASAS-SN Sky Patrol instrument and photometric calibration configuration.

Per-filter passband metadata and PhotCal zero-point pairs for the ASAS-SN ``V``
(legacy APASS-calibrated) and ``g`` (REFCAT2-calibrated) bands. Flux values from
Sky Patrol are stored in millijanskys (mJy); see Kochanek et al. (2017) and
Shappee et al. (2023) for pipeline details.
"""

from __future__ import annotations

import logging
import math

from astropy import units as u

from skvo_veb.utils.lc_config import (
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
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

# Timing and reference-frame metadata for VOTable export.
ASASSN_TIMESCALE = "UTC"
ASASSN_REFPOSITION = "HELIOCENTER"
ASASSN_PIPELINE = "ASAS-SN Sky Patrol"

# Native flux column unit returned by Sky Patrol (LC Server v1.0).
ASASSN_FLUX_UNIT = "mJy"

# AB reference flux density (Jy) for Sloan g zero-point pairing.
AB_REFERENCE_FLUX_JY = 3631.0
# Approximate Vega V reference flux density (Jy) for legacy V-band pairing.
VEGA_V_REFERENCE_FLUX_JY = 3540.0

ASASSN_BANDS = frozenset({"V", "g"})

# Sloan g (current operations; REFCAT2 calibration).
ASASSN_G_FILTER_IDENTIFIER = "SLOAN/SDSS.g"
ASASSN_G_EFFECTIVE_WAVELENGTH = 480.3e-9  # metres (480.3 nm central wavelength)
ASASSN_G_FILTER_NAME = "ASAS-SN g"
ASASSN_G_MAG_SYS = "AB"
ASASSN_G_CALIBRATION_CATALOG = "ATLAS REFCAT2"

# Legacy Johnson V (APASS calibration).
ASASSN_V_FILTER_IDENTIFIER = "Johnson/V"
ASASSN_V_EFFECTIVE_WAVELENGTH = 551.0e-9  # metres
ASASSN_V_FILTER_NAME = "ASAS-SN V"
ASASSN_V_MAG_SYS = "Vega"
ASASSN_V_CALIBRATION_CATALOG = "APASS"

ASASSN_G_ZP_FLUX = 1.0
ASASSN_G_ZP_FLUX_UNIT = ASASSN_FLUX_UNIT
ASASSN_G_ZP_MAG = -2.5 * math.log10(1e-3 / AB_REFERENCE_FLUX_JY)

ASASSN_V_ZP_FLUX = 1.0
ASASSN_V_ZP_FLUX_UNIT = ASASSN_FLUX_UNIT
ASASSN_V_ZP_MAG = -2.5 * math.log10(1e-3 / VEGA_V_REFERENCE_FLUX_JY)


def normalise_asassn_band(band: str) -> str:
    """Validates and normalises an ASAS-SN filter code.

    Args:
        band (str): Photometric filter identifier (``'V'`` or ``'g'``).

    Returns:
        str: Normalised band code.

    Raises:
        PipeException: If ``band`` is not supported.
    """
    if band not in ASASSN_BANDS:
        raise PipeException(f"Unsupported ASAS-SN band '{band}'. Expected one of {sorted(ASASSN_BANDS)}.")
    return band


def asassn_calibration_catalog(band: str) -> str:
    """Returns the external catalogue used to calibrate a given ASAS-SN band.

    Args:
        band (str): Photometric filter identifier (``'V'`` or ``'g'``).

    Returns:
        str: Calibration catalogue name.
    """
    band = normalise_asassn_band(band)
    if band == "g":
        return ASASSN_G_CALIBRATION_CATALOG
    return ASASSN_V_CALIBRATION_CATALOG


def resolve_asassn_photcal(band: str) -> dict:
    """Builds serialisable ``metadata['photcal']`` for an ASAS-SN lightcurve band.

    Each band carries its own filter identifier, effective wavelength, magnitude
    system, and zero-point pair appropriate for flux stored in mJy.

    Args:
        band (str): Photometric filter identifier (``'V'`` or ``'g'``).

    Returns:
        dict: PhotCal GROUP fields for CurveDash serialisation and export.
    """
    band = normalise_asassn_band(band)
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


def asassn_effective_wavelength_display(band: str) -> str:
    """Returns a human-readable effective wavelength string for export descriptions.

    Args:
        band (str): Photometric filter identifier (``'V'`` or ``'g'``).

    Returns:
        str: Wavelength label with unit.
    """
    band = normalise_asassn_band(band)
    wavelength_m = ASASSN_G_EFFECTIVE_WAVELENGTH if band == "g" else ASASSN_V_EFFECTIVE_WAVELENGTH
    angstrom = (wavelength_m * u.m).to_value(u.Angstrom)
    return f"{angstrom:.1f} Angstrom"
