"""Tests for export row filtering by active-domain photometry validity."""

from __future__ import annotations

import numpy as np
import numpy.ma as ma
import pytest

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import (
    curvedash_to_table,
    valid_photometry_row_mask,
)
from skvo_veb.utils.lc_config import DOMAIN_FLUX, DOMAIN_MAG


def test_valid_photometry_row_mask_ignores_bad_uncertainties():
    """Rows with valid flux but masked or NaN errors remain exportable."""
    lcd = CurveDash(
        jd=[57000.0, 57001.0, 57002.0],
        flux=[1.0, 2.0, 3.0],
        flux_err=[0.01, np.nan, ma.masked],
        active_domain=DOMAIN_FLUX,
    )
    mask = valid_photometry_row_mask(lcd)
    np.testing.assert_array_equal(mask, [True, True, True])


def test_valid_photometry_row_mask_excludes_invalid_phot():
    """Masked or non-finite photometry values are excluded."""
    lcd = CurveDash(
        jd=[57000.0, 57001.0, 57002.0, 57003.0],
        flux=ma.array([1.0, 2.0, 3.0, 4.0], mask=[False, True, False, False]),
        flux_err=[0.01, 0.01, 0.01, 0.01],
        active_domain=DOMAIN_FLUX,
    )
    lcd.lightcurve.loc[2, "flux"] = np.nan
    mask = valid_photometry_row_mask(lcd)
    np.testing.assert_array_equal(mask, [True, False, False, True])


def test_curvedash_to_table_exports_only_valid_phot_rows():
    """VOTable-oriented export table omits invalid photometry rows."""
    lcd = CurveDash(
        jd=[57000.0, 57001.0, 57002.0],
        flux=[10.0, np.nan, 12.0],
        flux_err=[0.1, 0.1, ma.masked],
        active_domain=DOMAIN_FLUX,
    )
    table = curvedash_to_table(lcd)
    assert len(table) == 2
    np.testing.assert_allclose(table["phot"], [10.0, 12.0])


def test_curvedash_to_table_mag_domain_keeps_rows_with_invalid_mag_err():
    """Magnitude rows with invalid mag_err still export when mag is valid."""
    lcd = CurveDash(
        jd=[57000.0, 57001.0],
        mag=[18.5, 18.7],
        mag_err=[ma.masked, np.nan],
        active_domain=DOMAIN_MAG,
    )
    table = curvedash_to_table(lcd)
    assert len(table) == 2


def test_curvedash_to_table_mag_domain_filters_invalid_mag():
    """Magnitude-domain export drops invalid mag rows, not based on mag_err."""
    lcd = CurveDash(
        jd=[57000.0, 57001.0, 57002.0],
        mag=[18.5, np.nan, 18.7],
        mag_err=[0.01, 0.01, ma.masked],
        active_domain=DOMAIN_MAG,
    )
    table = curvedash_to_table(lcd)
    assert len(table) == 2
    np.testing.assert_allclose(table["phot"], [18.5, 18.7])


def test_curvedash_to_tabular_table_filters_label_with_phot_rows():
    """Tabular export keeps label aligned when invalid photometry rows are dropped."""
    from skvo_veb.utils.lc_bridge import curvedash_to_tabular_table

    lcd = CurveDash(
        jd=[57000.0, 57001.0, 57002.0],
        flux=[10.0, np.nan, 12.0],
        flux_err=[0.1, 0.1, 0.1],
        label=[1, 2, 3],
        active_domain=DOMAIN_FLUX,
    )
    table = curvedash_to_tabular_table(lcd)
    assert len(table) == 2
    assert list(table["label"]) == [1, 3]


def test_export_raises_when_no_valid_phot_rows():
    """Export fails clearly when every photometry value is invalid."""
    lcd = CurveDash(
        jd=[57000.0, 57001.0],
        flux=[np.nan, ma.masked],
        flux_err=[0.01, 0.01],
        active_domain=DOMAIN_FLUX,
    )
    with pytest.raises(Exception, match="no rows with valid photometry"):
        curvedash_to_table(lcd)
