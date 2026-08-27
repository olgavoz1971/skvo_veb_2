"""Tests for extended phase prep plot helpers."""

import numpy as np
import pytest

from skvo_veb.utils.gp.prep_phase_plot import (
    EXTENDED_PHASE_XMAX,
    EXTENDED_PHASE_XMIN,
    assert_phase_intervals_not_duplicates,
    build_extended_phase_plot_arrays,
    merge_overlapping_phase_segments,
    phase_vrect_bounds_extended,
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


def test_merge_overlapping_phase_segments_collapses_stacked_copies():
    """Many nearly-identical minima become a handful of unique phase bands."""
    period = 0.05937839
    t0 = 2459853.0
    intervals = [[t0 + i * period - 0.01, t0 + i * period + 0.01] for i in range(50)]
    raw = []
    for start, end in intervals:
        raw.extend(phase_vrect_bounds_extended(start, end, t0, period))
    merged = merge_overlapping_phase_segments(raw)
    assert len(raw) > 50
    assert len(merged) <= 4
    for lo, hi in merged:
        assert lo < hi
        assert hi - lo < 0.5


def test_merge_overlapping_phase_segments_keeps_disjoint_ranges():
    merged = merge_overlapping_phase_segments(
        [(0.1, 0.2), (0.8, 0.9), (0.15, 0.22)]
    )
    assert len(merged) == 2
    assert merged[0] == pytest.approx((0.1, 0.22))
    assert merged[1] == pytest.approx((0.8, 0.9))


def test_merge_overlapping_phase_segments_empty():
    assert merge_overlapping_phase_segments([]) == []
