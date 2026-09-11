"""Tests for linear O-C period/epoch correction."""

from __future__ import annotations

import numpy as np
import pytest

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, display_epoch_offset
from skvo_veb.utils.oc.compute import compute_step1_oc
from skvo_veb.utils.oc.period_correct import (
    correct_period_from_oc_payload,
    cycle_range_from_relayout,
    inverse_variance_weights,
    mask_by_cycle_range,
)


def _payload_from_true_ephemeris(
    *,
    t0: float,
    p_true: float,
    p_trial: float,
    n: int = 20,
    sigma: float | None = 0.0001,
) -> dict:
    """Builds a Step 1 O-C payload from evenly spaced true maxima.

    Args:
        t0 (float): True epoch as absolute JD.
        p_true (float): True period in days.
        p_trial (float): Trial period used to compute O-C.
        n (int): Number of maxima.
        sigma (float | None): Constant timing σ, or ``None`` for missing σ.

    Returns:
        dict: ``compute_step1_oc`` payload.
    """
    cycle_e = np.arange(n, dtype=float)
    jd_ext = t0 + cycle_e * p_true
    records = [
        {
            "jd_ext": float(jd),
            "sigma_jd": float("nan") if sigma is None else float(sigma),
        }
        for jd in jd_ext
    ]
    return compute_step1_oc(records, t0_jd=t0, p0=p_trial, source="gp")


def test_correct_period_recovers_true_p_from_oc_vs_jd_slope():
    """``P / (1 - S)`` recovers the true period when E is held fixed."""
    t0 = 2458749.0
    p_true = 0.5
    p_trial = 0.499
    payload = _payload_from_true_ephemeris(t0=t0, p_true=p_true, p_trial=p_trial)
    result = correct_period_from_oc_payload(payload)
    assert result["n_points"] == 20
    assert result["p_corrected"] == pytest.approx(p_true, rel=1e-10)
    assert result["t0_corrected_jd"] == pytest.approx(t0, abs=1e-8)
    assert result["delta_p"] == pytest.approx(p_true - p_trial, rel=1e-8)
    assert abs(result["slope_oc_vs_jd"]) < 1e-8


def test_correct_period_window_requires_two_points():
    """A cycle window with fewer than two points fails fast."""
    payload = _payload_from_true_ephemeris(
        t0=2458749.0, p_true=0.5, p_trial=0.5, n=5
    )
    with pytest.raises(ValueError, match="at least 2 O-C points"):
        correct_period_from_oc_payload(payload, e_min=2.0, e_max=2.0)


def test_correct_period_rejects_abs_slope_ge_one():
    """``|S| ≥ 1`` cannot be inverted to a corrected period."""
    t0 = 2458749.0
    records = [
        {"jd_ext": t0 + 0.0, "sigma_jd": 0.001},
        {"jd_ext": t0 + 1.0, "sigma_jd": 0.001},
        {"jd_ext": t0 + 2.0, "sigma_jd": 0.001},
    ]
    payload = compute_step1_oc(records, t0_jd=t0, p0=1.0, source="gp")
    payload["E"] = [2.0, 1.0, 0.0]
    payload["OC"] = [
        float(jd - t0 - e * 1.0)
        for jd, e in zip(payload["jd_ext"], payload["E"])
    ]
    with pytest.raises(ValueError, match=r"\|S\|"):
        correct_period_from_oc_payload(payload)


def test_correct_period_rejects_single_cycle_number():
    """A window whose points share one cycle cannot define a period slope."""
    t0 = 2458749.0
    records = [
        {"jd_ext": t0 + 0.0, "sigma_jd": 0.001},
        {"jd_ext": t0 + 0.01, "sigma_jd": 0.001},
    ]
    payload = compute_step1_oc(records, t0_jd=t0, p0=1.0, source="gp")
    payload["E"] = [0.0, 0.0]
    with pytest.raises(ValueError, match="distinct cycle"):
        correct_period_from_oc_payload(payload)


def test_proposed_epoch_is_absolute_jd():
    """Corrected epoch is an absolute JD; display MJD is an offset from jd0."""
    t0 = 2458749.25
    payload = _payload_from_true_ephemeris(
        t0=t0, p_true=0.4, p_trial=0.399, n=12
    )
    result = correct_period_from_oc_payload(payload)
    assert result["t0_corrected_jd"] == pytest.approx(t0, abs=1e-6)
    assert result["t0_corrected_jd"] > 1e6
    display_mjd = display_epoch_offset(
        result["t0_corrected_jd"], DEFAULT_EPOCH_JD
    )
    assert display_mjd == pytest.approx(t0 - DEFAULT_EPOCH_JD)


def test_mask_by_cycle_range_inclusive():
    """Fit mask keeps endpoints and ignores the rest of the diagram."""
    cycle_e = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    mask = mask_by_cycle_range(cycle_e, 1.0, 3.0)
    assert mask.tolist() == [False, True, True, True, False]


def test_correct_period_uses_only_points_in_cycle_window():
    """Points outside the E window do not enter the linear fit."""
    t0 = 2458749.0
    p_true = 0.5
    p_trial = 0.49
    payload = _payload_from_true_ephemeris(
        t0=t0, p_true=p_true, p_trial=p_trial, n=30
    )
    result = correct_period_from_oc_payload(payload, e_min=5.0, e_max=14.0)
    assert result["n_points"] == 10
    assert result["e_min"] == pytest.approx(5.0)
    assert result["e_max"] == pytest.approx(14.0)
    assert result["p_corrected"] == pytest.approx(p_true, rel=1e-8)
    assert result["line_e"] == [5.0, 14.0]


def test_mixed_finite_sigma_fails_fast():
    """A window that mixes finite and missing σ is not silently reweighted."""
    payload = _payload_from_true_ephemeris(
        t0=2458749.0, p_true=0.5, p_trial=0.5, n=4, sigma=0.001
    )
    payload["sigma_jd"][1] = float("nan")
    with pytest.raises(ValueError, match="Cannot mix"):
        correct_period_from_oc_payload(payload)


def test_all_nonfinite_sigma_is_unweighted():
    """Missing σ on every point is an unweighted fit, not an invented weight."""
    weights = inverse_variance_weights(np.array([np.nan, np.inf]))
    assert weights is None
    payload = _payload_from_true_ephemeris(
        t0=2458749.0, p_true=0.5, p_trial=0.499, n=8, sigma=None
    )
    result = correct_period_from_oc_payload(payload)
    assert result["p_corrected"] == pytest.approx(0.5, rel=1e-8)


def test_cycle_range_from_relayout_reads_e_axis():
    """Visible O-C zoom is cycle number, including the top-axis keys."""
    e_lo, e_hi = cycle_range_from_relayout(
        {"xaxis.range[0]": 120.0, "xaxis.range[1]": 340.0}
    )
    assert e_lo == pytest.approx(120.0)
    assert e_hi == pytest.approx(340.0)
    e_lo, e_hi = cycle_range_from_relayout({"xaxis2.range": [50.0, 10.0]})
    assert e_lo == pytest.approx(10.0)
    assert e_hi == pytest.approx(50.0)
    with pytest.raises(ValueError, match="Zoom the O-C"):
        cycle_range_from_relayout({"xaxis.autorange": True})
    with pytest.raises(ValueError, match="Zoom the O-C"):
        cycle_range_from_relayout(None)
