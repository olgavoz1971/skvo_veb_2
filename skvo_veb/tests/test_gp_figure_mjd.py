"""GP fit figure uses the same MJD axis convention as the prep plot."""

from unittest.mock import MagicMock

import numpy as np

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD
from skvo_veb.utils.gp.figure import figure_from_gp_result


def test_figure_from_gp_result_mjd_axis_and_title():
    """Peak label and x coordinates are MJD, not absolute JD."""
    jd_peak = 2458749.729
    mjd_peak = jd_peak - DEFAULT_EPOCH_JD
    gp = MagicMock()
    gp.X_train_ = np.array([[2458749.0], [2458750.0]])
    gp.y_train_ = np.array([1.0, 1.1])
    gp_res = {
        "gp": gp,
        "noise_sigma_norm": 0.01,
        "jd_grid": np.linspace(2458749, 2458750, 10),
        "mean_grid": np.ones(10),
        "std_grid": np.ones(10) * 0.1,
        "jd_peak": jd_peak,
        "jd_peak_std": 0.05,
        "peaks_jd": np.array([jd_peak - 0.01, jd_peak + 0.01]),
        "mean_peak": 1.05,
    }

    fig = figure_from_gp_result(gp_res, display_epoch=DEFAULT_EPOCH_JD)

    assert f"Peak: {mjd_peak:.2f}" in fig.layout.title.text
    assert not fig.layout.xaxis.title.text
    assert fig.layout.xaxis.tickformat == ".2f"
    assert fig.layout.xaxis.exponentformat == "none"
    assert float(fig.data[0].x[0]) < 100_000
