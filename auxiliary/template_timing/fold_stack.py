"""Phase folding for template building (truncated JD, constant period)."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd


def phase_centred(
    t: np.ndarray | float,
    t_ref: float,
    period: float,
) -> np.ndarray:
    """Centred phase in [-0.5, 0.5) for constant period."""
    cycles = (np.asarray(t, dtype=float) - t_ref) / period
    return cycles - np.round(cycles)


def cycle_count(
    t: np.ndarray | float,
    t_ref: float,
    period: float,
) -> np.ndarray:
    """Cycle count since ``t_ref`` for constant period."""
    return (np.asarray(t, dtype=float) - t_ref) / period


def observation_tau(
    t: np.ndarray | float,
    t_ref: float,
    period: float,
    *,
    tau_peak: float,
) -> np.ndarray:
    """Map observation time to extended-fold ``tau`` (days), matching Step 1."""
    phi = phase_centred(t, t_ref, period)
    tau_a = phi * period
    tau_b = (phi + 1.0) * period
    t_arr = np.asarray(t, dtype=float)
    if t_arr.ndim == 0:
        return tau_b if abs(tau_b - tau_peak) < abs(tau_a - tau_peak) else tau_a
    use_b = np.abs(tau_b - tau_peak) < np.abs(tau_a - tau_peak)
    return np.where(use_b, tau_b, tau_a)


def cycle_index_at_time(t: float, t_ref: float, period: float) -> int:
    """Nearest integer cycle index for ephemeris inversion."""
    return int(np.round(cycle_count(t, t_ref, period)))


def t_from_tau_on_cycle(
    tau: float,
    *,
    t_ref: float,
    period: float,
    cycle_index: int,
) -> float:
    """Calendar time at fold coordinate ``tau`` on cycle ``cycle_index`` (O-C / ephemeris use)."""
    return t_ref + cycle_index * period + tau


def t_max_from_delta_tau_at_anchor(
    delta_tau: float,
    *,
    t_anchor: float,
    t_ref: float,
    period: float,
    tau_peak: float,
) -> float:
    """Calendar JD of the template peak after shift ``delta_tau``, local to ``t_anchor``.

    Step 2 fits data in a known JD interval; ``t_max`` is obtained by correcting
    ``t_anchor`` in fold-time ``tau`` (same extended-fold branch as ``observation_tau``),
    without global cycle counting.
    """
    tau_target = float(tau_peak + delta_tau)
    tau_anchor = observation_tau(t_anchor, t_ref, period, tau_peak=tau_peak)
    tau_anchor = float(np.asarray(tau_anchor, dtype=float).reshape(-1)[0])
    return float(t_anchor + (tau_target - tau_anchor))


def extended_tau_from_phase(phi: np.ndarray, period: float) -> np.ndarray:
    """Map centred phase and +1 copy to tau = phi_ext * P (days, phase 0 at tau=0)."""
    phi_ext = np.concatenate([phi, phi + 1.0])
    return phi_ext * period


def load_detrended_mag_dat(path: Path) -> tuple[pd.DataFrame, dict]:
    """Load detrended ASCII LC with optional ``# JD0=`` and ``# mag0=`` header lines."""
    jd0 = 0.0
    mag0 = None
    header_cols: list[str] | None = None
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("#"):
                break
            body = line[1:].strip()
            if m := re.match(r"(?i)JD0\s*=\s*([-\d.]+)", body):
                jd0 = float(m.group(1))
            elif m := re.match(r"(?i)mag0\s*=\s*([-\d.]+)", body):
                mag0 = float(m.group(1))
            elif re.search(r"(?i)\bjd\b", body) and re.search(r"(?i)\bmag\b", body):
                header_cols = body.split()

    if header_cols:
        names = [c.lower() for c in header_cols]
    else:
        names = ["jd", "mag", "dmag", "label"]

    df = pd.read_csv(path, sep=r"\s+", comment="#", names=names)
    meta = {"jd0": jd0, "mag0": mag0}
    return df, meta


def fold_for_template(
    df: pd.DataFrame,
    *,
    t_min: float,
    t_max: float,
    t_ref: float,
    period: float,
    time_col: str = "jd",
    mag_col: str = "mag",
    err_col: str = "dmag",
) -> pd.DataFrame:
    """Pre-fold time cut, phase fold with extended +1 copy, abscissa ``tau`` (days)."""
    if period <= 0:
        raise ValueError("period must be positive")

    piece = df.loc[(df[time_col] >= t_min) & (df[time_col] <= t_max)].copy()
    if piece.empty:
        raise ValueError(f"no points in [{t_min}, {t_max}]")

    times = piece[time_col].to_numpy(dtype=float)
    phi = phase_centred(times, t_ref, period)
    tau = extended_tau_from_phase(phi, period)
    mag = np.concatenate([piece[mag_col].to_numpy(dtype=float)] * 2)
    if err_col in piece.columns:
        err = np.concatenate([piece[err_col].to_numpy(dtype=float)] * 2)
    else:
        err = np.full_like(mag, np.nan)

    return pd.DataFrame({"tau": tau, "mag": mag, "dmag": err})
