"""Explicit TESS / HLSP flux and background column registry for archive ingest.

Column names are stored in registry canonical form (FITS uppercase) and
normalised to lowercase when matching Lightkurve ``LightCurve.columns``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

FLUX_METHOD_DEFAULT = "default"
FLUX_METHOD_BACKGROUND = "background"

CALIBRATION_PHYSICAL = "physical"
CALIBRATION_NORMALIZED_CATALOG = "normalized_catalog"

UNIT_PHYSICAL_ELECTRON_S = "electron s-1"
UNIT_DIMENSIONLESS = ""


@dataclass(frozen=True)
class FluxColumnSpec:
    """Photometry flux / flux-error pair for one pipeline sector range."""

    flux_col: str
    flux_err_col: Optional[str]
    calibration: str
    zp_mag_source: Optional[str]
    sector_min: Optional[int] = None
    sector_max: Optional[int] = None
    notes: str = ""


@dataclass(frozen=True)
class BackgroundColumnSpec:
    """Per-cadence background column delivered with a pipeline product."""

    bkg_col: str
    bkg_err_col: Optional[str]
    unit_type: str
    notes: str = ""


class UnknownPipelineError(RuntimeError):
    """Raised when the author/pipeline is not in the registry."""


class UnknownSectorRangeError(RuntimeError):
    """Raised when no registry entry covers the requested sector."""


FLUX_COLUMN_REGISTRY: dict[str, list[FluxColumnSpec]] = {
    "SPOC": [
        FluxColumnSpec(
            flux_col="PDCSAP_FLUX",
            flux_err_col="PDCSAP_FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Systematics-corrected aperture photometry, e-/s (Lightkurve default).",
        ),
        FluxColumnSpec(
            flux_col="SAP_FLUX",
            flux_err_col="SAP_FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Uncorrected aperture photometry, e-/s.",
        ),
    ],
    "TESS-SPOC": [
        FluxColumnSpec(
            flux_col="PDCSAP_FLUX",
            flux_err_col="PDCSAP_FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Same convention as SPOC PDCSAP_FLUX; e-/s.",
        ),
        FluxColumnSpec(
            flux_col="SAP_FLUX",
            flux_err_col="SAP_FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Same convention as SPOC SAP_FLUX; e-/s.",
        ),
    ],
    "QLP": [
        FluxColumnSpec(
            flux_col="SAP_FLUX",
            flux_err_col="SAP_FLUX_ERR",
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source="TESSMAG",
            sector_min=1,
            sector_max=55,
            notes="Un-detrended flux, dimensionless, catalog-anchored.",
        ),
        FluxColumnSpec(
            flux_col="KSPSAP_FLUX",
            flux_err_col="KSPSAP_FLUX_ERR",
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source="TESSMAG",
            sector_min=1,
            sector_max=55,
            notes="Detrended flux (Lightkurve default for QLP S1–55).",
        ),
        FluxColumnSpec(
            flux_col="SAP_FLUX",
            flux_err_col="SAP_FLUX_ERR",
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source="TESSMAG",
            sector_min=56,
            sector_max=None,
            notes="Un-detrended flux, dimensionless (S56+).",
        ),
        FluxColumnSpec(
            flux_col="DET_FLUX",
            flux_err_col="DET_FLUX_ERR",
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source="TESSMAG",
            sector_min=56,
            sector_max=None,
            notes="Detrended flux (Lightkurve default for QLP S56+).",
        ),
        FluxColumnSpec(
            flux_col="SYS_RM_FLUX",
            flux_err_col=None,
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source="TESSMAG",
            sector_min=56,
            sector_max=None,
            notes="Systematics removed; no dedicated error column.",
        ),
    ],
    "TASOC": [
        FluxColumnSpec(
            flux_col="FLUX_CORR",
            flux_err_col="FLUX_CORR_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Systematics-corrected flux, e-/s heritage.",
        ),
        FluxColumnSpec(
            flux_col="FLUX_RAW",
            flux_err_col="FLUX_RAW_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Raw aperture photometry, pre-correction.",
        ),
    ],
    "TGLC": [
        FluxColumnSpec(
            flux_col="cal_psf_flux",
            flux_err_col="cal_psf_flux_err",
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source="GAIAMAG",
            notes="PSF-fit flux calibrated against Gaia photometry.",
        ),
    ],
    "Kepler": [
        FluxColumnSpec(
            flux_col="PDCSAP_FLUX",
            flux_err_col="PDCSAP_FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Physical e-/s; Kepler convention.",
        ),
        FluxColumnSpec(
            flux_col="SAP_FLUX",
            flux_err_col="SAP_FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Physical e-/s, uncorrected.",
        ),
    ],
    "GSFC-ELEANOR-LITE": [
        FluxColumnSpec(
            flux_col="CORR_FLUX",
            flux_err_col=None,
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Systematics-corrected aperture photometry, e-/s (Lightkurve default).",
        ),
        FluxColumnSpec(
            flux_col="RAW_FLUX",
            flux_err_col="FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Uncorrected aperture photometry; FLUX_ERR applies to RAW_FLUX.",
        ),
        FluxColumnSpec(
            flux_col="PCA_FLUX",
            flux_err_col=None,
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="PCA-detrended flux; no dedicated error column in the FITS product.",
        ),
    ],
}

BACKGROUND_COLUMN_REGISTRY: dict[str, BackgroundColumnSpec] = {
    "SPOC": BackgroundColumnSpec(
        bkg_col="SAP_BKG",
        bkg_err_col="SAP_BKG_ERR",
        unit_type=CALIBRATION_PHYSICAL,
        notes="Sky/aperture background, e-/s.",
    ),
    "TESS-SPOC": BackgroundColumnSpec(
        bkg_col="SAP_BKG",
        bkg_err_col="SAP_BKG_ERR",
        unit_type=CALIBRATION_PHYSICAL,
        notes="Sky/aperture background, e-/s.",
    ),
    "Kepler": BackgroundColumnSpec(
        bkg_col="SAP_BKG",
        bkg_err_col="SAP_BKG_ERR",
        unit_type=CALIBRATION_PHYSICAL,
        notes="Sky/aperture background, e-/s.",
    ),
    "QLP": BackgroundColumnSpec(
        bkg_col="SAP_BKG",
        bkg_err_col="SAP_BKG_ERR",
        unit_type=CALIBRATION_NORMALIZED_CATALOG,
        notes="Difference-imaging background; dimensionless, may be negative.",
    ),
    "TASOC": BackgroundColumnSpec(
        bkg_col="FLUX_BKG",
        bkg_err_col="FLUX_BKG_ERR",
        unit_type=CALIBRATION_PHYSICAL,
        notes="Background level, e-/s.",
    ),
    "GSFC-ELEANOR-LITE": BackgroundColumnSpec(
        bkg_col="FLUX_BKG",
        bkg_err_col=None,
        unit_type=CALIBRATION_PHYSICAL,
        notes="Per-cadence background fraction; e-/s heritage via Lightkurve reader.",
    ),
}


def normalize_lc_column(name: str) -> str:
    """Normalises a column name to lowercase Lightkurve convention.

    Args:
        name (str): Registry or FITS column name.

    Returns:
        str: Lowercase column name for ``LightCurve`` access.
    """
    return str(name).strip().lower()


def _sector_ok(spec: FluxColumnSpec, sector: Optional[int]) -> bool:
    if sector is None:
        return True
    if spec.sector_min is not None and sector < spec.sector_min:
        return False
    if spec.sector_max is not None and sector > spec.sector_max:
        return False
    return True


def _lower_colset(colnames: Sequence[str]) -> set[str]:
    return {normalize_lc_column(c) for c in colnames}


def _column_present(colnames: Sequence[str], column: Optional[str]) -> bool:
    if column is None:
        return True
    return normalize_lc_column(column) in _lower_colset(colnames)


def get_background_spec(author: str) -> Optional[BackgroundColumnSpec]:
    """Returns the background column spec for a pipeline, if any.

    Args:
        author (str): Pipeline author tag from Lightkurve.

    Returns:
        BackgroundColumnSpec or None: Background metadata, or ``None`` for TGLC etc.
    """
    return BACKGROUND_COLUMN_REGISTRY.get(author)


def list_photometry_specs(author: str, sector: Optional[int] = None) -> list[FluxColumnSpec]:
    """Lists registry photometry specs for an author and optional sector.

    Args:
        author (str): Pipeline author tag.
        sector (int, optional): TESS sector number.

    Returns:
        list[FluxColumnSpec]: Matching registry entries in declaration order.

    Raises:
        UnknownPipelineError: When ``author`` is absent from the registry.
    """
    if author not in FLUX_COLUMN_REGISTRY:
        raise UnknownPipelineError(
            f"Pipeline/author '{author}' is not in FLUX_COLUMN_REGISTRY. "
            f"Known pipelines: {sorted(FLUX_COLUMN_REGISTRY)}."
        )
    return [spec for spec in FLUX_COLUMN_REGISTRY[author] if _sector_ok(spec, sector)]


def resolve_default_flux_origin(lc) -> str:
    """Returns the Lightkurve author-default flux column name for a product.

    Args:
        lc: Lightkurve ``LightCurve`` instance.

    Returns:
        str: Lowercase default flux column name.
    """
    origin = getattr(lc, "FLUX_ORIGIN", None)
    if origin:
        return normalize_lc_column(origin)
    flux_col = getattr(getattr(lc, "flux", None), "name", None)
    if flux_col:
        return normalize_lc_column(flux_col)
    raise ValueError("LightCurve has no FLUX_ORIGIN or flux.name for default labelling.")


def list_available_photometry_specs(
    author: str,
    sector: Optional[int],
    colnames: Sequence[str],
) -> list[FluxColumnSpec]:
    """Lists photometry specs whose flux column is present in a downloaded file.

    Args:
        author (str): Pipeline author tag.
        sector (int, optional): TESS sector number.
        colnames (sequence of str): Columns on the Lightkurve product.

    Returns:
        list[FluxColumnSpec]: Registry entries present in ``colnames``.
    """
    try:
        registry_specs = list_photometry_specs(author, sector)
    except UnknownPipelineError:
        return []

    available: list[FluxColumnSpec] = []
    seen: set[str] = set()
    for spec in registry_specs:
        key = normalize_lc_column(spec.flux_col)
        if key in seen:
            continue
        if not _column_present(colnames, spec.flux_col):
            continue
        if spec.flux_err_col is not None and not _column_present(colnames, spec.flux_err_col):
            continue
        available.append(spec)
        seen.add(key)
    return available


def get_photometry_spec(
    author: str,
    sector: Optional[int],
    preferred: str,
    colnames: Optional[Sequence[str]] = None,
) -> FluxColumnSpec:
    """Resolves one photometry spec by preferred flux column name.

    Args:
        author (str): Pipeline author tag.
        sector (int, optional): TESS sector number.
        preferred (str): Registry flux column name (any case).
        colnames (sequence of str, optional): When given, verify columns exist.

    Returns:
        FluxColumnSpec: Matching registry entry.

    Raises:
        UnknownPipelineError: Unknown author.
        ValueError: Preferred column or colnames mismatch.
    """
    matches = list_photometry_specs(author, sector)
    preferred_key = normalize_lc_column(preferred)
    filtered = [s for s in matches if normalize_lc_column(s.flux_col) == preferred_key]
    if not filtered:
        raise ValueError(
            f"Flux column '{preferred}' is not registered for author='{author}', sector={sector}."
        )
    spec = filtered[0]
    if colnames is not None:
        if not _column_present(colnames, spec.flux_col):
            raise ValueError(
                f"Flux column '{spec.flux_col}' is not present in the downloaded file."
            )
        if spec.flux_err_col is not None and not _column_present(colnames, spec.flux_err_col):
            raise ValueError(
                f"Flux error column '{spec.flux_err_col}' is not present in the downloaded file."
            )
    return spec


def background_available(author: str, colnames: Sequence[str]) -> bool:
    """Checks whether the pipeline background columns exist in a file.

    Args:
        author (str): Pipeline author tag.
        colnames (sequence of str): Columns on the Lightkurve product.

    Returns:
        bool: True when background flux column is present.
    """
    spec = get_background_spec(author)
    if spec is None:
        return False
    if not _column_present(colnames, spec.bkg_col):
        return False
    if spec.bkg_err_col is not None and not _column_present(colnames, spec.bkg_err_col):
        return False
    return True


def storage_flux_unit_for_selection(author: str, flux_method: str) -> str:
    """Returns the serialised flux-unit label for a flux-column selection.

    Args:
        author (str): Pipeline author tag.
        flux_method (str): ``default``, ``background``, or a photometry column name.

    Returns:
        str: Unit string for ``CurveDash`` metadata.
    """
    if flux_method == FLUX_METHOD_BACKGROUND:
        bkg = get_background_spec(author)
        if bkg is None:
            raise ValueError(f"Pipeline '{author}' does not provide a background column.")
        if bkg.unit_type == CALIBRATION_NORMALIZED_CATALOG:
            return UNIT_DIMENSIONLESS
        return UNIT_PHYSICAL_ELECTRON_S

    if flux_method == FLUX_METHOD_DEFAULT:
        if author in {"QLP", "TGLC"}:
            return UNIT_DIMENSIONLESS
        return UNIT_PHYSICAL_ELECTRON_S

    spec = get_photometry_spec(author, sector=None, preferred=flux_method)
    if spec.calibration == CALIBRATION_NORMALIZED_CATALOG:
        return UNIT_DIMENSIONLESS
    return UNIT_PHYSICAL_ELECTRON_S


def parse_sector_from_mission_label(mission_label: str) -> Optional[int]:
    """Extracts a TESS sector number from an AgGrid mission label.

    Args:
        mission_label (str): Row ``mission`` field, e.g. ``Sector 97``.

    Returns:
        int or None: Parsed sector number.
    """
    if not mission_label:
        return None
    match = re.search(r"Sector\s+(\d+)", str(mission_label), re.IGNORECASE)
    return int(match.group(1)) if match else None


def default_flux_option_label(default_origin: Optional[str] = None) -> str:
    """Builds the RadioItems label for the author-default flux choice.

    Args:
        default_origin (str, optional): Lightkurve default flux column name.

    Returns:
        str: Short label such as ``pdcsap_flux(default)``.

    Raises:
        ValueError: When ``default_origin`` is missing.
    """
    if not default_origin:
        raise ValueError(
            "Cannot label author-default flux without the Lightkurve column name."
        )
    return f"{normalize_lc_column(default_origin)}(default)"


def build_flux_radio_options(
    author: str,
    sector: Optional[int],
    colnames: Optional[Sequence[str]] = None,
    *,
    default_origin: Optional[str] = None,
) -> list[dict[str, str]]:
    """Builds RadioItems options for the TESS archive flux selector.

    Always includes the author-default option plus every registry photometry
    column present in the file, even when that column is the Lightkurve default.

    Args:
        author (str): Pipeline author for the selected row(s).
        sector (int, optional): TESS sector number.
        colnames (sequence of str, optional): Downloaded columns when known.
        default_origin (str, optional): Lightkurve default flux column name for labelling.

    Returns:
        list[dict]: Dash RadioItems ``options`` entries.
    """
    options: list[dict[str, str]] = [
        {"label": default_flux_option_label(default_origin), "value": FLUX_METHOD_DEFAULT},
    ]

    if colnames is not None:
        photometry = list_available_photometry_specs(author, sector, colnames)
    else:
        try:
            photometry = list_photometry_specs(author, sector)
        except UnknownPipelineError:
            photometry = []

    seen: set[str] = set()
    for spec in photometry:
        col = normalize_lc_column(spec.flux_col)
        if col in seen:
            continue
        seen.add(col)
        options.append({"label": col, "value": col})

    if colnames is not None:
        if background_available(author, colnames):
            options.append({"label": "background", "value": FLUX_METHOD_BACKGROUND})
    elif get_background_spec(author) is not None:
        options.append({"label": "background", "value": FLUX_METHOD_BACKGROUND})

    return options


def merge_flux_radio_options(option_lists: Sequence[list[dict[str, str]]]) -> list[dict[str, str]]:
    """Merges flux radio options from several rows, preserving default first.

    Args:
        option_lists (sequence): Option lists from ``build_flux_radio_options``.

    Returns:
        list[dict]: De-duplicated Dash RadioItems options.
    """
    merged: dict[str, dict[str, str]] = {}
    ordered_values: list[str] = []
    for options in option_lists:
        for opt in options:
            value = opt["value"]
            if value not in merged:
                ordered_values.append(value)
            merged[value] = opt
    if FLUX_METHOD_DEFAULT in merged:
        ordered_values = [FLUX_METHOD_DEFAULT] + [
            v for v in ordered_values if v != FLUX_METHOD_DEFAULT
        ]
    return [merged[v] for v in ordered_values]


def apply_flux_column_selection(
    lc,
    author: str,
    sector: Optional[int],
    flux_method: str,
) -> tuple[str, bool]:
    """Assigns ``lc.flux`` / ``lc.flux_err`` from registry metadata.

    Args:
        lc: Lightkurve ``LightCurve`` instance.
        author (str): Pipeline author tag.
        sector (int, optional): TESS sector number.
        flux_method (str): ``default``, ``background``, or photometry column name.

    Returns:
        tuple[str, bool]: Origin label for metadata and whether background was selected.

    Raises:
        ValueError: When the requested column is missing or unknown.
    """
    import numpy as np

    colnames = list(getattr(lc, "columns", []))
    lower_map = {normalize_lc_column(c): c for c in colnames}

    if flux_method == FLUX_METHOD_DEFAULT:
        return resolve_default_flux_origin(lc), False

    if flux_method == FLUX_METHOD_BACKGROUND:
        bkg = get_background_spec(author)
        if bkg is None:
            raise ValueError(f"Pipeline '{author}' does not provide a background column.")
        bkg_key = normalize_lc_column(bkg.bkg_col)
        if bkg_key not in lower_map:
            raise ValueError(
                f"Background column '{bkg.bkg_col}' is not present in the downloaded file."
            )
        lc.flux = lc[lower_map[bkg_key]]
        if bkg.bkg_err_col is not None:
            err_key = normalize_lc_column(bkg.bkg_err_col)
            if err_key not in lower_map:
                raise ValueError(
                    f"Background error column '{bkg.bkg_err_col}' is not present."
                )
            lc.flux_err = lc[lower_map[err_key]]
        return normalize_lc_column(bkg.bkg_col), True

    spec = get_photometry_spec(author, sector, flux_method, colnames=colnames)
    flux_key = normalize_lc_column(spec.flux_col)
    if flux_key not in lower_map:
        raise ValueError(
            f"Flux column '{spec.flux_col}' is not present in the downloaded file."
        )
    lc.flux = lc[lower_map[flux_key]]
    if spec.flux_err_col is not None:
        err_key = normalize_lc_column(spec.flux_err_col)
        lc.flux_err = lc[lower_map[err_key]]
    elif (
        flux_key == "corr_flux"
        and "raw_flux" in lower_map
        and "raw_flux_err" in lower_map
    ):
        lc.flux_err = (
            lc[lower_map[flux_key]]
            * lc[lower_map["raw_flux_err"]]
            / lc[lower_map["raw_flux"]]
        )
    else:
        lc.flux_err = np.full(len(lc.flux), np.nan)
        logger.warning(
            "Photometry column '%s' has no error column; flux_err set to NaN.",
            spec.flux_col,
        )
    return flux_key, False
