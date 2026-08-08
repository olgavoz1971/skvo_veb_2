"""Template shift + offset fits in fold-time ``tau`` (cross-correlation and NLS)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.optimize import minimize
from scipy.stats import median_abs_deviation

from fold_stack import observation_tau, t_max_from_delta_tau_at_anchor

logger = logging.getLogger(__name__)


@dataclass
class EphemerisContext:
    """Local fold context for mapping ``delta_tau`` to calendar time near one interval."""

    t_ref: float
    period: float
    tau_peak: float
    t_anchor: float

    def t_max_from_delta_tau(self, delta_tau: float) -> float:
        """Calendar time of template peak after shift ``delta_tau`` (days in ``tau``)."""
        return t_max_from_delta_tau_at_anchor(
            delta_tau,
            t_anchor=self.t_anchor,
            t_ref=self.t_ref,
            period=self.period,
            tau_peak=self.tau_peak,
        )


@dataclass
class ShiftFitResult:
    """Outcome of a template alignment (shift, optional scale, offset)."""

    delta_tau: float
    delta_y: float
    t_max: float
    rms: float
    n_used: int
    method: str
    scale: float = 1.0
    inlier_mask: np.ndarray | None = field(default=None)


class TemplateCurve:
    """GP template mean ``mu(tau)`` with cubic interpolation."""

    def __init__(self, tau: np.ndarray, mu: np.ndarray, tau_peak: float) -> None:
        order = np.argsort(tau)
        tau = np.asarray(tau, dtype=float)[order]
        mu = np.asarray(mu, dtype=float)[order]
        if len(tau) < 4:
            raise ValueError("template grid too small for cubic spline")
        self.tau = tau
        self.tau_min = float(tau[0])
        self.tau_max = float(tau[-1])
        self.tau_peak = float(tau_peak)
        self._spline = CubicSpline(tau, mu, extrapolate=False)

    def eval(self, tau_query: np.ndarray) -> np.ndarray:
        """Evaluate template; out-of-grid points are NaN."""
        return np.asarray(self._spline(np.asarray(tau_query, dtype=float)), dtype=float)


def _active_mask_tau(
    tau_obs: np.ndarray,
    delta_tau: float,
    tau_mask_min: float,
    tau_mask_max: float,
) -> np.ndarray:
    tau = tau_obs - delta_tau
    return (tau >= tau_mask_min) & (tau <= tau_mask_max)


def _subset_indices_at_shift(
    template: TemplateCurve,
    tau_obs: np.ndarray,
    y: np.ndarray,
    delta_tau: float,
    tau_mask_min: float,
    tau_mask_max: float,
    keep: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Global indices, data, and template values used at ``delta_tau``."""
    base = keep & _active_mask_tau(tau_obs, delta_tau, tau_mask_min, tau_mask_max)
    global_idx = np.flatnonzero(base)
    tau_q = tau_obs[base] - delta_tau
    y_m = y[base]
    t_vals = template.eval(tau_q)
    ok = np.isfinite(t_vals)
    return global_idx[ok], y_m[ok], t_vals[ok]


