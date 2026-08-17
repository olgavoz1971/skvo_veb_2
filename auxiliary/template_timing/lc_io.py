"""Load light curves for template timing via the approved VO bridge."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from skvo_veb.utils.lc_bridge import ingest_lightcurve_file, photcal_from_metadata
from skvo_veb.utils.lc_config import DOMAIN_FLUX, DOMAIN_MAG

logger = logging.getLogger(__name__)

PHOTOMETRY_DOMAINS = frozenset({DOMAIN_MAG, DOMAIN_FLUX})


def load_lightcurve(path: Path):
    """Ingest a light-curve file through ``ingest_lightcurve_file``.

    Args:
        path (Path): Path to ``.vot``, ``.dat``, ``.csv``, or ``.ecsv``.

    Returns:
        CurveDash: Parsed light curve with absolute ``jd`` and native ``active_domain``.
    """
    path = path.resolve()
    return ingest_lightcurve_file(path, path.name)


def ensure_working_domain(lcd, working_domain: str):
    """Align ``CurveDash`` storage domain with the manifest working domain.

    Args:
        lcd: Ingested light curve.
        working_domain (str): ``mag`` or ``flux`` from the manifest.

    Returns:
        CurveDash: Same instance, converted in place when needed.

    Raises:
        ValueError: When ``working_domain`` is invalid or photcal is incomplete.
    """
    if working_domain not in PHOTOMETRY_DOMAINS:
        raise ValueError(
            f"photometry_domain must be one of {sorted(PHOTOMETRY_DOMAINS)}, "
            f"got {working_domain!r}"
        )
    native = lcd.active_domain
    if working_domain == native:
        return lcd
    if working_domain == DOMAIN_MAG:
        lcd.convert_to_mag()
    else:
        lcd.convert_to_flux()
    return lcd


def _photometry_arrays(lcd) -> tuple[np.ndarray, np.ndarray]:
    """Return photometry and uncertainty arrays for the active domain."""
    if lcd.active_domain == DOMAIN_MAG:
        phot = np.asarray(lcd.mag, dtype=float)
        err = np.asarray(lcd.mag_err, dtype=float)
    elif lcd.active_domain == DOMAIN_FLUX:
        phot = np.asarray(lcd.flux, dtype=float)
        err = np.asarray(lcd.flux_err, dtype=float)
    else:
        raise ValueError(f"unsupported active_domain {lcd.active_domain!r}")
    return phot, err


def lightcurve_to_frame(lcd) -> pd.DataFrame:
    """Build a timing pipeline DataFrame with absolute JD and photometry columns.

    Args:
        lcd: Light curve already aligned to the manifest working domain.

    Returns:
        pandas.DataFrame: Columns ``jd``, ``phot``, ``phot_err``.
    """
    phot, err = _photometry_arrays(lcd)
    return pd.DataFrame(
        {
            "jd": np.asarray(lcd.jd, dtype=float),
            "phot": phot,
            "phot_err": err,
        }
    )


def load_lightcurve_frame(path: Path, *, working_domain: str) -> tuple[pd.DataFrame, dict]:
    """Load a file and return the full LC as a normalised DataFrame.

    Args:
        path (Path): Light-curve file path.
        working_domain (str): Manifest ``photometry_domain`` (``mag`` or ``flux``).

    Returns:
        tuple: ``(dataframe, metadata)`` with ``photcal`` and domain fields.
    """
    lcd = load_lightcurve(path)
    native_domain = lcd.active_domain
    lcd = ensure_working_domain(lcd, working_domain)
    meta = {
        "active_domain": lcd.active_domain,
        "native_domain": native_domain,
        "photcal": dict(lcd.metadata.get("photcal") or {}),
        "source_path": str(path),
    }
    return lightcurve_to_frame(lcd), meta


def load_lc_fragment(
    path: Path,
    t_min: float,
    t_max: float,
    *,
    working_domain: str,
) -> tuple[pd.DataFrame, dict]:
    """Load and slice a light curve on absolute Julian Date.

    Args:
        path (Path): Light-curve file path.
        t_min (float): Window lower bound (absolute JD, days).
        t_max (float): Window upper bound (absolute JD, days).
        working_domain (str): Manifest ``photometry_domain``.

    Returns:
        tuple: Sliced ``(dataframe, metadata)``.

    Raises:
        ValueError: When the window contains no points.
    """
    df, meta = load_lightcurve_frame(path, working_domain=working_domain)
    piece = df.loc[(df["jd"] >= t_min) & (df["jd"] <= t_max)].copy()
    if piece.empty:
        raise ValueError(f"no LC points in [{t_min}, {t_max}] for {path}")
    return piece, meta


def require_photcal(meta: dict, *, context: str):
    """Return ``PhotCal`` from fragment metadata or raise.

    Args:
        meta (dict): Loader metadata containing ``photcal``.
        context (str): Label for error messages.

    Returns:
        PhotCal: Calibration for domain conversion.
    """
    try:
        return photcal_from_metadata(meta.get("photcal"))
    except ValueError as exc:
        raise ValueError(f"{context}: {exc}") from exc
