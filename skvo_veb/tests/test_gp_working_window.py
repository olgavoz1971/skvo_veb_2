"""Tests for GP prep working time window helpers."""

import json

import numpy as np
import pytest

from skvo_veb.utils.gp.working_window import (
    WORKING_WINDOW_DISABLED,
    build_working_window_store,
    clip_transport_json_to_jd_window,
    filter_plot_arrays_by_jd_window,
    interval_overlaps_jd_window,
    normalize_working_window,
    transport_json_for_prep_export,
)
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD
from skvo_veb.utils.lc_bridge import get_intervals_from_phase
from skvo_veb.utils.my_tools import PipeException


def _minimal_transport(times, jd0=0.0):
    return json.dumps(
        {
            "meta": {"jd0": jd0},
            "schema": {"error": None},
            "data": [[t - jd0, 1.0, None, 0] for t in times],
        }
    )


def test_normalize_working_window_disabled_by_default():
    assert normalize_working_window(WORKING_WINDOW_DISABLED) is None
    assert normalize_working_window({"enabled": False}) is None


def test_filter_plot_arrays_by_jd_window():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    y = np.array([10.0, 20.0, 30.0, 40.0])
    xf, yf, _ = filter_plot_arrays_by_jd_window(x, y, None, 1.5, 3.5)
    np.testing.assert_array_equal(xf, [2.0, 3.0])
    np.testing.assert_array_equal(yf, [20.0, 30.0])


def test_build_working_window_rejects_empty_range():
    lc = _minimal_transport([2459000.0, 2459010.0])
    with pytest.raises(PipeException):
        build_working_window_store(2459005.0, 2459005.0, lc)


def test_build_working_window_full_span_disables():
    lc = _minimal_transport([2459000.0, 2459010.0])
    store = build_working_window_store(2459000.0, 2459010.0, lc)
    assert store["enabled"] is False


def test_get_intervals_from_phase_respects_observation_bounds():
    jd0 = DEFAULT_EPOCH_JD
    t0 = jd0 + 100.0
    times = [t0 + i * 1.0 for i in range(10)]
    lc = _minimal_transport(times, jd0=0.0)
    period = 2.5
    epoch = t0
    full = get_intervals_from_phase(lc, 0.0, 0.2, period, epoch=epoch)
    clipped = get_intervals_from_phase(
        lc,
        0.0,
        0.2,
        period,
        epoch=epoch,
        observation_jd_bounds=(t0 + 2.0, t0 + 5.0),
    )
    assert len(clipped) <= len(full)
    for seg in clipped:
        assert seg[0] >= t0 + 2.0 - 1e-6
        assert seg[1] <= t0 + 5.0 + 1e-6


def test_interval_overlaps_jd_window():
    assert interval_overlaps_jd_window([1.0, 5.0], 2.0, 3.0)
    assert not interval_overlaps_jd_window([1.0, 2.0], 5.0, 6.0)


def test_clip_transport_json_to_jd_window():
    lc = _minimal_transport([2459000.0, 2459010.0, 2459020.0])
    clipped = clip_transport_json_to_jd_window(lc, 2459005.0, 2459015.0)
    data = json.loads(clipped)["data"]
    assert len(data) == 1
    assert data[0][0] == 2459010.0


def test_transport_json_for_prep_export_full_when_disabled():
    lc = _minimal_transport([2459000.0, 2459010.0])
    assert transport_json_for_prep_export(lc, WORKING_WINDOW_DISABLED) == lc

