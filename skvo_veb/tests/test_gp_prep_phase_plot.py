"""Tests for extended phase prep plot helpers."""

import numpy as np
import pytest

from skvo_veb.utils.gp.prep_phase_plot import (
    EXTENDED_PHASE_XMAX,
    EXTENDED_PHASE_XMIN,
    assert_phase_intervals_not_duplicates,
    build_extended_phase_plot_arrays,
    validate_extended_phase_selection,
)
from skvo_veb.utils.my_tools import PipeException


def test_validate_rejects_wide_selection():
    with pytest.raises(PipeException, match="Ambiguous"):
        validate_extended_phase_selection(-0.5, 1.5)


def test_validate_accepts_narrow_window():
    lo, hi = validate_extended_phase_selection(-0.05, 0.05)
    assert lo == pytest.approx(-0.05)
    assert hi == pytest.approx(0.05)


def test_duplicate_intervals_rejected():
    existing = [[100.0, 101.0]]
    new = [[100.0, 101.0]]
    with pytest.raises(PipeException, match="already registered"):
        assert_phase_intervals_not_duplicates(new, existing)


def test_extended_plot_triples_points_in_range():
    period = 1.0
    t0 = 0.0
    x_jd = np.array([0.1, 0.6])
    y = np.array([1.0, 2.0])
    x_out, y_out, _ = build_extended_phase_plot_arrays(x_jd, y, None, t0, period)
    assert len(x_out) >= 4
    assert np.min(x_out) >= EXTENDED_PHASE_XMIN - 0.01
    assert np.max(x_out) <= EXTENDED_PHASE_XMAX + 0.01
