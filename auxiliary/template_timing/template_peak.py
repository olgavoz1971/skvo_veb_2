"""Rules for choosing the timing peak on a folded GP template."""

from __future__ import annotations

import logging

import numpy as np
from scipy.signal import argrelmax, argrelmin

logger = logging.getLogger(__name__)


def _local_extrema_tau(
    tau: np.ndarray,
    mu: np.ndarray,
    *,
    extrema_mode: str,
    order: int,
) -> list[tuple[float, float]]:
    """Return ``(tau, mu)`` at each local extremum of the template mean."""
    if extrema_mode == "max":
        idx = argrelmax(mu, order=order)[0]
    else:
        idx = argrelmin(mu, order=order)[0]
    return [(float(tau[i]), float(mu[i])) for i in idx]


def select_template_peak_tau(
    tau: np.ndarray,
    mu: np.ndarray,
    period: float,
    *,
    extended_fold: bool,
    extrema_mode: str = "max",
    local_order: int = 20,
    period_pair_tol: float = 0.15,
    min_prominence_frac: float = 0.5,
) -> float:
    """Choose ``tau_peak`` for timing; extended fold prefers the primary lobe near tau=0.

    When ``extended_fold`` is true and two candidate peaks are separated by roughly
    one period, they are treated as duplicate lobes from the phi+1 copy; the peak
    nearer ``tau=0`` (phase 0) is selected. Otherwise, among prominent local extrema,
    the one closest to ``tau=0`` is used. If no local extrema pass the prominence cut,
    falls back to the global extremum on the grid.

    Args:
        tau (numpy.ndarray): Template grid in days (phase fold coordinate).
        mu (numpy.ndarray): GP mean on ``tau``.
        period (float): Period in days (duplicate-lobe separation).
        extended_fold (bool): Whether Step 1 used the extended phi+1 stack.
        extrema_mode (str): ``max`` or ``min``.
        local_order (int): ``argrelmax`` neighbourhood (grid points).
        period_pair_tol (float): Allowed fractional deviation from ``period`` for pairs.
        min_prominence_frac (float): Local extrema below this fraction of global
            extremum magnitude are ignored (edge artefacts).

    Returns:
        float: Selected ``tau_peak`` in days.
    """
    tau = np.asarray(tau, dtype=float)
    mu = np.asarray(mu, dtype=float)
    if extrema_mode == "max":
        global_val = float(np.max(mu))
        sign = 1.0
    else:
        global_val = float(np.min(mu))
        sign = -1.0

    candidates = _local_extrema_tau(tau, mu, extrema_mode=extrema_mode, order=local_order)
    if extrema_mode == "min":
        candidates = [(t, v) for t, v in candidates if sign * v <= sign * global_val * (2 - min_prominence_frac)]
    else:
        floor = min_prominence_frac * global_val
        candidates = [(t, v) for t, v in candidates if v >= floor]

    if not candidates:
        idx = int(np.argmax(mu)) if extrema_mode == "max" else int(np.argmin(mu))
        logger.warning("no prominent local peaks; using global extremum on grid")
        return float(tau[idx])

    if extended_fold and len(candidates) >= 2:
        tol = period_pair_tol * period
        if extrema_mode == "max":
            strong = [(t, v) for t, v in candidates if v >= 0.9 * global_val]
        else:
            strong = [(t, v) for t, v in candidates if v <= 0.9 * global_val]
        search = strong if len(strong) >= 2 else candidates
        for i, (t1, m1) in enumerate(search):
            for t2, m2 in search[i + 1 :]:
                if abs(abs(t2 - t1) - period) > tol:
                    continue
                if extrema_mode == "max" and min(m1, m2) < 0.85 * global_val:
                    continue
                chosen = t1 if abs(t1) < abs(t2) else t2
                logger.info(
                    "extended-fold peak pair at tau=%.5f and %.5f; chose primary %.5f",
                    t1,
                    t2,
                    chosen,
                )
                return chosen

    chosen = min(candidates, key=lambda item: abs(item[0]))[0]
    logger.info("selected template peak tau=%.5f (nearest phase 0)", chosen)
    return chosen


def fit_tau_mask(
    tau_peak: float,
    length_scale: float,
    *,
    half_width_factor: float = 2.5,
    min_half_width: float = 0.012,
) -> tuple[float, float]:
    """Working tau interval for Step 2 centred on ``tau_peak``."""
    half = max(half_width_factor * length_scale, min_half_width)
    return tau_peak - half, tau_peak + half
