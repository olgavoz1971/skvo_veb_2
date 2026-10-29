"""Synthetic-truth tests of the Mikulasek engine (global fit and virtual minima)."""

from __future__ import annotations

import numpy as np
import pytest

from mikulasek_eb import EBModel, fit_global, phase, virtual_minima

SEED = 20261029
PERIOD_D = 0.5
M0_D = 0.123
SPAN_D = 20.0
CADENCE_D = 6.0 / 1440.0
NOISE_MAG = 0.002
NSIGMA_TOLERANCE = 5.0
TRUE_PARAMS = dict(A1=0.40, A2=0.30, D1=0.04, G1=1.5, C1=0.0, H2=0.05)
FREE_TEMPLATE = ["A1", "A2", "D1", "G1", "H2"]
START_PERTURBATION = dict(A1=0.9, A2=1.2, D1=1.3, G1=0.8, H2=0.6)
GAP_START_D = 8.0
GAP_END_D = 9.2
M0_OFFSET_D = 0.004
TIMING_SIGMA_TOLERANCE = 3.0


def _make_lightcurve(gap: tuple[float, float] | None = None):
    """Generate a noisy synthetic light curve from the true model.

    Args:
        gap (tuple[float, float] | None): Optional (start, end) time interval
            (days) to remove from the series.

    Returns:
        tuple: ``(t, mag, sig, model)`` with times in days from zero.
    """
    rng = np.random.default_rng(SEED)
    t = np.arange(0.0, SPAN_D, CADENCE_D)
    if gap is not None:
        t = t[(t < gap[0]) | (t > gap[1])]
    model = EBModel(profile=1, harmonics=(2,), ocon=False)
    theta = phase(t, M0_D, PERIOD_D)
    mag = model(theta, TRUE_PARAMS) + rng.normal(0.0, NOISE_MAG, len(t))
    sig = np.full(len(t), NOISE_MAG)
    return t, mag, sig, model


def test_global_fit_recovers_truth():
    """Free template and ephemeris parameters are recovered within errors."""
    t, mag, sig, model = _make_lightcurve()
    start = {k: (v * START_PERTURBATION[k] if k in START_PERTURBATION else v)
             for k, v in TRUE_PARAMS.items()}
    res = fit_global(t, mag, sig, model, start, FREE_TEMPLATE,
                     dict(M0=M0_D, P0=PERIOD_D), order=0)
    assert res.success
    assert not res.rank_deficient
    for name in FREE_TEMPLATE:
        assert abs(res.p[name] - TRUE_PARAMS[name]) < NSIGMA_TOLERANCE * res.err[name], name
    assert abs(res.ephem["M0"] - M0_D) < NSIGMA_TOLERANCE * res.err["M0"]
    assert abs(res.ephem["P0"] - PERIOD_D) < NSIGMA_TOLERANCE * res.err["P0"]


def test_virtual_minima_recover_injected_offset():
    """A wrong ephemeris zero point appears as a common shift of all timings."""
    t, mag, sig, model = _make_lightcurve()
    wrong = dict(M0=M0_D + M0_OFFSET_D, P0=PERIOD_D)
    vm = virtual_minima(t, mag, sig, model, TRUE_PARAMS, wrong, window=0.25, order=1)
    assert len(vm["T"]) > 60
    mean_delta = float(np.mean(vm["delta"]))
    mean_err = float(np.std(vm["delta"]) / np.sqrt(len(vm["delta"])))
    assert abs(abs(mean_delta) - M0_OFFSET_D) < TIMING_SIGMA_TOLERANCE * max(mean_err, 1e-6)


def test_virtual_minima_reports_gap_rejections():
    """Events inside a data gap are listed in ``rejected`` with a reason."""
    t, mag, sig, model = _make_lightcurve(gap=(GAP_START_D, GAP_END_D))
    rejected: list = []
    vm = virtual_minima(t, mag, sig, model, TRUE_PARAMS,
                        dict(M0=M0_D, P0=PERIOD_D), window=0.25, order=1,
                        rejected=rejected)
    assert rejected, "events inside the gap must be reported"
    reasons = {row["reason"] for row in rejected}
    assert reasons <= {"too_few_points", "one_side_uncovered", "walls_uncovered", "fit_failed"}
    rejected_e = {row["E"] for row in rejected}
    assert rejected_e.isdisjoint(set(vm["E"].tolist()))
    for e in rejected_e:
        centre_d = M0_D + PERIOD_D * e
        assert GAP_START_D - PERIOD_D < centre_d < GAP_END_D + PERIOD_D


@pytest.mark.parametrize("window", [0.25, 0.15])
def test_virtual_minima_sigma_calibrated(window):
    """Formal timing errors are of the right size on white noise (std(z) near 1)."""
    t, mag, sig, model = _make_lightcurve()
    vm = virtual_minima(t, mag, sig, model, TRUE_PARAMS,
                        dict(M0=M0_D, P0=PERIOD_D), window=window, order=1)
    z = vm["delta"] / vm["sigma"]
    assert 0.5 < float(np.std(z)) < 1.6
