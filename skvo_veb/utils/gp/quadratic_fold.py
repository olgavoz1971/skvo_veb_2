"""Quadratic O-C ephemeris folding for the GP prep plot."""

from __future__ import annotations

import logging

import numpy as np

from skvo_veb.utils.lc_bridge import get_jd_limits
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

FOLD_EPHEMERIS_CONSTANT = "constant"
FOLD_EPHEMERIS_QUADRATIC_OC = "quadratic_oc"

_DISCRIMINANT_ATOL = 1e-16


def corrected_ephemeris_linear_parts(
    period: float,
    epoch_jd: float,
    oc_b: float,
    oc_c: float,
) -> tuple[float, float]:
    """Applies O-C linear terms to the reference ephemeris.

    Args:
        period (float): Reference period ``P_0`` (days).
        epoch_jd (float): Reference epoch ``T_0`` (absolute JD).
        oc_b (float): Linear O-C coefficient (days per cycle).
        oc_c (float): Constant O-C offset (days).

    Returns:
        tuple[float, float]: ``(P_0 + b, T_0 + c)``.
    """
    return float(period) + float(oc_b), float(epoch_jd) + float(oc_c)


def jd_from_continuous_cycle(
    cycle_e: float | np.ndarray,
    period: float,
    epoch_jd: float,
    oc_a: float,
    oc_b: float,
    oc_c: float,
) -> float | np.ndarray:
    """Maps continuous cycle number ``E`` to absolute Julian Date.

    Uses ``JD(E) = a E^2 + (P_0 + b) E + (T_0 + c)``.

    Args:
        cycle_e: Continuous cycle number(s).
        period (float): Reference period ``P_0``.
        epoch_jd (float): Reference epoch ``T_0`` (absolute JD).
        oc_a (float): Quadratic O-C coefficient.
        oc_b (float): Linear O-C coefficient.
        oc_c (float): Constant O-C offset.

    Returns:
        float or numpy.ndarray: Absolute JD at ``E``.
    """
    p_corr, t_corr = corrected_ephemeris_linear_parts(period, epoch_jd, oc_b, oc_c)
    e = np.asarray(cycle_e, dtype=float)
    return oc_a * e ** 2 + p_corr * e + t_corr


def continuous_cycles_from_jd(
    jd: np.ndarray,
    period: float,
    epoch_jd: float,
    oc_a: float,
    oc_b: float,
    oc_c: float,
) -> np.ndarray:
    """Solves for continuous cycle number ``E`` at each absolute JD.

    Inverts ``JD = a E^2 + (P_0 + b) E + (T_0 + c)`` using the same root branch
    as ``auxiliary/binary_processor.fold_lightcurve_with_oc``.

    Args:
        jd (numpy.ndarray): Absolute Julian dates.
        period (float): Reference period ``P_0``.
        epoch_jd (float): Reference epoch ``T_0``.
        oc_a (float): Quadratic O-C coefficient.
        oc_b (float): Linear O-C coefficient.
        oc_c (float): Constant O-C offset.

    Returns:
        numpy.ndarray: Continuous cycle numbers ``E``.

    Raises:
        PipeException: When the discriminant is negative for any point.
    """
    jd_arr = np.asarray(jd, dtype=float)
    p_corr, t_corr = corrected_ephemeris_linear_parts(period, epoch_jd, oc_b, oc_c)
    if np.isclose(oc_a, 0.0, atol=_DISCRIMINANT_ATOL):
        if np.isclose(p_corr, 0.0, atol=_DISCRIMINANT_ATOL):
            raise PipeException("Corrected period is zero; cannot fold.")
        return (jd_arr - t_corr) / p_corr

    discriminant = p_corr ** 2 - 4.0 * oc_a * (t_corr - jd_arr)
    if np.any(discriminant < 0):
        bad = int(np.sum(discriminant < 0))
        raise PipeException(
            f"Quadratic fold failed for {bad} point(s): discriminant < 0. "
            "Check P, epoch, and O-C coefficients against this time span."
        )
    return (-p_corr + np.sqrt(discriminant)) / (2.0 * oc_a)


def phases_from_quadratic_oc(
    jd: np.ndarray,
    period: float,
    epoch_jd: float,
    oc_a: float,
    oc_b: float,
    oc_c: float,
) -> np.ndarray:
    """Fractional phases ``E mod 1`` from a quadratic O-C ephemeris.

    Args:
        jd (numpy.ndarray): Absolute Julian dates.
        period (float): Reference period ``P_0``.
        epoch_jd (float): Reference epoch ``T_0``.
        oc_a (float): Quadratic O-C coefficient.
        oc_b (float): Linear O-C coefficient.
        oc_c (float): Constant O-C offset.

    Returns:
        numpy.ndarray: Phases in ``[0, 1)``.
    """
    cycles = continuous_cycles_from_jd(jd, period, epoch_jd, oc_a, oc_b, oc_c)
    return np.mod(cycles, 1.0)


