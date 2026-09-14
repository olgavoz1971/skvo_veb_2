"""Tests for local parabola ToM interval fitting."""

from __future__ import annotations

import numpy as np
import pytest

from skvo_veb.utils.oc.tom_io import parse_compact_tom_contents
from skvo_veb.utils.parabola_tom.config import MIN_POINTS
from skvo_veb.utils.parabola_tom.export import format_compact_extrema_dat
from skvo_veb.utils.parabola_tom.pipeline import (
    apply_half_width_cap,
    expected_curvature_sign,
    fit_interval,
    resolve_max_half_width_d,
)


def _mag_eclipse(n: int = 40, t0: float = 2451000.10) -> tuple[np.ndarray, np.ndarray]:
    """Faintest at ``t0`` in magnitude (local maximum of mag numbers)."""
    t = np.linspace(2451000.00, 2451000.20, n)
    y = 12.0 - 25.0 * (t - t0) ** 2
    return t, y


def _flux_eclipse(n: int = 40, t0: float = 2451000.10) -> tuple[np.ndarray, np.ndarray]:
    """Faintest at ``t0`` in flux (local minimum of flux)."""
    t = np.linspace(2451000.00, 2451000.20, n)
    y = 1.0 + 0.4 * (t - t0) ** 2
    return t, y


def test_expected_curvature_sign_mag_and_flux():
    """Eclipse in mag opens downwards; eclipse in flux opens upwards."""
    assert expected_curvature_sign(working_domain="mag", extremum_kind="min") == -1.0
    assert expected_curvature_sign(working_domain="flux", extremum_kind="min") == 1.0
    assert expected_curvature_sign(working_domain="mag", extremum_kind="max") == 1.0
    assert expected_curvature_sign(working_domain="flux", extremum_kind="max") == -1.0


def test_fit_interval_recovers_mag_minimum():
    """Magnitude eclipse ToM lies near the true vertex with a finite σ."""
    t, y = _mag_eclipse()
    fit = fit_interval(
        t, y, None, float(t.min()), float(t.max()), working_domain="mag", extrema_mode="min"
    )
    assert fit.ok, fit.fail_reason
    assert abs(fit.t_ext - 2451000.10) < 1e-6
    assert np.isfinite(fit.sigma_t_ext)
    assert fit.sigma_t_ext > 0.0
    assert fit.c2 < 0.0


def test_fit_interval_recovers_flux_minimum():
    """Flux eclipse ToM lies near the true vertex."""
    t, y = _flux_eclipse()
    fit = fit_interval(
        t, y, None, float(t.min()), float(t.max()), working_domain="flux", extrema_mode="min"
    )
    assert fit.ok, fit.fail_reason
    assert abs(fit.t_ext - 2451000.10) < 1e-6
    assert fit.c2 > 0.0


def test_fit_interval_recovers_mag_maximum():
    """Brightest magnitude (local mag minimum) is recovered as Search maxima."""
    t0 = 2451000.10
    t = np.linspace(2451000.00, 2451000.20, 40)
    y = 12.0 + 25.0 * (t - t0) ** 2
    fit = fit_interval(
        t, y, None, float(t.min()), float(t.max()), working_domain="mag", extrema_mode="max"
    )
    assert fit.ok, fit.fail_reason
    assert abs(fit.t_ext - t0) < 1e-6
    assert fit.c2 > 0.0


def test_fit_interval_recovers_flux_maximum():
    """Flux peak (local flux maximum) is recovered as Search maxima."""
    t0 = 2451000.10
    t = np.linspace(2451000.00, 2451000.20, 40)
    y = 1.0 - 0.4 * (t - t0) ** 2
    fit = fit_interval(
        t, y, None, float(t.min()), float(t.max()), working_domain="flux", extrema_mode="max"
    )
    assert fit.ok, fit.fail_reason
    assert abs(fit.t_ext - t0) < 1e-6
    assert fit.c2 < 0.0


def test_sparse_interval_fails_without_raising():
    """Fewer than MIN_POINTS yields a failed result so the batch can continue."""
    t = np.linspace(2451000.0, 2451000.1, MIN_POINTS - 1)
    y = 12.0 - (t - 2451000.05) ** 2
    fit = fit_interval(
        t, y, None, float(t.min()), float(t.max()), working_domain="mag", extrema_mode="min"
    )
    assert fit.ok is False
    assert "Need at least" in (fit.fail_reason or "")
    assert fit.n_points == MIN_POINTS - 1


def test_weights_fail_when_errors_missing():
    """Weights on with no error column fails the card, not an unweighted fit."""
    t, y = _mag_eclipse()
    fit = fit_interval(
        t,
        y,
        None,
        float(t.min()),
        float(t.max()),
        working_domain="mag",
        extrema_mode="min",
        use_weights=True,
    )
    assert fit.ok is False
    assert "uncertaint" in (fit.fail_reason or "").lower()


def test_weights_fail_when_some_errors_missing():
    """A mixed error column does not silently drop to partial weights."""
    t, y = _mag_eclipse()
    err = np.full_like(y, 0.01)
    err[0] = np.nan
    fit = fit_interval(
        t,
        y,
        err,
        float(t.min()),
        float(t.max()),
        working_domain="mag",
        extrema_mode="min",
        use_weights=True,
    )
    assert fit.ok is False
    assert "lack" in (fit.fail_reason or "").lower()


