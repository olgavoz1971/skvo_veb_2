"""MAVKA fit figure uses the same MJD axis convention as the prep plot."""

import numpy as np
import pytest

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD
from skvo_veb.utils.mavka.config import MAVKA_PIECE_COLOURS
from skvo_veb.utils.mavka.figure import figure_from_mavka_result
from skvo_veb.utils.mavka.models import ApproxFitResult, model_curve
from skvo_veb.utils.mavka.pipeline import fit_interval


def test_figure_from_mavka_result_mjd_axis_and_title():
    """TOM label and x coordinates are MJD, not absolute JD."""
    t0 = 2458749.729
    t = np.linspace(t0 - 0.1, t0 + 0.1, 40)
    y = 12.0 + 25.0 * (t - t0) ** 2
    fit = fit_interval("WSAP", t, y, extrema_mode="min")
    assert fit.ok, fit.fail_reason

    fig = figure_from_mavka_result(
        t, y, fit, display_epoch=DEFAULT_EPOCH_JD, invert_y=True
    )
    tom_mjd = fit.t_ext - DEFAULT_EPOCH_JD
    assert f"TOM: {tom_mjd:.2f}" in fig.layout.title.text
    assert " s)" not in fig.layout.title.text
    assert not fig.layout.xaxis.title.text
    assert fig.layout.xaxis.tickformat == ".2f"
    assert float(fig.data[0].x[0]) < 100_000
    assert fig.layout.yaxis.autorange == "reversed"
    y_model = model_curve(fit.method, fit.params, t)
    assert y_model.shape == t.shape
    line_traces = [tr for tr in fig.data if tr.mode == "lines"]
    assert len(line_traces) >= 2
    colours = {tr.line.color for tr in line_traces}
    assert MAVKA_PIECE_COLOURS["core"] in colours


def test_figure_from_mavka_result_rejects_failed_fit():
    """Failed fits have no model curve to plot."""
    fit = ApproxFitResult(
        method="WSAP",
        ok=False,
        t_ext=float("nan"),
        sigma_t_ext=float("nan"),
        y_ext=float("nan"),
        sigma_y_ext=float("nan"),
        c4=float("nan"),
        c5=float("nan"),
        eclipse_duration=float("nan"),
        sigma_duration=float("nan"),
        params=np.asarray([]),
        rms=float("nan"),
        n_points=2,
        fail_reason="Need at least 6 points, got 2",
    )
    with pytest.raises(ValueError, match="failed fit"):
        figure_from_mavka_result(np.array([1.0]), np.array([1.0]), fit)
