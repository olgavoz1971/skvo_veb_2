"""Load VOTable light curves and interval files using template_timing helpers."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from paths import ensure_import_paths

ensure_import_paths()

from lc_io import load_lc_fragment, load_lightcurve_frame  # noqa: E402
from skvo_veb.utils.gp.intervals import load_intervals  # noqa: E402

logger = logging.getLogger(__name__)


def load_interval_pairs_jd(path: Path) -> list[tuple[float, float]]:
    """Load two-column interval bounds already stored as absolute JD.

    The spike data files use absolute JD (same convention as many
    ``template_timing`` interval exports with ``intervals_time.scale: jd``).

    Args:
        path (Path): Interval ``.dat`` path.

    Returns:
        list[tuple[float, float]]: ``(t_start, t_end)`` in absolute JD.

    Raises:
        FileNotFoundError: If ``path`` is missing.
        ValueError: If the file contains no intervals.
    """
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"intervals not found: {path}")
    with path.open(encoding="utf-8") as handle:
        raw = load_intervals(handle)
    if not raw:
        raise ValueError(f"no intervals in {path}")
    out: list[tuple[float, float]] = []
    for a, b in raw:
        t0, t1 = float(a), float(b)
        if t0 > t1:
            t0, t1 = t1, t0
        out.append((t0, t1))
    logger.info("Loaded %s interval(s) from %s", len(out), path.name)
    return out


def load_full_lightcurve(
    path: Path, *, working_domain: str
) -> tuple[pd.DataFrame, dict]:
    """Load an entire LC into ``jd`` / ``phot`` / ``phot_err`` columns.

    Args:
        path (Path): ``.vot`` / ``.dat`` / … path.
        working_domain (str): ``flux`` or ``mag``.

    Returns:
        tuple: DataFrame and loader metadata.
    """
    path = path.resolve()
    df, meta = load_lightcurve_frame(path, working_domain=working_domain)
    logger.info(
        "Loaded LC %s: %s points, domain=%s (native=%s)",
        path.name,
        len(df),
        meta.get("active_domain"),
        meta.get("native_domain"),
    )
    return df, meta


def slice_interval(
    df: pd.DataFrame, t_start: float, t_end: float
) -> pd.DataFrame:
    """Return LC rows inside ``[t_start, t_end]`` (inclusive).

    Args:
        df (pandas.DataFrame): Full light curve with ``jd`` column.
        t_start (float): Interval start (absolute JD).
        t_end (float): Interval end (absolute JD).

    Returns:
        pandas.DataFrame: Slice (may be empty).
    """
    mask = (df["jd"] >= t_start) & (df["jd"] <= t_end)
    return df.loc[mask].copy()


def interval_arrays(
    piece: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract time, photometry, and optional error arrays.

    Args:
        piece (pandas.DataFrame): Interval slice.

    Returns:
        tuple: ``(jd, phot, phot_err)``; ``phot_err`` may be all-NaN.
    """
    jd = piece["jd"].to_numpy(dtype=float)
    phot = piece["phot"].to_numpy(dtype=float)
    if "phot_err" in piece.columns:
        err = piece["phot_err"].to_numpy(dtype=float)
    else:
        err = np.full_like(jd, np.nan)
    return jd, phot, err


# Re-export fragment loader for callers that prefer per-window I/O.
__all__ = [
    "load_interval_pairs_jd",
    "load_full_lightcurve",
    "slice_interval",
    "interval_arrays",
    "load_lc_fragment",
]
