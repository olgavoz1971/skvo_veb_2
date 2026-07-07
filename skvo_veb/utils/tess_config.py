"""TESS Instrument and Pipeline Configuration.

This module stores standard physical and metadata parameters for TESS observations,
including timescales, calibrations, filter definitions, and reference positions.
It provides a single source of truth for TESS-related constants across the application.
"""

import logging
from os import getenv
from astropy import units as u

logger = logging.getLogger(__name__)

# Standard TESS physical and coordinate parameters
TESS_TIMESCALE = "TCB"
TESS_REFPOSITION = "BARYCENTER"
TESS_TIMEORIGIN = 2457000.0  # Lightkurve BTJD offset (internal plotting/ingest only; not VOTable timeorigin)

# Photometric calibration parameters for SPOC and TESS-SPOC pipelines
TESS_SPOC_ZERO_POINT_REF_MAG = 20.44
# TESS_SPOC_ZERO_POINT_FLUX = 2632.0  # zeroPointFlux in Jy
TESS_SPOC_ZERO_POINT_FLUX = 1.0     # zeroPoint if electrons per second
TESS_SPOC_ZERO_POINT_FLUX_UNIT = "electron s-1"
TESS_FILTER_IDENTIFIER = "TESS/TESS.Red"
TESS_EFFECTIVE_WAVELENGTH = 7697.6027003917 * u.Angstrom

# Author tag for user-defined FFI/TPF cutout photometry (uncalibrated).
CUTOUT_PIPELINE_AUTHOR = "user"


def is_spoc_pipeline(authors) -> bool:
    """Checks if the given pipeline author list contains SPOC or TESS-SPOC.

    Args:
        authors (str or list of str): The pipeline author(s) to check.

    Returns:
        bool: True if SPOC or TESS-SPOC is in the author list, False otherwise.
    """
    if not authors:
        return False
    if isinstance(authors, str):
        authors = [authors]
    return any(isinstance(a, str) and a.upper() in ["SPOC", "TESS-SPOC"] for a in authors)


def tess_filter_group_meta() -> dict:
    """Returns serialisable TESS passband fields for ``metadata['photcal']``.

    Returns:
        dict: Filter identifier, effective wavelength, and display name.
    """
    return {
        "filter_identifier": TESS_FILTER_IDENTIFIER,
        "effective_wavelength": float(TESS_EFFECTIVE_WAVELENGTH.to(u.m).value),
        "effective_wavelength_unit": "m",
        "filter_name": "TESS",
    }


def resolve_tess_photcal(authors, stitched: bool = False) -> dict:
    """Builds serialisable photcal GROUP metadata for TESS archive lightcurves.

    Filter passband fields are always stored. SPOC pipeline zero points apply
    only to unstitched curves; stitched and non-SPOC pipelines omit zero points
    but retain filter identification for export and future multicolour work.

    Args:
        authors (str or list of str): Pipeline author tag(s) from Lightkurve.
        stitched (bool): True when sectors were stitched with relative normalisation.

    Returns:
        dict: Full photcal GROUP fields appropriate for serialised storage.
    """
    meta = tess_filter_group_meta()
    if stitched or not is_spoc_pipeline(authors):
        return meta
    meta.update({
        "zp_flux": TESS_SPOC_ZERO_POINT_FLUX,
        "zp_flux_unit": TESS_SPOC_ZERO_POINT_FLUX_UNIT,
        "zp_mag": TESS_SPOC_ZERO_POINT_REF_MAG,
        "zp_mag_unit": "mag",
        "mag_sys": "Vega",
    })
    return meta
