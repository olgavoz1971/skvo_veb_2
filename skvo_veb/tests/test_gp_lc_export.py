"""Tests for GP light curve export from transport JSON."""

from __future__ import annotations

import io
import json

import numpy as np

from skvo_veb.tests.test_gp_manual_detrend import _minimal_mag_packet
from skvo_veb.tests.volightcurve.test_time_reference import _gaia_style_votable
from skvo_veb.utils.gp.export import (
    apply_prep_fold_ephemeris,
    export_stem_from_upload_filename,
    gp_intervals_export_download_name,
    gp_lc_export_download_name,
)
from skvo_veb.utils.gp.manual_detrend import apply_manual_linear_detrend
from skvo_veb.utils.lc_bridge import (
    curvedash_from_transport_json,
    export_curvedash,
    pack_volc_to_json,
    volc_to_curvedash,
)
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, VOTABLE_FORMAT_BINARY
from skvo_veb.volightcurve import VOLightCurve


def _minimal_flux_packet(
    fluxes: list[float],
    jds: list[float],
    *,
    labels: list[str | None] | None = None,
) -> str:
    """Builds a tiny flux-native transport JSON with optional string labels."""
    if labels is None:
        flags: list[str | None] = [None] * len(jds)
    else:
        flags = labels
    struct = {
        "schema": {
            "time": "t",
            "value": "flux",
            "error": "flux_err",
            "flag": "label",
        },
        "meta": {
            "active_domain": "flux",
            "jd0": 0.0,
            "photcal": {},
        },
        "data": [
            [jd, flux, 0.01, flag]
            for jd, flux, flag in zip(jds, fluxes, flags, strict=True)
        ],
    }
    return json.dumps(struct)


def test_gp_lc_export_download_name_appends_extension():
    """Basename-only stems receive the format extension."""
    name = gp_lc_export_download_name("my_curve_lc", VOTABLE_FORMAT_BINARY)
    assert name.endswith(".vot")


def test_gp_intervals_export_download_name_appends_dat():
    """Interval export stems receive a .dat extension for text downloads."""
    assert gp_intervals_export_download_name("target_intervals") == "target_intervals.dat"
    assert gp_intervals_export_download_name("  ") == "intervals_export.dat"


def test_export_stem_from_upload_filename_strips_extension():
    """Upload filenames map to basename-only export stems."""
    assert export_stem_from_upload_filename("curve.dat") == "curve"
    assert export_stem_from_upload_filename("intervals.txt") == "intervals"
    assert export_stem_from_upload_filename(None) == ""


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


def test_curvedash_from_transport_json_flux_domain_exports():
    """Flux-native transport rebuilds without duplicate active_domain."""
    jds = [2450000.0, 2450001.0, 2450002.0]
    payload = _minimal_flux_packet([1.0, 1.1, 1.2], jds)
    lcd = curvedash_from_transport_json(payload, source_name="flux_curve.dat")
    assert lcd.active_domain == "flux"
    blob = export_curvedash(lcd, "ascii.ecsv")
    assert len(blob) > 50


def test_curvedash_from_transport_json_preserves_string_labels():
    """String flag cells round-trip through transport export rebuild."""
    jds = [2450000.0, 2450001.0, 2450002.0]
    labels = ["sector_a", "sector_b", "sector_c"]
    payload = _minimal_flux_packet([1.0, 1.1, 1.2], jds, labels=labels)
    lcd = curvedash_from_transport_json(payload, source_name="labelled.dat")
    assert list(lcd.label) == labels
    table = export_curvedash(lcd, "ascii.ecsv")
    text = table.decode("utf-8")
    for label in labels:
        assert label in text


def test_export_after_flux_detrend_preserves_string_labels():
    """Flux detrend then export keeps string labels and succeeds."""
    jds = [2450000.0, 2450001.0, 2450002.0]
    fluxes = [2.0, 2.2, 2.4]
    labels = ["run_1", "run_1", "run_2"]
    payload = _minimal_flux_packet(fluxes, jds, labels=labels)
    x0 = jds[0] - DEFAULT_EPOCH_JD
    x1 = jds[2] - DEFAULT_EPOCH_JD
    detrended = apply_manual_linear_detrend(
        payload,
        view_mode="flux",
        anchor_a=(x0, 2.0),
        anchor_b=(x1, 2.4),
        time_axis_mode="mjd",
    )
    lcd = curvedash_from_transport_json(detrended, source_name="detrended.dat")
    assert list(lcd.label) == labels
    assert export_curvedash(lcd, "ascii.ecsv")


def test_apply_prep_fold_ephemeris_overrides_ingest_metadata():
    """Sidebar P / Epoch win over empty ingest transport meta."""
    payload = _minimal_flux_packet([1.0, 1.1], [2450000.0, 2450001.0])
    lcd = curvedash_from_transport_json(payload, source_name="t.dat")
    assert lcd.period is None
    apply_prep_fold_ephemeris(lcd, 2.5, 58000.0, display_epoch=DEFAULT_EPOCH_JD)
    assert lcd.period == 2.5
    assert lcd.period_unit == "d"
    assert lcd.epoch == 58000.0 + DEFAULT_EPOCH_JD


def test_apply_prep_fold_ephemeris_empty_widgets_leave_ingest_values():
    """Empty sidebar fields do not wipe period/epoch already on CurveDash."""
    payload = _minimal_flux_packet([1.0, 1.1], [2450000.0, 2450001.0])
    lcd = curvedash_from_transport_json(payload, source_name="t.dat")
    lcd.period = 1.23
    lcd.epoch = 2451234.5
    apply_prep_fold_ephemeris(lcd, None, None, display_epoch=DEFAULT_EPOCH_JD)
    assert lcd.period == 1.23
    assert lcd.epoch == 2451234.5


def test_ecsv_export_includes_sidebar_period_and_epoch():
    """ECSV header carries stamped fold ephemeris."""
    payload = _minimal_flux_packet([1.0, 1.1], [2450000.0, 2450001.0])
    lcd = curvedash_from_transport_json(payload, source_name="t.dat")
    apply_prep_fold_ephemeris(lcd, 0.41, 59883.12, display_epoch=DEFAULT_EPOCH_JD)
    text = export_curvedash(lcd, "ascii.ecsv").decode("utf-8")
    assert "period: 0.41" in text
    assert f"epoch: {59883.12 + DEFAULT_EPOCH_JD}" in text
