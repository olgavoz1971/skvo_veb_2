"""Linear period/epoch correction from a selected part of a Step 1 O-C."""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
from astropy.modeling import fitting, models

logger = logging.getLogger(__name__)

PERIOD_CORRECT_MAX_ITER = 5
PERIOD_CORRECT_TOL = 1e-8
FIT_RANGE_DISABLED: dict[str, Any] = {"enabled": False}


def cycle_range_from_relayout(relayout_data: dict | None) -> tuple[float, float]:
    """Reads the visible cycle-number window from O-C graph relayout data.

    Args:
        relayout_data (dict | None): Plotly ``relayoutData`` from ``oc-graph``.

    Returns:
        tuple[float, float]: Inclusive ``(e_lo, e_hi)`` in cycle number.

    Raises:
        ValueError: If the axes are not zoomed to a finite cycle range.
    """
    if not relayout_data:
        raise ValueError("Zoom the O-C before using the visible range.")
    if relayout_data.get("xaxis.autorange") is True:
        raise ValueError("Zoom the O-C before using the visible range.")
    if relayout_data.get("xaxis2.autorange") is True:
        raise ValueError("Zoom the O-C before using the visible range.")

    left = relayout_data.get("xaxis.range[0]")
    right = relayout_data.get("xaxis.range[1]")
    if left is None or right is None:
        pair = relayout_data.get("xaxis.range")
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            left, right = pair[0], pair[1]
    if left is None or right is None:
        left = relayout_data.get("xaxis2.range[0]")
        right = relayout_data.get("xaxis2.range[1]")
    if left is None or right is None:
        pair = relayout_data.get("xaxis2.range")
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            left, right = pair[0], pair[1]
    if left is None or right is None:
        raise ValueError("Zoom the O-C before using the visible range.")
    e_lo = float(left)
    e_hi = float(right)
    if not math.isfinite(e_lo) or not math.isfinite(e_hi):
        raise ValueError("Visible cycle range is not finite.")
    if e_lo > e_hi:
        e_lo, e_hi = e_hi, e_lo
    return e_lo, e_hi


def build_fit_range_store(e_min: float, e_max: float) -> dict[str, Any]:
    """Builds the client store payload for an O-C cycle fit window.

    Args:
        e_min (float): Inclusive lower cycle bound.
        e_max (float): Inclusive upper cycle bound.

    Returns:
        dict: JSON-safe ``enabled`` / ``e_min`` / ``e_max`` payload.
    """
    lo = float(e_min)
    hi = float(e_max)
    if lo > hi:
        lo, hi = hi, lo
    return {"enabled": True, "e_min": lo, "e_max": hi}


def normalize_fit_range(store_data: dict | None) -> tuple[float, float] | None:
    """Returns ``(e_min, e_max)`` when a fit window is enabled.

    Args:
        store_data (dict | None): ``store-oc-fit-range`` payload.

    Returns:
        tuple[float, float] | None: Inclusive cycle window, or ``None`` for full O-C.
    """
    if not store_data or not store_data.get("enabled"):
        return None
    e_min = float(store_data["e_min"])
    e_max = float(store_data["e_max"])
    if e_min > e_max:
        e_min, e_max = e_max, e_min
    return e_min, e_max


def mask_by_cycle_range(
    cycle_e: np.ndarray,
    e_min: float | None,
    e_max: float | None,
) -> np.ndarray:
    """Boolean mask of points whose cycle number lies in ``[e_min, e_max]``.

    Args:
        cycle_e (numpy.ndarray): Cycle numbers.
        e_min (float | None): Inclusive lower bound; ``None`` keeps every point.
        e_max (float | None): Inclusive upper bound; ``None`` keeps every point.

    Returns:
        numpy.ndarray: Boolean mask, same length as ``cycle_e``.
    """
    cycle_e = np.asarray(cycle_e, dtype=float)
    if e_min is None or e_max is None:
        return np.ones(cycle_e.shape, dtype=bool)
    lo = float(e_min)
    hi = float(e_max)
    if lo > hi:
        lo, hi = hi, lo
    return (cycle_e >= lo) & (cycle_e <= hi)


