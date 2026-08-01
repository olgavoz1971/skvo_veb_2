"""GP-specific flux extraction for timing fits (normalised instrumental flux)."""

from __future__ import annotations

import json
import logging

import astropy.units as u
import numpy as np
import pandas as pd

from skvo_veb.utils.lc_config import PHOTCAL_KEY_ZP_FLUX, PHOTCAL_KEY_ZP_MAG
from skvo_veb.utils.lc_bridge import (
    get_flux_fragment,
    unpack_json_for_plotly,
)
from skvo_veb.utils.gp.config import DEFAULT_REFERENCE_MAG, GP_ZP_FLUX_DIMENSIONLESS
from skvo_veb.volightcurve.lightcurve import PhotCal

logger = logging.getLogger(__name__)


def resolve_gp_photcal(meta: dict) -> PhotCal:
    """Build a ``PhotCal`` for mag-to-flux conversion on the GP page.

    Uses transport ``photcal`` when both zero points are present; otherwise applies
    GP config defaults (dimensionless instrumental flux, configurable reference mag).

    Args:
        meta (dict): Transport packet ``meta`` block.

    Returns:
        PhotCal: Calibration for monotonic mag-to-flux conversion before GP normalisation.
    """
    photcal = meta.get("photcal") or {}
    zp_mag = photcal.get(PHOTCAL_KEY_ZP_MAG)
    zp_flux = photcal.get(PHOTCAL_KEY_ZP_FLUX)
    if zp_mag is not None and zp_flux is not None:
        return PhotCal(
            zp_flux=float(zp_flux),
            zp_flux_unit=photcal.get("zp_flux_unit") or None,
            zp_mag=float(zp_mag),
            zp_mag_unit=photcal.get("zp_mag_unit") or "mag",
        )
    if zp_mag is None:
        zp_mag = DEFAULT_REFERENCE_MAG
    else:
        zp_mag = float(zp_mag)
    if zp_flux is None:
        zp_flux = GP_ZP_FLUX_DIMENSIONLESS
    else:
        zp_flux = float(zp_flux)
    return PhotCal(zp_flux=zp_flux, zp_flux_unit=None, zp_mag=zp_mag, zp_mag_unit="mag")


def get_gp_flux_fragment(json_str: str, jd_min: float, jd_max: float) -> pd.DataFrame:
    """Return a JD-sliced fragment as instrumental flux for ``gp_peak_pipeline``.

    Prefers bridge ``get_flux_fragment`` when photcal metadata is complete. For
    magnitude-native uploads, converts via ``PhotCal`` using metadata or GP defaults.

    Args:
        json_str (str): Serialised lightcurve transport JSON.
        jd_min (float): Interval lower bound (absolute JD).
        jd_max (float): Interval upper bound (absolute JD).

    Returns:
        pandas.DataFrame: Columns ``jd``, ``flux``, ``flux_err``.
    """
    packet = json.loads(json_str)
    meta = packet["meta"]
    photcal = meta.get("photcal") or {}
    has_pair = (
        photcal.get(PHOTCAL_KEY_ZP_MAG) is not None
        and photcal.get(PHOTCAL_KEY_ZP_FLUX) is not None
    )
    if meta.get("active_domain") == "flux" and has_pair:
        return get_flux_fragment(json_str, jd_min, jd_max)

    if meta.get("active_domain") == "flux":
        lc_flux = unpack_json_for_plotly(json_str, view_mode="flux")
        df = pd.DataFrame({
            "jd": lc_flux["x"],
            "flux": lc_flux["y"],
            "flux_err": lc_flux["err"] if lc_flux["err"] is not None else np.nan,
        })
        mask = (df["jd"] >= jd_min) & (df["jd"] <= jd_max)
        return df.loc[mask].dropna(subset=["jd", "flux"]).copy()

    lc_mag = unpack_json_for_plotly(json_str, view_mode="mag")
    pc = resolve_gp_photcal(meta)
    x = lc_mag["x"]
    mag = lc_mag["y"]
    err_mag = lc_mag["err"]

    flux = np.asarray(pc.mag_to_flux(mag * u.mag).value, dtype=float)
    if err_mag is not None and np.any(np.isfinite(err_mag)):
        err_q = np.where(np.isfinite(err_mag), err_mag, 0.0) * u.mag
        mag_q = mag * u.mag
        flux_err = np.asarray(
            pc.mag_err_to_flux_err(mag_q, err_q).value, dtype=float
        )
        flux_err = np.where(np.isfinite(err_mag), flux_err, np.nan)
    else:
        flux_err = np.full_like(flux, np.nan)

    df = pd.DataFrame({"jd": x, "flux": flux, "flux_err": flux_err})
    mask = (df["jd"] >= jd_min) & (df["jd"] <= jd_max)
    frag = df.loc[mask].dropna(subset=["jd", "flux"]).copy()
    return frag
