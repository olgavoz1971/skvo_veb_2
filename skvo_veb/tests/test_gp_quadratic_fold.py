"""Tests for quadratic O-C ephemeris folding."""

import json

import numpy as np
import pytest

from skvo_veb.utils.gp.quadratic_fold import (
    continuous_cycles_from_jd,
    get_intervals_from_quadratic_phase,
    jd_from_continuous_cycle,
    phases_from_quadratic_oc,
)
from skvo_veb.utils.my_tools import PipeException


def test_linear_oc_matches_constant_fold():
    """a=0, b=0, c=0 gives standard linear phase."""
    p0 = 1.5
    t0 = 2459000.0
    jd = np.array([t0, t0 + 0.5 * p0, t0 + p0])
    phi = phases_from_quadratic_oc(jd, p0, t0, 0.0, 0.0, 0.0)
    np.testing.assert_allclose(phi, [0.0, 0.5, 0.0], atol=1e-10)


def test_quadratic_round_trip():
    """JD(E) and inverse E(JD) are consistent for a non-zero parabola."""
    p0 = 2.0
    t0 = 2459000.0
    a, b, c = 1e-6, 0.001, 0.01
    e_true = np.array([10.0, 10.25, 10.5])
    jd = jd_from_continuous_cycle(e_true, p0, t0, a, b, c)
    e_back = continuous_cycles_from_jd(jd, p0, t0, a, b, c)
    np.testing.assert_allclose(e_back, e_true, rtol=1e-9)


def test_get_intervals_from_quadratic_phase_clips_window():
    """Phase box maps to JD segments inside the observation window."""
    p0 = 1.0
    t0 = 2459000.0
    a, b, c = 0.0, 0.0, 0.0
    jd_start, jd_end = t0 + 5.2, t0 + 7.8
    intervals = get_intervals_from_quadratic_phase(
        jd_start,
        jd_end,
        0.1,
        0.2,
        p0,
        t0,
        a,
        b,
        c,
    )
    assert intervals
    for seg in intervals:
        assert seg[0] >= jd_start - 1e-6
        assert seg[1] <= jd_end + 1e-6


def test_negative_discriminant_raises():
    """Invalid coefficients fail fast."""
    with pytest.raises(PipeException, match="discriminant"):
        continuous_cycles_from_jd(
            np.array([2458000.0]),
            period=1.0,
            epoch_jd=2459000.0,
            oc_a=1.0,
            oc_b=0.0,
            oc_c=0.0,
        )
