"""Tests for shared Plotly time-axis coordinate helpers."""

import numpy as np
import pytest

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, TIME_AXIS_DATE, TIME_AXIS_MJD
from skvo_veb.utils.lc_figure import (
    absolute_jd_to_plot_x,
    format_timesys_axis_suffix,
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


def test_format_timesys_axis_suffix():
    """Suffix lists timescale and reference position from VOTable TIMESYS."""
    assert format_timesys_axis_suffix("tcb", "barycenter") == " (TCB, BARYCENTER)"
