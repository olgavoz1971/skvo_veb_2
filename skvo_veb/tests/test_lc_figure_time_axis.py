"""Tests for shared Plotly time-axis coordinate helpers."""

import numpy as np
import pytest

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, TIME_AXIS_DATE, TIME_AXIS_MJD
from skvo_veb.utils.lc_figure import (
    absolute_jd_to_plot_x,
    format_timesys_axis_suffix,
    maybe_interval_observations_figure,
    time_axis_xaxis_title,
)


def test_absolute_jd_to_plot_x_mjd_offset():
    """MJD plot coordinates subtract the display epoch."""
    jd = np.array([DEFAULT_EPOCH_JD + 100.0, DEFAULT_EPOCH_JD + 200.25])
    out = absolute_jd_to_plot_x(jd, TIME_AXIS_MJD, DEFAULT_EPOCH_JD)
    np.testing.assert_allclose(out, [100.0, 200.25])


def test_absolute_jd_to_plot_x_scalar_mjd():
    """Scalar JD maps to a single MJD offset."""
    assert absolute_jd_to_plot_x(DEFAULT_EPOCH_JD + 52500.0, TIME_AXIS_MJD) == pytest.approx(
        52500.0
    )


def test_time_axis_xaxis_title_modes():
    """Axis titles distinguish MJD and calendar date; TIMESYS is optional."""
    assert time_axis_xaxis_title(TIME_AXIS_MJD) == "MJD"
    assert time_axis_xaxis_title(TIME_AXIS_DATE) == "Date"
    assert time_axis_xaxis_title(TIME_AXIS_MJD, "TCB", "BARYCENTER") == (
        "MJD (TCB, BARYCENTER)"
    )
    assert time_axis_xaxis_title(TIME_AXIS_MJD, numeric_scale_label="JD") == "JD"
    assert time_axis_xaxis_title(
        TIME_AXIS_MJD, "TCB", None, numeric_scale_label="JD-2450000"
    ) == "JD-2450000 (TCB)"
    assert time_axis_xaxis_title(TIME_AXIS_DATE, numeric_scale_label="JD") == "Date"


def test_format_timesys_axis_suffix():
    """Suffix lists timescale and reference position from VOTable TIMESYS."""
    assert format_timesys_axis_suffix("tcb", "barycenter") == " (TCB, BARYCENTER)"


def test_maybe_interval_observations_figure_mjd_scatter():
    """Failed-interval plots show MJD points and no model line."""
    t = np.array([DEFAULT_EPOCH_JD + 10.0, DEFAULT_EPOCH_JD + 10.1])
    y = np.array([12.1, 12.2])
    fig = maybe_interval_observations_figure(
        t, y, display_epoch=DEFAULT_EPOCH_JD, invert_y=True, y_label="Magnitude"
    )
    assert fig is not None
    assert "Fit failed" in fig.layout.title.text
    assert float(fig.data[0].x[0]) == pytest.approx(10.0)
    assert fig.data[0].mode == "markers"
    assert len(fig.data) == 1
    assert fig.layout.yaxis.autorange == "reversed"


def test_maybe_interval_observations_figure_empty_is_none():
    """No finite points means no figure, not an empty axis."""
    t = np.array([np.nan, np.nan])
    y = np.array([1.0, 2.0])
    assert maybe_interval_observations_figure(t, y) is None
