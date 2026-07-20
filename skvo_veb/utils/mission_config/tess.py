"""TESS instrument configuration, ingest photcal, and VOTable export profiles.

Handles archive pipeline lightcurves (profile ``tess``) and user FFI/TPF cutouts
(profile ``cutout``).
"""

from __future__ import annotations

import logging

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
from skvo_veb.volightcurve.time_reference import export_absolute_jd_as_time_offset
from skvo_veb.utils.my_tools import PipeException, sanitize_filename

logger = logging.getLogger(__name__)

MISSION_ID = "tess"
CUTOUT_MISSION_ID = "cutout"

TESS_TIMESCALE = "TCB"
TESS_REFPOSITION = "BARYCENTER"
TESS_TIMEORIGIN = 2457000.0  # Lightkurve BTJD offset (ingest/plot only; not VOTable timeorigin)

TESS_SPOC_ZERO_POINT_REF_MAG = 20.44
TESS_SPOC_ZERO_POINT_FLUX = 1.0
TESS_SPOC_ZERO_POINT_FLUX_UNIT = "electron s-1"
TESS_FILTER_IDENTIFIER = "TESS/TESS.Red"
TESS_EFFECTIVE_WAVELENGTH = 7453 * u.Angstrom

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


def filter_group_meta() -> dict:
    """Returns serialisable TESS passband fields for ``metadata['photcal']``.

    Returns:
        dict: Filter identifier, effective wavelength, and display name.
    """
    return {
        PHOTCAL_KEY_FILTER_IDENTIFIER: TESS_FILTER_IDENTIFIER,
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH: float(TESS_EFFECTIVE_WAVELENGTH.to(u.m).value),
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT: "m",
        PHOTCAL_KEY_FILTER_NAME: "TESS",
    }


def resolve_photcal(authors, stitched: bool = False) -> dict:
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
    meta = filter_group_meta()
    if stitched or not is_spoc_pipeline(authors):
        return meta
    meta.update({
        PHOTCAL_KEY_ZP_FLUX: TESS_SPOC_ZERO_POINT_FLUX,
        PHOTCAL_KEY_ZP_FLUX_UNIT: TESS_SPOC_ZERO_POINT_FLUX_UNIT,
        PHOTCAL_KEY_ZP_MAG: TESS_SPOC_ZERO_POINT_REF_MAG,
        PHOTCAL_KEY_ZP_MAG_UNIT: "mag",
        PHOTCAL_KEY_MAG_SYS: "Vega",
    })
    return meta


# Backward-compatible aliases for existing import paths during migration.
tess_filter_group_meta = filter_group_meta
resolve_tess_photcal = resolve_photcal


def resolve_cutout_mask_mode(auto_mask, mask_type: str | None) -> str:
    """Maps UI mask controls to a descriptive mask mode label.

    Args:
        auto_mask: Truthy when automatic mask generation is enabled.
        mask_type (str, optional): ``'pipeline'`` or ``'threshold'`` when auto mask is on.

    Returns:
        str: One of ``'handmade'``, ``'threshold'``, or ``'pipeline'``.
    """
    if not auto_mask:
        return "handmade"
    if mask_type == "pipeline":
        return "pipeline"
    return "threshold"


def build_cutout_title(lcd) -> str:
    """Builds a display title for user cutout lightcurves.

    Args:
        lcd (CurveDash): Cutout lightcurve with cutout metadata populated.

    Returns:
        str: Title string for Plotly figures and export metadata.
    """
    from skvo_veb.utils.curve_dash import CurveDash
    from skvo_veb.utils.lc_bridge import _parse_list_meta

    if not isinstance(lcd, CurveDash):
        return "TESS cutout lightcurve"

    meta = lcd.metadata or {}
    stored = meta.get("title") or lcd.title
    if stored:
        return stored

    parts = []
    source = meta.get("cutout_source") or meta.get("pixel_type")
    if source:
        parts.append(str(source).upper())

    lookup = meta.get("lookup_name") or ""
    name = meta.get("name") or ""
    if lookup:
        parts.append(str(lookup))
    if name and str(name) != str(lookup):
        parts.append(str(name))

    sectors = _parse_list_meta(meta.get("sectors"))
    if sectors:
        parts.append(f"sector:{','.join(sectors)}")

    mask_mode = meta.get("mask_mode")
    if mask_mode:
        parts.append(f"mask:{mask_mode}")

    parts.append("user cutout")
    return " ".join(parts) if parts else "TESS cutout lightcurve"


