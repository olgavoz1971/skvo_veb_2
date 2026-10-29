"""Load TESS-style Discovery VOTables for Mikulasek spike scripts."""

from __future__ import annotations

import logging
from pathlib import Path

import astropy.units as u
import numpy as np
from volightcurve import PhotCalError, read_lightcurve
from volightcurve.time_reference import (
    normalise_table_epoch_to_absolute_jd,
    resolve_observation_timesys,
    time_offset_to_absolute_jd,
)

logger = logging.getLogger(__name__)


def _column_as_mag(quantity) -> np.ndarray:
    """Return a magnitude column as a float array in mag.

    Args:
        quantity: Astropy column or Quantity from PhotCal.

    Returns:
        ndarray: Magnitudes (mag).
    """
    unit = getattr(quantity, "unit", None)
    if unit is not None:
        converted = quantity.to(u.mag)
        return np.asarray(getattr(converted, "value", converted), dtype=float)
    return np.asarray(quantity, dtype=float)


def load_tess_votable(path: str | Path) -> dict:
    """Load time, magnitude, period and folding epoch from a VOTable.

    Ingest is ``read_lightcurve``. Magnitudes come from a declared mag column
    or from ``add_mag_column_from_flux`` / PhotCal. Times and the ``epoch``
    PARAM are converted to absolute Julian Date with TIMESYS. Period is the
    TABLE PARAM ``period``.

    Args:
        path (str | Path): Path to a VOTable.

    Returns:
        dict: ``t`` (absolute JD, d), ``mag``, ``sig``, ``title``, ``period``,
        ``epoch_jd`` (absolute JD, T0 for eclipse numbering), ``timescale``,
        ``timeorigin``.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        PhotCalError: If PhotCal cannot convert flux to magnitude.
        ValueError: If columns, TIMESYS, period or epoch are missing or
            ambiguous, or if no finite rows remain.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"VOTable not found: {path}")

    volc = read_lightcurve(path, filename=path.name, strict=True)
    convert_blockers = [
        p
        for p in volc.time_problems()
        if "time origin" in p or "No observation time column" in p
    ]
    if convert_blockers:
        raise ValueError(
            "TIMESYS cannot convert times to Julian Date:\n" + "\n".join(convert_blockers)
        )

    time_cols = volc.get_time_colnames()
    if len(time_cols) != 1:
        raise ValueError(f"Need exactly one time column, found {time_cols!r}.")
    tcol = time_cols[0]
    ts = resolve_observation_timesys(volc)

    mag_cols = volc.get_mag_colnames()
    flux_cols = volc.get_flux_colnames()
    if mag_cols:
        if len(mag_cols) != 1:
            raise ValueError(f"Need exactly one magnitude column, found {mag_cols!r}.")
        mag_err_cols = volc.get_mag_error_colnames()
        if len(mag_err_cols) != 1:
            raise ValueError(
                f"Need exactly one magnitude-error column, found {mag_err_cols!r}."
            )
        mag_col, err_col = mag_cols[0], mag_err_cols[0]
        mag_q = volc.table[mag_col]
        sig_q = volc.table[err_col]
    elif flux_cols:
        if len(flux_cols) != 1:
            raise ValueError(f"Need exactly one flux column, found {flux_cols!r}.")
        flux_err_cols = volc.get_flux_error_colnames()
        if len(flux_err_cols) != 1:
            raise ValueError(
                f"Need exactly one flux-error column, found {flux_err_cols!r}."
            )
        flux_col, err_col = flux_cols[0], flux_err_cols[0]
        problems = volc.conversion_problems(flux_col)
        if problems:
            raise PhotCalError(problems)
        photcal = volc.photdms[flux_col].photcal
        mag_col = volc.add_mag_column_from_flux(flux_col)
        mag_q = volc.table[mag_col]
        sig_q = photcal.flux_err_to_mag_err(volc.table[flux_col], volc.table[err_col])
    else:
        raise ValueError("No magnitude or flux column via UCD discovery.")

    mag = _column_as_mag(mag_q)
    sig = _column_as_mag(sig_q)
    raw_t = np.asarray(volc.table[tcol], dtype=float)
    t_jd = np.full(raw_t.shape, np.nan, dtype=float)
    finite_t = np.isfinite(raw_t)
    t_jd[finite_t] = [
        time_offset_to_absolute_jd(float(v), ts.timeorigin) for v in raw_t[finite_t]
    ]
    ok = np.isfinite(mag) & np.isfinite(sig) & np.isfinite(t_jd)
    n_drop = int((~ok).sum())
    if n_drop:
        logger.info("dropped %s non-finite rows", n_drop)
    if not np.any(ok):
        raise ValueError("No finite magnitude and time rows in the VOTable.")
    mag, sig, t_jd = mag[ok], sig[ok], t_jd[ok]

    period = volc.table.meta.get("period")
    if period is None:
        raise ValueError("VOTable has no TABLE PARAM period.")
    period = float(period)
    if not np.isfinite(period) or period <= 0:
        raise ValueError(f"VOTable period={period!r} is not a positive finite period.")

    raw_epoch = volc.table.meta.get("epoch")
    if raw_epoch is None:
        raise ValueError("VOTable has no TABLE PARAM epoch (folding T0).")
    epoch_jd = normalise_table_epoch_to_absolute_jd(volc, raw_epoch)
    if epoch_jd is None or not np.isfinite(epoch_jd):
        raise ValueError("Could not convert TABLE PARAM epoch to absolute JD via TIMESYS.")

    title = volc.table.meta.get("title") or volc.table.meta.get("name") or path.name
    logger.info(
        "loaded %s points from %s  title=%s  period=%s d  T0=%.10f JD",
        len(t_jd),
        path.name,
        title,
        period,
        epoch_jd,
    )
    return {
        "t": t_jd,
        "mag": mag,
        "sig": sig,
        "title": str(title),
        "period": period,
        "epoch_jd": float(epoch_jd),
        "timescale": ts.timescale,
        "timeorigin": ts.timeorigin,
    }
