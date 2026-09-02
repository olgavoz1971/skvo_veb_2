"""Refine smooth minima by local parabola fits on raw light-curve points."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.modeling import models
from astropy.modeling.fitting import LinearLSQFitter

from extremum_kind import expected_curvature_sign, normalize_extremum_kind
from smooth_extrema import SmoothExtremaResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParabolaTomConfig:
    """Settings for per-extremum parabola ToM refinement.

    Attributes:
        fit_half_width_d (float): Half-width of the calendar-time window (days)
            centred on each rough extremum. Raw LC points with
            ``|t - t_rough| <= fit_half_width_d`` enter the fit.
        min_points (int): Minimum raw points required in the window.
        use_weights (bool): Weight by ``1/phot_err^2`` when errors are finite.
        extremum_kind (str): ``min`` or ``max`` in the working domain.
    """

    fit_half_width_d: float
    min_points: int = 5
    use_weights: bool = False
    extremum_kind: str = "min"


@dataclass(frozen=True)
class ParabolaTomHit:
    """One parabola-refined time of extremum.

    Attributes:
        tom_jd (float): Refined extremum time (JD).
        sigma_t_d (float): Formal propagated uncertainty on ``tom_jd`` (days).
        y_ext (float): Parabola photometry at ``tom_jd``.
        rough_jd (float): Anchor time from the smooth-extremum detector.
        curvature (float): Quadratic coefficient ``c2`` in the centred parabola.
        rms (float): RMS of in-window residuals (photometry units).
        n_points (int): Raw points used in the fit.
        dt_ext (float): Extremum offset from ``rough_jd`` (days).
    """

    tom_jd: float
    sigma_t_d: float
    y_ext: float
    rough_jd: float
    curvature: float
    rms: float
    n_points: int
    dt_ext: float


@dataclass(frozen=True)
class ParabolaTomResult:
    """Batch output from parabola ToM refinement.

    Attributes:
        hits (list[ParabolaTomHit]): Successful refined extrema.
        n_attempted (int): Number of rough extrema submitted.
        n_failed (int): Number of extrema that did not yield a valid fit.
        fit_half_width_d (float): Half-width used for all fits (days).
        extremum_kind (str): ``min`` or ``max`` in the working domain.
    """

    hits: list[ParabolaTomHit]
    n_attempted: int
    n_failed: int
    fit_half_width_d: float
    extremum_kind: str

    @property
    def n_ok(self) -> int:
        """Return the number of successful ToM fits."""
        return len(self.hits)


def effective_fit_half_width(
    rough_jd: float,
    all_rough_jd: np.ndarray,
    *,
    fit_half_width_d: float,
) -> float:
    """Cap the fit window so neighbouring minima do not share raw points.

    Args:
        rough_jd (float): Anchor time for this minimum.
        all_rough_jd (numpy.ndarray): All rough minimum times.
        fit_half_width_d (float): Requested half-width (days).

    Returns:
        float: Effective half-width (days).
    """
    if all_rough_jd.size < 2:
        return float(fit_half_width_d)

    others = all_rough_jd[np.asarray(all_rough_jd, dtype=float) != float(rough_jd)]
    if others.size == 0:
        return float(fit_half_width_d)

    nearest = float(np.min(np.abs(others - float(rough_jd))))
    cap = 0.45 * nearest
    return float(min(float(fit_half_width_d), cap))


def _effective_half_width(
    rough_jd: float,
    all_rough_jd: np.ndarray,
    *,
    fit_half_width_d: float,
) -> float:
    """Return ``effective_fit_half_width`` (private alias for in-module use)."""
    return effective_fit_half_width(
        rough_jd,
        all_rough_jd,
        fit_half_width_d=fit_half_width_d,
    )


def _sigma_t_from_parabola(
    *,
    c1: float,
    c2: float,
    cov: np.ndarray,
) -> float:
    """Propagate parameter covariance to uncertainty on ``dt_ext = -c1/(2*c2)``.

    Args:
        c1 (float): Linear coefficient.
        c2 (float): Quadratic coefficient.
        cov (numpy.ndarray): ``3×3`` covariance of ``(c0, c1, c2)``.

    Returns:
        float: ``sigma_t`` (days) for the extremum offset from the anchor.

    Raises:
        ValueError: If ``c2`` is zero or the propagated variance is invalid.
    """
    if abs(c2) < 1e-30:
        raise ValueError("quadratic coefficient is zero; cannot form TOM uncertainty")
    jacobian = np.array([0.0, -1.0 / (2.0 * c2), c1 / (2.0 * c2 * c2)], dtype=float)
    variance = float(jacobian @ cov @ jacobian.T)
    if not np.isfinite(variance) or variance < 0.0:
        raise ValueError(f"non-physical TOM variance: {variance}")
    return float(np.sqrt(variance))


def _fit_parabola_at_anchor(
    jd: np.ndarray,
    phot: np.ndarray,
    phot_err: np.ndarray,
    *,
    t_anchor: float,
    half_width_d: float,
    min_points: int,
    use_weights: bool,
    working_domain: str,
    extremum_kind: str,
) -> ParabolaTomHit:
    """Fit a centred parabola on raw points around one rough extremum.

    Args:
        jd (numpy.ndarray): Raw observation times.
        phot (numpy.ndarray): Raw photometry.
        phot_err (numpy.ndarray): Per-point uncertainties.
        t_anchor (float): Rough extremum time (JD).
        half_width_d (float): Fit half-width (days).
        min_points (int): Minimum in-window points.
        use_weights (bool): Use inverse-variance weights when possible.
        working_domain (str): ``mag`` or ``flux``.
        extremum_kind (str): ``min`` or ``max`` in the working domain.

    Returns:
        ParabolaTomHit: Refined ToM and diagnostics.

    Raises:
        ValueError: If the fit is underdetermined or the extremum is invalid.
    """
    kind = normalize_extremum_kind(extremum_kind)
    mask = (jd >= t_anchor - half_width_d) & (jd <= t_anchor + half_width_d)
    t_win = np.asarray(jd[mask], dtype=float)
    y_win = np.asarray(phot[mask], dtype=float)
    e_win = np.asarray(phot_err[mask], dtype=float)
    if t_win.size < min_points:
        raise ValueError(
            f"need at least {min_points} raw points in fit window, got {t_win.size}"
        )

    dt = t_win - float(t_anchor)
    poly = models.Polynomial1D(degree=2)
    fitter = LinearLSQFitter(calc_uncertainties=True)
    weights = None
    if use_weights:
        finite = np.isfinite(e_win) & (e_win > 0.0)
        if np.count_nonzero(finite) >= min_points:
            inv_var = np.zeros_like(y_win)
            inv_var[finite] = 1.0 / (e_win[finite] ** 2)
            weights = inv_var

    fitted = fitter(poly, dt, y_win, weights=weights)
    c0 = float(getattr(fitted.c0, "value", fitted.c0))
    c1 = float(getattr(fitted.c1, "value", fitted.c1))
    c2 = float(getattr(fitted.c2, "value", fitted.c2))
    if not (np.isfinite(c0) and np.isfinite(c1) and np.isfinite(c2)):
        raise ValueError("parabola fit returned non-finite coefficients")

    expected_sign = expected_curvature_sign(
        working_domain=working_domain,
        extremum_kind=kind,
    )
    if expected_sign * c2 <= 0.0:
        raise ValueError(
            f"curvature sign incompatible with {kind}imum in {working_domain!r} "
            f"(c2={c2:.3e})"
        )

    dt_ext = -c1 / (2.0 * c2)
    if abs(dt_ext) > half_width_d:
        raise ValueError(
            f"parabola extremum outside fit window: |dt_ext|={abs(dt_ext):.6f} "
            f"> half_width={half_width_d:.6f}"
        )

    if not hasattr(fitted, "cov_matrix") or fitted.cov_matrix is None:
        raise ValueError("fit covariance unavailable; enable calc_uncertainties")
    cov = np.asarray(fitted.cov_matrix.cov_matrix, dtype=float)
    sigma_t_d = _sigma_t_from_parabola(c1=c1, c2=c2, cov=cov)

    y_model = fitted(dt)
    resid = y_win - y_model
    dof = max(t_win.size - 3, 1)
    rms = float(np.sqrt(np.sum(resid**2) / dof))
    tom_jd = float(t_anchor + dt_ext)
    y_ext = float(fitted(dt_ext))

    return ParabolaTomHit(
        tom_jd=tom_jd,
        sigma_t_d=sigma_t_d,
        y_ext=y_ext,
        rough_jd=float(t_anchor),
        curvature=c2,
        rms=rms,
        n_points=int(t_win.size),
        dt_ext=float(dt_ext),
    )


def fit_parabola_tom(
    jd: np.ndarray,
    phot: np.ndarray,
    phot_err: np.ndarray,
    extrema: SmoothExtremaResult,
    *,
    working_domain: str,
    cfg: ParabolaTomConfig,
) -> ParabolaTomResult:
    """Refine each rough smooth extremum with a local parabola on raw data.

    Args:
        jd (numpy.ndarray): Raw observation times.
        phot (numpy.ndarray): Raw photometry.
        phot_err (numpy.ndarray): Per-point uncertainties.
        extrema (SmoothExtremaResult): Rough extrema from the smoothed curve.
        working_domain (str): ``mag`` or ``flux``.
        cfg (ParabolaTomConfig): Fit window and weight settings.

    Returns:
        ParabolaTomResult: Successful refined extrema and failure counts.

    Raises:
        ValueError: If configuration or inputs are invalid.
    """
    kind = normalize_extremum_kind(cfg.extremum_kind)
    if kind != extrema.extremum_kind:
        raise ValueError(
            f"extremum_kind mismatch: cfg={kind!r}, extrema={extrema.extremum_kind!r}"
        )
    if cfg.fit_half_width_d <= 0.0:
        raise ValueError(f"fit_half_width_d must be positive, got {cfg.fit_half_width_d}")
    if cfg.min_points < 3:
        raise ValueError(f"min_points must be >= 3, got {cfg.min_points}")
    if extrema.n_extrema == 0:
        logger.warning("No rough %sima to refine", kind)
        return ParabolaTomResult(
            hits=[],
            n_attempted=0,
            n_failed=0,
            fit_half_width_d=float(cfg.fit_half_width_d),
            extremum_kind=kind,
        )

    hits: list[ParabolaTomHit] = []
    n_failed = 0
    rough_jd = np.asarray(extrema.jd, dtype=float)

    for anchor in rough_jd:
        half_w = _effective_half_width(
            anchor,
            rough_jd,
            fit_half_width_d=cfg.fit_half_width_d,
        )
        try:
            hit = _fit_parabola_at_anchor(
                jd,
                phot,
                phot_err,
                t_anchor=float(anchor),
                half_width_d=half_w,
                min_points=int(cfg.min_points),
                use_weights=bool(cfg.use_weights),
                working_domain=working_domain,
                extremum_kind=kind,
            )
        except ValueError as exc:
            n_failed += 1
            logger.warning("Parabola ToM failed at rough jd=%.8f: %s", anchor, exc)
            continue
        hits.append(hit)

    logger.info(
        "Parabola ToM (%s): %s ok, %s failed (fit_half_width=%.6f d)",
        kind,
        len(hits),
        n_failed,
        cfg.fit_half_width_d,
    )
    return ParabolaTomResult(
        hits=hits,
        n_attempted=int(extrema.n_extrema),
        n_failed=n_failed,
        fit_half_width_d=float(cfg.fit_half_width_d),
        extremum_kind=kind,
    )


def export_parabola_tom_ascii(
    path,
    result: ParabolaTomResult,
    *,
    source_lc: str,
    working_domain: str,
    cfg: ParabolaTomConfig,
) -> None:
    """Write refined ToM table as a ``#``-commented ASCII file.

    Columns: ``tom_jd  sigma_t_d  rough_jd  n_points  rms  curvature  dt_ext``.

    Args:
        path: Output file path.
        result (ParabolaTomResult): Refinement output.
        source_lc (str): Input light-curve label.
        working_domain (str): ``mag`` or ``flux``.
        cfg (ParabolaTomConfig): Fit settings used.

    Returns:
        None.
    """
    out_path = Path(path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# tool: running_parabola_spike\n")
        handle.write("# step: parabola_tom\n")
        handle.write(f"# source_lc: {source_lc}\n")
        handle.write(f"# working_domain: {working_domain}\n")
        handle.write(f"# extremum: {result.extremum_kind}\n")
        handle.write(f"# fit_half_width_d: {cfg.fit_half_width_d}\n")
        handle.write(f"# min_points: {cfg.min_points}\n")
        handle.write(f"# use_weights: {cfg.use_weights}\n")
        handle.write(f"# n_ok: {result.n_ok}\n")
        handle.write(f"# n_failed: {result.n_failed}\n")
        handle.write(
            "# columns: tom_jd sigma_t_d rough_jd n_points rms curvature dt_ext\n"
        )
        handle.write("# tom_jd sigma_t_d rough_jd n_points rms curvature dt_ext\n")
        for hit in result.hits:
            handle.write(
                f"{hit.tom_jd:.8f}  {hit.sigma_t_d:.8e}  {hit.rough_jd:.8f}  "
                f"{hit.n_points}  {hit.rms:.8e}  {hit.curvature:.8e}  "
                f"{hit.dt_ext:.8e}\n"
            )
    logger.info("Wrote %s (%s row(s))", out_path, result.n_ok)
