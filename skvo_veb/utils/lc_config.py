"""Mission-agnostic lightcurve configuration defaults.

Centralises physical constants and fallback values used across the application
bridge and CurveDash layers. Instrument-specific parameters (e.g. TESS) belong
in dedicated modules such as ``tess_config.py``.
"""

# Julian Date offset for Modified Julian Date: MJD = JD - JD_TO_MJD.
JD_TO_MJD = 2400000.5

# Display epoch for relative JD axes (jd - DEFAULT_EPOCH_JD).
DEFAULT_EPOCH_JD = JD_TO_MJD

# Fallback magnitude zero point when no PhotCal metadata is available.
FALLBACK_MAG_ZERO_POINT = 25.0

# First-order error propagation factors (used only when PhotCal is unavailable).
MAG_TO_FLUX_ERR_FACTOR = 0.921034
FLUX_TO_MAG_ERR_FACTOR = 1.085736

# Photometric domain identifiers stored in CurveDash metadata.
DOMAIN_FLUX = "flux"
DOMAIN_MAG = "mag"