def inverse_variance_weights(sigma: np.ndarray | None) -> np.ndarray | None:
    """Weights for ``LinearLSQFitter`` so the fit is inverse-variance.

    Astropy multiplies the design matrix and the data by ``weights`` once, so
    ``weights = 1/σ`` minimises ``Σ ((O-C)/σ)²``.

    Args:
        sigma (numpy.ndarray | None): Timing uncertainties (days).

    Returns:
        numpy.ndarray | None: ``1/σ`` per point, or ``None`` for an unweighted fit.

    Raises:
        ValueError: If finite and non-finite σ are mixed, or a finite σ is not
            positive.
    """
    if sigma is None:
        return None
    sigma_arr = np.asarray(sigma, dtype=float)
    finite = np.isfinite(sigma_arr)
    if not np.any(finite):
        return None
    if not np.all(finite):
        raise ValueError(
            "Cannot mix points with and without finite timing σ in the fit window."
        )
    if np.any(sigma_arr <= 0.0):
        raise ValueError("Timing σ must be positive for a weighted fit.")
    return 1.0 / sigma_arr


def fit_linear_oc(
    x: np.ndarray,
    oc: np.ndarray,
    sigma: np.ndarray | None = None,
) -> tuple[float, float]:
    """Fits ``O-C ≈ intercept + slope * x`` with Astropy ``Linear1D``.

    Args:
        x (numpy.ndarray): Independent variable (centred JD or cycle number).
        oc (numpy.ndarray): O-C residuals (days).
        sigma (numpy.ndarray | None): Timing σ for inverse-variance weights.

    Returns:
        tuple[float, float]: ``(slope, intercept)``.

    Raises:
        ValueError: If fewer than two points are supplied, or weighting fails.
    """
    x_arr = np.asarray(x, dtype=float)
    oc_arr = np.asarray(oc, dtype=float)
    if x_arr.size < 2:
        raise ValueError("Need at least 2 O-C points for a linear fit.")
    weights = inverse_variance_weights(sigma)
    line = models.Linear1D()
    fitter = fitting.LinearLSQFitter()
    if weights is not None:
        fitted = fitter(line, x_arr, oc_arr, weights=weights)
    else:
        fitted = fitter(line, x_arr, oc_arr)
    return float(fitted.slope.value), float(fitted.intercept.value)


