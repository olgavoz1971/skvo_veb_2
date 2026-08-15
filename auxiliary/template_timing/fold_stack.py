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
    """Calendar time at fold coordinate ``tau`` on cycle ``cycle_index`` (O-C use only)."""
    return t_ref + cycle_index * period + tau


def ensemble_calendar_from_delta_tau(
    delta_tau: float,
    *,
    t_ref: float,
    period: float,
    tau_peak: float,
    t_pick: float,
) -> tuple[int, float, float]:
    """Map a fold-space template shift to one calendar ToM on the nearest cycle.

    Constant-period inversion: ``t = T0 + E P + tau``. ``E`` is the integer cycle
    nearest ``t_pick`` (typically the fit-window centre, start, or end).

    Args:
        delta_tau (float): Fitted shift of the template peak in tau (days).
        t_ref (float): Fold epoch ``T0`` (same origin as the tau coordinate).
        period (float): Fold period ``P`` (days).
        tau_peak (float): Unshifted template peak in tau (days).
        t_pick (float): Calendar time that selects the reporting cycle.

    Returns:
        tuple[int, float, float]: ``(cycle_index, t_anchor, t_max)`` where
        ``t_anchor`` is the unshifted template peak on that cycle and
        ``t_max = t_anchor + delta_tau``.
    """
    cycle_index = cycle_index_at_time(t_pick, t_ref, period)
    t_anchor = t_from_tau_on_cycle(
        tau_peak, t_ref=t_ref, period=period, cycle_index=cycle_index
    )
    t_max = t_from_tau_on_cycle(
        tau_peak + delta_tau, t_ref=t_ref, period=period, cycle_index=cycle_index
    )
    return cycle_index, t_anchor, t_max


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


def extended_tau_from_phase(phi: np.ndarray, period: float) -> np.ndarray:
    """Map centred phase and +1 copy to tau = phi_ext * P (days, phase 0 at tau=0)."""
    phi_ext = np.concatenate([phi, phi + 1.0])
    return phi_ext * period


def continuous_cycles_from_quadratic_oc(
    t: np.ndarray | float,
    *,
    period: float,
    epoch: float,
    oc_a: float,
    oc_b: float,
    oc_c: float,
) -> np.ndarray:
    """Solve for continuous cycle number ``E`` at truncated JD ``t``.

    Inverts ``JD = a E² + (P₀ + b) E + (T₀ + c)`` using the same root branch as
    ``skvo_veb.utils.gp.quadratic_fold`` and ``binary_processor.fold_lightcurve_with_oc``.

    Args:
        t (numpy.ndarray | float): Julian dates (truncated JD, same units as epoch).
        period (float): Reference period ``P₀`` (days).
        epoch (float): Reference epoch ``T₀`` (truncated JD).
        oc_a (float): Quadratic O-C coefficient on ``E²``.
        oc_b (float): Linear O-C coefficient on ``E``.
        oc_c (float): Constant O-C offset (days).

    Returns:
        numpy.ndarray: Continuous cycle numbers ``E``.

    Raises:
        ValueError: When the discriminant is negative or the corrected period is zero.
    """
    t_arr = np.asarray(t, dtype=float)
    p_corr = period + oc_b
    t_corr = epoch + oc_c
    if np.isclose(oc_a, 0.0, atol=1e-16):
        if np.isclose(p_corr, 0.0, atol=1e-16):
            raise ValueError("corrected period is zero; cannot fold")
        return (t_arr - t_corr) / p_corr

    discriminant = p_corr**2 - 4.0 * oc_a * (t_corr - t_arr)
    if np.any(discriminant < 0):
        bad = int(np.count_nonzero(discriminant < 0))
        raise ValueError(
            f"quadratic fold failed for {bad} point(s): discriminant < 0"
        )
    return (-p_corr + np.sqrt(discriminant)) / (2.0 * oc_a)


