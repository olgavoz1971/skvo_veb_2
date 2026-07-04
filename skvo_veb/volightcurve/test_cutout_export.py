"""Tests for uncalibrated TESS cutout VOTable export."""

import re

import io
import numpy as np
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import export_curvedash, enrich_cutout_curvedash, resolve_cutout_mask_mode
from skvo_veb.utils.lc_config import DOMAIN_FLUX
from skvo_veb.volightcurve.lightcurve import VOLightCurve


def test_cutout_export_no_zero_points():
    """Cutout profile must omit PhotCal zero points and document source and mask."""
    jd = np.array([2459000.1, 2459000.2, 2459000.3])
    flux = np.array([1200.5, 1201.2, 1199.8])
    flux_err = np.array([10.0, 11.0, 9.5])
    label = np.array([16, 16, 16], dtype=np.uint8)

    lcd = CurveDash(
        jd=jd,
        flux=flux,
        flux_err=flux_err,
        label=label,
        name="TIC 123456",
        lookup_name="My Star",
        time_unit="d",
        timescale="tdb",
        flux_unit="e-/s",
        flux_correction="backgrounded flattened",
        active_domain=DOMAIN_FLUX,
    )
    enrich_cutout_curvedash(
        lcd,
        pixel_metadata={'pixel_type': 'TPF', 'lookup_name': 'My Star'},
        sector=16,
        mask_mode='threshold',
        ra=256.7,
        dec=-54.0,
    )

    xml = export_curvedash(lcd, 'votable_binary', profile='cutout').decode('utf-8')
    norm = re.sub(r'\s+', ' ', xml)
    assert 'zeroPointFlux' not in xml
    assert 'zeroPointReferenceMagnitude' not in xml
    assert 'effectiveWavelength' in xml
    assert 'name="cutout_source"' in xml and 'value="TPF"' in xml
    assert 'name="mask_mode"' in xml and 'value="threshold"' in xml
    assert 'Data source: TPF' in norm
    assert 'Aperture mask mode: threshold' in norm
    assert 'Pipeline: user' in norm
    assert 'name="label"' in xml
    assert 'timeorigin="2400000.5"' in xml

    volc = VOLightCurve(io.BytesIO(export_curvedash(lcd, 'votable_binary', profile='cutout')))
    assert volc.timesys.jd0 == 2400000.5
    np.testing.assert_allclose(volc['obs_time'], jd - 2400000.5)


def test_resolve_cutout_mask_mode():
    """Mask mode helper maps UI controls to export labels."""
    assert resolve_cutout_mask_mode(0, 'threshold') == 'handmade'
    assert resolve_cutout_mask_mode(1, 'pipeline') == 'pipeline'
    assert resolve_cutout_mask_mode(1, 'threshold') == 'threshold'


if __name__ == '__main__':
    test_resolve_cutout_mask_mode()
    test_cutout_export_no_zero_points()
