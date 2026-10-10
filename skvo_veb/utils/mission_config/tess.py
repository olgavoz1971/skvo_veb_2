"""TESS instrument configuration, ingest photcal, and VOTable export profiles.

Handles archive pipeline lightcurves (profile ``tess``) and user FFI/TPF cutouts
(profile ``cutout``). Photometric policy and pipeline-column behaviour are
documented in ``docs/tess.md``.
"""

from __future__ import annotations

import logging

from astropy import units as u

from skvo_veb.utils.lc_config import (
    METADATA_KEY_FILE_COMMENTS,
    METADATA_KEY_VO_ENVELOPE,
    PHOTCAL_KEY_EFFECTIVE_WAVELENGTH,
    PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT,
    PHOTCAL_KEY_FILTER_IDENTIFIER,
    PHOTCAL_KEY_FILTER_NAME,
    PHOTCAL_KEY_MAG_SYS,
    PHOTCAL_KEY_ZP_FLUX,
    PHOTCAL_KEY_ZP_FLUX_UNIT,
    PHOTCAL_KEY_ZP_MAG,
    PHOTCAL_KEY_ZP_MAG_UNIT,
    VO_ENVELOPE_KEY_TABLE_DESCRIPTION,
    VO_ENVELOPE_KEY_TABLE_NAME,
    VO_ENVELOPE_KEY_VOTABLE_DESCRIPTION,
)
from skvo_veb.utils.lc_bridge import apply_phot_domain_view
from volightcurve.vo_unit_codec import to_internal
from skvo_veb.utils.my_tools import PipeException, sanitize_filename

logger = logging.getLogger(__name__)

MISSION_ID = "tess"
CUTOUT_MISSION_ID = "cutout"

TESS_TIMESCALE = "TDB"
TESS_REFPOSITION = "BARYCENTER"
TESS_TIMEORIGIN = 2457000.0  # Lightkurve BTJD offset (ingest/plot only; not VOTable timeorigin)

# Instrument conversion for flux in electron s-1 (photoelectrons per second):
#   mag = -2.5 log10(F / 1 electron s-1) + 20.44
# TESS Instrument Handbook; public restatement:
# https://tess.mit.edu/public/tesstransients/pages/readme.html
# Zero-point uncertainty 0.05 mag. Vega system (TESS defined to match Cousins I).
# Use only when stored flux is electron s-1 (SPOC, TESS-SPOC, user TPF/FFI
# aperture sums). Do not apply to dimensionless QLP/TARS flux, ppm,
# or background columns.
#
# Normalised (dimensionless) pipeline lightcurves: QLP and TARS. PhotCal uses
# header TESSMAG from Lightkurve metadata when it is present and finite:
#   mag = TESSMAG - 2.5 log10(flux), with ZP_FLUX = 1 (dimensionless).
# If TESSMAG is missing, photcal is passband-only and magnitude conversion is
# refused. TASOC TESSMAG is catalogue metadata only; FLUX_CORR is ppm stored
# as dimensionless without this zero point.
TESS_ELECTRON_S_ZERO_POINT_REF_MAG = 20.44
TESS_ELECTRON_S_ZERO_POINT_REF_MAG_UNCERTAINTY = 0.05
TESS_ELECTRON_S_ZERO_POINT_FLUX = 1.0
TESS_ELECTRON_S_ZERO_POINT_FLUX_UNIT = "electron s-1"
TESS_ELECTRON_S_ZERO_POINT_SOURCE_URL = (
    "https://tess.mit.edu/public/tesstransients/pages/readme.html"
)

# Historical names; same values as the instrument electron s-1 zero point.
TESS_SPOC_ZERO_POINT_REF_MAG = TESS_ELECTRON_S_ZERO_POINT_REF_MAG
TESS_SPOC_ZERO_POINT_FLUX = TESS_ELECTRON_S_ZERO_POINT_FLUX
TESS_SPOC_ZERO_POINT_FLUX_UNIT = TESS_ELECTRON_S_ZERO_POINT_FLUX_UNIT
QLP_FLUX_UNIT = u.dimensionless_unscaled
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


def is_tars_pipeline(authors) -> bool:
    """Checks if the pipeline author list includes TARS.

    Args:
        authors (str or list of str): The pipeline author(s) to check.

    Returns:
        bool: True when TARS is present, False otherwise.
    """
    if not authors:
        return False
    if isinstance(authors, str):
        authors = [authors]
    return any(isinstance(a, str) and a.upper() == "TARS" for a in authors)