def _subset_at_shift(
    template: TemplateCurve,
    tau_obs: np.ndarray,
    y: np.ndarray,
    delta_tau: float,
    tau_mask_min: float,
    tau_mask_max: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Data and template values used at ``delta_tau``."""
    mask = _active_mask_tau(tau_obs, delta_tau, tau_mask_min, tau_mask_max)
    tau_q = tau_obs[mask] - delta_tau
    y_m = y[mask]
    t_vals = template.eval(tau_q)
    ok = np.isfinite(t_vals)
    return tau_obs[mask][ok], y_m[ok], t_vals[ok]


def fit_cross_correlation(
    template: TemplateCurve,
    tau_obs: np.ndarray,
    y: np.ndarray,
    ephem: EphemerisContext,
    *,
    tau_mask_min: float,
    tau_mask_max: float,
    delta_tau_min: float,
    delta_tau_max: float,
    n_grid: int = 401,
) -> ShiftFitResult:
    """Grid search on ``delta_tau`` with demeaned correlation; then ``delta_y``."""
    if delta_tau_max <= delta_tau_min:
        raise ValueError("delta_tau search bounds invalid")

    grid = np.linspace(delta_tau_min, delta_tau_max, n_grid)
    best_score = -np.inf
    best_dtau = float(grid[0])
    best_n = 0

    for delta_tau in grid:
        mask = _active_mask_tau(tau_obs, delta_tau, tau_mask_min, tau_mask_max)
        tau_q = tau_obs[mask] - delta_tau
        t_vals = template.eval(tau_q)
        ok = np.isfinite(t_vals)
        if np.count_nonzero(ok) < 5:
            continue
        y_m = y[mask][ok]
        t_m = t_vals[ok]
        y_c = y_m - np.mean(y_m)
        t_c = t_m - np.mean(t_m)
        denom = np.sqrt(np.sum(y_c**2) * np.sum(t_c**2))
        if denom <= 0:
            continue
        score = float(np.sum(y_c * t_c) / denom)
        if score > best_score:
            best_score = score
            best_dtau = float(delta_tau)
            best_n = int(np.count_nonzero(ok))

    if best_n < 5:
        raise ValueError("cross-correlation: too few points in tau mask for all shifts")

    _, y_fit, t_fit = _subset_at_shift(
        template, tau_obs, y, best_dtau, tau_mask_min, tau_mask_max
    )
    delta_y = float(np.mean(y_fit - t_fit))
    resid = y_fit - t_fit - delta_y
    rms = float(np.sqrt(np.mean(resid**2)))

    return ShiftFitResult(
        delta_tau=best_dtau,
        delta_y=delta_y,
        t_max=ephem.t_max_from_delta_tau(best_dtau),
        rms=rms,
        n_used=best_n,
        method="cc",
    )


def fit_nonlinear_least_squares(
    template: TemplateCurve,
    tau_obs: np.ndarray,
    y: np.ndarray,
    ephem: EphemerisContext,
    *,
    tau_mask_min: float,
    tau_mask_max: float,
    delta_tau_min: float,
    delta_tau_max: float,
    delta_tau_init: float | None = None,
    keep: np.ndarray | None = None,
    method_label: str = "nls",
    fit_scale: bool = False,
    scale_min: float = 0.05,
    scale_max: float = 5.0,
    scale_init: float | None = None,
) -> ShiftFitResult:
    """Minimise chi-squared in ``delta_tau``, ``delta_y``, and optionally ``scale``."""

    tau_work = tau_obs if keep is None else tau_obs[keep]
    y_work = y if keep is None else y[keep]

    dtau0 = float(
        delta_tau_init
        if delta_tau_init is not None
        else 0.5 * (delta_tau_min + delta_tau_max)
    )
    s0 = float(scale_init if scale_init is not None else 1.0)

    def chi2(params: np.ndarray) -> float:
        delta_tau = float(params[0])
        delta_y = float(params[1])
        scale = float(params[2]) if fit_scale else 1.0
        _, y_used, t_fit = _subset_at_shift(
            template, tau_work, y_work, delta_tau, tau_mask_min, tau_mask_max
        )
        if len(y_used) < 5:
            return 1e12
        resid = y_used - scale * t_fit - delta_y
        return float(np.sum(resid**2))

    if fit_scale:
        x0 = np.array([dtau0, 0.0, s0])
        bounds = [(delta_tau_min, delta_tau_max), (None, None), (scale_min, scale_max)]
    else:
        x0 = np.array([dtau0, 0.0])
        bounds = [(delta_tau_min, delta_tau_max), (None, None)]

    def chi2_two(p: np.ndarray) -> float:
        return chi2(np.array([p[0], p[1], 1.0]))

    objective = chi2 if fit_scale else chi2_two
    result = minimize(
        objective,
        x0=x0 if fit_scale else x0[:2],
        bounds=bounds,
        method="L-BFGS-B",
    )
    if fit_scale:
        delta_tau, delta_y, scale = float(result.x[0]), float(result.x[1]), float(result.x[2])
    else:
        delta_tau, delta_y, scale = float(result.x[0]), float(result.x[1]), 1.0
    _, y_used, t_fit = _subset_at_shift(
        template, tau_work, y_work, delta_tau, tau_mask_min, tau_mask_max
    )
    resid = y_used - scale * t_fit - delta_y
    rms = float(np.sqrt(np.mean(resid**2))) if len(resid) else float("nan")

    inlier_full = None
    if keep is not None:
        inlier_full = keep.copy()

    return ShiftFitResult(
        delta_tau=delta_tau,
        delta_y=delta_y,
        t_max=ephem.t_max_from_delta_tau(delta_tau),
        rms=rms,
        n_used=len(y_used),
        method=method_label,
        scale=scale,
        inlier_mask=inlier_full,
    )


def fit_nls_scale_iterative_outlier_clean(
    template: TemplateCurve,
    tau_obs: np.ndarray,
    y: np.ndarray,
    ephem: EphemerisContext,
    *,
    tau_mask_min: float,
    tau_mask_max: float,
    delta_tau_min: float,
    delta_tau_max: float,
    delta_tau_init: float | None = None,
    scale_init: float | None = None,
    mad_k: float = 3.0,
    max_iter: int = 8,
    min_inliers: int = 8,
    scale_min: float = 0.05,
    scale_max: float = 5.0,
) -> ShiftFitResult:
    """NLS with ``scale``, iterative MAD outlier rejection."""
    keep = np.ones(len(y), dtype=bool)
    fit = fit_nonlinear_least_squares(
        template,
        tau_obs,
        y,
        ephem,
        tau_mask_min=tau_mask_min,
        tau_mask_max=tau_mask_max,
        delta_tau_min=delta_tau_min,
        delta_tau_max=delta_tau_max,
        delta_tau_init=delta_tau_init,
        scale_init=scale_init,
        keep=keep,
        method_label="nls_scale_clean",
        fit_scale=True,
        scale_min=scale_min,
        scale_max=scale_max,
    )

    for iteration in range(max_iter):
        global_idx, y_sub, t_sub = _subset_indices_at_shift(
            template,
            tau_obs,
            y,
            fit.delta_tau,
            tau_mask_min,
            tau_mask_max,
            keep,
        )
        if len(y_sub) < min_inliers:
            break
        resid = y_sub - fit.scale * t_sub - fit.delta_y
        mad = float(median_abs_deviation(resid, scale="normal"))
        if mad <= 0:
            mad = float(np.std(resid)) if np.std(resid) > 0 else 1e-9
        threshold = mad_k * mad
        bad_local = np.abs(resid) > threshold
        if not np.any(bad_local):
            break
        bad_global = global_idx[bad_local]
        keep[bad_global] = False
        if np.count_nonzero(keep) < min_inliers:
            keep[bad_global] = True
            break
        logger.info(
            "nls_scale_clean iter %s: rejected %s point(s), %s inliers left",
            iteration + 1,
            int(np.count_nonzero(bad_local)),
            int(np.count_nonzero(keep)),
        )
        fit = fit_nonlinear_least_squares(
            template,
            tau_obs,
            y,
            ephem,
            tau_mask_min=tau_mask_min,
            tau_mask_max=tau_mask_max,
            delta_tau_min=delta_tau_min,
            delta_tau_max=delta_tau_max,
            delta_tau_init=fit.delta_tau,
            scale_init=fit.scale,
            keep=keep,
            method_label="nls_scale_clean",
            fit_scale=True,
            scale_min=scale_min,
            scale_max=scale_max,
        )

    fit.inlier_mask = keep
    return fit


def fit_nls_iterative_outlier_clean(
    template: TemplateCurve,
    tau_obs: np.ndarray,
    y: np.ndarray,
    ephem: EphemerisContext,
    *,
    tau_mask_min: float,
    tau_mask_max: float,
    delta_tau_min: float,
    delta_tau_max: float,
    delta_tau_init: float | None = None,
    mad_k: float = 3.0,
    max_iter: int = 8,
    min_inliers: int = 8,
) -> ShiftFitResult:
    """NLS with iterative MAD rejection of outliers on normalised residuals."""
    keep = np.ones(len(y), dtype=bool)
    fit = fit_nonlinear_least_squares(
        template,
        tau_obs,
        y,
        ephem,
        tau_mask_min=tau_mask_min,
        tau_mask_max=tau_mask_max,
        delta_tau_min=delta_tau_min,
        delta_tau_max=delta_tau_max,
        delta_tau_init=delta_tau_init,
        keep=keep,
        method_label="nls_clean",
    )

    for iteration in range(max_iter):
        global_idx, y_sub, t_sub = _subset_indices_at_shift(
            template,
            tau_obs,
            y,
            fit.delta_tau,
            tau_mask_min,
            tau_mask_max,
            keep,
        )
        if len(y_sub) < min_inliers:
            break
        resid = y_sub - t_sub - fit.delta_y
        mad = float(median_abs_deviation(resid, scale="normal"))
        if mad <= 0:
            mad = float(np.std(resid)) if np.std(resid) > 0 else 1e-9
        threshold = mad_k * mad
        bad_local = np.abs(resid) > threshold
        if not np.any(bad_local):
            break
        bad_global = global_idx[bad_local]
        keep[bad_global] = False
        if np.count_nonzero(keep) < min_inliers:
            keep[bad_global] = True
            break
        logger.info(
            "nls_clean iter %s: rejected %s point(s), %s inliers left",
            iteration + 1,
            int(np.count_nonzero(bad_local)),
            int(np.count_nonzero(keep)),
        )
        fit = fit_nonlinear_least_squares(
            template,
            tau_obs,
            y,
            ephem,
            tau_mask_min=tau_mask_min,
            tau_mask_max=tau_mask_max,
            delta_tau_min=delta_tau_min,
            delta_tau_max=delta_tau_max,
            delta_tau_init=fit.delta_tau,
            keep=keep,
            method_label="nls_clean",
        )

    fit.inlier_mask = keep
    return fit
