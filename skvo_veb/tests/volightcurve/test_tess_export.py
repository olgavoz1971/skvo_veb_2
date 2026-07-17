"""Test suite for TESS configuration and VOTable export integration.

This test verifies that the TESS export profile in ``lc_bridge.export_curvedash``
correctly handles SPOC and non-SPOC pipelines according to zero-point rules.
"""

import io
import numpy as np
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import export_curvedash
from skvo_veb.utils.mission_config.tess import (
    TESS_SPOC_ZERO_POINT_FLUX,
    is_spoc_pipeline,
    resolve_tess_photcal,
)
from skvo_veb.volightcurve.lightcurve import VOLightCurve


def test_tess_export():
    """Tests TESS-specific VOTable export with SPOC and non-SPOC pipelines."""
    jd = np.array([2459000.1, 2459000.2, 2459000.3])
    flux = np.array([12.5, 12.6, 12.4])
    flux_err = np.array([0.01, 0.02, 0.015])
    label = np.array([40, 40, 40], dtype=np.uint8)

    lcd = CurveDash(
        name="TIC 159717514",
        lookup_name="My Target",
        jd=jd,
        flux=flux,
        flux_err=flux_err,
        label=label,
        time_unit="d",
        timescale="tdb",
        flux_unit="e-/s",
        period=4.39327,
        epoch=2184.403,
    )
    lcd.metadata['ra'] = 256.698
    lcd.metadata['dec'] = -54.050
    lcd.metadata['authors'] = ["SPOC"]
    lcd.metadata['sectors'] = ["40"]
    lcd.metadata['flux_origins'] = ["pdcsap"]
    lcd.metadata['photcal'] = resolve_tess_photcal(lcd.metadata['authors'])

    assert is_spoc_pipeline(lcd.metadata.get('authors', [])) is True

    xml_spoc = export_curvedash(lcd, 'votable_binary', profile='tess').decode('utf-8')
    assert 'timeorigin="2400000.5"' in xml_spoc
    assert "zeroPointFlux" in xml_spoc
    assert "zeroPointReferenceMagnitude" in xml_spoc
    assert "TESS/TESS.Red" in xml_spoc
    assert str(TESS_SPOC_ZERO_POINT_FLUX) in xml_spoc
    assert "20.44" in xml_spoc
    assert 'Photometry method(s): pdcsap' in xml_spoc
    assert 'name="label"' in xml_spoc

    lcd_qlp = CurveDash(
        name="TIC 159717514",
        lookup_name="My Target",
        jd=jd,
        flux=flux,
        flux_err=flux_err,
        label=label,
        time_unit="d",
        timescale="tdb",
        flux_unit="e-/s",
    )
    lcd_qlp.metadata['ra'] = 256.698
    lcd_qlp.metadata['dec'] = -54.050
    lcd_qlp.metadata['authors'] = ["QLP"]
    lcd_qlp.metadata['photcal'] = resolve_tess_photcal(lcd_qlp.metadata['authors'])

    assert is_spoc_pipeline(lcd_qlp.metadata['authors']) is False

    xml_qlp = export_curvedash(lcd_qlp, 'votable_binary', profile='tess').decode('utf-8')
    assert "zeroPointFlux" not in xml_qlp
    assert "zeroPointReferenceMagnitude" not in xml_qlp
    assert "TESS/TESS.Red" in xml_qlp
    assert "effectiveWavelength" in xml_qlp

    lcd_stitched = CurveDash(
        name="TIC 159717514",
        lookup_name="My Target",
        jd=jd,
        flux=flux,
        flux_err=flux_err,
        label=np.array([40, 41, 41], dtype=np.uint8),
        time_unit="d",
        timescale="tdb",
        flux_unit="relative flux",
    )
    lcd_stitched.metadata['ra'] = 256.698
    lcd_stitched.metadata['dec'] = -54.050
    lcd_stitched.metadata['authors'] = ["SPOC"]
    lcd_stitched.metadata['sectors'] = ["40", "41"]
    lcd_stitched.metadata['flux_origins'] = ["pdcsap"]
    lcd_stitched.metadata['stitched'] = True
    lcd_stitched.metadata['photcal'] = resolve_tess_photcal(lcd_stitched.metadata['authors'], stitched=True)

    xml_stitched = export_curvedash(lcd_stitched, 'votable_binary', profile='tess').decode('utf-8')
    assert "zeroPointFlux" not in xml_stitched
    assert "zeroPointReferenceMagnitude" not in xml_stitched
    assert "effectiveWavelength" in xml_stitched
    assert "Photometric zero points are omitted" in xml_stitched

    buf_spoc = io.BytesIO(export_curvedash(lcd, 'votable_binary', profile='tess'))
    lc = VOLightCurve(buf_spoc)
    assert len(lc) == 3
    assert lc.timesys.jd0 == 2400000.5
    np.testing.assert_allclose(lc['obs_time'], jd - 2400000.5)
    assert 'obs_time' in lc.colnames
    assert 'phot' in lc.colnames
    assert 'flux_error' in lc.colnames


if __name__ == "__main__":
    test_tess_export()
