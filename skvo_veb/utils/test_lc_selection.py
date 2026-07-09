"""Tests for lightcurve selection helpers."""

import numpy as np
import plotly.express as px
import pytest

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, DOMAIN_FLUX
from skvo_veb.utils.lc_figure import build_curvedash_scatter_figure
from skvo_veb.utils.lc_interaction import (
    apply_plot_point_selection,
    apply_selectedpoints_to_figure,
    clear_plot_point_selection,
    delete_rows_by_perm_indices,
    delete_selected_rows,
    merge_perm_indices_from_plot_event,
    normalize_selected_perm_store,
    trace_selected_indices,
    trace_selected_indices_from_column,
    trim_curvedash_display_range,
)


def _sample_lcd():
    jd = np.array([2459000.0, 2459000.5, 2459001.0, 2459001.5])
    flux = np.array([1.0, 2.0, 3.0, 4.0])
    return CurveDash(
        jd=jd,
        flux=flux,
        flux_err=np.full_like(flux, 0.1),
        name='Test',
        active_domain=DOMAIN_FLUX,
    )


def test_normalize_selected_perm_store():
    """Selection store parsing accepts list payloads and empty values."""
    assert normalize_selected_perm_store(None) == []
    assert normalize_selected_perm_store([1, 2, 3]) == [1, 2, 3]


def test_trace_selected_indices():
    """Trace indices follow perm_index membership."""
    lcd = _sample_lcd()
    perm_values = lcd.perm_index.tolist()
    assert trace_selected_indices(lcd, [perm_values[0], perm_values[2]]) == [0, 2]


def test_delete_rows_by_perm_indices():
    """Delete removes rows by perm_index without renumbering survivors."""
    lcd = _sample_lcd()
    perm_values = lcd.perm_index.tolist()
    delete_rows_by_perm_indices(lcd, [perm_values[1]])
    assert len(lcd.lightcurve) == 3
    assert lcd.perm_index.tolist() == [perm_values[0], perm_values[2], perm_values[3]]


def test_merge_perm_indices_from_plot_event():
    """Plot events append perm_index values to the selection store list."""
    event = {'points': [{'customdata': [2]}, {'customdata': [5]}]}
    merged = merge_perm_indices_from_plot_event([1], event)
    assert merged == [1, 2, 5]


def test_apply_selectedpoints_to_figure():
    """Figure traces receive selectedpoints derived from perm_index customdata."""
    lcd = _sample_lcd()
    perm_values = lcd.perm_index.tolist()
    fig = build_curvedash_scatter_figure(
        lcd,
        title='Test',
        display_epoch=DEFAULT_EPOCH_JD,
        color_by_label=False,
    )
    apply_selectedpoints_to_figure(fig, [perm_values[1], perm_values[3]])
    assert list(fig.data[0].selectedpoints) == [1, 3]


def test_apply_plot_point_selection_uses_point_index():
    """Click events without customdata still mark rows via pointIndex."""
    lcd = _sample_lcd()
    event = {'points': [{'pointIndex': 1}, {'pointNumber': 3}]}
    apply_plot_point_selection(lcd, event)
    assert lcd.lightcurve['selected'].tolist() == [0, 1, 0, 1]


def test_trace_selected_indices_from_column():
    """Selected column maps directly to Plotly selectedpoints indices."""
    lcd = _sample_lcd()
    lcd.lightcurve.loc[0, 'selected'] = 1
    lcd.lightcurve.loc[2, 'selected'] = 1
    assert trace_selected_indices_from_column(lcd) == [0, 2]


def test_clear_and_delete_selected_rows():
    """Unselect clears markers; delete removes marked rows."""
    lcd = _sample_lcd()
    lcd.lightcurve.loc[1, 'selected'] = 1
    clear_plot_point_selection(lcd)
    assert trace_selected_indices_from_column(lcd) == []

    lcd.lightcurve.loc[1, 'selected'] = 1
    lcd.lightcurve.loc[3, 'selected'] = 1
    delete_selected_rows(lcd)
    assert len(lcd.lightcurve) == 2


def test_uirevision_changes_after_trim():
    """Trim must bump uirevision so Plotly drops stale box-select highlights."""
    lcd = _sample_lcd()
    fig_before = build_curvedash_scatter_figure(
        lcd,
        title='Test',
        display_epoch=DEFAULT_EPOCH_JD,
        color_by_label=True,
    )
    trim_curvedash_display_range(
        lcd,
        2459000.5 - DEFAULT_EPOCH_JD,
        2459001.0 - DEFAULT_EPOCH_JD,
        display_epoch=DEFAULT_EPOCH_JD,
    )
    fig_after = build_curvedash_scatter_figure(
        lcd,
        title='Test',
        display_epoch=DEFAULT_EPOCH_JD,
        color_by_label=True,
    )
    assert len(lcd.lightcurve) == 2
    assert fig_before.layout.uirevision != fig_after.layout.uirevision


def test_uirevision_unchanged_for_view_only_replot():
    """Mag/flux toggles with the same rows should keep uirevision stable."""
    lcd = _sample_lcd()
    fig_flux = build_curvedash_scatter_figure(
        lcd,
        title='Test',
        display_epoch=DEFAULT_EPOCH_JD,
        color_by_label=True,
    )
    fig_flux_again = build_curvedash_scatter_figure(
        lcd,
        title='Test',
        display_epoch=DEFAULT_EPOCH_JD,
        color_by_label=True,
    )
    assert fig_flux.layout.uirevision == fig_flux_again.layout.uirevision


def test_build_curvedash_scatter_figure_uses_selected_column():
    """Figure builder restores highlights from the selected column."""
    lcd = _sample_lcd()
    lcd.lightcurve.loc[1, 'selected'] = 1
    fig = build_curvedash_scatter_figure(
        lcd,
        title='Test',
        display_epoch=DEFAULT_EPOCH_JD,
        color_by_label=False,
    )
    assert list(fig.data[0].selectedpoints) == [1]


def test_build_curvedash_scatter_figure_mjd_tickformat():
    """MJD axis uses full numeric ticks without SI prefixes."""
    lcd = _sample_lcd()
    fig = build_curvedash_scatter_figure(
        lcd,
        title='Test',
        display_epoch=DEFAULT_EPOCH_JD,
        color_by_label=False,
        time_axis_mode='mjd',
    )
    assert fig.layout.xaxis.title.text.startswith('MJD')
    assert fig.layout.xaxis.tickformat == '.2f'
    assert fig.layout.xaxis.exponentformat == 'none'


def test_build_curvedash_scatter_figure_date_axis():
    """Date axis mode uses calendar datetime values."""
    lcd = _sample_lcd()
    fig = build_curvedash_scatter_figure(
        lcd,
        title='Test',
        display_epoch=DEFAULT_EPOCH_JD,
        color_by_label=False,
        time_axis_mode='date',
    )
    assert fig.layout.xaxis.title.text.startswith('Date')
    assert fig.layout.xaxis.type == 'date'


def test_build_curvedash_scatter_figure_applies_selection():
    """Figure builder restores highlights from perm_index list input."""
    lcd = _sample_lcd()
    perm_values = lcd.perm_index.tolist()
    fig = build_curvedash_scatter_figure(
        lcd,
        title='Test',
        display_epoch=DEFAULT_EPOCH_JD,
        color_by_label=False,
        selected_perm_indices=[perm_values[0]],
    )
    assert list(fig.data[0].selectedpoints) == [0]
