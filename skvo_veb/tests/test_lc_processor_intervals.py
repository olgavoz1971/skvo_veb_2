"""Tests for processor rough-extrema intervals and uploaded reference marks."""

from __future__ import annotations

import pytest

from skvo_veb.utils.lc_processor.intervals import (
    add_manual_interval,
    build_processor_interval_pick_payload,
    format_cached_intervals_download,
    generate_intervals_from_extrema,
    interval_shape_name,
    intervals_as_pairs,
    intervals_without_marked_ids,
    parse_uploaded_extrema_jds,
    processor_interval_band_shapes,
    remove_interval_near_time,
)


def test_parse_uploaded_extrema_jds_with_jd0():
    """Parses relative JD rows against an explicit JD0 comment."""
    text = "# JD0 = 2400000.5\n100.0\n101.5\n"
    payload = parse_uploaded_extrema_jds(text)
    assert payload["jd0"] == 2400000.5
    assert payload["times_jd"] == [2400100.5, 2400102.0]


def test_parse_uploaded_extrema_jds_absolute_when_no_jd0():
    """Treats bare numbers as absolute JD when JD0 is absent."""
    text = "2458000.1\n2458001.2\n"
    payload = parse_uploaded_extrema_jds(text)
    assert payload["jd0"] == 0.0
    assert payload["times_jd"] == [2458000.1, 2458001.2]


def test_parse_uploaded_extrema_ignores_extra_columns():
    """Keeps only the first column; σ / labels / commas are ignored."""
    text = (
        "# JD0 = 0\n"
        "2458000.1  nan  max\n"
        "2458001.2,0.01,flag\n"
        "2458002.3\t0.02\n"
    )
    payload = parse_uploaded_extrema_jds(text)
    assert payload["times_jd"] == [2458000.1, 2458001.2, 2458002.3]


def test_parse_uploaded_extrema_rejects_empty_and_bad_rows():
    """Fails fast on empty files and non-numeric first columns."""
    with pytest.raises(ValueError, match="no JD rows"):
        parse_uploaded_extrema_jds("# comment only\n")
    with pytest.raises(ValueError, match="first column must be a Julian Date"):
        parse_uploaded_extrema_jds("not-a-number 1.0\n")
    with pytest.raises(ValueError, match="first column must be a Julian Date"):
        parse_uploaded_extrema_jds("2458087.288.0.20 \n")


def test_generate_add_remove_and_export_sorted():
    """Generates from extrema, keeps manual edits, exports sorted survivors."""
    extrema = {
        "hits": [
            {"jd": 2458002.0},
            {"jd": 2458000.0},
        ]
    }
    generated = generate_intervals_from_extrema(extrema, delta_time_d=0.1)
    pairs = intervals_as_pairs(generated)
    assert pairs == [[2457999.9, 2458000.1], [2458001.9, 2458002.1]]

    with_manual = add_manual_interval(
        generated, start_jd=2458005.5, end_jd=2458005.0
    )
    assert intervals_as_pairs(with_manual)[-1] == [2458005.0, 2458005.5]

    trimmed, removed = remove_interval_near_time(
        with_manual, jd=2458000.0, hit_window_d=0.2
    )
    assert removed is True
    assert intervals_as_pairs(trimmed) == [
        [2458001.9, 2458002.1],
        [2458005.0, 2458005.5],
    ]

    body = format_cached_intervals_download(
        trimmed,
        source_file="demo.dat",
        extrema_payload={"kind": "min"},
    )
    assert "demo.dat" in body
    lines = [ln for ln in body.splitlines() if ln and not ln.startswith("#")]
    assert lines[0].startswith("2458001.9")
    assert lines[1].startswith("2458005.0")


def test_export_fails_without_intervals():
    """Export refuses an empty interval cache."""
    with pytest.raises(ValueError, match="No intervals to export"):
        format_cached_intervals_download({"intervals": []})


def test_add_manual_interval_rejects_duplicate_window():
    """Refuses a second interval with the same start and end."""
    first = add_manual_interval(None, start_jd=2458000.0, end_jd=2458000.2)
    with pytest.raises(ValueError, match="already in the list"):
        add_manual_interval(first, start_jd=2458000.2, end_jd=2458000.0)


def test_intervals_without_marked_ids_keeps_unmarked():
    """Drops only the marked ids; sort order of survivors is unchanged."""
    payload = generate_intervals_from_extrema(
        {"hits": [{"jd": 2458000.0}, {"jd": 2458002.0}]},
        delta_time_d=0.1,
    )
    rows = payload["intervals"]
    assert len(rows) == 2
    trimmed = intervals_without_marked_ids(payload, [rows[0]["id"]])
    assert intervals_as_pairs(trimmed) == [[2458001.9, 2458002.1]]


def test_processor_interval_band_shapes_name_by_id():
    """Band shape names use the interval id so marks survive a re-sort."""
    payload = add_manual_interval(None, start_jd=2458001.0, end_jd=2458001.5)
    interval_id = payload["intervals"][0]["id"]
    shapes = processor_interval_band_shapes(
        payload, time_axis_mode="mjd", display_epoch=2400000.5
    )
    assert len(shapes) == 1
    assert shapes[0]["name"] == interval_shape_name(interval_id)
    assert shapes[0]["name"].startswith("lcp-int-")
    pick = build_processor_interval_pick_payload(
        payload,
        time_axis_mode="mjd",
        display_epoch=2400000.5,
    )
    assert pick["enabled"] is True
    assert pick["bands"][0]["id"] == interval_id
    marked = processor_interval_band_shapes(
        payload,
        time_axis_mode="mjd",
        display_epoch=2400000.5,
        marked_ids=[interval_id],
    )
    assert marked[0]["line"]["color"] == "#dc3545"


def test_figure_horizontal_interval_select_matches_gp_layout():
    """Interval control uses GP-style horizontal box select on plot 1."""
    import numpy as np

    from skvo_veb.utils.lc_processor.figures import figure_raw_with_trend

    times = np.array([2459000.0, 2459000.5, 2459001.0])
    fig = figure_raw_with_trend(
        times,
        np.array([1.0, 0.8, 1.0]),
        None,
        None,
        y_label="Flux",
        invert_y=False,
        show_errors=False,
        uirevision="test",
        horizontal_interval_select=True,
    )
    assert fig.layout.selectdirection == "h"
    obs = next(t for t in fig.data if t.name == "observed")
    assert obs.selected.marker.color == "green"
    assert obs.unselected.marker.opacity == 0.7