def phase_centred_from_quadratic_oc(
    t: np.ndarray | float,
    *,
    period: float,
    epoch: float,
    oc_a: float,
    oc_b: float,
    oc_c: float,
) -> np.ndarray:
    """Centred phase in [-0.5, 0.5) from a quadratic O-C ephemeris."""
    cycles = continuous_cycles_from_quadratic_oc(
        t,
        period=period,
        epoch=epoch,
        oc_a=oc_a,
        oc_b=oc_b,
        oc_c=oc_c,
    )
    return cycles - np.round(cycles)


def instantaneous_period_at_cycle(
    cycle_e: float | np.ndarray,
    *,
    period: float,
    oc_b: float,
    oc_a: float,
) -> float | np.ndarray:
    """Instantaneous period ``P(E) = P₀ + b + 2 a E``."""
    return period + oc_b + 2.0 * oc_a * np.asarray(cycle_e, dtype=float)


def resolve_tau_period(
    *,
    period: float,
    epoch: float,
    oc_a: float,
    oc_b: float,
    oc_c: float,
    jd_segment_start: float,
    tau_period_override: float | None,
) -> tuple[float, float]:
    """Resolve ``P_τ`` for ``tau = phi_ext * P_τ``.

    Args:
        period (float): Reference period ``P₀``.
        epoch (float): Reference epoch ``T₀``.
        oc_a (float): Quadratic O-C coefficient.
        oc_b (float): Linear O-C coefficient.
        oc_c (float): Constant O-C offset.
        jd_segment_start (float): Segment start JD (typically ``template_window.t_min``).
        tau_period_override (float | None): Manifest override; ``None`` → ``P(E_start)``.

    Returns:
        tuple[float, float]: ``(P_tau, E_start)``.
    """
    e_start = float(
        continuous_cycles_from_quadratic_oc(
            jd_segment_start,
            period=period,
            epoch=epoch,
            oc_a=oc_a,
            oc_b=oc_b,
            oc_c=oc_c,
        )
    )
    p_inst = float(
        instantaneous_period_at_cycle(
            e_start, period=period, oc_b=oc_b, oc_a=oc_a
        )
    )
    if tau_period_override is not None:
        return float(tau_period_override), e_start
    return p_inst, e_start


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


def fold_for_template_quadratic(
    df: pd.DataFrame,
    *,
    t_min: float,
    t_max: float,
    epoch: float,
    period: float,
    oc_a: float,
    oc_b: float,
    oc_c: float,
    tau_period: float,
    time_col: str = "jd",
    mag_col: str = "mag",
    err_col: str = "dmag",
) -> pd.DataFrame:
    """Pre-fold with quadratic O-C phase and separate ``P_τ`` for the tau axis.

    Args:
        df (pandas.DataFrame): Detrended light curve.
        t_min (float): Template window start (truncated JD).
        t_max (float): Template window end (truncated JD).
        epoch (float): Reference epoch ``T₀`` (truncated JD).
        period (float): Reference period ``P₀`` (days).
        oc_a (float): Quadratic O-C coefficient.
        oc_b (float): Linear O-C coefficient.
        oc_c (float): Constant O-C offset.
        tau_period (float): ``P_τ`` scaling phase to days on the tau axis.
        time_col (str): Time column name.
        mag_col (str): Magnitude column name.
        err_col (str): Uncertainty column name.

    Returns:
        pandas.DataFrame: Folded stack with ``tau``, ``mag``, ``dmag``.
    """
    if tau_period <= 0:
        raise ValueError("tau_period must be positive")

    piece = df.loc[(df[time_col] >= t_min) & (df[time_col] <= t_max)].copy()
    if piece.empty:
        raise ValueError(f"no points in [{t_min}, {t_max}]")

    times = piece[time_col].to_numpy(dtype=float)
    phi = phase_centred_from_quadratic_oc(
        times,
        period=period,
        epoch=epoch,
        oc_a=oc_a,
        oc_b=oc_b,
        oc_c=oc_c,
    )
    tau = extended_tau_from_phase(phi, tau_period)
    mag = np.concatenate([piece[mag_col].to_numpy(dtype=float)] * 2)
    if err_col in piece.columns:
        err = np.concatenate([piece[err_col].to_numpy(dtype=float)] * 2)
    else:
        err = np.full_like(mag, np.nan)

    return pd.DataFrame({"tau": tau, "mag": mag, "dmag": err})
