"""Configuration and ADQL 2.0 templates for the Gaia DR3 (ARI) TAP provider."""

from __future__ import annotations

from dataclasses import dataclass

from skvo_veb.lc_providers.tap.adql import adql_top_limit_clause
from skvo_veb.lc_providers.tap.dialect import TapQueryDialect

PROVIDER_ID = "gaia_dr3_ari"
DISPLAY_NAME = "Gaia DR3 (ARI)"
TAP_URL = "https://gaia.ari.uni-heidelberg.de/tap"
TAP_QUERY_DIALECT = TapQueryDialect.ADQL_2_0
OBSCORE_TABLE = "ivoa.ObsCore"
OBS_COLLECTION = "gaiadr3"
DATA_PRODUCT_TYPE = "timeseries"

# Archive photcal GROUPs provide zeroPointFlux (Jy) but omit zeroPointReferenceMagnitude.
GAIA_ARI_ZERO_POINT_REFERENCE_MAGNITUDE = 0.0

OBSCORE_SELECT_COLUMNS = (
    "s_ra",
    "s_dec",
    "t_min",
    "t_max",
    "t_xel",
    "access_url",
    "obs_id",
)

N_POINTS_PROVIDER_NOTE = (
    "Point count from ObsCore t_xel reflects the G-band lightcurve length only."
)


@dataclass(frozen=True)
class GaiaAriBandSpec:
    """One Gaia DR3 epoch-photometry band inside a bundled access URL product."""

    band_code: str
    filter_name: str
    table_id: int


GAIA_ARI_BANDS: tuple[GaiaAriBandSpec, ...] = (
    GaiaAriBandSpec(band_code="G", filter_name="Gaia G", table_id=0),
    GaiaAriBandSpec(band_code="BP", filter_name="Gaia BP", table_id=1),
    GaiaAriBandSpec(band_code="RP", filter_name="Gaia RP", table_id=2),
)


def _select_clause() -> str:
    """Returns the shared ObsCore SELECT column list.

    Returns:
        str: Comma-separated ObsCore column names.
    """
    return ", ".join(OBSCORE_SELECT_COLUMNS)


def _base_predicates() -> list[str]:
    """Returns shared ObsCore collection and product-type predicates.

    Returns:
        list[str]: ADQL WHERE fragments.
    """
    return [
        f"obs_collection = '{OBS_COLLECTION}'",
        f"dataproduct_type = '{DATA_PRODUCT_TYPE}'",
    ]


def _time_bound_clauses(
    *,
    time_start_mjd: float | None,
    time_end_mjd: float | None,
) -> list[str]:
    """Builds optional ADQL time-window predicates in MJD.

    Args:
        time_start_mjd (float, optional): Lower bound in MJD.
        time_end_mjd (float, optional): Upper bound in MJD.

    Returns:
        list[str]: Zero or more ADQL predicate fragments.
    """
    clauses: list[str] = []
    if time_start_mjd is not None:
        clauses.append(f"t_min > {float(time_start_mjd)}")
    if time_end_mjd is not None:
        clauses.append(f"t_max < {float(time_end_mjd)}")
    return clauses


def adql_catalog_by_obs_id(
    obs_id: int | str,
    *,
    time_start_mjd: float | None = None,
    time_end_mjd: float | None = None,
) -> str:
    """Builds ADQL 2.0 for direct Gaia ``obs_id`` ObsCore catalogue lookup.

    Args:
        obs_id (int or str): Gaia DR3 source identifier stored as ObsCore ``obs_id``.
        time_start_mjd (float, optional): Lower time bound in MJD.
        time_end_mjd (float, optional): Upper time bound in MJD.

    Returns:
        str: Complete ADQL query string.
    """
    predicates = [
        *_base_predicates(),
        f"obs_id = '{int(obs_id)}'",
        *_time_bound_clauses(
            time_start_mjd=time_start_mjd,
            time_end_mjd=time_end_mjd,
        ),
    ]
    where = " AND ".join(predicates)
    return f"SELECT {_select_clause()} FROM {OBSCORE_TABLE} WHERE {where}"


def adql_catalog_cone(
    *,
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    time_start_mjd: float | None = None,
    time_end_mjd: float | None = None,
    row_limit: int | None = None,
) -> str:
    """Builds ADQL 2.0 for cone search on ObsCore sky position columns.

    Args:
        ra_deg (float): Cone centre right ascension in degrees.
        dec_deg (float): Cone centre declination in degrees.
        radius_arcsec (float): Cone radius in arcseconds.
        time_start_mjd (float, optional): Lower time bound in MJD.
        time_end_mjd (float, optional): Upper time bound in MJD.
        row_limit (int, optional): Maximum number of ObsCore rows (``SELECT TOP``).

    Returns:
        str: Complete ADQL query string.
    """
    radius_deg = float(radius_arcsec) / 3600.0
    ra = float(ra_deg)
    dec = float(dec_deg)
    predicates = [
        *_base_predicates(),
        f"1 = CONTAINS(POINT('ICRS', s_ra, s_dec), CIRCLE('ICRS', {ra}, {dec}, {radius_deg}))",
        *_time_bound_clauses(
            time_start_mjd=time_start_mjd,
            time_end_mjd=time_end_mjd,
        ),
    ]
    where = " AND ".join(predicates)
    top = adql_top_limit_clause(row_limit)
    return f"SELECT {top}{_select_clause()} FROM {OBSCORE_TABLE} WHERE {where}"