def is_qlp_pipeline(authors) -> bool:
    """Checks if the pipeline author list includes QLP.

    Args:
        authors (str or list of str): The pipeline author(s) to check.

    Returns:
        bool: True when QLP is present, False otherwise.
    """
    if not authors:
        return False
    if isinstance(authors, str):
        authors = [authors]
    return any(isinstance(a, str) and a.upper() == "QLP" for a in authors)


def uses_tessmag_catalog_photcal(authors) -> bool:
    """True when archive photcal uses header ``TESSMAG`` as in QLP.

    Args:
        authors (str or list of str): Pipeline author(s) to check.

    Returns:
        bool: True for QLP or TARS.
    """
    return is_qlp_pipeline(authors) or is_tars_pipeline(authors)


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


def instrument_electron_s_photcal() -> dict:
    """Returns TESS passband metadata plus the electron s-1 instrument zero point.

    Shared by SPOC / TESS-SPOC archive curves and user FFI/TPF
    cutout aperture photometry. Not a pipeline-product keyword: the same
    handbook conversion applies whenever flux is in electron s-1.

    Returns:
        dict: Serialisable photcal GROUP including zero points.
    """
    meta = filter_group_meta()
    meta.update({
        PHOTCAL_KEY_ZP_FLUX: TESS_ELECTRON_S_ZERO_POINT_FLUX,
        PHOTCAL_KEY_ZP_FLUX_UNIT: TESS_ELECTRON_S_ZERO_POINT_FLUX_UNIT,
        PHOTCAL_KEY_ZP_MAG: TESS_ELECTRON_S_ZERO_POINT_REF_MAG,
        PHOTCAL_KEY_ZP_MAG_UNIT: "mag",
        PHOTCAL_KEY_MAG_SYS: "Vega",
    })
    return meta


def resolve_photcal(
    authors,
    tess_mag: float | None = None,
) -> dict:
    """Builds serialisable photcal GROUP metadata for TESS archive lightcurves.

    Filter passband fields are always stored. SPOC and TESS-SPOC
    curves use the shared instrument electron s-1 zero point. QLP and TARS
    curves use ``tess_mag`` from Lightkurve ``TESSMAG`` header
    metadata when supplied. Pipelines without
    calibration metadata omit zero points but retain filter identification
    for export and future multicolour work.

    Args:
        authors (str or list of str): Pipeline author tag(s) from Lightkurve.
        tess_mag (float, optional): ``TESSMAG`` from downloaded QLP or TARS
            product header.

    Returns:
        dict: Full photcal GROUP fields appropriate for serialised storage.
    """
    meta = filter_group_meta()
    if is_spoc_pipeline(authors):
        return instrument_electron_s_photcal()
    if uses_tessmag_catalog_photcal(authors):
        pipeline_name = "TARS" if is_tars_pipeline(authors) else "QLP"
        if tess_mag is None:
            logger.warning(
                "%s TESS lightcurve missing TESSMAG metadata; photcal passband only.",
                pipeline_name,
            )
            return meta
        try:
            zp_mag = float(tess_mag)
        except (TypeError, ValueError):
            logger.warning(
                "%s photcal skipped: invalid TESSMAG value %r.",
                pipeline_name,
                tess_mag,
            )
            return meta
        meta.update({
            PHOTCAL_KEY_ZP_FLUX: 1.0,
            PHOTCAL_KEY_ZP_FLUX_UNIT: to_internal(QLP_FLUX_UNIT),
            PHOTCAL_KEY_ZP_MAG: zp_mag,
            PHOTCAL_KEY_ZP_MAG_UNIT: "mag",
            PHOTCAL_KEY_MAG_SYS: "Vega",
        })
        return meta
    return meta


# Backward-compatible aliases for existing import paths during migration.
tess_filter_group_meta = filter_group_meta
resolve_tess_photcal = resolve_photcal


def serialise_lightkurve_flux_unit(lightkurve_flux_unit) -> str | None:
    """Serialises a Lightkurve flux unit, treating ppm as dimensionless.

    Physical units (for example electron / s) are kept. ``ppm`` is a
    dimensionless relative scale, so it is stored as ``None``.

    Args:
        lightkurve_flux_unit: Unit object or string from the downloaded product.

    Returns:
        str or None: Serialised unit label, or ``None`` when dimensionless or ppm.
    """
    label = to_internal(lightkurve_flux_unit)
    if label is None:
        return None
    compact = str(label).strip().lower().replace("_", " ")
    if compact in {"ppm", "1e-6"} or "parts per million" in compact:
        return None
    return label


