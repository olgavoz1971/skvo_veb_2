"""Tests for GP prep-plot interval pick bands."""

import pytest

from skvo_veb.utils.gp.prep_interval_bands import (
    build_unfolded_interval_pick_payload,
    interval_shape_name,
    intervals_without_marked_indices,
    prep_interval_band_shape,
    prep_interval_band_shape_style,
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


def test_build_unfolded_interval_pick_payload_respects_jd_window():
    jd0 = 2400000.5
    intervals = [
        [2459000.0, 2459001.0],
        [2459100.0, 2459101.0],
    ]
    payload = build_unfolded_interval_pick_payload(
        intervals,
        time_axis_mode="mjd",
        display_epoch=jd0,
        timescale=None,
        jd_window=(2459099.0, 2459102.0),
    )
    assert len(payload["bands"]) == 1
    assert payload["bands"][0]["i"] == 1


def test_prep_interval_band_shape_style_marked_flag():
    plain = prep_interval_band_shape_style(marked=False)
    marked = prep_interval_band_shape_style(marked=True)
    assert plain["fillcolor"] == "green"
    assert marked["fillcolor"].startswith("rgba(220, 53, 69")
    assert marked["line"]["width"] == 2
    assert plain["editable"] is False
    assert marked["editable"] is False


def test_prep_interval_band_shape_spans_plot_height():
    shape = prep_interval_band_shape(10.0, 11.0, name=interval_shape_name(2))
    assert shape["type"] == "rect"
    assert shape["yref"] == "paper"
    assert (shape["y0"], shape["y1"]) == (0, 1)
    assert (shape["x0"], shape["x1"]) == (10.0, 11.0)
    assert shape["layer"] == "below"
    assert shape["name"] == "gp-int-2"


def test_prep_interval_band_shape_omits_name_when_unnamed():
    """Folded-view bands are never marked, so they carry no shape name."""
    assert "name" not in prep_interval_band_shape(0.1, 0.2)


def test_prep_interval_band_shape_matches_style_helper():
    for marked in (False, True):
        shape = prep_interval_band_shape(0.0, 1.0, marked=marked)
        style = prep_interval_band_shape_style(marked=marked)
        for key, value in style.items():
            assert shape[key] == value


def test_prep_interval_band_shape_accepts_datetime_axis_bounds():
    """Date-axis bounds arrive as ISO strings and must pass through unchanged."""
    shape = prep_interval_band_shape("2023-01-01T00:00:00", "2023-01-02T00:00:00")
    assert shape["x0"] == "2023-01-01T00:00:00"
    assert shape["x1"] == "2023-01-02T00:00:00"


def test_intervals_without_marked_indices():
    intervals = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    out = intervals_without_marked_indices(intervals, [1])
    assert out == [[1.0, 2.0], [5.0, 6.0]]


def test_pick_payload_carries_band_mark_styles():
    """Clientside recolour reads its colours from the payload, not from JS literals."""
    payload = build_unfolded_interval_pick_payload(
        [[2459000.0, 2459001.0]],
        time_axis_mode="mjd",
        display_epoch=2400000.5,
        timescale=None,
    )
    assert payload["styles"]["plain"] == prep_interval_band_shape_style(marked=False)
    assert payload["styles"]["marked"] == prep_interval_band_shape_style(marked=True)


def test_pick_payload_carries_styles_when_no_intervals():
    payload = build_unfolded_interval_pick_payload(
        [],
        time_axis_mode="mjd",
        display_epoch=2400000.5,
        timescale=None,
    )
    assert payload["bands"] == []
    assert payload["styles"]["marked"]["fillcolor"] == "rgba(220, 53, 69, 0.35)"


def test_windowed_pick_payload_band_order_matches_shape_order():
    """Band order must equal drawn-shape order, since the clientside recolour
    maps interval index to shape position by name."""
    jd0 = 2400000.5
    intervals = [
        [2459000.0, 2459001.0],
        [2459100.0, 2459101.0],
        [2459200.0, 2459201.0],
        [2459300.0, 2459301.0],
    ]
    window = (2459050.0, 2459250.0)
    payload = build_unfolded_interval_pick_payload(
        intervals,
        time_axis_mode="mjd",
        display_epoch=jd0,
        timescale=None,
        jd_window=window,
    )
    from skvo_veb.utils.gp.working_window import interval_overlaps_jd_window

    drawn = [
        interval_shape_name(i)
        for i, iv in enumerate(intervals)
        if interval_overlaps_jd_window(iv, window[0], window[1])
    ]
    assert [interval_shape_name(b["i"]) for b in payload["bands"]] == drawn
    assert drawn == ["gp-int-1", "gp-int-2"]
