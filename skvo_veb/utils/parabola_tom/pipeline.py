"""Fit one local parabola ToM on a marked interval (no GP or MAVKA imports)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from astropy.modeling import models
from astropy.modeling.fitting import LinearLSQFitter

from skvo_veb.utils.lc_config import DOMAIN_FLUX, DOMAIN_MAG
from skvo_veb.utils.lc_working_window import (
    apply_half_width_cap,
    filter_plot_arrays_by_jd_window,
    resolve_max_half_width_d,
)
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.parabola_tom.config import MIN_POINTS, MIN_POINTS_ABSOLUTE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParabolaFitResult:
    """One interval parabola fit (success or failure).

    Attributes:
        ok (bool): True when a ToM was accepted.
        t_ext (float): Vertex time (absolute JD), or NaN on failure.
        sigma_t_ext (float): Formal ``σ(t)`` in days from coefficient covariance.
        y_ext (float): Parabola photometry at ``t_ext``.
        curvature (float): Quadratic coefficient ``c2`` in the centred parabola.
        rms (float): Residual RMS in photometry units.
        n_points (int): Finite points used in the fit.
        dt_ext (float): Vertex offset from the interval midpoint (days).
        t_anchor (float): Interval midpoint used as the fit origin (absolute JD).
        c0 (float): Constant coefficient of the centred parabola.
        c1 (float): Linear coefficient of the centred parabola.
        c2 (float): Quadratic coefficient of the centred parabola.
        jd_min (float): Inclusive fit-window start (absolute JD).
        jd_max (float): Inclusive fit-window stop (absolute JD).
        extrema_mode (str): ``min`` or ``max`` in the working domain.
        working_domain (str): ``mag`` or ``flux``.
        use_weights (bool): Whether inverse-variance weights were requested.
        window_capped (bool): True when a max half-width trimmed this interval.
        fail_reason (str | None): Why the interval was rejected, if ``ok`` is false.
        fail_vertex_jd (float | None): Rejected vertex (absolute JD) when the
            vertex fell outside the fit window; otherwise ``None``.
    """

    ok: bool
    t_ext: float
    sigma_t_ext: float
    y_ext: float
    curvature: float
    rms: float
    n_points: int
    dt_ext: float
    t_anchor: float
    c0: float
    c1: float
    c2: float
    jd_min: float
    jd_max: float
    extrema_mode: str
    working_domain: str
    use_weights: bool
    window_capped: bool = False
    fail_reason: str | None = None
    fail_vertex_jd: float | None = None


def normalize_extremum_kind(extremum: str) -> str:
    """Normalises an extremum selector to ``min`` or ``max``.

    Args:
        extremum (str): ``min`` or ``max`` in the working photometry domain.

    Returns:
        str: Normalised extremum kind.

    Raises:
        ValueError: If ``extremum`` is not ``min`` or ``max``.
    """
    kind = str(extremum).strip().lower()
    if kind not in ("min", "max"):
        raise ValueError(f"extremum must be 'min' or 'max', got {extremum!r}")
    return kind


def normalize_working_domain(working_domain: str) -> str:
    """Normalises the working photometry domain label.

    Args:
        working_domain (str): ``mag`` or ``flux``.

    Returns:
        str: Normalised domain label.

    Raises:
        ValueError: If ``working_domain`` is unsupported.
    """
    domain = str(working_domain).strip().lower()
    if domain not in (DOMAIN_MAG, DOMAIN_FLUX):
        raise ValueError(
            f"working_domain must be 'mag' or 'flux', got {working_domain!r}"
        )
    return domain


def expected_curvature_sign(*, working_domain: str, extremum_kind: str) -> float:
    """Returns the required sign of parabola ``c2`` for the requested extremum.

    A magnitude minimum (eclipse) is a local maximum of magnitude numbers, so
    ``c2 < 0``. A flux minimum is a local minimum of flux, so ``c2 > 0``.

    Args:
        working_domain (str): ``mag`` or ``flux``.
        extremum_kind (str): ``min`` or ``max`` in that domain.

    Returns:
        float: Expected sign of the quadratic coefficient (``+1`` or ``-1``).
    """
    domain = normalize_working_domain(working_domain)
    kind = normalize_extremum_kind(extremum_kind)
    if domain == DOMAIN_FLUX:
        return 1.0 if kind == "min" else -1.0
    return -1.0 if kind == "min" else 1.0


def _sigma_t_from_parabola(*, c1: float, c2: float, cov: np.ndarray) -> float:
    """Propagates ``(c0, c1, c2)`` covariance to ``σ(dt_ext)`` for ``-c1/(2 c2)``.

    Args:
        c1 (float): Linear coefficient.
        c2 (float): Quadratic coefficient.
        cov (numpy.ndarray): ``3×3`` covariance of ``(c0, c1, c2)``.

    Returns:
        float: ``sigma_t`` in days for the extremum offset from the anchor.

    Raises:
        ValueError: If ``c2`` is zero or the propagated variance is invalid.
    """
    if abs(c2) < 1e-30:
        raise ValueError("quadratic coefficient is zero; cannot form ToM uncertainty")
    jacobian = np.array([0.0, -1.0 / (2.0 * c2), c1 / (2.0 * c2 * c2)], dtype=float)
    variance = float(jacobian @ cov @ jacobian.T)
    if not np.isfinite(variance) or variance < 0.0:
        raise ValueError(f"non-physical ToM variance: {variance}")
    return float(np.sqrt(variance))


def _failure(
    *,
    jd_min: float,
    jd_max: float,
    n_points: int,
    reason: str,
    extrema_mode: str,
    working_domain: str,
    use_weights: bool,
    t_anchor: float,
    window_capped: bool = False,
    fail_vertex_jd: float | None = None,
) -> ParabolaFitResult:
    """Builds a failed interval result so the batch can continue.

    Args:
        jd_min (float): Interval start (absolute JD).
        jd_max (float): Interval stop (absolute JD).
        n_points (int): Points available when the fit stopped.
        reason (str): Message shown on the failure card.
        extrema_mode (str): ``min`` or ``max``.
        working_domain (str): ``mag`` or ``flux``.
        use_weights (bool): Whether weights were requested.
        t_anchor (float): Interval midpoint.
        window_capped (bool): True when a max half-width trimmed this interval.
        fail_vertex_jd (float | None): Rejected vertex (absolute JD) when the
            vertex fell outside the window.

    Returns:
        ParabolaFitResult: ``ok=False`` row.
    """
    nan = float("nan")
    logger.info("Parabola interval failed (%s–%s): %s", jd_min, jd_max, reason)
    return ParabolaFitResult(
        ok=False,
        t_ext=nan,
        sigma_t_ext=nan,
        y_ext=nan,
        curvature=nan,
        rms=nan,
        n_points=int(n_points),
        dt_ext=nan,
        t_anchor=float(t_anchor),
        c0=nan,
        c1=nan,
        c2=nan,
        jd_min=float(jd_min),
        jd_max=float(jd_max),
        extrema_mode=extrema_mode,
        working_domain=working_domain,
        use_weights=use_weights,
        window_capped=window_capped,
        fail_reason=reason,
        fail_vertex_jd=fail_vertex_jd,
    )


def fit_interval(
    times_jd: np.ndarray,
    photometry: np.ndarray,
    phot_err: np.ndarray | None,
    jd_min: float,
    jd_max: float,
    *,
    working_domain: str,
    extrema_mode: str = "min",
    use_weights: bool = False,
    min_points: int = MIN_POINTS,
    max_half_width_d: float | None = None,
) -> ParabolaFitResult:
    """Fits a centred parabola on one marked interval and returns the vertex.

    The marked interval is the fit window unless ``max_half_width_d`` is set
    and the interval is wider than twice that value; then the window is
    trimmed to ± the half-width around the midpoint. The time origin is that
    midpoint. The vertex must lie inside the fit window, and ``c2`` must match
    the requested extremum in the working domain. Covariance is required.

    Args:
        times_jd (numpy.ndarray): Absolute Julian Dates for the light curve.
        photometry (numpy.ndarray): Working-domain photometry (mag or flux).
        phot_err (numpy.ndarray | None): Per-point uncertainties, or ``None``.
        jd_min (float): Inclusive marked-interval start (absolute JD).
        jd_max (float): Inclusive marked-interval stop (absolute JD).
        working_domain (str): ``mag`` or ``flux``.
        extrema_mode (str): ``min`` or ``max`` in that domain.
        use_weights (bool): Weight by ``1/σ²`` when true.
        min_points (int): Minimum finite points required (must be ≥ 3).
        max_half_width_d (float | None): Optional cap on interval half-width (days).

    Returns:
        ParabolaFitResult: Structured fit (``ok=False`` on sparse or invalid windows).

    Raises:
        ValueError: If ``min_points`` is below 3, the domain/kind is invalid,
            or ``max_half_width_d`` is set but not a positive finite number.
    """
    if int(min_points) < MIN_POINTS_ABSOLUTE:
        raise ValueError(f"min_points must be >= {MIN_POINTS_ABSOLUTE}, got {min_points}")

    kind = normalize_extremum_kind(extrema_mode)
    domain = normalize_working_domain(working_domain)
    lo, hi, capped = apply_half_width_cap(jd_min, jd_max, max_half_width_d)
    t_anchor = 0.5 * (lo + hi)

    try:
        t_win, y_win, e_win = filter_plot_arrays_by_jd_window(
            times_jd, photometry, phot_err, lo, hi
        )
    except PipeException as exc:
        return _failure(
            jd_min=lo,
            jd_max=hi,
            n_points=0,
            reason=str(exc),
            extrema_mode=kind,
            working_domain=domain,
            use_weights=bool(use_weights),
            t_anchor=t_anchor,
            window_capped=capped,
        )

    t_win = np.asarray(t_win, dtype=float)
    y_win = np.asarray(y_win, dtype=float)
    finite = np.isfinite(t_win) & np.isfinite(y_win)
    t_win = t_win[finite]
    y_win = y_win[finite]
    if e_win is not None:
        e_win = np.asarray(e_win, dtype=float)[finite]
    n = int(t_win.size)
    if n < int(min_points):
        return _failure(
            jd_min=lo,
            jd_max=hi,
            n_points=n,
            reason=f"Need at least {int(min_points)} points, got {n}",
            extrema_mode=kind,
            working_domain=domain,
            use_weights=bool(use_weights),
            t_anchor=t_anchor,
            window_capped=capped,
        )

    weights = None
    if use_weights:
        if e_win is None:
            return _failure(
                jd_min=lo,
                jd_max=hi,
                n_points=n,
                reason=(
                    "Inverse-variance weights require photometric uncertainties; "
                    "this light curve has none."
                ),
                extrema_mode=kind,
                working_domain=domain,
                use_weights=True,
                t_anchor=t_anchor,
                window_capped=capped,
            )
        finite_err = np.isfinite(e_win) & (e_win > 0.0)
        n_err = int(np.count_nonzero(finite_err))
        if n_err < n:
            return _failure(
                jd_min=lo,
                jd_max=hi,
                n_points=n,
                reason=(
                    "Inverse-variance weights need a finite positive uncertainty "
                    f"on every in-window point; {n - n_err} of {n} lack one."
                ),
                extrema_mode=kind,
                working_domain=domain,
                use_weights=True,
                t_anchor=t_anchor,
                window_capped=capped,
            )
        weights = 1.0 / (e_win**2)

    dt = t_win - float(t_anchor)
    poly = models.Polynomial1D(degree=2)
    fitter = LinearLSQFitter(calc_uncertainties=True)
    try:
        fitted = fitter(poly, dt, y_win, weights=weights)
    except Exception as exc:
        return _failure(
            jd_min=lo,
            jd_max=hi,
            n_points=n,
            reason=f"Parabola least-squares fit failed: {exc}",
            extrema_mode=kind,
            working_domain=domain,
            use_weights=bool(use_weights),
            t_anchor=t_anchor,
            window_capped=capped,
        )

    c0 = float(getattr(fitted.c0, "value", fitted.c0))
    c1 = float(getattr(fitted.c1, "value", fitted.c1))
    c2 = float(getattr(fitted.c2, "value", fitted.c2))
    if not (np.isfinite(c0) and np.isfinite(c1) and np.isfinite(c2)):
        return _failure(
            jd_min=lo,
            jd_max=hi,
            n_points=n,
            reason="Parabola fit returned non-finite coefficients",
            extrema_mode=kind,
            working_domain=domain,
            use_weights=bool(use_weights),
            t_anchor=t_anchor,
            window_capped=capped,
        )

    expected_sign = expected_curvature_sign(
        working_domain=domain, extremum_kind=kind
    )
    if expected_sign * c2 <= 0.0:
        return _failure(
            jd_min=lo,
            jd_max=hi,
            n_points=n,
            reason=(
                f"Curvature sign incompatible with {kind}imum in {domain!r} "
                f"(c2={c2:.3e})"
            ),
            extrema_mode=kind,
            working_domain=domain,
            use_weights=bool(use_weights),
            t_anchor=t_anchor,
            window_capped=capped,
        )

    dt_ext = -c1 / (2.0 * c2)
    tom_jd = float(t_anchor + dt_ext)
    if not (lo <= tom_jd <= hi):
        return _failure(
            jd_min=lo,
            jd_max=hi,
            n_points=n,
            reason=(
                f"Parabola vertex {tom_jd:.6f} lies outside the fit window "
                f"[{lo:.6f}, {hi:.6f}]"
            ),
            extrema_mode=kind,
            working_domain=domain,
            use_weights=bool(use_weights),
            t_anchor=t_anchor,
            window_capped=capped,
            fail_vertex_jd=tom_jd,
        )

    if not hasattr(fitted, "cov_matrix") or fitted.cov_matrix is None:
        return _failure(
            jd_min=lo,
            jd_max=hi,
            n_points=n,
            reason="Fit covariance unavailable; enable calc_uncertainties",
            extrema_mode=kind,
            working_domain=domain,
            use_weights=bool(use_weights),
            t_anchor=t_anchor,
            window_capped=capped,
        )
    try:
        cov = np.asarray(fitted.cov_matrix.cov_matrix, dtype=float)
        sigma_t_d = _sigma_t_from_parabola(c1=c1, c2=c2, cov=cov)
    except ValueError as exc:
        return _failure(
            jd_min=lo,
            jd_max=hi,
            n_points=n,
            reason=str(exc),
            extrema_mode=kind,
            working_domain=domain,
            use_weights=bool(use_weights),
            t_anchor=t_anchor,
            window_capped=capped,
        )

    y_model = fitted(dt)
    resid = y_win - y_model
    dof = max(n - 3, 1)
    rms = float(np.sqrt(np.sum(resid**2) / dof))
    y_ext = float(fitted(dt_ext))

    return ParabolaFitResult(
        ok=True,
        t_ext=tom_jd,
        sigma_t_ext=float(sigma_t_d),
        y_ext=y_ext,
        curvature=c2,
        rms=rms,
        n_points=n,
        dt_ext=float(dt_ext),
        t_anchor=float(t_anchor),
        c0=c0,
        c1=c1,
        c2=c2,
        jd_min=lo,
        jd_max=hi,
        extrema_mode=kind,
        working_domain=domain,
        use_weights=bool(use_weights),
        window_capped=capped,
    )
