"""Bisector-of-chords and Kwee-van Woerden epoch estimates on a GP template."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from astropy.modeling import fitting, models
from scipy.optimize import minimize_scalar

from epoch_config import EXPORT_METHODS, EpochSpikeConfig
from epoch_io import LoadedTemplate, days_to_seconds

logger = logging.getLogger(__name__)


@dataclass
class BisectorLevel:
    """One flux-level chord on the GP mean."""

    depth: float
    flux: float
    tau_left: float
    tau_right: float
    tau_bis: float
    sigma_tau_bis: float


@dataclass
class BisectorResult:
    """Bisector ladder plus core summary."""

    levels: list[BisectorLevel]
    tau_core: float
    sigma_tau_core: float
    tau_extrap_floor: float
    slope_days_per_depth: float


@dataclass
class KvwResult:
    """Kwee-van Woerden minimum on the GP mean."""

    tau: float
    cost_min: float
    n_pairs: int
    tau_parabola: float
    curvature: float
    sigma_tau: float
    scan_tau: np.ndarray
    scan_cost: np.ndarray
    lags: np.ndarray


@dataclass
class EpochSpikeResult:
    """All epoch estimators for one stored template."""

    template: LoadedTemplate
    copy_lo: float
    copy_hi: float
    continuum: float
    bottom: float
    kvw_half_width_days: float
    kvw_search_half_width_days: float
    bisector: BisectorResult
    kvw: KvwResult
    tau_gp_argmin: float

    @property
    def delta_kvw_minus_argmin_s(self) -> float:
        """KvW minus GP-argmin offset in seconds."""
        return days_to_seconds(self.kvw.tau - self.tau_gp_argmin)

    @property
    def delta_bisector_minus_argmin_s(self) -> float:
        """Core bisector minus GP-argmin offset in seconds."""
        return days_to_seconds(self.bisector.tau_core - self.tau_gp_argmin)

    def tau_for_method(self, method: str) -> float:
        """Return the fold epoch for an export method name.

        Args:
            method (str): ``kvw``, ``bisector_core``, or ``bisector_extrap``.

        Returns:
            float: Selected ``tau_peak`` in days.

        Raises:
            ValueError: If ``method`` is not a supported export name.
        """
        if method not in EXPORT_METHODS:
            raise ValueError(
                f"export method must be one of {sorted(EXPORT_METHODS)}, got {method!r}"
            )
        if method == "kvw":
            return self.kvw.tau
        if method == "bisector_core":
            return self.bisector.tau_core
        return self.bisector.tau_extrap_floor


def copy_window(template: LoadedTemplate) -> tuple[float, float]:
    """Isolate one eclipse copy around the stored ``tau_peak``.

    Args:
        template (LoadedTemplate): Loaded GP template.

    Returns:
        tuple[float, float]: Inclusive ``tau`` bounds for the working copy.

    Raises:
        ValueError: If the window is empty after clipping to photometric support.
    """
    half = 0.45 * template.fold_period
    lo = max(template.tau_data_min, template.tau_peak - half)
    hi = min(template.tau_data_max, template.tau_peak + half)
    if hi <= lo:
        raise ValueError(
            f"empty copy window after clipping to data range "
            f"[{template.tau_data_min}, {template.tau_data_max}]"
        )
    return lo, hi


def continuum_and_bottom(
    template: LoadedTemplate,
    *,
    copy_lo: float,
    copy_hi: float,
) -> tuple[float, float]:
    """Measure out-of-eclipse continuum and eclipse extremum on ``mu``.

    Continuum is the 95th percentile of ``mu`` in the data range for minima, or
    the 5th percentile for maxima. The bottom is the extremum of ``mu`` inside
    the isolated copy window.

    Args:
        template (LoadedTemplate): Loaded GP template.
        copy_lo (float): Lower ``tau`` of the isolated copy.
        copy_hi (float): Upper ``tau`` of the isolated copy.

    Returns:
        tuple[float, float]: ``(continuum, bottom)`` in normalised flux.

    Raises:
        ValueError: If the copy has too few points or zero eclipse amplitude.
    """
    in_data = (template.tau >= template.tau_data_min) & (
        template.tau <= template.tau_data_max
    )
    in_copy = (template.tau >= copy_lo) & (template.tau <= copy_hi)
    if int(np.count_nonzero(in_data)) < 8:
        raise ValueError("too few grid points in the photometric data range")
    if int(np.count_nonzero(in_copy)) < 8:
        raise ValueError("too few grid points in the isolated copy window")
    mu_data = template.mu[in_data]
    mu_copy = template.mu[in_copy]
    if template.extrema_mode == "min":
        continuum = float(np.percentile(mu_data, 95))
        bottom = float(np.min(mu_copy))
        if not (bottom < continuum):
            raise ValueError(
                f"minimum template has no eclipse amplitude "
                f"(continuum={continuum}, bottom={bottom})"
            )
    else:
        continuum = float(np.percentile(mu_data, 5))
        bottom = float(np.max(mu_copy))
        if not (bottom > continuum):
            raise ValueError(
                f"maximum template has no eclipse amplitude "
                f"(continuum={continuum}, bottom={bottom})"
            )
    return continuum, bottom


def flux_at_depth(depth: float, *, continuum: float, bottom: float) -> float:
    """Interpolate flux from out-of-eclipse (depth 0) to the extremum (depth 1).

    Args:
        depth (float): Fractional eclipse depth in ``(0, 1)``.
        continuum (float): Out-of-eclipse GP mean.
        bottom (float): GP mean at the eclipse extremum.

    Returns:
        float: GP-mean flux at that depth.
    """
    return continuum + depth * (bottom - continuum)


def _chord_crossings(
    template: LoadedTemplate,
    flux: float,
    *,
    copy_lo: float,
    copy_hi: float,
    centre: float,
) -> tuple[float, float] | None:
    """Return the nearest ingress/egress pair around ``centre`` at ``flux``.

    Roots are restricted to half a period about ``centre`` so an extended-fold
    copy of the neighbouring eclipse cannot supply the outer chord.
    """
    half = 0.25 * template.fold_period
    lo = max(copy_lo, centre - half)
    hi = min(copy_hi, centre + half)
    roots = np.asarray(
        template.mu_spline.solve(flux, extrapolate=False),
        dtype=float,
    )
    roots = roots[np.isfinite(roots)]
    roots = roots[(roots >= lo) & (roots <= hi)]
    left = roots[roots < centre]
    right = roots[roots > centre]
    if left.size == 0 or right.size == 0:
        return None
    return float(np.max(left)), float(np.min(right))


def _sigma_tau_crossing(template: LoadedTemplate, tau_cross: float) -> float:
    """Crossing-time uncertainty from GP sigma and local slope."""
    slope = float(template.dmu_spline(tau_cross))
    sigma_mu = float(template.sigma_spline(tau_cross))
    if not np.isfinite(slope) or not np.isfinite(sigma_mu):
        raise ValueError(f"non-finite spline at crossing tau={tau_cross}")
    if abs(slope) == 0.0:
        raise ValueError(f"zero slope at crossing tau={tau_cross}")
    return abs(sigma_mu / slope)


def compute_bisector(
    template: LoadedTemplate,
    cfg: EpochSpikeConfig,
    *,
    copy_lo: float,
    copy_hi: float,
    continuum: float,
    bottom: float,
    centre: float,
) -> BisectorResult:
    """Build a bisector ladder on the GP mean and summarise the core band.

    Args:
        template (LoadedTemplate): Loaded GP template.
        cfg (EpochSpikeConfig): Depth-band settings.
        copy_lo (float): Lower copy bound.
        copy_hi (float): Upper copy bound.
        continuum (float): Out-of-eclipse flux.
        bottom (float): Extremum flux.
        centre (float): Trial centre used to split ingress and egress.

    Returns:
        BisectorResult: Accepted levels and core / floor-extrapolation epochs.

    Raises:
        ValueError: If too few levels yield a valid outer chord pair.
    """
    depths = np.linspace(cfg.depth_min, cfg.depth_max, cfg.n_levels)
    levels: list[BisectorLevel] = []
    skipped = 0
    for depth in depths:
        flux = flux_at_depth(float(depth), continuum=continuum, bottom=bottom)
        pair = _chord_crossings(
            template,
            flux,
            copy_lo=copy_lo,
            copy_hi=copy_hi,
            centre=centre,
        )
        if pair is None:
            skipped += 1
            logger.warning(
                "bisector depth=%.3f flux=%.5f: no ingress/egress pair in copy window",
                depth,
                flux,
            )
            continue
        tau_left, tau_right = pair
        try:
            sig_left = _sigma_tau_crossing(template, tau_left)
            sig_right = _sigma_tau_crossing(template, tau_right)
        except ValueError as exc:
            skipped += 1
            logger.warning("bisector depth=%.3f skipped: %s", depth, exc)
            continue
        sigma_bis = 0.5 * float(np.sqrt(sig_left**2 + sig_right**2))
        levels.append(
            BisectorLevel(
                depth=float(depth),
                flux=float(flux),
                tau_left=tau_left,
                tau_right=tau_right,
                tau_bis=0.5 * (tau_left + tau_right),
                sigma_tau_bis=sigma_bis,
            )
        )
    if len(levels) < cfg.min_accepted_levels:
        raise ValueError(
            f"only {len(levels)} bisector levels accepted "
            f"(min_accepted_levels={cfg.min_accepted_levels}, skipped={skipped})"
        )

    tau_bis = np.asarray([row.tau_bis for row in levels], dtype=float)
    sig = np.asarray([row.sigma_tau_bis for row in levels], dtype=float)
    depth_arr = np.asarray([row.depth for row in levels], dtype=float)
    weight = 1.0 / np.square(sig)
    tau_core = float(np.sum(weight * tau_bis) / np.sum(weight))
    sigma_core = float(np.sqrt(1.0 / np.sum(weight)))

    line = models.Polynomial1D(degree=1)
    fitted = fitting.LinearLSQFitter()(line, depth_arr, tau_bis)
    slope = float(fitted.c1.value)
    tau_extrap = float(fitted(1.0))
    logger.info(
        "bisector: %s/%s levels, tau_core=%.6f d, slope=%.4f s per unit depth",
        len(levels),
        cfg.n_levels,
        tau_core,
        days_to_seconds(slope),
    )
    return BisectorResult(
        levels=levels,
        tau_core=tau_core,
        sigma_tau_core=sigma_core,
        tau_extrap_floor=tau_extrap,
        slope_days_per_depth=slope,
    )


def _kvw_cost(
    tau0: float,
    template: LoadedTemplate,
    lags: np.ndarray,
    *,
    copy_lo: float,
    copy_hi: float,
    weight_by_sigma: bool,
    n_pairs_min: int,
) -> tuple[float, int]:
    """Return KvW cost and the number of finite pairs at ``tau0``."""
    left = tau0 - lags
    right = tau0 + lags
    ok = (left >= copy_lo) & (right <= copy_hi)
    n_ok = int(np.count_nonzero(ok))
    if n_ok < n_pairs_min:
        return float("inf"), n_ok
    diff = template.mu_spline(left[ok]) - template.mu_spline(right[ok])
    if weight_by_sigma:
        var = np.square(template.sigma_spline(left[ok])) + np.square(
            template.sigma_spline(right[ok])
        )
        cost = float(np.sum(np.square(diff) / var))
    else:
        cost = float(np.sum(np.square(diff)))
    if not np.isfinite(cost):
        return float("inf"), n_ok
    return cost, n_ok


def compute_kvw(
    template: LoadedTemplate,
    cfg: EpochSpikeConfig,
    *,
    copy_lo: float,
    copy_hi: float,
    core_half_width_days: float,
    search_half_width_days: float,
) -> KvwResult:
    """Minimise the Kwee-van Woerden cost on the GP mean.

    Args:
        template (LoadedTemplate): Loaded GP template.
        cfg (EpochSpikeConfig): Pair-count and weighting settings.
        copy_lo (float): Lower copy bound.
        copy_hi (float): Upper copy bound.
        core_half_width_days (float): Maximum lag used in each pair.
        search_half_width_days (float): Search half-width around ``tau_peak``.

    Returns:
        KvwResult: Minimiser location, curvature, and cost scan.

    Raises:
        ValueError: If the bounded search or the curvature parabola fails.
    """
    dt = float(np.median(np.diff(template.tau)))
    lags = np.arange(dt, core_half_width_days + 0.5 * dt, dt)
    if lags.size < cfg.kvw_n_pairs_min:
        raise ValueError(
            f"KvW lag grid has {lags.size} samples; increase kvw.half_width_phase"
        )
    lo = template.tau_peak - search_half_width_days
    hi = template.tau_peak + search_half_width_days
    if lo <= copy_lo or hi >= copy_hi:
        raise ValueError(
            "KvW search window is not strictly inside the isolated copy window"
        )

    def objective(tau0: float) -> float:
        cost, _n_ok = _kvw_cost(
            float(tau0),
            template,
            lags,
            copy_lo=copy_lo,
            copy_hi=copy_hi,
            weight_by_sigma=cfg.weight_by_sigma,
            n_pairs_min=cfg.kvw_n_pairs_min,
        )
        return cost

    result = minimize_scalar(objective, bounds=(lo, hi), method="bounded")
    if not result.success:
        raise ValueError(f"KvW minimisation failed: {result.message}")
    tau_hat = float(result.x)
    cost_min, n_pairs = _kvw_cost(
        tau_hat,
        template,
        lags,
        copy_lo=copy_lo,
        copy_hi=copy_hi,
        weight_by_sigma=cfg.weight_by_sigma,
        n_pairs_min=cfg.kvw_n_pairs_min,
    )
    if not np.isfinite(cost_min):
        raise ValueError("KvW cost is non-finite at the minimiser")

    scan_tau = np.linspace(lo, hi, 401)
    scan_cost = np.asarray([objective(float(t)) for t in scan_tau], dtype=float)
    finite = np.isfinite(scan_cost)
    if int(np.count_nonzero(finite)) < 8:
        raise ValueError("KvW cost scan has too few finite samples")

    near = np.abs(scan_tau - tau_hat) <= 0.3 * search_half_width_days
    fit_mask = finite & near
    if int(np.count_nonzero(fit_mask)) < 5:
        raise ValueError("not enough KvW cost samples for a curvature parabola")
    poly = models.Polynomial1D(degree=2)
    fitted = fitting.LinearLSQFitter()(poly, scan_tau[fit_mask], scan_cost[fit_mask])
    curvature = float(fitted.c2.value)
    if curvature <= 0.0:
        raise ValueError(
            f"KvW cost parabola is not a minimum (c2={curvature}); "
            "the core window may be too wide or the profile too asymmetric"
        )
    tau_parabola = float(-float(fitted.c1.value) / (2.0 * curvature))
    sigma_tau = float(np.sqrt(cost_min / (2.0 * n_pairs * curvature)))
    logger.info(
        "KvW: tau=%.6f d (parabola %.6f d), S_min=%.6g, n_pairs=%s, "
        "sigma=%.3f s, offset from argmin=%.3f s",
        tau_hat,
        tau_parabola,
        cost_min,
        n_pairs,
        days_to_seconds(sigma_tau),
        days_to_seconds(tau_hat - template.tau_peak),
    )
    return KvwResult(
        tau=tau_hat,
        cost_min=cost_min,
        n_pairs=n_pairs,
        tau_parabola=tau_parabola,
        curvature=curvature,
        sigma_tau=sigma_tau,
        scan_tau=scan_tau,
        scan_cost=scan_cost,
        lags=lags,
    )


def run_epoch_estimators(
    template: LoadedTemplate,
    cfg: EpochSpikeConfig,
) -> EpochSpikeResult:
    """Run GP-argmin, bisector, and KvW on one stored template.

    Args:
        template (LoadedTemplate): Loaded GP template.
        cfg (EpochSpikeConfig): Spike settings.

    Returns:
        EpochSpikeResult: Windows, ladder, and KvW scan.
    """
    copy_lo, copy_hi = copy_window(template)
    continuum, bottom = continuum_and_bottom(
        template, copy_lo=copy_lo, copy_hi=copy_hi
    )
    core_hw = cfg.kvw_half_width_phase * template.fold_period
    search_hw = cfg.kvw_search_half_width_phase * template.fold_period
    logger.info(
        "copy window [%.5f, %.5f] d, continuum=%.5f, bottom=%.5f, "
        "KvW half-width +/-%.5f d, search +/-%.5f d",
        copy_lo,
        copy_hi,
        continuum,
        bottom,
        core_hw,
        search_hw,
    )
    kvw = compute_kvw(
        template,
        cfg,
        copy_lo=copy_lo,
        copy_hi=copy_hi,
        core_half_width_days=core_hw,
        search_half_width_days=search_hw,
    )
    bisector = compute_bisector(
        template,
        cfg,
        copy_lo=copy_lo,
        copy_hi=copy_hi,
        continuum=continuum,
        bottom=bottom,
        centre=kvw.tau,
    )
    return EpochSpikeResult(
        template=template,
        copy_lo=copy_lo,
        copy_hi=copy_hi,
        continuum=continuum,
        bottom=bottom,
        kvw_half_width_days=core_hw,
        kvw_search_half_width_days=search_hw,
        bisector=bisector,
        kvw=kvw,
        tau_gp_argmin=template.tau_peak,
    )
