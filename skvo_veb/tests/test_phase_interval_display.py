"""Tests for JD interval to phase display mapping."""

import pytest

from skvo_veb.utils.lc_bridge import phase_vrect_bounds_for_jd_interval


def test_phase_vrect_simple_interval():
    t0 = 2459000.0
    period = 1.0
    bounds = phase_vrect_bounds_for_jd_interval(
        t0 + 0.2, t0 + 0.5, t0, period
    )
    assert len(bounds) == 1
    assert bounds[0][0] == pytest.approx(0.2)
    assert bounds[0][1] == pytest.approx(0.5)


def test_phase_vrect_wraps_at_phase_one():
    t0 = 2459000.0
    period = 1.0
    bounds = phase_vrect_bounds_for_jd_interval(
        t0 + 0.8, t0 + 1.2, t0, period
    )
    assert len(bounds) == 2
    assert bounds[0][0] == pytest.approx(0.8)
    assert bounds[0][1] == pytest.approx(1.0)
    assert bounds[1][0] == pytest.approx(0.0)
    assert bounds[1][1] == pytest.approx(0.2)