def archive_flux_unit_for_pipeline(authors, lightkurve_flux_unit) -> str | None:
    """Returns the flux-unit label stored on a TESS archive ``CurveDash``.

    The unit comes from the selected column of the file; it is not guessed
    from the pipeline name. ppm is stored as dimensionless.

    Args:
        authors (str or list of str): Pipeline author tag(s); kept for call
            compatibility and not used for the unit.
        lightkurve_flux_unit: Unit object or string from the downloaded product.

    Returns:
        str or None: Serialised flux unit for ``CurveDash`` metadata
        (``None`` = dimensionless or unknown).
    """
    return serialise_lightkurve_flux_unit(lightkurve_flux_unit)


def validate_tess_magnitude_conversion(lcd) -> None:
    """Checks that a TESS archive lightcurve may be converted to magnitudes.

    Products without zero-point metadata must not be converted;
    unit mismatches are left to ``PhotCal`` and surface as conversion errors.

    Args:
        lcd (CurveDash): Cached lightcurve from the TESS archive page.

    Raises:
        PipeException: When magnitude conversion is not scientifically defined.
    """
    if lcd.metadata is None:
        raise PipeException("Cannot convert to magnitude: lightcurve metadata is missing.")

    if lcd.metadata.get("is_background_flux"):
        raise PipeException(
            "Cannot convert to magnitude: background columns are not target photometry."
        )

    photcal = lcd.metadata.get("photcal") or {}
    if photcal.get(PHOTCAL_KEY_ZP_MAG) is None or photcal.get(PHOTCAL_KEY_ZP_FLUX) is None:
        raise PipeException(
            "Cannot convert to magnitude: photometric zero point is not defined for this "
            "lightcurve."
        )


def apply_tess_phot_domain_view(lcd, show_magnitude: bool) -> None:
    """Converts a TESS archive lightcurve between flux and magnitude views.

    Uses the shared bridge conversion path after TESS-specific preconditions
    are met. Does not invent photcal; incomplete or incoherent zero points
    raise rather than filling defaults.

    Args:
        lcd (CurveDash): Cached lightcurve to mutate.
        show_magnitude (bool): When true, convert to magnitude domain.
    """
    if show_magnitude:
        validate_tess_magnitude_conversion(lcd)

    apply_phot_domain_view(lcd, show_magnitude)


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

    User FFI/TPF aperture sums in electron s-1 share the SPOC instrument zero
    point. The pipeline author is tagged as ``user`` for VOTable export.

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
    lcd.metadata["photcal"] = instrument_electron_s_photcal()
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
    attach_cutout_export_provenance(lcd)
    return lcd


def attach_cutout_export_provenance(lcd) -> None:
    """Stores cutout provenance for all export formats (comments + VO envelope).

    Call at enrich time so ``export_curvedash`` / ``write_lightcurve`` never need
    a VOTable-only profile to recover source, mask, or calibration notes.

    Args:
        lcd (CurveDash): Cutout lightcurve with cutout metadata already set.
    """
    meta = lcd.metadata if isinstance(getattr(lcd, "metadata", None), dict) else {}
    lcd.metadata = meta
    tic_id = lcd.name or lcd.lookup_name or "Unknown Target"
    source = str(meta.get("cutout_source") or meta.get("pixel_type") or "unknown").upper()
    mask_mode = meta.get("mask_mode", "unknown")
    from skvo_veb.utils.lc_bridge import _parse_list_meta

    sectors = _parse_list_meta(meta.get("sectors")) or []
    sectors_str = ", ".join(sectors) if sectors else "unknown"
    flux_correction = meta.get("flux_correction") or ""
    processing_note = f" Processing applied: {flux_correction}." if flux_correction else ""
    zp = TESS_ELECTRON_S_ZERO_POINT_REF_MAG
    zp_err = TESS_ELECTRON_S_ZERO_POINT_REF_MAG_UNCERTAINTY
    calibration_note = (
        f" Magnitudes use the TESS instrument zero point of {zp} mag at "
        f"1 {TESS_ELECTRON_S_ZERO_POINT_FLUX_UNIT} "
        f"(TESS Instrument Handbook; {TESS_ELECTRON_S_ZERO_POINT_SOURCE_URL}). "
        f"The zero-point uncertainty is {zp_err} mag. This is a user-mask "
        "aperture sum, not SPOC pipeline photometry; crowding and background "
        "residuals remain."
    )
    desc = (
        f"TESS cutout lightcurve for target {tic_id}. "
        f"Data source: {source}. Aperture mask mode: {mask_mode}. "
        f"Sector: {sectors_str}. Pipeline: {CUTOUT_PIPELINE_AUTHOR}."
        f"{processing_note}{calibration_note}"
    )
    meta[METADATA_KEY_FILE_COMMENTS] = [desc]
    meta[METADATA_KEY_VO_ENVELOPE] = {
        VO_ENVELOPE_KEY_TABLE_NAME: f"TESS_cutout_{sanitize_filename(tic_id)}",
        VO_ENVELOPE_KEY_TABLE_DESCRIPTION: desc,
        VO_ENVELOPE_KEY_VOTABLE_DESCRIPTION: desc,
        "creator": f"TESS {CUTOUT_PIPELINE_AUTHOR} cutout",
        "refposition": TESS_REFPOSITION,
        "timescale": TESS_TIMESCALE,
    }


