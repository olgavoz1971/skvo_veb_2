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

# Supported user-facing lightcurve download formats (VOTable is always the default).
DEFAULT_EXPORT_FORMAT = "votable"
EXPORT_FORMAT_OPTIONS = [
    {"label": "VOTable (.vot)", "value": "votable"},
    {"label": "ECSV (.ecsv)", "value": "ascii.ecsv"},
    {"label": "ASCII Commented Header (.dat)", "value": "ascii.commented_header"},
    {"label": "CSV (.csv)", "value": "csv"},
]
EXPORT_FORMATS = tuple(opt["value"] for opt in EXPORT_FORMAT_OPTIONS)
