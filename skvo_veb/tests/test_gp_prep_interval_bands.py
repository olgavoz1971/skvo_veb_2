"""Tests for GP prep-plot interval pick bands."""

import pytest

from skvo_veb.utils.gp.prep_interval_bands import (
    build_unfolded_interval_pick_payload,
    interval_shape_name,
    intervals_without_marked_indices,
)


def test_interval_shape_name():
    assert interval_shape_name(3) == "gp-int-3"


def test_build_unfolded_interval_pick_payload_mjd():
    jd0 = 2400000.5
    intervals = [[2459000.0, 2459001.0]]
    payload = build_unfolded_interval_pick_payload(
        intervals,
        time_axis_mode="mjd",
        display_epoch=jd0,
        timescale=None,
    )
    assert payload["enabled"] is True
    assert len(payload["bands"]) == 1
    assert payload["bands"][0]["i"] == 0
    assert payload["bands"][0]["x0"] == pytest.approx(58999.5)
    assert payload["bands"][0]["x1"] == pytest.approx(59000.5)


def test_intervals_without_marked_indices():
    intervals = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    out = intervals_without_marked_indices(intervals, [1])
    assert out == [[1.0, 2.0], [5.0, 6.0]]
