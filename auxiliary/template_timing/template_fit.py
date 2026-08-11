"""Template fit in calendar time: slide peak-centred shape along the LC time axis."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.optimize import minimize
from scipy.stats import median_abs_deviation

logger = logging.getLogger(__name__)


@dataclass
class IntervalFitContext:
    """Anchor time within the interval; peak time is ``t_anchor + delta_t``."""

    t_anchor: float

    def t_max_from_delta_t(self, delta_t: float) -> float:
        """Calendar time of template peak (same units as the light curve)."""
        return float(self.t_anchor + delta_t)


@dataclass
class ShiftFitResult:
    """Outcome of a template alignment in time domain."""

    delta_t: float
    delta_y: float
    t_max: float
    rms: float
    n_used: int
    method: str
    scale: float = 1.0
    inlier_mask: np.ndarray | None = field(default=None)


class TemplateCurve:
    """GP template ``mu`` on the Step 1 fold grid, evaluated vs days from the peak.

    The stored grid extends a little beyond the folded photometry so that the GP
    mean stays smooth at the ends. That pad is extrapolation, so the curve is
    defined only inside ``[tau_data_min, tau_data_max]``: queries outside return
    NaN and callers drop those points instead of fitting against invented shape.
    """

    def __init__(
        self,
        tau: np.ndarray,
        mu: np.ndarray,
        tau_peak: float,
        *,
        tau_data_min: float,
        tau_data_max: float,
    ) -> None:
        """Build the interpolator.

        Args:
            tau (numpy.ndarray): Fold grid in days, including the pad.
            mu (numpy.ndarray): GP mean on ``tau``.
            tau_peak (float): Fold coordinate of the timed extremum.
            tau_data_min (float): Lowest ``tau`` covered by folded photometry.
            tau_data_max (float): Highest ``tau`` covered by folded photometry.

        Raises:
            ValueError: If the grid is too short or the data range is empty.
        """
        order = np.argsort(tau)
        tau = np.asarray(tau, dtype=float)[order]
        mu = np.asarray(mu, dtype=float)[order]
        if len(tau) < 4:
            raise ValueError("template grid too small for cubic spline")
        if tau_data_max <= tau_data_min:
            raise ValueError(
                f"empty template data range [{tau_data_min}, {tau_data_max}]"
            )
        self.tau = tau
        self.tau_min = float(max(tau[0], tau_data_min))
        self.tau_max = float(min(tau[-1], tau_data_max))
        self.tau_peak = float(tau_peak)
        self._spline = CubicSpline(tau, mu, extrapolate=False)

    def eval(self, tau_query: np.ndarray) -> np.ndarray:
        """Evaluate the template; outside the photometric support this is NaN."""
        q = np.asarray(tau_query, dtype=float)
        values = np.asarray(self._spline(q), dtype=float)
        return np.where((q >= self.tau_min) & (q <= self.tau_max), values, np.nan)

    def eval_from_peak(self, dt: np.ndarray | float) -> np.ndarray:
        """Evaluate ``mu`` at ``dt`` days from template maximum (peak at ``dt=0``)."""
        return self.eval(np.asarray(dt, dtype=float) + self.tau_peak)


def _active_mask_time(
    t_jd: np.ndarray,
    t_anchor: float,
    delta_t: float,
    dt_min: float,
    dt_max: float,
) -> np.ndarray:
    """Points whose template abscissa ``t - t_max`` lies in the fit mask."""
    t_max = t_anchor + delta_t
    dt = t_jd - t_max
    return (dt >= dt_min) & (dt <= dt_max)


def _subset_indices_at_shift(
    template: TemplateCurve,
    t_jd: np.ndarray,
    y: np.ndarray,
    t_anchor: float,
    delta_t: float,
    dt_min: float,
    dt_max: float,
    keep: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Global indices, data, and template values at peak shift ``delta_t``."""
    base = keep & _active_mask_time(t_jd, t_anchor, delta_t, dt_min, dt_max)
    global_idx = np.flatnonzero(base)
    dt = t_jd[base] - (t_anchor + delta_t)
    y_m = y[base]
    t_vals = template.eval_from_peak(dt)
    ok = np.isfinite(t_vals)
    return global_idx[ok], y_m[ok], t_vals[ok]