def enrich_cutout_curvedash(lcd, pixel_metadata: dict, sector, mask_mode: str, ra=None, dec=None):
    """Attaches cutout-specific metadata to a CurveDash instance.

    User cutout photometry is uncalibrated; ``photcal`` retains passband only and
    the pipeline author is tagged as ``user`` for VOTable export.

    Args:
        lcd (CurveDash): Newly constructed cutout lightcurve.
        pixel_metadata (dict): Sector download metadata (``pixel_type``, ``lookup_name``, etc.).
        sector (int or str): TESS sector number.
        mask_mode (str): ``handmade``, ``threshold``, or ``pipeline``.
        ra (float, optional): Target right ascension in degrees.
        dec (float, optional): Target declination in degrees.

    Returns:
        CurveDash: The same instance with metadata and title populated.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    if not isinstance(lcd, CurveDash):
        raise PipeException("enrich_cutout_curvedash expects a CurveDash instance.")

    lcd.metadata["mission"] = CUTOUT_MISSION_ID
    lcd.metadata["photcal"] = filter_group_meta()
    lcd.metadata["authors"] = [CUTOUT_PIPELINE_AUTHOR]
    lcd.metadata["sectors"] = [str(sector)]
    lcd.metadata["cutout_source"] = str(pixel_metadata.get("pixel_type", "TPF")).upper()
    lcd.metadata["mask_mode"] = mask_mode
    if ra is not None:
        lcd.metadata["ra"] = ra
    if dec is not None:
        lcd.metadata["dec"] = dec

    title = build_cutout_title(lcd)
    lcd.title = title
    lcd.metadata["title"] = title
    return lcd


def apply_upload_cutout_metadata(lcd) -> None:
    """Ensures uploaded cutout VOTables retain passband metadata without zero points.

    Args:
        lcd (CurveDash): Lightcurve restored from an uploaded cutout VOTable.
    """
    from skvo_veb.utils.lc_bridge import _strip_zero_points_from_photcal

    lcd.metadata["mission"] = CUTOUT_MISSION_ID
    lcd.metadata["photcal"] = _strip_zero_points_from_photcal(lcd.metadata.get("photcal"))
    if not lcd.metadata["photcal"]:
        lcd.metadata["photcal"] = filter_group_meta()


def build_archive_votable_kwargs(lcd) -> dict:
    """Builds keyword arguments for TESS archive VOTable export (profile ``tess``).

    Args:
        lcd (CurveDash): Application lightcurve with TESS metadata.

    Returns:
        dict: Keyword arguments for ``write_vo_lightcurve``.
    """
    from skvo_veb.utils.lc_bridge import (
        _is_stitched_lightcurve,
        _parse_list_meta,
        _photcal_group_to_votable_fields,
    )

    authors = lcd.metadata.get("authors", [])
    if not authors and lcd.metadata.get("author"):
        authors = [lcd.metadata.get("author")]
    pipeline_str = ", ".join(_parse_list_meta(authors) or []) if authors else "Unknown"
    is_stitched = _is_stitched_lightcurve(lcd)
    photcal = lcd.metadata.get("photcal") or {}
    include_zero_points = (
        photcal.get(PHOTCAL_KEY_ZP_FLUX) is not None
        and photcal.get(PHOTCAL_KEY_ZP_MAG) is not None
        and not is_stitched
    )
    photcal_fields = _photcal_group_to_votable_fields(
        photcal, include_zero_points=include_zero_points
    )
    tic_id = lcd.name or lcd.lookup_name or "Unknown Target"

    sectors = _parse_list_meta(lcd.metadata.get("sectors")) or []
    flux_origins = _parse_list_meta(lcd.metadata.get("flux_origins")) or []
    methods_str = ", ".join(dict.fromkeys(flux_origins)) if flux_origins else "unknown"
    sectors_str = ", ".join(sectors) if sectors else "unknown"

    calibration_note = (
        " Photometric zero points are omitted because sector stitching invalidates "
        "pipeline flux calibration."
        if is_stitched
        else ""
    )

    return {
        "table_name": f"TESS_{sanitize_filename(tic_id)}",
        "refposition": TESS_REFPOSITION,
        "timescale": TESS_TIMESCALE,
        "timeorigin": JD_TO_MJD,
        "votable_description": (
            f"TESS space telescope lightcurve for target {tic_id}, "
            f"processed via the {pipeline_str} pipeline. "
            f"Photometry method(s): {methods_str}."
            f"{calibration_note}"
        ),
        "table_description": (
            f"Photometric time-series observations of {tic_id} from the TESS mission. "
            f"Data produced by the {pipeline_str} pipeline. "
            f"Sectors: {sectors_str}. Photometry method(s): {methods_str}."
            f"{calibration_note}"
        ),
        "creator": f"TESS {pipeline_str} Pipeline",
        "ra": lcd.metadata.get("ra"),
        "dec": lcd.metadata.get("dec"),
        "period": lcd.metadata.get("period"),
        "epoch": export_absolute_jd_as_time_offset(
            lcd.metadata.get("epoch"),
            timeorigin=JD_TO_MJD,
        ),
        "binary": True,
        **photcal_fields,
    }


def build_cutout_votable_kwargs(lcd) -> dict:
    """Builds keyword arguments for uncalibrated TESS cutout VOTable export (profile ``cutout``).

    Args:
        lcd (CurveDash): Cutout lightcurve with ``cutout_source`` and ``mask_mode`` metadata.

    Returns:
        dict: Keyword arguments for ``write_vo_lightcurve``.
    """
    from skvo_veb.utils.lc_bridge import _parse_list_meta, _photcal_group_to_votable_fields

    meta = lcd.metadata or {}
    tic_id = lcd.name or lcd.lookup_name or "Unknown Target"
    source = str(meta.get("cutout_source") or meta.get("pixel_type") or "unknown").upper()
    mask_mode = meta.get("mask_mode", "unknown")
    sectors = _parse_list_meta(meta.get("sectors")) or []
    sectors_str = ", ".join(sectors) if sectors else "unknown"
    flux_correction = meta.get("flux_correction") or ""
    processing_note = f" Processing applied: {flux_correction}." if flux_correction else ""

    calibration_note = (
        " Photometry is uncalibrated aperture summation; "
        "photometric zero points are omitted from the PhotCal group."
    )
    desc_core = (
        f"Uncalibrated TESS cutout lightcurve for target {tic_id}. "
        f"Data source: {source}. Aperture mask mode: {mask_mode}. "
        f"Sector: {sectors_str}. Pipeline: {CUTOUT_PIPELINE_AUTHOR}."
        f"{processing_note}"
    )

    photcal = meta.get("photcal") or {}
    photcal_fields = _photcal_group_to_votable_fields(photcal, include_zero_points=False)

    return {
        "table_name": f"TESS_cutout_{sanitize_filename(tic_id)}",
        "refposition": TESS_REFPOSITION,
        "timescale": TESS_TIMESCALE,
        "timeorigin": JD_TO_MJD,
        "votable_description": desc_core + calibration_note,
        "table_description": desc_core + calibration_note,
        "creator": f"TESS {CUTOUT_PIPELINE_AUTHOR} cutout",
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
