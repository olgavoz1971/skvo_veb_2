"""Tests for MAVKA interval fitting (sparse fail-and-continue, minima only)."""

from __future__ import annotations

import numpy as np
import pytest

from skvo_veb.utils.mavka.config import MAXIMA_NOT_AVAILABLE, MIN_POINTS
from skvo_veb.utils.mavka.pipeline import fit_interval, slice_interval_photometry


def _parabola_minimum(n: int = 40) -> tuple[np.ndarray, np.ndarray]:
    """Symmetric parabolic dip in magnitude (brighter = smaller y)."""
    t0 = 2451000.10
    t = np.linspace(2451000.00, 2451000.20, n)
    y = 12.0 + 25.0 * (t - t0) ** 2
    return t, y


def test_slice_interval_photometry_keeps_finite_points_inside_bounds():
    """Slice drops NaNs and points outside the JD window."""
    t = np.array([10.0, 11.0, 12.0, 13.0])
    y = np.array([1.0, np.nan, 3.0, 4.0])
    t_s, y_s = slice_interval_photometry(t, y, 11.0, 12.5)
    np.testing.assert_array_equal(t_s, np.array([12.0]))
    np.testing.assert_array_equal(y_s, np.array([3.0]))


def test_slice_interval_photometry_rejects_length_mismatch():
    """Mismatched arrays fail fast instead of silently truncating."""
    with pytest.raises(ValueError, match="length mismatch"):
        slice_interval_photometry(np.array([1.0, 2.0]), np.array([1.0]), 1.0, 2.0)


def test_wsap_recovers_symmetric_minimum():
    """Default WSAP TOM lies near the true parabolic vertex."""
    t, y = _parabola_minimum()
    fit = fit_interval("WSAP", t, y, extrema_mode="min")
    assert fit.ok, fit.fail_reason
    assert abs(fit.t_ext - 2451000.10) < 0.01
    assert np.isfinite(fit.sigma_t_ext)


def test_sparse_interval_fails_without_raising():
    """Fewer than MIN_POINTS yields a failed result so the batch can continue."""
    t = np.linspace(2451000.0, 2451000.1, MIN_POINTS - 1)
    y = np.ones_like(t)
    fit = fit_interval("WSAP", t, y, extrema_mode="min")
    assert fit.ok is False
    assert "Need at least" in (fit.fail_reason or "")
    assert fit.n_points == MIN_POINTS - 1


def test_maxima_mode_is_rejected():
    """v1 does not invert photometry; maxima must fail fast with an explicit error."""
    t, y = _parabola_minimum()
    with pytest.raises(ValueError, match="maxima"):
        fit_interval("WSAP", t, y, extrema_mode="max")
    assert "Search minima" in MAXIMA_NOT_AVAILABLE


def test_unknown_method_fails_interval_without_raising_to_batch():
    """Unknown method is reported on the card; the caller can continue."""
    t, y = _parabola_minimum()
    fit = fit_interval("NOPE", t, y, extrema_mode="min")
    assert fit.ok is False
    assert fit.fail_reason


def test_sparse_then_good_interval_can_continue():
    """A sparse window does not prevent fitting the next interval."""
    t_good, y_good = _parabola_minimum()
    t_sparse = np.linspace(2451000.0, 2451000.1, MIN_POINTS - 1)
    y_sparse = np.ones_like(t_sparse)
    first = fit_interval("WSAP", t_sparse, y_sparse, extrema_mode="min")
    second = fit_interval("WSAP", t_good, y_good, extrema_mode="min")
    assert first.ok is False
    assert second.ok, second.fail_reason
