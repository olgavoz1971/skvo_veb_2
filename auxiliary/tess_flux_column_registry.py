# -*- coding: utf-8 -*-
"""
tess_flux_column_registry.py
=============================

Explicit registry of flux / flux-error column names for TESS (and Kepler/K2,
kept for reference) light-curve products, keyed by pipeline ("author" in
Lightkurve / MAST search results) and, where the naming convention changed
mid-mission, by sector range.

WHY EXPLICIT RATHER THAN HEURISTIC
-----------------------------------
Column names such as SAP_FLUX carry *different physical meaning* depending on
which pipeline produced the file (see notes per-entry below: e.g. SPOC's
SAP_FLUX is a physical flux in e-/s, QLP's SAP_FLUX is a dimensionless flux
normalized to the target's catalog TESS magnitude). A name-matching heuristic
cannot recover that distinction -- it can find "a column with 'flux' in its
name", but not "whether this is a physical or catalog-anchored quantity, and
what its zero point is". Since that distinction changes how you legitimately
do unit-checked division against a PogsonZeroPoint (dimensionless vs. e-/s),
guessing silently is the wrong failure mode here: better to raise clearly on
an unrecognised author/sector than to hand back a column whose calibration
type is actually unknown.

This module is deliberately data (a registry), not clever code. Extend the
dict as new pipelines / HLSP versions appear; do not try to generalise the
matching logic further than this.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class FluxColumnSpec:
    """
    Describes the flux/flux-error columns for one pipeline (and, if
    applicable, one sector range within that pipeline's history).
    """
    flux_col: str
    flux_err_col: Optional[str]     # None if the pipeline genuinely provides no error column
    calibration: str                # "physical" (e-/s, an absolute detector flux)
                                     # or "normalized_catalog" (dimensionless, anchored to
                                     # a catalog magnitude stored elsewhere in the file)
    zp_mag_source: Optional[str]    # header/meta keyword holding the anchor magnitude,
                                     # only meaningful when calibration == "normalized_catalog"
    sector_min: Optional[int] = None
    sector_max: Optional[int] = None   # inclusive; None means "open-ended / no upper bound"
    notes: str = ""


# ---------------------------------------------------------------------------
# THE REGISTRY
# ---------------------------------------------------------------------------
# Keys are the pipeline identifier as it appears in Lightkurve's
# `search_lightcurve(...).table["author"]` column / MAST HLSP naming.
# Values are a list of FluxColumnSpec, since some pipelines (QLP) changed
# column names partway through the mission -- entries are checked in order
# and the first one whose sector range contains the requested sector wins.
# ---------------------------------------------------------------------------

FLUX_COLUMN_REGISTRY: dict[str, list[FluxColumnSpec]] = {

    # -- SPOC: 2-min / 20-s postage-stamp (TPF-derived) light curves --------
    # SAP_FLUX and PDCSAP_FLUX are both genuine physical fluxes in e-/s,
    # summed over the optimal aperture. PDCSAP has instrumental systematics
    # removed (CBV/PDC correction); SAP does not. Same convention inherited
    # directly from Kepler/K2.
    "SPOC": [
        FluxColumnSpec(
            flux_col="PDCSAP_FLUX", flux_err_col="PDCSAP_FLUX_ERR",
            calibration="physical", zp_mag_source=None,
            notes="Systematics-corrected aperture photometry, e-/s. "
                  "This is what Lightkurve loads by default for SPOC products."
        ),
        FluxColumnSpec(
            flux_col="SAP_FLUX", flux_err_col="SAP_FLUX_ERR",
            calibration="physical", zp_mag_source=None,
            notes="Un-corrected aperture photometry, e-/s. "
                  "Needs a CROWDSAP contamination correction if you want a "
                  "de-blended value -- check header keyword CROWDSAP / FLFRCSAP."
        ),
    ],

    # -- TESS-SPOC: SPOC pipeline heritage, applied to FFI pixels ------------
    # Same column names and same physical (e-/s) convention as SPOC, just
    # built from FFI cutouts instead of TPF postage stamps, hence sampled at
    # the sector's native FFI cadence rather than 2 min.
    "TESS-SPOC": [
        FluxColumnSpec(
            flux_col="PDCSAP_FLUX", flux_err_col="PDCSAP_FLUX_ERR",
            calibration="physical", zp_mag_source=None,
            notes="Same convention as SPOC PDCSAP_FLUX; e-/s."
        ),
        FluxColumnSpec(
            flux_col="SAP_FLUX", flux_err_col="SAP_FLUX_ERR",
            calibration="physical", zp_mag_source=None,
            notes="Same convention as SPOC SAP_FLUX; e-/s; also needs CROWDSAP "
                  "correction for de-blending if used directly."
        ),
    ],

    # -- QLP: MIT Quick-Look Pipeline, FFI difference imaging ----------------
    # IMPORTANT: unlike SPOC/TESS-SPOC, QLP's SAP_FLUX is NOT in e-/s. It is
    # built as a magnitude time series (catalog Tmag + measured differential
    # variation from difference imaging) and only converted to a normalized,
    # dimensionless flux (median ~= 1, anchored to the star's catalog TESS
    # magnitude) in the final delivered product (Huang et al. 2020, Part II).
    # Column names also changed at Sector 56 -- see the two entries below.
    "QLP": [
        FluxColumnSpec(
            flux_col="SAP_FLUX", flux_err_col="SAP_FLUX_ERR",
            calibration="normalized_catalog", zp_mag_source="TESSMAG",
            sector_min=1, sector_max=55,
            notes="Un-detrended flux, dimensionless, median ~1, anchored to "
                  "the catalog TESS magnitude (see zp_mag_source). "
                  "Use with zp_flux = 1.0 * u.dimensionless_unscaled, "
                  "zp_mag = header[zp_mag_source] * u.mag."
        ),
        FluxColumnSpec(
            flux_col="KSPSAP_FLUX", flux_err_col="KSPSAP_FLUX_ERR",
            calibration="normalized_catalog", zp_mag_source="TESSMAG",
            sector_min=1, sector_max=55,
            notes="Detrended flux (spline/high-pass), same dimensionless "
                  "convention as SAP_FLUX above. This is what Lightkurve "
                  "loads by default for QLP products -- NOT the raw column. "
                  "Absolute/DC flux level has been high-pass filtered; "
                  "still usable with the catalog-anchor formula above, but "
                  "expect slow real variability to be suppressed."
        ),
        FluxColumnSpec(
            flux_col="SAP_FLUX", flux_err_col="SAP_FLUX_ERR",
            calibration="normalized_catalog", zp_mag_source="TESSMAG",
            sector_min=56, sector_max=None,
            notes="Same meaning as pre-S56 SAP_FLUX; column name unchanged "
                  "across the S56 transition."
        ),
        FluxColumnSpec(
            flux_col="DET_FLUX", flux_err_col="DET_FLUX_ERR",
            calibration="normalized_catalog", zp_mag_source="TESSMAG",
            sector_min=56, sector_max=None,
            notes="Renamed from KSPSAP_FLUX at Sector 56. Same meaning: "
                  "detrended, dimensionless, catalog-anchored."
        ),
        FluxColumnSpec(
            flux_col="SYS_RM_FLUX", flux_err_col=None,
            calibration="normalized_catalog", zp_mag_source="TESSMAG",
            sector_min=56, sector_max=None,
            notes="Systematics removed but genuine stellar variability left "
                  "intact; sits between SAP_FLUX and DET_FLUX in how much "
                  "processing has been applied. No dedicated error column "
                  "is provided -- if you need one, propagate from SAP_FLUX_ERR "
                  "and document that choice explicitly; do not invent one."
        ),
    ],

    # -- TASOC: Aarhus/TASC photometry pipeline (asteroseismology-oriented) --
    "TASOC": [
        FluxColumnSpec(
            flux_col="FLUX_CORR", flux_err_col="FLUX_CORR_ERR",
            calibration="physical", zp_mag_source=None,
            notes="Systematics-corrected flux, e-/s heritage. Check the file's "
                  "own header for the exact unit string before assuming; "
                  "TASOC's convention has been more variable release-to-release "
                  "than SPOC/QLP."
        ),
        FluxColumnSpec(
            flux_col="FLUX_RAW", flux_err_col="FLUX_RAW_ERR",
            calibration="physical", zp_mag_source=None,
            notes="Raw aperture photometry, pre-correction."
        ),
    ],

    # -- TGLC: TESS-Gaia Light Curve, PSF-based FFI photometry ---------------
    "TGLC": [
        FluxColumnSpec(
            flux_col="cal_psf_flux", flux_err_col="cal_psf_flux_err",
            calibration="normalized_catalog", zp_mag_source="GAIAMAG",
            notes="PSF-fit flux calibrated against Gaia photometry; verify "
                  "zp_mag_source keyword name against the specific file's "
                  "header, as TGLC anchors to Gaia rather than TIC Tmag."
        ),
    ],

    # -- Kepler / K2, kept for reference (same convention as SPOC) -----------
    "Kepler": [
        FluxColumnSpec(
            flux_col="PDCSAP_FLUX", flux_err_col="PDCSAP_FLUX_ERR",
            calibration="physical", zp_mag_source=None,
            notes="Physical e-/s; identical convention to TESS SPOC, since "
                  "SPOC inherited the Kepler pipeline directly."
        ),
        FluxColumnSpec(
            flux_col="SAP_FLUX", flux_err_col="SAP_FLUX_ERR",
            calibration="physical", zp_mag_source=None,
            notes="Physical e-/s, uncorrected."
        ),
    ],
}


class UnknownPipelineError(RuntimeError):
    """Raised when the author/pipeline is not in the registry.

    Deliberately fatal rather than silently falling back to a heuristic --
    see module docstring for the reasoning: a wrong calibration-type guess
    (physical vs. normalized_catalog) breaks unit-checked Pogson conversion
    silently, which is worse than an explicit crash asking you to add a
    registry entry.
    """


class UnknownSectorRangeError(RuntimeError):
    """Raised when the pipeline is known but no entry covers the requested sector."""


def get_flux_column_spec(
    author: str,
    sector: Optional[int] = None,
    colnames: Optional[Sequence[str]] = None,
    preferred: Optional[str] = None,
) -> FluxColumnSpec:
    """
    Explicit (non-heuristic) lookup of the flux/flux-error column spec for a
    given pipeline and, where relevant, sector.

    Parameters
    ----------
    author : str
        Pipeline identifier as given by Lightkurve's search result table
        (e.g. "SPOC", "TESS-SPOC", "QLP", "TASOC", "TGLC", "Kepler").
    sector : int, optional
        TESS sector number. Required for pipelines whose column naming
        changed mid-mission (currently only QLP, at Sector 56). Ignored
        for pipelines with a single, unchanging convention.
    colnames : sequence of str, optional
        The actual column names present in the downloaded table/FITS file.
        If given, the chosen spec's flux_col/flux_err_col are verified to
        actually be present -- catches registry/data mismatches (e.g. an
        unexpected HLSP version) instead of returning a spec that silently
        doesn't match the file you have.
    preferred : str, optional
        For pipelines with multiple valid entries per sector (e.g. QLP has
        both a raw and a detrended flux at every sector), explicitly name
        which flux_col you want (e.g. "SAP_FLUX" vs "KSPSAP_FLUX"/"DET_FLUX").
        If omitted, the first matching entry in the registry is returned
        (documented per-pipeline as the "default" in the notes above).

    Returns
    -------
    FluxColumnSpec

    Raises
    ------
    UnknownPipelineError
        If `author` is not in the registry at all.
    UnknownSectorRangeError
        If `author` is known but no entry's sector range covers `sector`.
    ValueError
        If `colnames` is given and the resolved spec's columns aren't in it.
    """
    if author not in FLUX_COLUMN_REGISTRY:
        raise UnknownPipelineError(
            f"Pipeline/author '{author}' is not in FLUX_COLUMN_REGISTRY. "
            f"Known pipelines: {sorted(FLUX_COLUMN_REGISTRY)}. "
            f"Add an explicit entry rather than guessing."
        )

    candidates = FLUX_COLUMN_REGISTRY[author]

    def sector_ok(spec: FluxColumnSpec) -> bool:
        if sector is None:
            return True
        if spec.sector_min is not None and sector < spec.sector_min:
            return False
        if spec.sector_max is not None and sector > spec.sector_max:
            return False
        return True

    matches = [c for c in candidates if sector_ok(c)]

    if not matches:
        raise UnknownSectorRangeError(
            f"No FLUX_COLUMN_REGISTRY entry for author='{author}' covers "
            f"sector={sector}. Known entries for this author: {candidates}"
        )

    if preferred is not None:
        matches = [c for c in matches if c.flux_col.lower() == preferred.lower()]
        if not matches:
            raise ValueError(
                f"preferred='{preferred}' does not match any registry entry "
                f"for author='{author}', sector={sector}."
            )

    spec = matches[0]

    if colnames is not None:
        lower_cols = {c.lower() for c in colnames}
        if spec.flux_col.lower() not in lower_cols:
            raise ValueError(
                f"Registry expected flux column '{spec.flux_col}' for "
                f"author='{author}', sector={sector}, but it is not present "
                f"in the supplied colnames: {list(colnames)}. "
                f"The file may be from an HLSP version not yet covered by "
                f"this registry -- do not fall back to guessing; add an entry."
            )
        if spec.flux_err_col is not None and spec.flux_err_col.lower() not in lower_cols:
            raise ValueError(
                f"Registry expected error column '{spec.flux_err_col}' for "
                f"author='{author}', sector={sector}, but it is not present "
                f"in the supplied colnames: {list(colnames)}."
            )

    return spec


# ---------------------------------------------------------------------------
# Optional heuristic fallback -- NOT used by get_flux_column_spec() above.
# Kept only as a manual escape hatch for exploring an unrecognised file
# (e.g. a brand-new HLSP pipeline not yet added to the registry), and
# deliberately requires the caller to invoke it explicitly, so it can never
# silently substitute for a registry miss.
# ---------------------------------------------------------------------------

def heuristic_flux_columns_FALLBACK_ONLY(colnames: Sequence[str]) -> dict:
    """
    Name-pattern based guess at flux/flux-error column pairs. Use only to
    inspect an unfamiliar file while you write its proper registry entry --
    never as a substitute for get_flux_column_spec() in production code,
    since it cannot tell you the calibration type (physical vs.
    normalized_catalog), only that a column's name contains 'flux'.
    """
    import re
    names = list(colnames)
    lower_map = {c.lower(): c for c in names}
    flux_like = [
        c for c in names
        if re.search(r"flux", c, re.IGNORECASE)
        and not re.search(r"(err|unc|sigma)", c, re.IGNORECASE)
        and not re.search(r"bkg|background", c, re.IGNORECASE)
    ]
    pairs = {}
    for f in flux_like:
        err_guess = lower_map.get((f + "_err").lower()) or lower_map.get((f + "_ERR").lower())
        pairs[f] = err_guess
    return pairs


if __name__ == "__main__":
    # Minimal smoke test / usage example.
    spec = get_flux_column_spec("QLP", sector=4)
    print("QLP, sector 4, default entry:", spec)

    spec = get_flux_column_spec("QLP", sector=4, preferred="SAP_FLUX")
    print("QLP, sector 4, SAP_FLUX explicitly:", spec)

    spec = get_flux_column_spec("QLP", sector=60, preferred="DET_FLUX")
    print("QLP, sector 60, DET_FLUX explicitly:", spec)

    spec = get_flux_column_spec("SPOC", sector=4)
    print("SPOC, sector 4:", spec)