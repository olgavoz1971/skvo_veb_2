"""Tests for Lightcurve processor view copies and export stems."""

from __future__ import annotations

import numpy as np
import pytest

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.gp.export import suggested_lc_export_stem
from skvo_veb.utils.lc_config import DOMAIN_FLUX
from skvo_veb.utils.lc_processor.view import (
    crop_curvedash_copy,
    display_mjd_to_absolute_jd,
    selected_perm_indices,
)


def _sample_lcd() -> CurveDash:
    """Builds a four-point flux curve for crop tests.

    Returns:
        CurveDash: Tiny working curve.
    """
    jd = np.array([2459000.0, 2459000.5, 2459001.0, 2459001.5])
    flux = np.array([1.0, 2.0, 3.0, 4.0])
    return CurveDash(
        jd=jd,
        flux=flux,
        flux_err=np.full_like(flux, 0.1),
        name="TIC 1",
        active_domain=DOMAIN_FLUX,
    )


def test_suggested_lc_export_stem_appends_lc():
    """Default export stem is ``{name}_lc`` and does not duplicate the suffix."""
    assert suggested_lc_export_stem("tcp.vot") == "tcp_lc"
    assert suggested_lc_export_stem("tcp_lc.dat") == "tcp_lc"
    assert suggested_lc_export_stem(None) == "lightcurve_lc"


def test_crop_preserves_perm_index_and_leaves_source_intact():
    """Plot crop is a copy; selection ids still match the cached series."""
    lcd = _sample_lcd()
    original_n = len(lcd.lightcurve)
    view = crop_curvedash_copy(lcd, 2459000.4, 2459001.1)
    assert len(view.lightcurve) == 2
    assert list(view.lightcurve["perm_index"]) == [1, 2]
    assert len(lcd.lightcurve) == original_n


def test_crop_empty_and_inverted_fail_fast():
    """An empty or inverted crop is an error, not a silent full series."""
    lcd = _sample_lcd()
    with pytest.raises(ValueError, match="t min"):
        crop_curvedash_copy(lcd, 2459002.0, 2459000.0)
    with pytest.raises(ValueError, match="No points remain"):
        crop_curvedash_copy(lcd, 2459100.0, 2459200.0)


def test_apply_smooth_median_returns_trend_only():
    """Apply smooth is a trend at the observation times, not a residual."""
    from skvo_veb.utils.lc_processor.smooth import apply_smooth_method

    times = np.linspace(2459000.0, 2459010.0, 50)
    values = np.ones(50)
    trend = apply_smooth_method(
        times,
        values,
        None,
        method="median",
        break_tolerance=None,
        median_window_days=2.0,
        n_points=5,
        polyorder=2,
        smoothing_s=None,
        smoothing_rel=0.05,
        knots=np.asarray([], dtype=float),
        penalty_lambda=1.0,
        n_segments=4,
    )
    assert trend.shape == values.shape
    assert np.allclose(trend, 1.0)


def test_lsq_fit_requires_placed_knots():
    """Least-squares smooth does not invent a knot grid on Apply."""
    from skvo_veb.utils.lc_processor.apply import fit_smooth_overlay

    lcd = _sample_lcd()
    with pytest.raises(ValueError, match="Place knots first"):
        fit_smooth_overlay(
            lcd,
            method="spline_lsq",
            domain=DOMAIN_FLUX,
            split_gaps=False,
            break_tol=5.0,
            t_min=None,
            t_max=None,
            median_window=2.0,
            n_points=5,
            n_points_biweight=5,
            polyorder=2,
            smooth_rel=0.05,
            smooth_s=None,
            knots=[],
            n_knots=2,
            knot_grid_mode="uniform",
            penalty_lambda=1.0,
            n_segments=4,
        )


def test_knot_layout_shapes_are_vertical_lines():
    """Knot edits must be layout shapes, not a new photometry trace."""
    from skvo_veb.utils.lc_processor.figures import knot_layout_shapes

    shapes = knot_layout_shapes([2459000.5], time_axis_mode="mjd")
    assert len(shapes) == 1
    assert shapes[0]["type"] == "line"
    assert shapes[0]["x0"] == shapes[0]["x1"]
    assert knot_layout_shapes([], time_axis_mode="mjd") == []


def test_working_figure_uses_gp_scatter_marker():
    """Processor photometry uses the GP prep Scattergl marker, not Discovery px."""
    from skvo_veb.utils.lc_processor.figures import figure_raw_with_trend

    lcd = _sample_lcd()
    fig = figure_raw_with_trend(
        np.asarray(lcd.jd, dtype=float),
        np.asarray(lcd.phot, dtype=float),
        np.asarray(lcd.phot_err, dtype=float),
        None,
        y_label="Flux",
        invert_y=False,
        show_errors=False,
        uirevision="test",
    )
    assert fig.data[0].type == "scattergl"
    assert fig.data[0].marker.size == 4
    assert fig.data[0].marker.color == "blue"
    assert fig.data[0].marker.opacity == 0.7
    assert fig.layout.font.size == 12
    assert fig.layout.margin.t == 20


def test_single_label_uses_gp_scatter_marker():
    """One label type must stay GP-blue at opacity 0.7, not the qualitative palette."""
    from skvo_veb.utils.lc_processor.figures import figure_raw_with_trend

    lcd = _sample_lcd()
    fig = figure_raw_with_trend(
        np.asarray(lcd.jd, dtype=float),
        np.asarray(lcd.phot, dtype=float),
        np.asarray(lcd.phot_err, dtype=float),
        None,
        y_label="Flux",
        invert_y=False,
        show_errors=False,
        uirevision="test",
        labels=["V"] * len(lcd.jd),
    )
    assert fig.data[0].marker.color == "blue"
    assert fig.data[0].marker.opacity == 0.7
    assert fig.layout.showlegend is False


def test_display_mjd_and_selected_indices():
    """Crop widgets are display MJD; selection reads the ``selected`` column."""
    assert display_mjd_to_absolute_jd(None) is None
    assert display_mjd_to_absolute_jd(59000.0) == pytest.approx(2459000.5)
    lcd = _sample_lcd()
    assert selected_perm_indices(lcd) == []
    lcd.lightcurve.loc[lcd.lightcurve["perm_index"] == 2, "selected"] = 1
    assert selected_perm_indices(lcd) == [2]
