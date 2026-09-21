"""Tests for Skvo-boundary Julian Date ordering on lightcurve ingest."""

from __future__ import annotations

import io

import numpy as np
import pytest

from skvo_veb.utils.lc_bridge import (
    _order_series_by_absolute_jd,
    ingest_lightcurve_file,
)


def test_order_series_by_absolute_jd_stable_and_aligned():
    """Sorts JD ascending and keeps photometry / labels with their rows."""
    jd = np.array([3.0, 1.0, 1.0, 2.0])
    phot = np.array([30.0, 10.0, 11.0, 20.0])
    labels = np.array(["c", "a", "b", "d"])
    ordered_jd, ordered_phot, ordered_labels = _order_series_by_absolute_jd(
        jd, phot, labels
    )
    assert np.all(np.diff(ordered_jd) >= 0.0)
    assert ordered_jd.tolist() == [1.0, 1.0, 2.0, 3.0]
    # Stable: equal JD keeps original relative order (10 before 11).
    assert ordered_phot.tolist() == [10.0, 11.0, 20.0, 30.0]
    assert ordered_labels.tolist() == ["a", "b", "d", "c"]


def test_order_series_by_absolute_jd_rejects_non_finite():
    """Fails fast when any Julian Date is non-finite."""
    with pytest.raises(ValueError, match="non-finite Julian Date"):
        _order_series_by_absolute_jd(np.array([1.0, np.nan]), np.array([1.0, 2.0]))


def test_ingest_lightcurve_file_orders_unsorted_dat():
    """Upload path returns CurveDash rows in increasing absolute JD."""
    dat = (
        b"# MAG0=12.0\n"
        b"# JD MAG MAG_ERR\n"
        b"2459002.0 12.2 0.01\n"
        b"2459000.0 12.0 0.01\n"
        b"2459001.0 12.1 0.01\n"
    )
    lcd = ingest_lightcurve_file(io.BytesIO(dat), "unsorted.dat")
    jd = np.asarray(lcd.jd, dtype=float)
    phot = np.asarray(lcd.phot, dtype=float)
    assert np.all(np.diff(jd) > 0.0)
    assert jd.tolist() == pytest.approx([2459000.0, 2459001.0, 2459002.0])
    assert phot.tolist() == pytest.approx([12.0, 12.1, 12.2])