def get_intervals_from_quadratic_phase(
    jd_obs_start: float,
    jd_obs_end: float,
    phi_min: float,
    phi_max: float,
    period: float,
    epoch_jd: float,
    oc_a: float,
    oc_b: float,
    oc_c: float,
) -> list[list[float]]:
    """Converts a phase box to JD intervals under a quadratic O-C ephemeris.

    For each integer cycle index ``k`` spanning the observation window, maps
    ``E in [k + phi_min, k + phi_max]`` forward through ``JD(E)`` and clips to
    the observation JD limits.

    Args:
        jd_obs_start (float): Observation window start (absolute JD).
        jd_obs_end (float): Observation window end (absolute JD).
        phi_min (float): Lower phase bound from the prep plot selection.
        phi_max (float): Upper phase bound.
        period (float): Reference period ``P_0``.
        epoch_jd (float): Reference epoch ``T_0``.
        oc_a (float): Quadratic O-C coefficient.
        oc_b (float): Linear O-C coefficient.
        oc_c (float): Constant O-C offset.

    Returns:
        list: ``[[jd_start, jd_end], ...]`` clipped to the observation window.
    """
    lo_jd, hi_jd = sorted((float(jd_obs_start), float(jd_obs_end)))
    if hi_jd <= lo_jd:
        return []

    e_lo = float(
        continuous_cycles_from_jd(
            np.array([lo_jd]), period, epoch_jd, oc_a, oc_b, oc_c
        )[0]
    )
    e_hi = float(
        continuous_cycles_from_jd(
            np.array([hi_jd]), period, epoch_jd, oc_a, oc_b, oc_c
        )[0]
    )
    if e_hi < e_lo:
        e_lo, e_hi = e_hi, e_lo

    k_start = int(np.floor(e_lo))
    k_end = int(np.ceil(e_hi))
    phi_lo = float(min(phi_min, phi_max))
    phi_hi = float(max(phi_min, phi_max))

    intervals: list[list[float]] = []
    for k in range(k_start, k_end + 1):
        e_start = k + phi_lo
        e_end = k + phi_hi
        t_start = float(
            jd_from_continuous_cycle(e_start, period, epoch_jd, oc_a, oc_b, oc_c)
        )
        t_end = float(
            jd_from_continuous_cycle(e_end, period, epoch_jd, oc_a, oc_b, oc_c)
        )
        seg_lo = min(t_start, t_end)
        seg_hi = max(t_start, t_end)
        actual_start = max(seg_lo, lo_jd)
        actual_end = min(seg_hi, hi_jd)
        if actual_end > actual_start:
            intervals.append([round(actual_start, 6), round(actual_end, 6)])
    return intervals


def get_intervals_from_phase_quadratic(
    json_str: str,
    phi_min: float,
    phi_max: float,
    period: float,
    epoch_jd: float,
    oc_a: float,
    oc_b: float,
    oc_c: float,
    observation_jd_bounds: tuple[float, float] | None = None,
) -> list[list[float]]:
    """Builds JD interval rows from a phase selection and transport JSON span.

    Args:
        json_str (str): Serialised light curve transport.
        phi_min (float): Lower phase bound.
        phi_max (float): Upper phase bound.
        period (float): Reference period ``P_0``.
        epoch_jd (float): Reference epoch ``T_0``.
        oc_a (float): Quadratic O-C coefficient.
        oc_b (float): Linear O-C coefficient.
        oc_c (float): Constant O-C offset.
        observation_jd_bounds (tuple, optional): Working-range clip in absolute JD.

    Returns:
        list: JD interval pairs clipped to the effective observation window.
    """
    jd_start, jd_end = get_jd_limits(json_str)
    if observation_jd_bounds is not None:
        w0, w1 = sorted(observation_jd_bounds)
        jd_start = max(jd_start, w0)
        jd_end = min(jd_end, w1)
        if jd_end <= jd_start:
            return []
    return get_intervals_from_quadratic_phase(
        jd_start,
        jd_end,
        phi_min,
        phi_max,
        period,
        epoch_jd,
        oc_a,
        oc_b,
        oc_c,
    )
