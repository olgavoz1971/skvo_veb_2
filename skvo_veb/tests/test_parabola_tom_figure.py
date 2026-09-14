"""Parabola fit figure uses the same MJD axis convention as the prep plot."""

import numpy as np
import pytest

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD
from skvo_veb.components.extrema_modeller_appearance import PARABOLA_LINE_COLOUR
from skvo_veb.utils.parabola_tom.figure import (
    figure_from_parabola_observations,
    figure_from_parabola_result,
)
from skvo_veb.utils.parabola_tom.pipeline import ParabolaFitResult, fit_interval


def test_figure_from_parabola_result_mjd_axis_and_title():
    """ToM label and x coordinates are MJD, not absolute JD."""
    t0 = 2458749.729
    t = np.linspace(t0 - 0.1, t0 + 0.1, 40)
    y = 12.0 - 25.0 * (t - t0) ** 2
    fit = fit_interval(
        t, y, None, float(t.min()), float(t.max()), working_domain="mag", extrema_mode="min"
    )
    assert fit.ok, fit.fail_reason

    fig = figure_from_parabola_result(
        t, y, fit, display_epoch=DEFAULT_EPOCH_JD, invert_y=True
    )
    tom_mjd = fit.t_ext - DEFAULT_EPOCH_JD
    assert f"ToM (MJD): {tom_mjd:.2f}" in fig.layout.title.text
    assert not fig.layout.xaxis.title.text
    assert fig.layout.xaxis.tickformat == ".2f"
    assert float(fig.data[0].x[0]) < 100_000
    assert fig.layout.yaxis.autorange == "reversed"
    line_traces = [tr for tr in fig.data if tr.mode == "lines"]
    assert len(line_traces) == 1
    assert line_traces[0].line.color == PARABOLA_LINE_COLOUR


def test_figure_from_parabola_result_rejects_failed_fit():
    """Failed fits have no parabola to plot."""
    nan = float("nan")
    fit = ParabolaFitResult(
        ok=False,
        t_ext=nan,
        sigma_t_ext=nan,
        y_ext=nan,
        curvature=nan,
        rms=nan,
        n_points=2,
        dt_ext=nan,
        t_anchor=nan,
        c0=nan,
        c1=nan,
        c2=nan,
        jd_min=1.0,
        jd_max=2.0,
        extrema_mode="min",
        working_domain="mag",
        use_weights=False,
        fail_reason="Need at least 5 points, got 2",
    )
    with pytest.raises(ValueError, match="failed fit"):
        figure_from_parabola_result(np.array([1.0]), np.array([1.0]), fit)


def test_figure_from_parabola_observations_shows_points():
    """Failed parabola cards can still plot the interval photometry."""
    t = np.array([DEFAULT_EPOCH_JD + 1.0, DEFAULT_EPOCH_JD + 1.1])
    y = np.array([12.0, 12.1])
    fig = figure_from_parabola_observations(t, y, display_epoch=DEFAULT_EPOCH_JD)
    assert fig is not None
    assert "Fit failed" in fig.layout.title.text
    assert fig.data[0].mode == "markers"
    assert len(fig.data) == 1