def attach_tess_archive_export_provenance(lcd) -> None:
    """Stores TESS archive provenance for all export formats.

    Args:
        lcd (CurveDash): Archive lightcurve with authors/sectors/photcal set.
    """
    meta = lcd.metadata if isinstance(getattr(lcd, "metadata", None), dict) else {}
    lcd.metadata = meta
    from skvo_veb.utils.lc_bridge import _parse_list_meta

    authors = meta.get("authors", [])
    if not authors and meta.get("author"):
        authors = [meta.get("author")]
    pipeline_str = ", ".join(_parse_list_meta(authors) or []) if authors else "Unknown"
    tic_id = lcd.name or lcd.lookup_name or "Unknown Target"
    sectors = _parse_list_meta(meta.get("sectors")) or []
    flux_origins = _parse_list_meta(meta.get("flux_origins")) or []
    methods_str = ", ".join(dict.fromkeys(flux_origins)) if flux_origins else "unknown"
    sectors_str = ", ".join(sectors) if sectors else "unknown"
    votable_description = (
        f"TESS space telescope lightcurve for target {tic_id}, "
        f"processed via the {pipeline_str} pipeline. "
        f"Photometry method(s): {methods_str}."
    )
    table_description = (
        f"Photometric time-series observations of {tic_id} from the TESS mission. "
        f"Data produced by the {pipeline_str} pipeline. "
        f"Sectors: {sectors_str}. Photometry method(s): {methods_str}."
    )
    meta[METADATA_KEY_FILE_COMMENTS] = [table_description]
    meta[METADATA_KEY_VO_ENVELOPE] = {
        VO_ENVELOPE_KEY_TABLE_NAME: f"TESS_{sanitize_filename(tic_id)}",
        VO_ENVELOPE_KEY_TABLE_DESCRIPTION: table_description,
        VO_ENVELOPE_KEY_VOTABLE_DESCRIPTION: votable_description,
        "creator": f"TESS {pipeline_str} Pipeline",
        "refposition": TESS_REFPOSITION,
        "timescale": TESS_TIMESCALE,
    }


def apply_upload_cutout_metadata(lcd) -> None:
    """Ensures uploaded cutout VOTables keep mission tags and electron s-1 photcal.

    Existing zero points are preserved. Files that lack a ZP pair receive the
    shared instrument electron s-1 zero point (same as a fresh cutout).

    Args:
        lcd (CurveDash): Lightcurve restored from an uploaded cutout VOTable.
    """
    lcd.metadata["mission"] = CUTOUT_MISSION_ID
    existing = dict(lcd.metadata.get("photcal") or {})
    instrument = instrument_electron_s_photcal()
    has_zp = (
        existing.get(PHOTCAL_KEY_ZP_MAG) is not None
        and existing.get(PHOTCAL_KEY_ZP_FLUX) is not None
    )
    if has_zp:
        lcd.metadata["photcal"] = {**instrument, **existing}
    else:
        lcd.metadata["photcal"] = {**existing, **instrument}


def build_archive_votable_kwargs(lcd) -> dict:
    """Legacy VOTable kwargs helper; prefers metadata already attached at build.

    Args:
        lcd (CurveDash): Application lightcurve with TESS metadata.

    Returns:
        dict: Keyword arguments for ``write_vo_lightcurve``.
    """
    attach_tess_archive_export_provenance(lcd)
    from skvo_veb.utils.lc_bridge import build_votable_kwargs_from_metadata

    return build_votable_kwargs_from_metadata(lcd)


def build_cutout_votable_kwargs(lcd) -> dict:
    """Legacy VOTable kwargs helper; prefers metadata already attached at enrich.

    Args:
        lcd (CurveDash): Cutout lightcurve with ``cutout_source`` and ``mask_mode`` metadata.

    Returns:
        dict: Keyword arguments for ``write_vo_lightcurve``.
    """
    attach_cutout_export_provenance(lcd)
    from skvo_veb.utils.lc_bridge import build_votable_kwargs_from_metadata

    return build_votable_kwargs_from_metadata(lcd)
