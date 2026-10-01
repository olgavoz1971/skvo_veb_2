"""Tests for TESS cutout VOTable export with the instrument zero point."""

import re

import io
import numpy as np
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import export_curvedash
from skvo_veb.utils.mission_config.tess import (
    TESS_ELECTRON_S_ZERO_POINT_SOURCE_URL,
    enrich_cutout_curvedash,
    resolve_cutout_mask_mode,
)
from skvo_veb.utils.lc_config import DOMAIN_FLUX
from volightcurve.lightcurve import VOLightCurve


def test_cutout_export_includes_instrument_zero_point():
    """Cutout export includes the shared electron s-1 zero point and provenance."""
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

    xml = export_curvedash(lcd, 'votable_binary').decode('utf-8')
    norm = re.sub(r'\s+', ' ', xml)
    assert 'zeroPointFlux' in xml
    assert 'zeroPointReferenceMagnitude' in xml
    assert '20.44' in xml
    assert 'effectiveWavelength' in xml
    assert 'name="cutout_source"' in xml and 'value="TPF"' in xml
    assert 'name="mask_mode"' in xml and 'value="threshold"' in xml
    assert 'Data source: TPF' in norm
    assert 'Aperture mask mode: threshold' in norm
    assert 'Pipeline: user' in norm
    assert TESS_ELECTRON_S_ZERO_POINT_SOURCE_URL in norm
    assert 'name="label"' in xml
    assert 'timeorigin="2400000.5"' in xml

    volc = VOLightCurve(io.BytesIO(export_curvedash(lcd, 'votable_binary')))
    assert volc.timesys.jd0 == 2400000.5
    time_col = "obs_time" if "obs_time" in volc.table.colnames else "jd"
    np.testing.assert_allclose(volc[time_col], jd - 2400000.5)

    dat = export_curvedash(lcd, 'ascii.commented_header').decode('utf-8')
    assert 'Data source: TPF' in dat
    assert 'Aperture mask mode: threshold' in dat
    assert '20.44' in dat
    assert 'FILTER' in dat or 'TESS/TESS.Red' in dat


def test_resolve_cutout_mask_mode():
    """Mask mode helper maps UI controls to export labels."""
    assert resolve_cutout_mask_mode(0, 'threshold') == 'handmade'
    assert resolve_cutout_mask_mode(1, 'pipeline') == 'pipeline'
    assert resolve_cutout_mask_mode(1, 'threshold') == 'threshold'


if __name__ == '__main__':
    test_resolve_cutout_mask_mode()
    test_cutout_export_includes_instrument_zero_point()
