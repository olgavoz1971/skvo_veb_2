"""Tests for Lightcurve processor view copies and export stems."""

from __future__ import annotations

import numpy as np
import pytest

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.gp.export import (
    suggested_detrended_export_stem,
    suggested_intervals_export_stem,
    suggested_lc_export_stem,
    suggested_rough_toms_export_stem,
)
from skvo_veb.utils.lc_config import DOMAIN_FLUX, DOMAIN_MAG
from skvo_veb.utils.lc_processor.view import (
    clear_sector_labels,
    crop_curvedash_copy,
    display_mjd_to_absolute_jd,
    raw_labels,
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


def test_clear_sector_labels_makes_series_unlabelled():
    """Merge sectors writes ``None`` into ``label`` and leaves photometry intact."""
    jd = np.array([2459000.0, 2459000.5, 2459001.0, 2459001.5])
    flux = np.array([1.0, 2.0, 3.0, 4.0])
    lcd = CurveDash(
        jd=jd,
        flux=flux,
        flux_err=np.full_like(flux, 0.1),
        label=["40", "40", "41", "41"],
        name="TIC 1",
        active_domain=DOMAIN_FLUX,
    )
    n_cleared = clear_sector_labels(lcd)
    assert n_cleared == 4
    assert all(value is None for value in raw_labels(lcd))
    assert list(lcd.phot) == [1.0, 2.0, 3.0, 4.0]
    assert clear_sector_labels(lcd) == 0


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


def test_running_parabola_centre_recovers_a_quadratic():
    """A parabola centred on an observation of a global quadratic is exact."""
    from skvo_veb.utils.lc_processor.running_parabola import (
        RunningParabolaConfig,
        evaluate_at_centre,
    )

    times = np.linspace(2459000.0, 2459010.0, 201)
    dt = times - times[0]
    values = 2.0 + 0.3 * dt + 0.02 * dt**2
    err = np.full_like(values, np.nan)
    cfg = RunningParabolaConfig(
        window_width_d=1.0, step_d=0.25, min_points=5, use_weights=False
    )
    mid = times[100]
    got = evaluate_at_centre(times, values, err, mid, cfg=cfg)
    assert got == pytest.approx(float(values[100]), abs=1e-8)


def test_running_parabola_recovers_a_quadratic():
    """A local parabola on a global quadratic must recover T(t_i)."""
    from skvo_veb.utils.lc_processor.smooth import apply_smooth_method

    times = np.linspace(2459000.0, 2459010.0, 201)
    dt = times - times[0]
    values = 2.0 + 0.3 * dt + 0.02 * dt**2
    trend = apply_smooth_method(
        times,
        values,
        None,
        method="running_parabola",
        break_tolerance=None,
        median_window_days=2.0,
        n_points=5,
        polyorder=2,
        smoothing_s=None,
        smoothing_rel=0.05,
        knots=np.asarray([], dtype=float),
        penalty_lambda=1.0,
        n_segments=4,
        rp_window_days=1.0,
        rp_step_days=0.25,
        rp_min_points=5,
        rp_use_weights=False,
    )
    assert trend.shape == values.shape
    interior = slice(10, -10)
    assert np.isfinite(trend[interior]).all()
    assert np.allclose(trend[interior], values[interior], atol=5e-3)


def test_running_parabola_skips_sparse_segment_without_aborting():
    """A one-point gap-split fragment is skipped; the rest still fits."""
    from skvo_veb.utils.lc_processor.smooth import apply_smooth_method

    times = np.concatenate(
        [np.linspace(2459000.0, 2459002.0, 80), np.asarray([2459010.0])]
    )
    values = np.ones(times.size)
    trend = apply_smooth_method(
        times,
        values,
        None,
        method="running_parabola",
        break_tolerance=5.0,
        median_window_days=2.0,
        n_points=5,
        polyorder=2,
        smoothing_s=None,
        smoothing_rel=0.05,
        knots=np.asarray([], dtype=float),
        penalty_lambda=1.0,
        n_segments=4,
        rp_window_days=0.5,
        rp_step_days=0.1,
        rp_min_points=5,
        rp_use_weights=False,
    )
    assert trend.shape == values.shape
    assert np.isfinite(trend[10:-2]).all()
    assert not np.isfinite(trend[-1])


def test_running_parabola_does_not_broadcast_a_single_centre():
    """One surviving window centre is not painted onto the whole night."""
    from skvo_veb.utils.lc_processor.smooth import running_parabola_trend

    times = np.linspace(2459000.0, 2459000.08, 40)
    values = np.linspace(0.0, 0.2, times.size)
    trend = running_parabola_trend(
        times,
        values,
        None,
        window_width_d=0.05,
        step_d=0.05,
        min_points=5,
        use_weights=False,
        break_tolerance=None,
    )
    finite = trend[np.isfinite(trend)]
    assert finite.size > 0
    assert np.unique(np.round(finite, 6)).size > 1


def test_running_parabola_short_night_evaluates_locally():
    """A night shorter than the window still gets local T(t_i), not all-NaN."""
    from skvo_veb.utils.lc_processor.smooth import running_parabola_trend

    times = np.linspace(2459000.0, 2459000.04, 30)
    values = np.ones(times.size)
    trend = running_parabola_trend(
        times,
        values,
        None,
        window_width_d=0.25,
        step_d=0.002,
        min_points=5,
        use_weights=False,
        break_tolerance=None,
    )
    assert np.isfinite(trend[5:-5]).all()
    assert np.allclose(trend[5:-5], 1.0, atol=1e-8)
    assert not np.isfinite(trend[0])
    assert not np.isfinite(trend[-1])


def test_running_parabola_rejects_one_sided_window():
    """A window with points on only one side of the centre is not a fit."""
    from skvo_veb.utils.lc_processor.running_parabola import (
        RunningParabolaConfig,
        evaluate_at_centre,
    )

    times = np.linspace(2459000.0, 2459000.1, 20)
    values = np.ones(times.size)
    err = np.full_like(values, np.nan)
    cfg = RunningParabolaConfig(
        window_width_d=0.25, step_d=0.01, min_points=5, use_weights=False
    )
    with pytest.raises(ValueError, match="one-sided"):
        evaluate_at_centre(times, values, err, float(times[0]), cfg=cfg)


def test_running_parabola_does_not_interp_across_a_wide_hole():
    """Centres more than one window apart do not invent T in the hole."""
    from skvo_veb.utils.lc_processor.smooth import _interp_centres_within_window

    t_obs = np.array([2459000.0, 2459000.5, 2459002.0])
    t_c = np.array([2459000.0, 2459002.0])
    y_c = np.array([0.0, 1.0])
    trend = _interp_centres_within_window(t_obs, t_c, y_c, window_width_d=0.25)
    assert not np.isfinite(trend).any()


def test_trend_line_breaks_at_gap_split():
    """The red overlay inserts a NaN vertex at a gap-split boundary."""
    from skvo_veb.utils.lc_processor.figures import trend_xy_with_gap_breaks

    times = np.array([2459000.0, 2459000.1, 2459005.0])
    trend = np.array([0.1, 0.2, 0.3])
    jd_out, y_out = trend_xy_with_gap_breaks(times, trend, 0.5)
    assert jd_out.size == 4
    assert not np.isfinite(jd_out[2])
    assert not np.isfinite(y_out[2])
    assert y_out[0] == pytest.approx(0.1)
    assert y_out[-1] == pytest.approx(0.3)


def test_figure_raw_with_trend_accepts_date_axis():
    """Date-axis display x is not float-cast when the trend is broken."""
    from datetime import datetime

    from skvo_veb.utils.lc_config import TIME_AXIS_DATE
    from skvo_veb.utils.lc_processor.figures import figure_raw_with_trend

    times = np.array([2459000.0, 2459000.1, 2459005.0])
    fig = figure_raw_with_trend(
        times,
        np.array([1.0, 1.1, 1.2]),
        None,
        np.array([1.0, 1.1, 1.2]),
        y_label="Flux",
        invert_y=False,
        show_errors=False,
        uirevision="test",
        time_axis_mode=TIME_AXIS_DATE,
        break_tolerance=0.5,
    )
    trend = next(trace for trace in fig.data if trace.name == "trend")
    assert isinstance(trend.x[0], datetime)
    assert trend.x[2] is None
    assert not np.isfinite(trend.y[2])


def test_running_parabola_empty_window_fails():
    """Apply does not invent a running-parabola window."""
    from skvo_veb.utils.lc_processor.apply import fit_smooth_overlay

    lcd = _sample_lcd()
    with pytest.raises(ValueError, match="Window"):
        fit_smooth_overlay(
            lcd,
            method="running_parabola",
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
            rp_window="",
            rp_step=0.0125,
            rp_min_points=5,
            rp_use_weights=False,
        )


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


def test_suggested_detrended_export_stem_strips_lc():
    """Detrended files are ``{base}_detrended``, not ``{base}_lc_detrended``."""
    assert suggested_detrended_export_stem("tcp_lc") == "tcp_detrended"
    assert suggested_detrended_export_stem("tcp") == "tcp_detrended"
    assert suggested_detrended_export_stem("tcp_detrended") == "tcp_detrended"
    assert suggested_detrended_export_stem(None) == "lightcurve_detrended"


def test_suggested_extrema_export_stems_strip_lc():
    """Interval and timing files drop ``_lc`` before the product suffix."""
    assert suggested_intervals_export_stem("tcp_lc") == "tcp_int"
    assert suggested_intervals_export_stem("tcp") == "tcp_int"
    assert suggested_intervals_export_stem("tcp_int") == "tcp_int"
    assert suggested_intervals_export_stem(None) == "lightcurve_int"
    assert suggested_rough_toms_export_stem("tcp_lc") == "tcp_rough_toms"
    assert suggested_rough_toms_export_stem("tcp") == "tcp_rough_toms"
    assert suggested_rough_toms_export_stem("tcp_rough_toms") == "tcp_rough_toms"
    assert suggested_rough_toms_export_stem(None) == "lightcurve_rough_toms"


def test_detrend_observed_subtracts_mag_and_divides_flux():
    """Screen-domain residual: magnitudes subtract; flux divides."""
    from skvo_veb.utils.lc_processor.smooth import detrend_observed

    observed = np.array([12.0, 11.0, 10.0])
    trend = np.array([11.0, 11.0, 11.0])
    assert np.allclose(detrend_observed(observed, trend, "mag"), [1.0, 0.0, -1.0])
    assert np.allclose(detrend_observed(observed, trend, "flux"), observed / trend)


def test_detrend_observed_rejects_finite_non_positive_flux_trend():
    """A finite non-positive flux trend cannot be a divisor."""
    from skvo_veb.utils.lc_processor.smooth import detrend_observed

    observed = np.array([1.0, 2.0])
    with pytest.raises(ValueError, match="strictly positive"):
        detrend_observed(observed, np.array([1.0, 0.0]), "flux")
    with pytest.raises(ValueError, match="strictly positive"):
        detrend_observed(observed, np.array([1.0, -0.2]), "flux")


def test_detrend_observed_keeps_nan_trend_as_nan_residual():
    """A missing flux trend stays non-finite; it does not abort the series."""
    from skvo_veb.utils.lc_processor.smooth import detrend_observed

    observed = np.array([1.0, 2.0, 3.0])
    trend = np.array([1.0, np.nan, 1.5])
    residual = detrend_observed(observed, trend, "flux")
    assert residual[0] == pytest.approx(1.0)
    assert not np.isfinite(residual[1])
    assert residual[2] == pytest.approx(2.0)


def _smooth_payload(lcd: CurveDash, trend: np.ndarray, *, method: str = "median") -> dict:
    """Builds a matching overlay payload for Apply-detrend tests.

    Args:
        lcd (CurveDash): Working curve.
        trend (numpy.ndarray): Trend at the observation times.
        method (str): Smooth method id stored on the payload.

    Returns:
        dict: Session-cache overlay.
    """
    from skvo_veb.utils.lc_processor.apply import pack_smooth_payload

    return pack_smooth_payload(
        times=np.asarray(lcd.jd, dtype=float),
        trend=trend,
        domain=lcd.active_domain,
        method=method,
        knots=[],
    )


def test_apply_detrend_from_smooth_mag_subtracts():
    """Apply detrend on magnitudes writes obs minus trend."""
    from skvo_veb.utils.lc_processor.apply import apply_detrend_from_smooth

    mag = np.array([10.0, 11.0, 12.0, 13.0])
    lcd = CurveDash(
        jd=np.array([2459000.0, 2459000.5, 2459001.0, 2459001.5]),
        mag=mag,
        mag_err=np.full_like(mag, 0.05),
        name="TIC 1",
        active_domain=DOMAIN_MAG,
    )
    trend = np.full_like(mag, 10.0)
    payload = apply_detrend_from_smooth(
        lcd,
        _smooth_payload(lcd, trend),
        method="median",
        domain=DOMAIN_MAG,
        t_min=None,
        t_max=None,
    )
    assert payload["domain"] == DOMAIN_MAG
    assert payload["origin"] == "smooth"
    assert payload["tilts"] == []
    assert payload["residual"] == [0.0, 1.0, 2.0, 3.0]


def test_apply_detrend_from_smooth_flux_divides():
    """Apply detrend on flux writes obs divided by trend."""
    from skvo_veb.utils.lc_processor.apply import apply_detrend_from_smooth

    lcd = _sample_lcd()
    trend = np.array([1.0, 2.0, 1.0, 2.0])
    payload = apply_detrend_from_smooth(
        lcd,
        _smooth_payload(lcd, trend),
        method="median",
        domain=DOMAIN_FLUX,
        t_min=None,
        t_max=None,
    )
    assert payload["domain"] == DOMAIN_FLUX
    assert payload["residual"] == pytest.approx([1.0, 1.0, 3.0, 2.0])


def test_apply_detrend_from_smooth_partial_nan_uses_nearest_t():
    """A hole next to a trusted T is filled; the point is kept."""
    from skvo_veb.utils.lc_processor.apply import apply_detrend_from_smooth

    lcd = _sample_lcd()
    trend = np.array([1.0, np.nan, 3.0, 2.0])
    payload = apply_detrend_from_smooth(
        lcd,
        _smooth_payload(lcd, trend),
        method="median",
        domain=DOMAIN_FLUX,
        t_min=None,
        t_max=None,
    )
    assert None not in payload["residual"]
    assert payload["residual"][0] == pytest.approx(1.0)
    assert payload["residual"][1] == pytest.approx(2.0)
    assert payload["residual"][2] == pytest.approx(1.0)
    assert payload["residual"][3] == pytest.approx(2.0)
    assert payload["fill"]["nearest"] == 1


def test_apply_detrend_from_smooth_all_nan_uses_piece_median():
    """A silent night is detrended with the piece photometry median."""
    from skvo_veb.utils.lc_processor.apply import apply_detrend_from_smooth

    lcd = _sample_lcd()
    trend = np.full(4, np.nan)
    payload = apply_detrend_from_smooth(
        lcd,
        _smooth_payload(lcd, trend),
        method="median",
        domain=DOMAIN_FLUX,
        t_min=None,
        t_max=None,
    )
    assert payload["residual"] == pytest.approx(np.array([1.0, 2.0, 3.0, 4.0]) / 2.5)
    assert payload["fill"]["median"] == 4


def test_fill_detrend_trend_interps_a_short_interior_hole():
    """Finite T on both sides and a short span uses a T interpolant."""
    from skvo_veb.utils.lc_processor.smooth import fill_detrend_trend

    times = np.array([2459000.0, 2459000.01, 2459000.02])
    values = np.array([1.0, 1.0, 1.0])
    trend = np.array([0.0, np.nan, 2.0])
    filled, counts = fill_detrend_trend(
        times, values, trend, break_tolerance=0.5, max_interp_span=0.05
    )
    assert filled[1] == pytest.approx(1.0)
    assert counts["interp"] == 1
    assert counts["nearest"] == 0


def test_fill_detrend_trend_does_not_use_the_next_night():
    """A rejected night uses its own median, not the previous night's T."""
    from skvo_veb.utils.lc_processor.smooth import fill_detrend_trend

    times = np.array([2459000.0, 2459000.1, 2459002.0, 2459002.1])
    values = np.array([10.0, 10.0, 2.0, 4.0])
    trend = np.array([10.0, 10.0, np.nan, np.nan])
    filled, counts = fill_detrend_trend(
        times, values, trend, break_tolerance=0.5, max_interp_span=0.25
    )
    assert filled[0] == pytest.approx(10.0)
    assert filled[2] == pytest.approx(3.0)
    assert filled[3] == pytest.approx(3.0)
    assert counts["median"] == 2
    assert counts["nearest"] == 0


def test_fill_detrend_trend_flux_median_must_stay_positive():
    """A non-positive piece median is not a legal flux divisor."""
    from skvo_veb.utils.lc_processor.smooth import (
        detrend_observed,
        fill_detrend_trend,
    )

    times = np.array([2459000.0, 2459000.5])
    values = np.array([0.0, -1.0])
    filled, counts = fill_detrend_trend(
        times,
        values,
        np.array([np.nan, np.nan]),
        break_tolerance=None,
    )
    assert counts["median"] == 2
    with pytest.raises(ValueError, match="strictly positive"):
        detrend_observed(values, filled, "flux")


def test_apply_detrend_from_smooth_requires_matching_overlay():
    """Apply detrend does not invent a residual without a matching smooth."""
    from skvo_veb.utils.lc_processor.apply import apply_detrend_from_smooth

    lcd = _sample_lcd()
    with pytest.raises(ValueError, match="Apply smooth first"):
        apply_detrend_from_smooth(
            lcd,
            None,
            method="median",
            domain=DOMAIN_FLUX,
            t_min=None,
            t_max=None,
        )


def test_figure_detrended_null_line_is_domain_aware():
    """Flux residual is marked at 1; magnitude residual is marked at 0."""
    from skvo_veb.utils.lc_processor.figures import figure_detrended

    times = np.array([2459000.0, 2459001.0])
    flux_fig = figure_detrended(
        times,
        np.array([0.9, 1.1]),
        None,
        y_label="flux / trend",
        invert_y=False,
        show_errors=False,
        uirevision="test|detrend",
    )
    mag_fig = figure_detrended(
        times,
        np.array([-0.1, 0.2]),
        None,
        y_label="Δmag (obs − trend)",
        invert_y=True,
        show_errors=False,
        uirevision="test|detrend",
    )
    assert flux_fig.layout.shapes[0].y0 == 1.0
    assert mag_fig.layout.shapes[0].y0 == 0.0
    assert flux_fig.data[0].marker.color == "blue"
    assert flux_fig.layout.dragmode == "zoom"


def test_extrema_signal_flips_for_domain_and_kind():
    """Magnitude minima are peaks of T; flux minima are peaks of -T."""
    from skvo_veb.utils.lc_processor.extrema import extrema_signal

    values = np.array([1.0, 2.0, 0.5])
    assert np.allclose(
        extrema_signal(values, working_domain="mag", extremum_kind="min"), values
    )
    assert np.allclose(
        extrema_signal(values, working_domain="mag", extremum_kind="max"), -values
    )
    assert np.allclose(
        extrema_signal(values, working_domain="flux", extremum_kind="min"), -values
    )
    assert np.allclose(
        extrema_signal(values, working_domain="flux", extremum_kind="max"), values
    )


def test_find_overlay_extrema_on_sine_flux_minima():
    """A 1-day sine in flux has minima near 0.75 + k."""
    from skvo_veb.utils.lc_processor.extrema import find_overlay_extrema

    times = np.linspace(2459000.0, 2459010.0, 1001)
    trend = 1.0 + np.sin(2.0 * np.pi * (times - times[0]))
    result = find_overlay_extrema(
        times,
        trend,
        working_domain="flux",
        extremum_kind="min",
        min_distance_d=0.5,
        break_tolerance=None,
    )
    assert result.n_extrema == 10
    phase = np.mod(result.jd - times[0], 1.0)
    assert np.allclose(phase, 0.75, atol=0.02)
    assert result.median_interval_d == pytest.approx(1.0, abs=0.02)


def test_find_overlay_extrema_respects_min_distance():
    """A large min-distance keeps only well-separated peaks."""
    from skvo_veb.utils.lc_processor.extrema import find_overlay_extrema

    times = np.linspace(2459000.0, 2459010.0, 1001)
    trend = 1.0 + np.sin(2.0 * np.pi * (times - times[0]))
    result = find_overlay_extrema(
        times,
        trend,
        working_domain="flux",
        extremum_kind="min",
        min_distance_d=3.5,
        break_tolerance=None,
    )
    assert result.n_extrema <= 3
    if result.n_extrema >= 2:
        assert np.min(np.diff(np.sort(result.jd))) >= 3.5 - 1e-6


def test_manual_extrema_add_and_remove():
    """A manual add keeps the clicked JD; delete uses the hit window."""
    from skvo_veb.utils.lc_processor.extrema import (
        add_manual_extremum,
        format_rough_toms_download,
        remove_extremum_near_time,
    )

    payload = add_manual_extremum(
        None,
        jd=2459001.25,
        smooth=0.4,
        kind="min",
        domain="flux",
        min_distance_d=0.3,
        delta_time_d=0.025,
    )
    payload = add_manual_extremum(
        payload,
        jd=2459000.4,
        smooth=1.1,
        kind="min",
        domain="flux",
        min_distance_d=0.3,
        delta_time_d=0.025,
    )
    assert payload["n_extrema"] == 2
    assert [hit["jd"] for hit in payload["hits"]] == [2459000.4, 2459001.25]
    tom_body = format_rough_toms_download(payload)
    data_jds = [
        float(line.split()[0])
        for line in tom_body.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert data_jds == [2459000.4, 2459001.25]
    assert payload["hits"][0]["origin"] == "manual"
    same = add_manual_extremum(
        payload,
        jd=2459000.4,
        smooth=1.1,
        kind="min",
        domain="flux",
        min_distance_d=0.3,
        delta_time_d=0.025,
    )
    assert same is payload
    kept = remove_extremum_near_time(payload, 2459010.0, hit_span_d=1.0)
    assert kept is payload
    gone = remove_extremum_near_time(payload, 2459000.4, hit_span_d=1.0)
    assert gone is not payload
    assert gone["n_extrema"] == 1
    assert gone["hits"][0]["jd"] == pytest.approx(2459001.25)


def test_find_overlay_extrema_skips_short_runs():
    """A 3-point dip is skipped at the default of 5; kept when the floor is 3."""
    from skvo_veb.utils.lc_processor.extrema import find_overlay_extrema

    t_short = np.array([2459000.0, 2459000.1, 2459000.2])
    y_short = np.array([1.0, 0.0, 1.0])
    t_long = np.linspace(2459010.0, 2459020.0, 1001)
    y_long = 1.0 + np.sin(2.0 * np.pi * (t_long - t_long[0]))
    times = np.concatenate([t_short, t_long])
    trend = np.concatenate([y_short, y_long])
    skipped = find_overlay_extrema(
        times,
        trend,
        working_domain="flux",
        extremum_kind="min",
        min_distance_d=0.5,
        break_tolerance=0.5,
        min_segment_points=5,
    )
    assert skipped.n_skipped_short == 1
    assert skipped.n_extrema >= 1
    assert np.min(skipped.jd) >= 2459010.0
    kept = find_overlay_extrema(
        times,
        trend,
        working_domain="flux",
        extremum_kind="min",
        min_distance_d=0.5,
        break_tolerance=0.5,
        min_segment_points=3,
    )
    assert kept.n_skipped_short == 0
    assert np.any(kept.jd < 2459001.0)
    with pytest.raises(ValueError, match="min_segment_points"):
        find_overlay_extrema(
            times,
            trend,
            working_domain="flux",
            extremum_kind="min",
            min_distance_d=0.5,
            break_tolerance=0.5,
            min_segment_points=2,
        )


def test_find_overlay_extrema_does_not_join_nan_hole():
    """A non-finite hole is a break; nights are not concatenated for find_peaks."""
    from skvo_veb.utils.lc_processor.extrema import find_overlay_extrema

    t_a = np.linspace(2459000.0, 2459001.0, 101)
    t_b = np.linspace(2459002.0, 2459003.0, 101)
    times = np.concatenate([t_a, t_b])
    trend = np.concatenate(
        [np.sin(2.0 * np.pi * (t_a - t_a[0])), np.full(t_b.size, np.nan)]
    )
    result = find_overlay_extrema(
        times,
        trend,
        working_domain="flux",
        extremum_kind="min",
        min_distance_d=0.3,
        break_tolerance=None,
    )
    assert result.n_extrema >= 1
    assert np.max(result.jd) < 2459001.5


def test_rough_interval_width_and_tom_nan_sigma():
    """Intervals are [t-δ, t+δ]; compact ToM writes nan σ and still parses."""
    from skvo_veb.utils.lc_processor.extrema import (
        OverlayExtremaResult,
        format_intervals_from_payload,
        format_rough_toms_download,
        pack_extrema_payload,
    )
    from skvo_veb.utils.oc.tom_io import parse_compact_tom_contents

    result = OverlayExtremaResult(
        jd=np.array([2459000.5, 2459001.5]),
        smooth=np.array([0.1, 0.2]),
        median_interval_d=1.0,
        min_distance_d=0.3,
        n_extrema=2,
        extremum_kind="min",
        working_domain="flux",
    )
    payload = pack_extrema_payload(result, delta_time_d=0.025)
    smooth = {
        "method": "running_parabola",
        "params": {
            "window_days": 0.05,
            "step_days": 0.0125,
            "min_points": 5,
            "break_tolerance_d": 0.7,
            "domain": "flux",
        },
    }
    body = format_intervals_from_payload(
        payload,
        delta_time_d=0.025,
        source_file="star.dat",
        smooth_payload=smooth,
    )
    assert "# source_file: star.dat" in body
    assert "# smooth_method: running_parabola" in body
    assert "# window_days: 0.05" in body
    assert "# Interval_Start  Interval_End" in body
    assert "2459000.475" in body
    assert "2459000.525" in body
    tom_body = format_rough_toms_download(
        payload, source_file="star.dat", smooth_payload=smooth
    )
    assert "# source_file: star.dat" in tom_body
    assert "# smooth_method: running_parabola" in tom_body
    assert "# Rough Minimum times" in tom_body
    assert "# JD_Minimum" in tom_body
    assert "# JD_Std" in tom_body
    records, _meta = parse_compact_tom_contents(tom_body)
    assert len(records) == 2
    assert records[0]["jd_ext"] == pytest.approx(2459000.5)
    assert np.isnan(records[0]["sigma_jd"])
    assert np.isnan(records[1]["sigma_jd"])


def test_figure_raw_with_trend_marks_extrema():
    """Rough extrema are a diamond overlay, not extra knot shapes."""
    from skvo_veb.utils.lc_processor.figures import (
        EXTREMA_MARKER,
        figure_raw_with_trend,
    )

    times = np.array([2459000.0, 2459000.5, 2459001.0])
    fig = figure_raw_with_trend(
        times,
        np.array([1.0, 0.8, 1.0]),
        None,
        np.array([1.0, 0.8, 1.0]),
        y_label="Flux",
        invert_y=False,
        show_errors=False,
        uirevision="test",
        extrema_jd=np.array([2459000.5]),
        extrema_y=np.array([0.8]),
    )
    names = [trace.name for trace in fig.data]
    assert "rough extrema" in names
    ext = next(trace for trace in fig.data if trace.name == "rough extrema")
    assert ext.type == "scattergl"
    assert fig.data[-1].name == "rough extrema"
    assert ext.marker.symbol == "diamond"
    assert ext.marker.color == EXTREMA_MARKER["color"]
    assert ext.marker.opacity == 1.0
    assert ext.hoverlabel.bgcolor == "white"
    assert "rough extremum" not in str(ext.hovertemplate).lower()
    assert "MJD=" in ext.hovertemplate
    assert "JD=" not in ext.hovertemplate.replace("MJD=", "")
    from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD

    assert float(ext.customdata[0]) == pytest.approx(2459000.5 - DEFAULT_EPOCH_JD)


def test_resolve_widget_defaults_use_fallbacks_or_factors():
    """Empty period uses fallbacks; a known P scales the period-aware knobs."""
    from skvo_veb.utils.lc_processor.config import (
        DEFAULT_INTERVAL_DELTA_DAYS,
        DEFAULT_MIN_PEAK_DISTANCE_DAYS,
        DEFAULT_RP_WINDOW_DAYS,
        resolve_widget_defaults,
    )

    window, step, distance, delta = resolve_widget_defaults(None)
    assert window == DEFAULT_RP_WINDOW_DAYS
    assert step == pytest.approx(DEFAULT_RP_WINDOW_DAYS * 0.25)
    assert distance == DEFAULT_MIN_PEAK_DISTANCE_DAYS
    assert delta == DEFAULT_INTERVAL_DELTA_DAYS
    window, step, distance, delta = resolve_widget_defaults(2.0)
    assert window == pytest.approx(1.0)
    assert step == pytest.approx(0.25)
    assert distance == pytest.approx(1.4)
    assert delta == pytest.approx(round(2.0 / 3.0, 6))
    window, step, distance, delta = resolve_widget_defaults(0.0)
    assert window == DEFAULT_RP_WINDOW_DAYS
    assert step == pytest.approx(DEFAULT_RP_WINDOW_DAYS * 0.25)


def test_copy_working_as_residual_records_origin():
    """Copy from plot 1 writes the cropped photometry onto plot 2."""
    from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD
    from skvo_veb.utils.lc_processor.tilt import copy_working_as_residual

    lcd = _sample_lcd()
    payload = copy_working_as_residual(
        lcd, domain=DOMAIN_FLUX, t_min=None, t_max=None
    )
    assert payload["origin"] == "copy"
    assert payload["method"] == "copy"
    assert payload["residual"] == pytest.approx([1.0, 2.0, 3.0, 4.0])
    assert payload["jd"][0] == pytest.approx(2459000.0)
    cropped = copy_working_as_residual(
        lcd,
        domain=DOMAIN_FLUX,
        t_min=2459000.4 - DEFAULT_EPOCH_JD,
        t_max=2459001.1 - DEFAULT_EPOCH_JD,
    )
    assert cropped["residual"] == pytest.approx([2.0, 3.0])


def test_apply_local_tilt_uses_working_window_not_handles():
    """The line is the model; Use-visible-range bounds are the locality."""
    from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, TIME_AXIS_MJD
    from skvo_veb.utils.lc_processor.apply import apply_detrend_from_smooth
    from skvo_veb.utils.lc_processor.tilt import apply_local_tilt

    mag = np.array([10.0, 11.0, 12.0, 13.0])
    lcd = CurveDash(
        jd=np.array([2459000.0, 2459000.5, 2459001.0, 2459001.5]),
        mag=mag,
        mag_err=np.full_like(mag, 0.05),
        name="TIC 1",
        active_domain=DOMAIN_MAG,
    )
    seeded = apply_detrend_from_smooth(
        lcd,
        _smooth_payload(lcd, np.full_like(mag, 10.0)),
        method="median",
        domain=DOMAIN_MAG,
        t_min=None,
        t_max=None,
    )
    # Residual is [0, 1, 2, 3]. Horizontal line at 1; window is first two times.
    x0 = 2459000.0 - DEFAULT_EPOCH_JD
    x1 = 2459000.5 - DEFAULT_EPOCH_JD
    tilted = apply_local_tilt(
        seeded,
        anchor_a=(x0, 1.0),
        anchor_b=(x1, 1.0),
        time_axis_mode=TIME_AXIS_MJD,
        display_epoch=DEFAULT_EPOCH_JD,
        jd_bounds=(2459000.0, 2459000.5),
    )
    assert tilted["residual"] == pytest.approx([-1.0, 0.0, 2.0, 3.0])
    assert tilted["origin"] == "smooth"
    assert tilted["tilts"][0]["n_updated"] == 2


def test_apply_local_tilt_flux_divides_and_stacks():
    """Flux divides by the line; a second apply appends a tilt record."""
    from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, TIME_AXIS_MJD
    from skvo_veb.utils.lc_processor.tilt import (
        apply_local_tilt,
        copy_working_as_residual,
    )

    lcd = _sample_lcd()
    seeded = copy_working_as_residual(
        lcd, domain=DOMAIN_FLUX, t_min=None, t_max=None
    )
    x0 = 2459000.0 - DEFAULT_EPOCH_JD
    x1 = 2459000.5 - DEFAULT_EPOCH_JD
    first = apply_local_tilt(
        seeded,
        anchor_a=(x0, 2.0),
        anchor_b=(x1, 2.0),
        time_axis_mode=TIME_AXIS_MJD,
        display_epoch=DEFAULT_EPOCH_JD,
    )
    assert first["residual"] == pytest.approx([0.5, 1.0, 1.5, 2.0])
    second = apply_local_tilt(
        first,
        anchor_a=(x0, 1.0),
        anchor_b=(x1, 1.0),
        time_axis_mode=TIME_AXIS_MJD,
        display_epoch=DEFAULT_EPOCH_JD,
    )
    assert second["residual"] == pytest.approx([0.5, 1.0, 1.5, 2.0])
    assert len(second["tilts"]) == 2


def test_apply_local_tilt_fails_without_a_seed_or_hits():
    """Empty plot 2, or a window with no points, is an error."""
    from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, TIME_AXIS_MJD
    from skvo_veb.utils.lc_processor.tilt import (
        apply_local_tilt,
        copy_working_as_residual,
    )

    with pytest.raises(ValueError, match="Seed plot 2"):
        apply_local_tilt(
            None,
            anchor_a=(0.0, 1.0),
            anchor_b=(1.0, 1.0),
            time_axis_mode=TIME_AXIS_MJD,
            display_epoch=DEFAULT_EPOCH_JD,
        )
    lcd = _sample_lcd()
    seeded = copy_working_as_residual(
        lcd, domain=DOMAIN_FLUX, t_min=None, t_max=None
    )
    with pytest.raises(ValueError, match="no plot-2 points"):
        apply_local_tilt(
            seeded,
            anchor_a=(10.0, 1.0),
            anchor_b=(11.0, 1.0),
            time_axis_mode=TIME_AXIS_MJD,
            display_epoch=DEFAULT_EPOCH_JD,
            jd_bounds=(2460000.0, 2460001.0),
        )


def test_status_alert_duration_and_dismissable():
    """Info uses the shared duration; warning and danger stay; all dismiss."""
    from skvo_veb.pages.lightcurve_processor import (
        STATUS_ALERT_DURATION_MS,
        _status_alert,
    )

    assert STATUS_ALERT_DURATION_MS == 4000
    info = _status_alert("Plot 2 seeded.", "info")
    assert info.dismissable is True
    assert info.duration == STATUS_ALERT_DURATION_MS
    assert info.is_open is True
    warning = _status_alert("Load a light curve first.", "warning")
    assert warning.dismissable is True
    assert warning.duration is None
    danger = _status_alert("Smooth fit failed.", "danger")
    assert danger.dismissable is True
    assert danger.duration is None
