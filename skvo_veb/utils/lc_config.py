"""Mission-agnostic lightcurve configuration defaults.

Centralises physical constants and fallback values used across the application
bridge and CurveDash layers. Instrument-specific parameters (e.g. TESS) belong
in dedicated modules under ``utils/mission_config/``.
"""

from __future__ import annotations

import math

# Julian Date offset for Modified Julian Date: MJD = JD - JD_TO_MJD.
JD_TO_MJD = 2400000.5

# Values below this threshold are treated as TIMESYS-relative offsets on ingest.
TIME_OFFSET_ABSOLUTE_JD_THRESHOLD = JD_TO_MJD

# Display epoch for relative JD axes (jd - DEFAULT_EPOCH_JD).
DEFAULT_EPOCH_JD = JD_TO_MJD


def resolve_catalog_epoch(epoch) -> float | None:
    """Normalises a catalogue folding epoch for ``CurveDash`` ingestion.

    Sky Patrol and legacy caches use ``0`` as a missing-epoch sentinel. Those
    values are treated as absent so ``CurveDash`` falls back to
    ``DEFAULT_EPOCH_JD``.

    Args:
        epoch: Raw epoch from a catalogue, cache, or upload metadata.

    Returns:
        float or None: Valid Julian Date epoch, or ``None`` when missing/invalid.
    """
    if epoch is None:
        return None
    try:
        value = float(epoch)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value == 0:
        return None
    return value


def display_epoch_offset(
    epoch_jd,
    display_epoch: float = DEFAULT_EPOCH_JD,
) -> float:
    """Converts an absolute epoch Julian Date to the UI input offset.

    The fold controls label ``Epoch-{display_epoch}`` expects values relative to
    ``display_epoch`` (typically MJD). Missing or sentinel epochs display as
    ``0.0``, matching the default ``DEFAULT_EPOCH_JD`` reference.

    Args:
        epoch_jd: Absolute Julian Date stored on the lightcurve, if any.
        display_epoch (float): Reference subtracted for the input field.

    Returns:
        float: Epoch relative to ``display_epoch``.
    """
    resolved = resolve_catalog_epoch(epoch_jd)
    if resolved is None:
        return 0.0
    return float(resolved) - float(display_epoch)

# Time-axis display modes for lightcurve plots (time view only).
TIME_AXIS_MJD = "mjd"
TIME_AXIS_DATE = "date"
TIME_AXIS_MODES = (TIME_AXIS_MJD, TIME_AXIS_DATE)
DEFAULT_TIME_AXIS_MODE = TIME_AXIS_MJD


def normalize_time_axis_mode(time_axis_mode: str | None) -> str:
    """Normalises a UI time-axis mode to a supported constant.

    Args:
        time_axis_mode (str): ``mjd`` or ``date`` from a page control.

    Returns:
        str: ``TIME_AXIS_MJD`` or ``TIME_AXIS_DATE``.
    """
    if time_axis_mode == TIME_AXIS_DATE:
        return TIME_AXIS_DATE
    return TIME_AXIS_MJD

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

# Serialised TIMESYS / VOTable envelope restored at ingest for mission-blind export.
METADATA_KEY_VO_ENVELOPE = "vo_envelope"

# Keys inside ``metadata['vo_envelope']`` (mission-blind round-trip).
VO_ENVELOPE_KEY_LIGHTCURVE_TITLE = "lightcurve_title"
VO_ENVELOPE_KEY_TABLE_DESCRIPTION = "table_description"
VO_ENVELOPE_KEY_VOTABLE_DESCRIPTION = "votable_description"
VO_ENVELOPE_KEY_PUBLICATION_ID = "publication_id"
VO_ENVELOPE_KEY_TABLE_NAME = "table_name"

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