def correct_period_from_oc_payload(
    payload: dict,
    *,
    e_min: float | None = None,
    e_max: float | None = None,
    max_iter: int = PERIOD_CORRECT_MAX_ITER,
    tol: float = PERIOD_CORRECT_TOL,
) -> dict[str, Any]:
    """Corrects trial ``P`` and ``T0`` from a linear O-C segment.

    Cycle numbers stay fixed. Each iteration refits O-C versus observed JD
    (JD centred at the window mean) and applies ``P ← P / (1 - S)``, then
    shifts ``T0`` so the mean residual in the window is zero.

    Args:
        payload (dict): ``compute_step1_oc`` arrays and trial ephemeris.
        e_min (float | None): Inclusive lower cycle bound, or ``None`` for all.
        e_max (float | None): Inclusive upper cycle bound, or ``None`` for all.
        max_iter (int): Maximum correction iterations.
        tol (float): Stop when ``|S|`` falls below this value.

    Returns:
        dict: JSON-safe proposed ephemeris, diagnostics, and overlay samples.

    Raises:
        ValueError: If there is no plot, fewer than two points in range, or
            ``|S| ≥ 1``.
    """
    if not payload:
        raise ValueError("Plot the O-C first.")
    cycle_e = np.asarray(payload["E"], dtype=float)
    jd_ext = np.asarray(payload["jd_ext"], dtype=float)
    oc_trial = np.asarray(payload["OC"], dtype=float)
    sigma_jd = np.asarray(payload["sigma_jd"], dtype=float)
    p_trial = float(payload["p0"])
    t0_trial = float(payload["t0_jd"])
    if not math.isfinite(p_trial) or p_trial <= 0.0:
        raise ValueError("Trial period P must be a positive finite number of days.")
    if not math.isfinite(t0_trial):
        raise ValueError("Trial epoch T0 must be a finite Julian Date.")

    mask = mask_by_cycle_range(cycle_e, e_min, e_max)
    n_points = int(np.count_nonzero(mask))
    if n_points < 2:
        raise ValueError(
            f"Need at least 2 O-C points in the fit range, got {n_points}."
        )

    jd_seg = jd_ext[mask]
    e_seg = cycle_e[mask]
    if np.unique(e_seg).size < 2:
        raise ValueError(
            "Need at least 2 distinct cycle numbers in the fit range."
        )
    oc_seg_trial = oc_trial[mask]
    sigma_seg = sigma_jd[mask]
    e_lo = float(np.min(e_seg) if e_min is None else e_min)
    e_hi = float(np.max(e_seg) if e_max is None else e_max)
    if e_lo > e_hi:
        e_lo, e_hi = e_hi, e_lo

    p_work = p_trial
    t0_work = t0_trial
    slope = float("nan")
    intercept_jd = float("nan")
    n_iter = 0
    jd_ref = float(np.mean(jd_seg))

    for n_iter in range(1, max_iter + 1):
        oc_seg = jd_seg - t0_work - e_seg * p_work
        slope, intercept_jd = fit_linear_oc(jd_seg - jd_ref, oc_seg, sigma_seg)
        if not math.isfinite(slope):
            raise ValueError("Linear O-C versus JD fit did not return a finite slope.")
        denom = 1.0 - slope
        if abs(slope) >= 1.0 or not math.isfinite(denom) or denom == 0.0:
            raise ValueError(
                f"|S| = {slope:.6g} is ≥ 1; P / (1 − S) is not defined."
            )
        p_work = p_work / denom
        if not math.isfinite(p_work) or p_work <= 0.0:
            raise ValueError("Corrected period is not a positive finite number of days.")
        oc_after_p = jd_seg - t0_work - e_seg * p_work
        t0_work = t0_work + float(np.mean(oc_after_p))
        logger.info(
            "O-C period correct iter %s: S=%.3e P=%.10f T0=%.6f",
            n_iter,
            slope,
            p_work,
            t0_work,
        )
        if abs(slope) < tol:
            break

    oc_final = jd_seg - t0_work - e_seg * p_work
    rms = float(np.sqrt(np.mean(oc_final**2)))
    slope_e, intercept_e = fit_linear_oc(e_seg, oc_seg_trial, sigma_seg)
    line_oc_lo = intercept_e + slope_e * e_lo
    line_oc_hi = intercept_e + slope_e * e_hi
    result = {
        "n_points": n_points,
        "n_iter": int(n_iter),
        "slope_oc_vs_jd": float(slope),
        "intercept_oc_vs_jd": float(intercept_jd),
        "slope_oc_vs_e": float(slope_e),
        "intercept_oc_vs_e": float(intercept_e),
        "p_trial": p_trial,
        "p_corrected": float(p_work),
        "t0_trial_jd": t0_trial,
        "t0_corrected_jd": float(t0_work),
        "delta_p": float(p_work - p_trial),
        "rms_d": rms,
        "e_min": e_lo,
        "e_max": e_hi,
        "line_e": [e_lo, e_hi],
        "line_oc": [float(line_oc_lo), float(line_oc_hi)],
    }
    logger.info(
        "O-C period correct: N=%s S=%.3e P=%.10f (ΔP=%+.3e) T0=%.6f RMS=%.6f d",
        n_points,
        slope,
        p_work,
        result["delta_p"],
        t0_work,
        rms,
    )
    return result
