"""Load light curves and convert to normalised flux (Step 1 / Step 2)."""

from __future__ import annotations

from pathlib import Path

import astropy.units as u
import numpy as np
import pandas as pd

from skvo_veb.utils.lc_config import DOMAIN_FLUX, DOMAIN_MAG

from lc_io import load_lc_fragment, require_photcal


def load_lc_window(
    path: Path,
    t_min: float,
    t_max: float,
    *,
    working_domain: str,
) -> tuple[pd.DataFrame, dict]:
    """Load a JD window in the manifest working photometry domain.

    Args:
        path (Path): Light-curve file.
        t_min (float): Lower bound (absolute JD).
        t_max (float): Upper bound (absolute JD).
        working_domain (str): ``mag`` or ``flux``.

    Returns:
        tuple: Sliced fragment and metadata (includes ``photcal``).
    """
    return load_lc_fragment(
        path,
        t_min,
        t_max,
        working_domain=working_domain,
    )


def photometry_to_normalised_flux(
    piece: pd.DataFrame,
    meta: dict,
    baseline_flux: float,
    ampl_guess_flux: float,
    *,
    context: str = "template fit",
) -> pd.DataFrame:
    """Convert fragment photometry to normalised flux for template alignment.

    Uses ``photcal`` from light-curve metadata only; no silent zero-point defaults.

    Args:
        piece (pandas.DataFrame): Columns ``phot``, optional ``phot_err``.
        meta (dict): Loader metadata with ``active_domain`` and ``photcal``.
        baseline_flux (float): Step 1 GP baseline for normalisation.
        ampl_guess_flux (float): Step 1 GP amplitude guess for normalisation.
        context (str): Label for error messages.

    Returns:
        pandas.DataFrame: Copy with ``flux`` and ``y_norm`` columns.
    """
    domain = meta.get("active_domain")
    if ampl_guess_flux <= 0:
        raise ValueError("ampl_guess_flux must be positive")

    if domain == DOMAIN_FLUX:
        flux = piece["phot"].to_numpy(dtype=float)
    elif domain == DOMAIN_MAG:
        pc = require_photcal(meta, context=context)
        mag = piece["phot"].to_numpy(dtype=float) * u.mag
        flux = np.asarray(pc.mag_to_flux(mag).value, dtype=float)
    else:
        raise ValueError(
            f"{context}: unsupported active_domain {domain!r}; expected mag or flux"
        )

    out = piece.copy()
    out["flux"] = flux
    out["y_norm"] = (flux - baseline_flux) / ampl_guess_flux
    return out
