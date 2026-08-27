"""Tests for per-interval GP flux error policy."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from skvo_veb.utils.gp.noise_policy import resolve_interval_noise_sigma_norm


@pytest.fixture
def xy_baseline():
    """Minimal x, y, baseline, ampl for MAD branch tests."""
    x = np.array([1.0, 2.0, 3.0, 4.0])
    y = np.array([0.9, 0.85, 0.88, 0.92])
    return x, y, 1.0, 0.1, "min"


def test_guess_sigma_forces_mad(xy_baseline):
    """Guess sigma on always uses scalar MAD noise."""
    x, y, baseline, ampl, mode = xy_baseline
    y_err = np.array([0.01, 0.02, 0.03, 0.04])
    with patch(
        "skvo_veb.utils.gp.pipeline.residual_noise_estimate",
        return_value=0.05,
    ):
        out = resolve_interval_noise_sigma_norm(
            y_err,
            x,
            y,
            baseline,
            ampl,
            mode,
            guess_sigma=True,
            noise_scale=1.0,
        )
    assert isinstance(out, float)
    assert out == pytest.approx(0.05 / ampl)


def test_all_nan_errors_use_mad(xy_baseline):
    """No finite errors falls back to MAD."""
    x, y, baseline, ampl, mode = xy_baseline
    y_err = np.array([np.nan, np.nan, np.nan, np.nan])
    with patch(
        "skvo_veb.utils.gp.pipeline.residual_noise_estimate",
        return_value=0.02,
    ):
        out = resolve_interval_noise_sigma_norm(
            y_err,
            x,
            y,
            baseline,
            ampl,
            mode,
            guess_sigma=False,
            noise_scale=1.0,
        )
    assert isinstance(out, float)
    assert out == pytest.approx(0.02 / ampl)


def test_below_threshold_uses_mad_for_all(xy_baseline):
    """50% finite is below 70%; entire interval uses MAD."""
    x, y, baseline, ampl, mode = xy_baseline
    y_err = np.array([0.01, np.nan, 0.03, np.nan])
    with patch(
        "skvo_veb.utils.gp.pipeline.residual_noise_estimate",
        return_value=0.04,
    ):
        out = resolve_interval_noise_sigma_norm(
            y_err,
            x,
            y,
            baseline,
            ampl,
            mode,
            guess_sigma=False,
            noise_scale=1.0,
            min_finite_fraction=0.7,
        )
    assert isinstance(out, float)


def test_at_threshold_median_impute(xy_baseline):
    """75% finite uses tabulated branch with median imputation for NaNs."""
    x, y, baseline, ampl, mode = xy_baseline
    y_err = np.array([0.02, 0.04, np.nan, 0.04])
    out = resolve_interval_noise_sigma_norm(
        y_err,
        x,
        y,
        baseline,
        ampl,
        mode,
        guess_sigma=False,
        noise_scale=1.0,
        min_finite_fraction=0.7,
    )
    assert isinstance(out, np.ndarray)
    assert out.shape == (4,)
    expected_median = 0.04
    assert out[2] == pytest.approx(expected_median / ampl)
    assert out[0] == pytest.approx(0.02 / ampl)
    assert out[1] == pytest.approx(0.04 / ampl)


def test_empty_interval_raises():
    """Zero rows is invalid."""
    with pytest.raises(ValueError, match="at least one row"):
        resolve_interval_noise_sigma_norm(
            np.array([]),
            np.array([]),
            np.array([]),
            0.0,
            1.0,
            "min",
            guess_sigma=False,
            noise_scale=1.0,
        )


def test_noise_scale_multiplies_tabulated_errors(xy_baseline):
    """Noise scale is a multiplier of tabulated flux errors."""
    x, y, baseline, ampl, mode = xy_baseline
    y_err = np.array([0.02, 0.04, np.nan, 0.04])
    out_unit = resolve_interval_noise_sigma_norm(
        y_err,
        x,
        y,
        baseline,
        ampl,
        mode,
        guess_sigma=False,
        noise_scale=1.0,
        min_finite_fraction=0.7,
    )
    out_double = resolve_interval_noise_sigma_norm(
        y_err,
        x,
        y,
        baseline,
        ampl,
        mode,
        guess_sigma=False,
        noise_scale=2.0,
        min_finite_fraction=0.7,
    )
    np.testing.assert_allclose(out_double, 2.0 * out_unit)


def test_noise_scale_multiplies_mad_guess(xy_baseline):
    """Noise scale is a multiplier of the MAD guess."""
    x, y, baseline, ampl, mode = xy_baseline
    y_err = np.array([0.01, 0.02, 0.03, 0.04])
    with patch(
        "skvo_veb.utils.gp.pipeline.residual_noise_estimate",
        return_value=0.05,
    ):
        out = resolve_interval_noise_sigma_norm(
            y_err,
            x,
            y,
            baseline,
            ampl,
            mode,
            guess_sigma=True,
            noise_scale=2.0,
        )
    assert out == pytest.approx(0.10 / ampl)


def test_noise_scale_must_be_positive(xy_baseline):
    """Non-positive noise scale is invalid."""
    x, y, baseline, ampl, mode = xy_baseline
    with pytest.raises(ValueError, match="noise_scale must be a positive"):
        resolve_interval_noise_sigma_norm(
            np.array([0.01]),
            np.array([1.0]),
            np.array([0.9]),
            baseline,
            ampl,
            mode,
            guess_sigma=False,
            noise_scale=0.0,
        )
