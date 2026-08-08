"""Estimate timing uncertainty from fit RMS and local template slope."""

from __future__ import annotations

import numpy as np

from template_fit import ShiftFitResult, TemplateCurve


def template_mu_slope_at_tau(curve: TemplateCurve, tau: float, *, eps: float = 1e-6) -> float:
    """Central finite difference of ``mu(tau)`` on the template spline."""
    tau_q = np.array([tau - eps, tau + eps], dtype=float)
    mu = curve.eval(tau_q)
    if not np.all(np.isfinite(mu)):
        raise ValueError(f"template gradient undefined at tau={tau}")
    return float((mu[1] - mu[0]) / (2.0 * eps))


def sigma_t_max_rms_slope(
    curve: TemplateCurve,
    fit: ShiftFitResult,
    *,
    tau_peak: float,
) -> float:
    """Map normalised RMS to ``sigma_t_max`` (days) via ``|d mu / d tau|`` at the peak.

    For ``y ≈ s·T + b``, ``sigma_tau ≈ rms / (|s| · |dT/dtau|)``; ``t_max`` shifts linearly
    with ``delta_tau``.
    """
    tau_at_peak = tau_peak + fit.delta_tau
    slope = template_mu_slope_at_tau(curve, tau_at_peak)
    denom = abs(fit.scale * slope)
    if denom <= 0:
        raise ValueError("cannot estimate sigma_t_max: zero template slope at peak")
    return float(fit.rms / denom)
