"""Tests for GP light curve export from transport JSON."""

from __future__ import annotations

import io

import numpy as np

from skvo_veb.tests.test_gp_manual_detrend import _minimal_mag_packet
from skvo_veb.tests.volightcurve.test_time_reference import _gaia_style_votable
from skvo_veb.utils.gp.export import gp_lc_export_download_name
from skvo_veb.utils.gp.manual_detrend import apply_manual_linear_detrend
from skvo_veb.utils.lc_bridge import (
    curvedash_from_transport_json,
    export_curvedash,
    pack_volc_to_json,
    volc_to_curvedash,
)
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, VOTABLE_FORMAT_BINARY
from skvo_veb.volightcurve import VOLightCurve


def test_gp_lc_export_download_name_appends_extension():
    """Basename-only stems receive the format extension."""
    name = gp_lc_export_download_name("my_curve_lc", VOTABLE_FORMAT_BINARY)
    assert name.endswith(".vot")


def test_curvedash_from_transport_json_matches_row_count():
    """Transport round-trip preserves observation count and JD span."""
    payload = _minimal_mag_packet([10.0, 11.0, 12.0], [2450000.0, 2450001.0, 2450002.0])
    lcd = curvedash_from_transport_json(payload, source_name="target.dat")
    assert len(lcd.lightcurve) == 3
    np.testing.assert_allclose(lcd.jd, [2450000.0, 2450001.0, 2450002.0])


def test_export_after_manual_detrend_via_transport():
    """Detrended transport JSON exports without error."""
    jds = [2450000.0, 2450001.0, 2450002.0]
    payload = _minimal_mag_packet([10.0, 11.0, 12.0], jds)
    x0 = jds[0] - DEFAULT_EPOCH_JD
    x1 = jds[2] - DEFAULT_EPOCH_JD
    detrended = apply_manual_linear_detrend(
        payload,
        view_mode="mag",
        anchor_a=(x0, 10.0),
        anchor_b=(x1, 12.0),
        time_axis_mode="mjd",
    )
    lcd = curvedash_from_transport_json(detrended, source_name="target.vot")
    blob = export_curvedash(lcd, "ascii.ecsv")
    assert b"target" in blob or len(blob) > 50


def test_volc_pack_transport_export_roundtrip():
    """VOLightCurve → transport → CurveDash → export bytes."""
    volc = VOLightCurve(io.BytesIO(_gaia_style_votable()))
    transport = pack_volc_to_json(volc)
    lcd_direct = volc_to_curvedash(volc, "gaia.vot")
    lcd_transport = curvedash_from_transport_json(transport, source_name="gaia.vot")
    assert len(lcd_transport.lightcurve) == len(lcd_direct.lightcurve)
    assert export_curvedash(lcd_transport, VOTABLE_FORMAT_BINARY)