def test_weights_succeed_with_finite_errors():
    """Inverse-variance weights with a complete error column still recover ToM."""
    t, y = _mag_eclipse()
    err = np.full_like(y, 0.01)
    fit = fit_interval(
        t,
        y,
        err,
        float(t.min()),
        float(t.max()),
        working_domain="mag",
        extrema_mode="min",
        use_weights=True,
    )
    assert fit.ok, fit.fail_reason
    assert abs(fit.t_ext - 2451000.10) < 1e-5


def test_vertex_outside_interval_fails():
    """A window entirely to one side of the vertex is rejected."""
    t0 = 2451000.00
    t = np.linspace(2451000.08, 2451000.20, 30)
    y = 12.0 - 25.0 * (t - t0) ** 2
    fit = fit_interval(
        t, y, None, float(t.min()), float(t.max()), working_domain="mag", extrema_mode="min"
    )
    assert fit.ok is False
    assert "outside" in (fit.fail_reason or "").lower()
    assert fit.fail_vertex_jd is not None
    from skvo_veb.utils.parabola_tom.review_page import review_entry_from_fit

    row = review_entry_from_fit(fit)
    assert row["is_fail"] is True
    assert "2451000" not in row["error"]
    assert "(MJD)" in row["error"]


def test_wrong_curvature_fails():
    """Search maxima on an eclipse (mag) is rejected by the curvature check."""
    t, y = _mag_eclipse()
    fit = fit_interval(
        t, y, None, float(t.min()), float(t.max()), working_domain="mag", extrema_mode="max"
    )
    assert fit.ok is False
    assert "curvature" in (fit.fail_reason or "").lower()


def test_resolve_max_half_width_d_empty_and_invalid():
    """Empty means no cap; a present non-positive value fails fast."""
    assert resolve_max_half_width_d(None) is None
    assert resolve_max_half_width_d("") is None
    assert resolve_max_half_width_d(0.04) == pytest.approx(0.04)
    with pytest.raises(ValueError, match="positive"):
        resolve_max_half_width_d(0)
    with pytest.raises(ValueError, match="positive"):
        resolve_max_half_width_d(-0.1)


def test_apply_half_width_cap_trims_only_wide_intervals():
    """A cap shorter than the marked half-width trims around the midpoint."""
    lo, hi, capped = apply_half_width_cap(2451000.00, 2451000.20, 0.04)
    assert capped is True
    assert lo == pytest.approx(2451000.06)
    assert hi == pytest.approx(2451000.14)
    lo2, hi2, capped2 = apply_half_width_cap(2451000.00, 2451000.20, 0.15)
    assert capped2 is False
    assert lo2 == pytest.approx(2451000.00)
    assert hi2 == pytest.approx(2451000.20)
    lo3, hi3, capped3 = apply_half_width_cap(2451000.00, 2451000.20, None)
    assert capped3 is False
    assert (lo3, hi3) == (lo2, hi2)


def test_max_half_width_caps_wide_interval_and_keeps_vertex():
    """A wide marked interval is trimmed; ToM still sits at the midpoint eclipse."""
    t, y = _mag_eclipse(n=81)
    fit_full = fit_interval(
        t, y, None, float(t.min()), float(t.max()), working_domain="mag", extrema_mode="min"
    )
    fit_cap = fit_interval(
        t,
        y,
        None,
        float(t.min()),
        float(t.max()),
        working_domain="mag",
        extrema_mode="min",
        max_half_width_d=0.04,
    )
    assert fit_full.ok, fit_full.fail_reason
    assert fit_cap.ok, fit_cap.fail_reason
    assert fit_cap.window_capped is True
    assert fit_full.window_capped is False
    assert fit_cap.n_points < fit_full.n_points
    assert fit_cap.jd_max - fit_cap.jd_min == pytest.approx(0.08)
    assert abs(fit_cap.t_ext - 2451000.10) < 1e-6


def test_max_half_width_leaves_narrow_interval_unchanged():
    """A cap larger than the marked half-width does not shrink the window."""
    t, y = _mag_eclipse()
    fit = fit_interval(
        t,
        y,
        None,
        float(t.min()),
        float(t.max()),
        working_domain="mag",
        extrema_mode="min",
        max_half_width_d=1.0,
    )
    assert fit.ok, fit.fail_reason
    assert fit.window_capped is False
    assert fit.jd_min == pytest.approx(float(t.min()))
    assert fit.jd_max == pytest.approx(float(t.max()))


def test_compact_export_is_parseable_by_oc():
    """Parabola compact .dat is accepted by the shared O-C ToM parser."""
    rows = [
        {"is_fail": False, "jd_peak": 2451000.123456, "jd_peak_std": 0.00015},
        {"is_fail": True},
    ]
    include = [True, False]
    body = format_compact_extrema_dat(
        rows, include, extrema_mode="min", use_weights=False
    )
    records, meta = parse_compact_tom_contents(body)
    assert body.startswith("# Parabola Minimum Results")
    assert "# weights: off" in body
    assert "# max_half_width_d: none" in body
    assert records[0]["jd_ext"] == pytest.approx(2451000.123456)
    assert records[0]["sigma_jd"] == pytest.approx(0.00015)
    assert meta[0] == "# Parabola Minimum Results"
