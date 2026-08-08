"""Load detrended mag LC and convert to normalised flux (Step 2)."""

from __future__ import annotations

from pathlib import Path

import astropy.units as u
import numpy as np
import pandas as pd

from skvo_veb.utils.gp.config import GP_ZP_FLUX_DIMENSIONLESS
from skvo_veb.utils.gp.flux import resolve_gp_photcal

from fold_stack import load_detrended_mag_dat


def load_lc_fragment(
    path: Path,
    t_min: float,
    t_max: float,
) -> tuple[pd.DataFrame, dict]:
    """Load ASCII LC and restrict to ``[t_min, t_max]`` on truncated JD."""
    df, header = load_detrended_mag_dat(path)
    piece = df.loc[(df["jd"] >= t_min) & (df["jd"] <= t_max)].copy()
    if piece.empty:
        raise ValueError(f"no LC points in [{t_min}, {t_max}]")
    return piece, header


def mag_to_normalised_flux(
    piece: pd.DataFrame,
    mag0: float | None,
    baseline_flux: float,
    ampl_guess_flux: float,
) -> pd.DataFrame:
    """Convert mag to instrumental flux and normalise with template Step 1 scales."""
    meta: dict = {}
    if mag0 is not None:
        meta["photcal"] = {
            "zp_mag": mag0,
            "zp_flux": GP_ZP_FLUX_DIMENSIONLESS,
        }
    pc = resolve_gp_photcal(meta)
    mag = piece["mag"].to_numpy(dtype=float) * u.mag
    flux = np.asarray(pc.mag_to_flux(mag).value, dtype=float)
    if ampl_guess_flux <= 0:
        raise ValueError("ampl_guess_flux must be positive")
    y_norm = (flux - baseline_flux) / ampl_guess_flux
    out = piece.copy()
    out["flux"] = flux
    out["y_norm"] = y_norm
    return out
