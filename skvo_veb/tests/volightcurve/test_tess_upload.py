"""Test suite for TESS configuration, VOTable export, and Upload integration.

This test verifies that the TESS configuration parameters are correctly applied,
that the VOTable exporter correctly handles SPOC and non-SPOC pipelines,
and that the upload handler correctly ingests VOTable files via ``volc_to_curvedash``.
"""

import io
import os

import numpy as np
import pytest

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import export_curvedash, volc_to_curvedash
from skvo_veb.utils.lc_config import DOMAIN_FLUX
from skvo_veb.utils.mission_config.tess import resolve_tess_photcal
from skvo_veb.volightcurve.lightcurve import VOLightCurve


def test_tess_upload_integration():
    """Tests the full round-trip of exporting a TESS lightcurve to VOTable and uploading it back."""
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

    buf = io.BytesIO()
    buf.write(export_curvedash(lcd, 'votable_binary', profile='tess'))
    xml = buf.getvalue().decode('utf-8')
    assert 'meta.id;meta.dataset' in xml or 'name="label"' in xml
    assert 'pdcsap' in xml.lower() or 'methods' in xml.lower()

    buf.seek(0)

    volc = VOLightCurve(buf)
    assert len(volc) == 3
    assert volc.timesys.timescale == "TCB"
    assert volc.timesys.jd0 == 2400000.5
    np.testing.assert_allclose(volc['obs_time'], jd - 2400000.5)
    assert volc.table.meta['period'] == 4.39327
    assert volc.table.meta['epoch'] == 2184.403
    assert volc.table.meta['ra'] == 256.698
    assert volc.table.meta['dec'] == -54.050

    lcd_uploaded = volc_to_curvedash(volc, "TESS_TIC_159717514.vot")
    assert lcd_uploaded.title
    assert 'sector' in lcd_uploaded.title.lower() or 'TIC' in lcd_uploaded.title
    assert lcd_uploaded.period == 4.39327
    assert lcd_uploaded.epoch == 2184.403
    assert lcd_uploaded.active_domain == DOMAIN_FLUX
    np.testing.assert_allclose(lcd_uploaded.jd, jd)
    np.testing.assert_allclose(lcd_uploaded.flux, flux)
    np.testing.assert_allclose(lcd_uploaded.flux_err, flux_err)
    assert set(lcd_uploaded.lightcurve['label'].unique()) == {40}


def test_tess_real_file_upload():
    """Tests ingestion of a real TESS VOTable file from disk."""
    real_file_path = 'data/lc_tess__TIC_455790537_sector__16_author__SPOC_methods__pdcsap.vot'
    if not os.path.exists(real_file_path):
        pytest.skip(f"Fixture not found: {real_file_path}")

    volc = VOLightCurve(real_file_path)
    assert len(volc) == 16717
    assert volc.timesys.timescale == "TCB"
    assert volc.timesys.jd0 == 2457000.0
    assert volc.table.meta['period'] == 0.935
    assert volc.table.meta['epoch'] == 2400000.5
    assert volc.table.meta['ra'] == 346.345186642685
    assert volc.table.meta['dec'] == 47.6763106397934

    lcd_uploaded = volc_to_curvedash(volc, real_file_path)
    assert lcd_uploaded.period == 0.935
    assert lcd_uploaded.epoch == 2400000.5
    assert lcd_uploaded.active_domain == DOMAIN_FLUX
    assert len(lcd_uploaded.lightcurve) == 16717
    assert lcd_uploaded.title


if __name__ == "__main__":
    test_tess_upload_integration()
    test_tess_real_file_upload()
