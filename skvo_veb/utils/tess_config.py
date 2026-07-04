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
TESS_SPOC_ZERO_POINT_FLUX = 2632.0  # zeroPointFlux in Jy

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
