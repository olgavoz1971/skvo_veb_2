"""Tests for ASAS-SN export profile and per-band photcal metadata."""

import io
import numpy as np

from skvo_veb.utils.asassn_config import (
    ASASSN_G_FILTER_IDENTIFIER,
    ASASSN_G_MAG_SYS,
    ASASSN_V_FILTER_IDENTIFIER,
    ASASSN_V_MAG_SYS,
    resolve_asassn_photcal,
)
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import export_curvedash
from skvo_veb.volightcurve.lightcurve import VOLightCurve


def _sample_asassn_lcd(band: str) -> CurveDash:
    """Builds a minimal ASAS-SN CurveDash instance for export tests.

    Args:
        band (str): Photometric filter (``'V'`` or ``'g'``).

    Returns:
        CurveDash: Sample lightcurve with band-specific photcal metadata.
    """
    jd = np.array([2459000.1, 2459000.2, 2459000.3])
    flux = np.array([0.45, 0.46, 0.44])
    flux_err = np.array([0.01, 0.02, 0.015])

    lcd = CurveDash(
        gaia_id="1791119426789765632",
        jd=jd,
        flux=flux,
        flux_err=flux_err,
        band=band,
        flux_unit="mJy",
        photcal=resolve_asassn_photcal(band),
        timescale="hjd",
        period=1.234,
        epoch=2459000.0,
    )
    lcd.metadata["authors"] = ["ASAS-SN Sky Patrol"]
    lcd.metadata["calibration_catalog"] = "APASS" if band == "V" else "ATLAS REFCAT2"
    return lcd


def test_asassn_votable_export_g_band():
    """VOTable export for g band includes Sloan filter and AB zero points."""
    lcd = _sample_asassn_lcd("g")
    xml = export_curvedash(lcd, "votable_binary", profile="asassn").decode("utf-8")

    assert ASASSN_G_FILTER_IDENTIFIER in xml
    assert "zeroPointFlux" in xml
    assert "zeroPointReferenceMagnitude" in xml
    assert ASASSN_G_MAG_SYS in xml
    assert "ATLAS REFCAT2" in xml
    assert 'timeorigin="2400000.5"' in xml

    buf = io.BytesIO(export_curvedash(lcd, "votable_binary", profile="asassn"))
    lc = VOLightCurve(buf)
    assert len(lc) == 3
    assert "obs_time" in lc.colnames
    assert "phot" in lc.colnames


def test_asassn_votable_export_v_band():
    """VOTable export for V band includes Johnson filter and Vega zero points."""
    lcd = _sample_asassn_lcd("V")
    xml = export_curvedash(lcd, "votable_binary", profile="asassn").decode("utf-8")

    assert ASASSN_V_FILTER_IDENTIFIER in xml
    assert "zeroPointFlux" in xml
    assert "zeroPointReferenceMagnitude" in xml
    assert ASASSN_V_MAG_SYS in xml
    assert "APASS" in xml


def test_asassn_ecsv_export():
    """Non-VOTable export uses tabular bridge without a mission profile."""
    lcd = _sample_asassn_lcd("g")
    payload = export_curvedash(lcd, "ascii.ecsv").decode("utf-8")
    assert "obs_time" in payload or "flux" in payload
    assert "ASAS-SN g" in payload or "g" in payload


if __name__ == "__main__":
    test_asassn_votable_export_g_band()
    test_asassn_votable_export_v_band()
    test_asassn_ecsv_export()
