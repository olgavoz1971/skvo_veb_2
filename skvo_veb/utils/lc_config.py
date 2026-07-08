"""Mission-agnostic lightcurve configuration defaults.

Centralises physical constants and fallback values used across the application
bridge and CurveDash layers. Instrument-specific parameters (e.g. TESS) belong
in dedicated modules under ``utils/mission_config/``.
"""

# Julian Date offset for Modified Julian Date: MJD = JD - JD_TO_MJD.
JD_TO_MJD = 2400000.5

# Display epoch for relative JD axes (jd - DEFAULT_EPOCH_JD).
DEFAULT_EPOCH_JD = JD_TO_MJD

# Photometric domain identifiers stored in CurveDash metadata.
DOMAIN_FLUX = "flux"
DOMAIN_MAG = "mag"

# Keys for ``metadata['photcal']``: mirrors the IVOA VOTable ``<GROUP name="photcal">``
# for the active photometry column. Multicolour support will extend this to a
# per-column map; single-band curves store one group here.
PHOTCAL_KEY_FILTER_IDENTIFIER = "filter_identifier"
PHOTCAL_KEY_EFFECTIVE_WAVELENGTH = "effective_wavelength"
PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT = "effective_wavelength_unit"
PHOTCAL_KEY_FILTER_NAME = "filter_name"
PHOTCAL_KEY_ZP_FLUX = "zp_flux"
PHOTCAL_KEY_ZP_FLUX_UNIT = "zp_flux_unit"
PHOTCAL_KEY_ZP_MAG = "zp_mag"
PHOTCAL_KEY_ZP_MAG_UNIT = "zp_mag_unit"
PHOTCAL_KEY_MAG_SYS = "mag_sys"

# Supported user-facing lightcurve download formats (VOTable binary is the default).
VOTABLE_FORMAT_BINARY = "votable_binary"
VOTABLE_FORMAT_TEXT = "votable_text"
DEFAULT_EXPORT_FORMAT = VOTABLE_FORMAT_BINARY
EXPORT_FORMAT_OPTIONS = [
    {"label": "VOTable binary (.vot)", "value": VOTABLE_FORMAT_BINARY},
    {"label": "VOTable text (.vot)", "value": VOTABLE_FORMAT_TEXT},
    {"label": "ECSV (.ecsv)", "value": "ascii.ecsv"},
    {"label": "ASCII Commented Header (.dat)", "value": "ascii.commented_header"},
    {"label": "CSV (.csv)", "value": "csv"},
]
EXPORT_FORMATS = tuple(opt["value"] for opt in EXPORT_FORMAT_OPTIONS)


def is_votable_export_format(table_format: str) -> bool:
    """Returns whether the export format identifier selects a VOTable encoding.

    Args:
        table_format (str): Export format value from the UI dropdown.

    Returns:
        bool: True for binary or text VOTable export options.
    """
    return table_format in (VOTABLE_FORMAT_BINARY, VOTABLE_FORMAT_TEXT, "votable")


def votable_binary_encoding(table_format: str) -> bool:
    """Maps a VOTable export format to the ``write_vo_lightcurve`` binary flag.

    Args:
        table_format (str): ``votable_binary``, ``votable_text``, or legacy ``votable``.

    Returns:
        bool: True for BINARY base64 encoding; False for TABLEDATA text rows.
    """
    if table_format in (VOTABLE_FORMAT_BINARY, "votable"):
        return True
    if table_format == VOTABLE_FORMAT_TEXT:
        return False
    raise ValueError(f"Not a VOTable export format: {table_format}")
