"""Estimate timing uncertainty from fit RMS and local template slope."""

from __future__ import annotations

import numpy as np

from template_fit import ShiftFitResult, TemplateCurve


def template_mu_slope_at_peak(curve: TemplateCurve, *, eps: float = 1e-6) -> float:
    """Central finite difference of ``mu`` vs days from peak at ``dt=0``."""
    dt_q = np.array([-eps, eps], dtype=float)
    mu = curve.eval_from_peak(dt_q)
    if not np.all(np.isfinite(mu)):
        raise ValueError("template gradient undefined at peak (dt=0)")
    return float((mu[1] - mu[0]) / (2.0 * eps))


def sigma_t_max_rms_slope(
    curve: TemplateCurve,
    fit: ShiftFitResult,
) -> float:
    """Map normalised RMS to ``sigma_t_max`` (days) via ``|d mu / d t|`` at the peak.

    For ``y ≈ s·T + b``, ``sigma_t_max ≈ rms / (|s| · |dT/dt|)`` at the fitted maximum.
    Returns NaN when the fit has no finite RMS or scale (a failed method).
    """
    if not np.isfinite(fit.rms) or not np.isfinite(fit.scale):
        return float("nan")
    slope = template_mu_slope_at_peak(curve)
    denom = abs(fit.scale * slope)
    if denom <= 0:
        raise ValueError("cannot estimate sigma_t_max: zero template slope at peak")
    return float(fit.rms / denom)