def _subset_at_shift(
    template: TemplateCurve,
    t_jd: np.ndarray,
    y: np.ndarray,
    t_anchor: float,
    delta_t: float,
    dt_min: float,
    dt_max: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Data and template values used at ``delta_t``."""
    mask = _active_mask_time(t_jd, t_anchor, delta_t, dt_min, dt_max)
    dt = t_jd[mask] - (t_anchor + delta_t)
    y_m = y[mask]
    t_vals = template.eval_from_peak(dt)
    ok = np.isfinite(t_vals)
    return t_jd[mask][ok], y_m[ok], t_vals[ok]


def fit_cross_correlation(
    template: TemplateCurve,
    t_jd: np.ndarray,
    y: np.ndarray,
    ctx: IntervalFitContext,
    *,
    dt_min: float,
    dt_max: float,
    delta_t_min: float,
    delta_t_max: float,
    n_grid: int = 401,
) -> ShiftFitResult:
    """Grid search on peak shift ``delta_t`` (days); then ``delta_y``."""
    if delta_t_max <= delta_t_min:
        raise ValueError("delta_t search bounds invalid")

    grid = np.linspace(delta_t_min, delta_t_max, n_grid)
    best_score = -np.inf
    best_dt = float(grid[0])
    best_n = 0

    for delta_t in grid:
        mask = _active_mask_time(t_jd, ctx.t_anchor, delta_t, dt_min, dt_max)
        dt = t_jd[mask] - (ctx.t_anchor + delta_t)
        t_vals = template.eval_from_peak(dt)
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
            best_dt = float(delta_t)
            best_n = int(np.count_nonzero(ok))

    if best_n < 5:
        raise ValueError("cross-correlation: too few points in mask for all shifts")

    _, y_fit, t_fit = _subset_at_shift(
        template, t_jd, y, ctx.t_anchor, best_dt, dt_min, dt_max
    )
    delta_y = float(np.mean(y_fit - t_fit))
    resid = y_fit - t_fit - delta_y
    rms = float(np.sqrt(np.mean(resid**2)))

    return ShiftFitResult(
        delta_t=best_dt,
        delta_y=delta_y,
        t_max=ctx.t_max_from_delta_t(best_dt),
        rms=rms,
        n_used=best_n,
        method="cc",
    )


def fit_nonlinear_least_squares(
    template: TemplateCurve,
    t_jd: np.ndarray,
    y: np.ndarray,
    ctx: IntervalFitContext,
    *,
    dt_min: float,
    dt_max: float,
    delta_t_min: float,
    delta_t_max: float,
    delta_t_init: float | None = None,
    keep: np.ndarray | None = None,
    method_label: str = "nls",
    fit_scale: bool = False,
    scale_min: float = 0.05,
    scale_max: float = 5.0,
    scale_init: float | None = None,
) -> ShiftFitResult:
    """Minimise chi-squared in peak shift ``delta_t``, ``delta_y``, optional ``scale``."""

    t_work = t_jd if keep is None else t_jd[keep]
    y_work = y if keep is None else y[keep]

    dt0 = float(
        delta_t_init
        if delta_t_init is not None
        else 0.5 * (delta_t_min + delta_t_max)
    )
    s0 = float(scale_init if scale_init is not None else 1.0)

    def chi2(params: np.ndarray) -> float:
        delta_t = float(params[0])
        delta_y = float(params[1])
        scale = float(params[2]) if fit_scale else 1.0
        _, y_used, t_fit = _subset_at_shift(
            template, t_work, y_work, ctx.t_anchor, delta_t, dt_min, dt_max
        )
        if len(y_used) < 5:
            return 1e12
        resid = y_used - scale * t_fit - delta_y
        return float(np.sum(resid**2))

    if fit_scale:
        x0 = np.array([dt0, 0.0, s0])
        bounds = [(delta_t_min, delta_t_max), (None, None), (scale_min, scale_max)]
    else:
        x0 = np.array([dt0, 0.0])
        bounds = [(delta_t_min, delta_t_max), (None, None)]

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
        delta_t, delta_y, scale = float(result.x[0]), float(result.x[1]), float(result.x[2])
    else:
        delta_t, delta_y, scale = float(result.x[0]), float(result.x[1]), 1.0
    _, y_used, t_fit = _subset_at_shift(
        template, t_work, y_work, ctx.t_anchor, delta_t, dt_min, dt_max
    )
    resid = y_used - scale * t_fit - delta_y
    rms = float(np.sqrt(np.mean(resid**2))) if len(resid) else float("nan")

    inlier_full = None
    if keep is not None:
        inlier_full = keep.copy()

    return ShiftFitResult(
        delta_t=delta_t,
        delta_y=delta_y,
        t_max=ctx.t_max_from_delta_t(delta_t),
        rms=rms,
        n_used=len(y_used),
        method=method_label,
        scale=scale,
        inlier_mask=inlier_full,
    )


def fit_nls_scale_iterative_outlier_clean(
    template: TemplateCurve,
    t_jd: np.ndarray,
    y: np.ndarray,
    ctx: IntervalFitContext,
    *,
    dt_min: float,
    dt_max: float,
    delta_t_min: float,
    delta_t_max: float,
    delta_t_init: float | None = None,
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
        t_jd,
        y,
        ctx,
        dt_min=dt_min,
        dt_max=dt_max,
        delta_t_min=delta_t_min,
        delta_t_max=delta_t_max,
        delta_t_init=delta_t_init,
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
            t_jd,
            y,
            ctx.t_anchor,
            fit.delta_t,
            dt_min,
            dt_max,
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
            t_jd,
            y,
            ctx,
            dt_min=dt_min,
            dt_max=dt_max,
            delta_t_min=delta_t_min,
            delta_t_max=delta_t_max,
            delta_t_init=fit.delta_t,
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
    t_jd: np.ndarray,
    y: np.ndarray,
    ctx: IntervalFitContext,
    *,
    dt_min: float,
    dt_max: float,
    delta_t_min: float,
    delta_t_max: float,
    delta_t_init: float | None = None,
    mad_k: float = 3.0,
    max_iter: int = 8,
    min_inliers: int = 8,
) -> ShiftFitResult:
    """NLS with iterative MAD rejection of outliers."""
    keep = np.ones(len(y), dtype=bool)
    fit = fit_nonlinear_least_squares(
        template,
        t_jd,
        y,
        ctx,
        dt_min=dt_min,
        dt_max=dt_max,
        delta_t_min=delta_t_min,
        delta_t_max=delta_t_max,
        delta_t_init=delta_t_init,
        keep=keep,
        method_label="nls_clean",
    )

    for iteration in range(max_iter):
        global_idx, y_sub, t_sub = _subset_indices_at_shift(
            template,
            t_jd,
            y,
            ctx.t_anchor,
            fit.delta_t,
            dt_min,
            dt_max,
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
            t_jd,
            y,
            ctx,
            dt_min=dt_min,
            dt_max=dt_max,
            delta_t_min=delta_t_min,
            delta_t_max=delta_t_max,
            delta_t_init=fit.delta_t,
            keep=keep,
            method_label="nls_clean",
        )

    fit.inlier_mask = keep
    return fit
