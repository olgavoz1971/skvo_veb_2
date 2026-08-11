"""Tests for manual GP prep linear detrend."""

from __future__ import annotations

import json

import numpy as np
import pytest

from skvo_veb.utils.gp.manual_detrend import apply_manual_linear_detrend, line_y_at_jd
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD
from skvo_veb.utils.my_tools import PipeException


def _minimal_mag_packet(mags: list[float], jds: list[float]) -> str:
    """Builds a tiny mag-native transport JSON."""
    struct = {
        "schema": {"time": "t", "value": "mag", "error": "mag_err", "flag": None},
        "meta": {
            "active_domain": "mag",
            "jd0": 0.0,
            "photcal": {
                "zp_mag": 20.0,
                "zp_flux": 1.0,
                "zp_mag_unit": "mag",
                "zp_flux_unit": "",
            },
        },
        "data": [
            [jd, mag, 0.01, None] for jd, mag in zip(jds, mags, strict=True)
        ],
    }
    return json.dumps(struct)


def test_line_y_at_jd_linear():
    """Line evaluation is linear in JD."""
    jd = np.array([2450000.0, 2450001.0, 2450002.0])
    y = line_y_at_jd(jd, 2450000.0, 10.0, 2450002.0, 12.0)
    np.testing.assert_allclose(y, [10.0, 11.0, 12.0])


def test_mag_view_subtracts_trend():
    """Magnitude view subtracts the line; errors unchanged."""
    jds = [2450000.0, 2450001.0, 2450002.0]
    mags = [10.0, 11.0, 12.0]
    payload = _minimal_mag_packet(mags, jds)
    x0 = jds[0] - DEFAULT_EPOCH_JD
    x1 = jds[2] - DEFAULT_EPOCH_JD
    out = apply_manual_linear_detrend(
        payload,
        view_mode="mag",
        anchor_a=(x0, 10.0),
        anchor_b=(x1, 12.0),
        time_axis_mode="mjd",
    )
    data = json.loads(out)["data"]
    new_mags = [row[1] for row in data]
    np.testing.assert_allclose(new_mags, [0.0, 0.0, 0.0], atol=1e-10)
    assert data[1][2] == 0.01


def test_detrend_jd_bounds_leaves_outside_rows_unchanged():
    """Detrend with jd_bounds only mutates rows inside the window."""
    jds = [2450000.0, 2450001.0, 2450002.0]
    mags = [10.0, 11.0, 12.0]
    payload = _minimal_mag_packet(mags, jds)
    x0 = jds[0] - DEFAULT_EPOCH_JD
    x1 = jds[2] - DEFAULT_EPOCH_JD
    out = apply_manual_linear_detrend(
        payload,
        view_mode="mag",
        anchor_a=(x0, 10.0),
        anchor_b=(x1, 12.0),
        time_axis_mode="mjd",
        jd_bounds=(2450000.5, 2450001.5),
    )
    data = json.loads(out)["data"]
    assert data[0][1] == 10.0
    np.testing.assert_allclose(data[1][1], 0.0, atol=1e-10)
    assert data[2][1] == 12.0


def test_detrend_preserves_missing_errors():
    """Rows with null uncertainties stay null through detrend and export rebuild."""
    struct = {
        "schema": {"time": "t", "value": "mag", "error": "mag_err", "flag": None},
        "meta": {
            "active_domain": "mag",
            "jd0": 0.0,
            "photcal": {
                "zp_mag": 20.0,
                "zp_flux": 1.0,
                "zp_mag_unit": "mag",
                "zp_flux_unit": "",
                "filter_identifier": "TEST",
                "filter_name": "TEST",
            },
            "vo_envelope": {
                "table_name": "t",
                "lightcurve_title": "t",
                "table_description": "test",
                "votable_description": "test",
            },
        },
        "data": [
            [2450000.0, 10.0, None, None],
            [2450001.0, 11.0, 0.05, None],
        ],
    }
    payload = json.dumps(struct)
    out = apply_manual_linear_detrend(
        payload,
        view_mode="mag",
        anchor_a=(2450000.0 - DEFAULT_EPOCH_JD, 10.0),
        anchor_b=(2450002.0 - DEFAULT_EPOCH_JD, 12.0),
        time_axis_mode="mjd",
    )
    rows = json.loads(out)["data"]
    assert rows[0][2] is None
    assert rows[1][2] == 0.05

    from skvo_veb.utils.lc_bridge import curvedash_from_transport_json

    lcd = curvedash_from_transport_json(out, source_name="t.dat")
    assert np.isnan(lcd.mag_err.iloc[0])
    assert lcd.mag_err.iloc[1] == 0.05


def test_identical_anchor_jd_raises():
    """Duplicate anchor times are rejected."""
    with pytest.raises(PipeException, match="same time"):
        line_y_at_jd(np.array([1.0]), 1.0, 1.0, 1.0, 2.0)
