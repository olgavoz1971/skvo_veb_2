"""Fit one MAVKA interval from photometry arrays (no GP imports)."""

from __future__ import annotations

import logging

import numpy as np

from skvo_veb.utils.mavka.config import MAXIMA_NOT_AVAILABLE, MIN_POINTS
from skvo_veb.utils.mavka.models import ApproxFitResult, fit_interval as fit_model

logger = logging.getLogger(__name__)


def slice_interval_photometry(
    times_jd: np.ndarray,
    photometry: np.ndarray,
    jd_min: float,
    jd_max: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Returns finite points whose times lie inside ``[jd_min, jd_max]``.

    Args:
        times_jd (numpy.ndarray): Absolute Julian Dates.
        photometry (numpy.ndarray): Working-domain photometry (mag or flux).
        jd_min (float): Inclusive interval start (absolute JD).
        jd_max (float): Inclusive interval stop (absolute JD).

    Returns:
        tuple: ``(t, y)`` arrays for the slice (may be empty).
    """
    times_jd = np.asarray(times_jd, dtype=float)
    photometry = np.asarray(photometry, dtype=float)
    if times_jd.shape != photometry.shape:
        raise ValueError(
            f"times_jd and photometry length mismatch: "
            f"{times_jd.size} vs {photometry.size}"
        )
    mask = (
        (times_jd >= float(jd_min))
        & (times_jd <= float(jd_max))
        & np.isfinite(times_jd)
        & np.isfinite(photometry)
    )
    return times_jd[mask], photometry[mask]


def _sparse_failure(method: str, n_points: int) -> ApproxFitResult:
    """Builds a failed result when an interval has too few points."""
    nan = float("nan")
    return ApproxFitResult(
        method=method.upper(),
        ok=False,
        t_ext=nan,
        sigma_t_ext=nan,
        y_ext=nan,
        sigma_y_ext=nan,
        c4=nan,
        c5=nan,
        eclipse_duration=nan,
        sigma_duration=nan,
        params=np.asarray([]),
        rms=nan,
        n_points=int(n_points),
        fail_reason=f"Need at least {MIN_POINTS} points, got {n_points}",
    )


def fit_interval(
    method: str,
    t_obs: np.ndarray,
    y_obs: np.ndarray,
    *,
    extrema_mode: str = "min",
    maxfev: int = 100_000,
) -> ApproxFitResult:
    """Fits one MAVKA method on an interval, failing sparse windows without aborting.

    Args:
        method (str): ``AP``, ``WSAP``, ``WSL``, or ``A``.
        t_obs (numpy.ndarray): Absolute times (JD) inside the interval.
        y_obs (numpy.ndarray): Photometry in the current Mag/Flux view.
        extrema_mode (str): Must be ``min`` in v1.
        maxfev (int): ``curve_fit`` iteration budget.

    Returns:
        ApproxFitResult: Structured fit (``ok=False`` on sparse or optimiser failure).

    Raises:
        ValueError: If ``extrema_mode`` is not ``min``.
    """
    if extrema_mode != "min":
        raise ValueError(MAXIMA_NOT_AVAILABLE)

    t_obs = np.asarray(t_obs, dtype=float)
    y_obs = np.asarray(y_obs, dtype=float)
    n = int(t_obs.size)
    if n < MIN_POINTS:
        logger.info("MAVKA sparse interval: %s points (method=%s)", n, method)
        return _sparse_failure(method, n)
    return fit_model(method, t_obs, y_obs, maxfev=maxfev)
