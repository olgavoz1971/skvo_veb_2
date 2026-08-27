"""Per-interval flux error policy for GP fits (tabulated vs guessed noise)."""

from __future__ import annotations

import logging

import numpy as np

from skvo_veb.utils.gp.config import GP_MIN_FINITE_ERROR_FRACTION

logger = logging.getLogger(__name__)


def resolve_interval_noise_sigma_norm(
    y_err: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    baseline: float,
    ampl_guess: float,
    extrema_mode: str,
    *,
    guess_sigma: bool,
    noise_scale: float,
    min_finite_fraction: float = GP_MIN_FINITE_ERROR_FRACTION,
) -> np.ndarray | float:
    """Chooses guessed or tabulated noise for one GP interval fragment.

    When ``guess_sigma`` is false and tabulated errors are mixed with ``NaN``,
    at least ``min_finite_fraction`` of rows must have finite ``flux_err`` to use
    the tabulated branch; missing rows receive the median of finite errors.
    Otherwise the interval uses a single MAD-based guess for all points.

    Args:
        y_err (numpy.ndarray): ``flux_err`` for the interval (may contain ``NaN``).
        x (numpy.ndarray): Time coordinates (JD).
        y (numpy.ndarray): Flux values.
        baseline (float): Baseline used for normalisation.
        ampl_guess (float): Amplitude scale for normalisation.
        extrema_mode (str): ``min`` or ``max``.
        guess_sigma (bool): User **Guess sigma** flag.
        noise_scale (float): Multiplier for guessed or tabulated errors
            (``effective_error = original * noise_scale``). Must be positive.
        min_finite_fraction (float): Minimum fraction of finite errors to impute.

    Returns:
        float or numpy.ndarray: ``noise_sigma_norm`` (scalar if guessed, per-point if tabulated).
    """
    y_err = np.asarray(y_err, dtype=float)
    n = len(y_err)
    if n == 0:
        raise ValueError("resolve_interval_noise_sigma_norm requires at least one row.")
    if not np.isfinite(noise_scale) or noise_scale <= 0:
        raise ValueError(
            f"noise_scale must be a positive finite number, got {noise_scale!r}"
        )

    def _mad_scalar() -> float:
        from skvo_veb.utils.gp.pipeline import residual_noise_estimate

        noise_sigma = residual_noise_estimate(x, y, baseline, ampl_guess, extrema_mode)
        noise_sigma *= noise_scale
        logger.info("Interval noise: MAD guess (sigma=%.4f flux units)", noise_sigma)
        return noise_sigma / ampl_guess

    if guess_sigma:
        return _mad_scalar()

    finite = np.isfinite(y_err)
    n_finite = int(np.count_nonzero(finite))

    if n_finite == 0:
        return _mad_scalar()

    fraction = n_finite / n
    if fraction < min_finite_fraction:
        logger.info(
            "Interval noise: %.1f%% finite flux_err (< %.0f%%); using MAD for all points",
            100.0 * fraction,
            100.0 * min_finite_fraction,
        )
        return _mad_scalar()

    median_err = float(np.nanmedian(y_err[finite]))
    filled = y_err.copy()
    filled[~finite] = median_err
    filled *= noise_scale
    if n_finite < n:
        logger.info(
            "Interval noise: %.1f%% finite flux_err; imputed median=%.4g for %d row(s)",
            100.0 * fraction,
            median_err,
            n - n_finite,
        )
    else:
        logger.info(
            "Interval noise: tabulated flux_err (mean=%.4g flux units)",
            float(np.mean(filled / noise_scale)),
        )
    return filled / ampl_guess
