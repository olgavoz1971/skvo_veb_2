"""Tests for shared lightcurve trim and export-window helpers."""

import numpy as np

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, DOMAIN_FLUX
from skvo_veb.utils.lc_interaction import (
    prepare_lcd_for_export,
    resolve_export_display_x_range,
    trim_curvedash_display_range,
    trim_curvedash_from_plot_selection,
)


def _sample_lcd():
    jd = np.array([2459000.0, 2459000.5, 2459001.0, 2459001.5])
    flux = np.array([1.0, 2.0, 3.0, 4.0])
    return CurveDash(
        jd=jd,
        flux=flux,
        flux_err=np.full_like(flux, 0.1),
        name='TIC 1',
        active_domain=DOMAIN_FLUX,
    )


def test_trim_removes_selected_display_range():
    """Trim should drop rows inside the selected display interval."""
    lcd = _sample_lcd()
    selected = {'range': {'x': [59000.0, 59000.5]}}
    trim_curvedash_from_plot_selection(lcd, selected, display_epoch=DEFAULT_EPOCH_JD)
    assert len(lcd.lightcurve) == 2
    np.testing.assert_allclose(lcd.jd, [2459000.0, 2459001.5])


def test_export_prefers_selection_over_zoom():
    """Export window should use selection bounds before visible zoom."""
    bounds = {'xmin': 59000.0, 'xmax': 59000.5}
    relayout = {'xaxis.range[0]': 58999.5, 'xaxis.range[1]': 59001.0}
    assert resolve_export_display_x_range(bounds, relayout) == (59000.0, 59000.5)


def test_prepare_lcd_for_export_keeps_source_unmodified():
    """Export clipping must not mutate the stored lightcurve."""
    lcd = _sample_lcd()
    export_lcd = prepare_lcd_for_export(
        lcd,
        relayout_data={'xaxis.range[0]': 58999.5, 'xaxis.range[1]': 59000.25},
        display_epoch=DEFAULT_EPOCH_JD,
    )
    assert len(lcd.lightcurve) == 4
    assert len(export_lcd.lightcurve) == 2


def test_export_after_trim_ignores_stale_selection_bounds():
    """Stale box bounds after trim must not clip export to the removed interval."""
    lcd = _sample_lcd()
    bounds = {'xmin': 59000.25, 'xmax': 59000.75}
    trim_curvedash_display_range(
        lcd, bounds['xmin'], bounds['xmax'], display_epoch=DEFAULT_EPOCH_JD
    )
    assert len(lcd.lightcurve) == 3

    # Stale bounds keep only the removed window; fallback must restore the trimmed curve.
    export_lcd = prepare_lcd_for_export(
        lcd,
        selection_bounds=bounds,
        display_epoch=DEFAULT_EPOCH_JD,
    )
    assert len(export_lcd.lightcurve) == 3

    export_lcd = prepare_lcd_for_export(
        lcd,
        selection_bounds=None,
        display_epoch=DEFAULT_EPOCH_JD,
    )
    assert len(export_lcd.lightcurve) == 3


def test_prepare_lcd_for_export_falls_back_when_clip_is_empty():
    """Export must not emit an empty file when the clip window has no points."""
    lcd = _sample_lcd()
    export_lcd = prepare_lcd_for_export(
        lcd,
        relayout_data={'xaxis.range[0]': 99999.0, 'xaxis.range[1]': 100000.0},
        display_epoch=DEFAULT_EPOCH_JD,
    )
    assert len(export_lcd.lightcurve) == 4
