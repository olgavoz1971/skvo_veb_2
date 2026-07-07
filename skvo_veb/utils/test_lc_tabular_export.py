"""Tests for tabular lightcurve export and upload round-trips."""

import io

import numpy as np

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import export_curvedash, ingest_lightcurve_file, volc_to_curvedash, apply_phot_domain_view
from skvo_veb.utils.lc_config import DOMAIN_FLUX, EXPORT_FORMATS, VOTABLE_FORMAT_BINARY, VOTABLE_FORMAT_TEXT
from skvo_veb.utils.tess_config import resolve_tess_photcal
from skvo_veb.volightcurve.lightcurve import VOLightCurve


def _sample_lcd():
    jd = np.array([2459000.0, 2459000.5, 2459001.0])
    flux = np.array([1.0, 2.0, 3.0])
    lcd = CurveDash(
        jd=jd,
        flux=flux,
        flux_err=np.full_like(flux, 0.1),
        name='TIC 123',
        lookup_name='Target A',
        active_domain=DOMAIN_FLUX,
        flux_unit='electron s-1',
    )
    lcd.metadata['ra'] = 10.5
    lcd.metadata['dec'] = -20.25
    lcd.metadata['period'] = 1.23
    lcd.metadata['epoch'] = 2459000.25
    lcd.metadata['authors'] = ['SPOC']
    lcd.metadata['flux_origins'] = ['pdcsap']
    lcd.metadata['photcal'] = resolve_tess_photcal(['SPOC'])
    return lcd


def test_export_formats_list_matches_ui():
    """UI export formats must stay aligned with bridge validation."""
    assert EXPORT_FORMATS == (
        VOTABLE_FORMAT_BINARY,
        VOTABLE_FORMAT_TEXT,
        'ascii.ecsv',
        'ascii.commented_header',
        'csv',
    )


def test_ecsv_export_stores_basic_metadata_only():
    """ECSV headers should carry descriptive metadata but not PhotCal blocks."""
    lcd = _sample_lcd()
    payload = export_curvedash(lcd, 'ascii.ecsv').decode('utf-8')
    assert '# meta:' in payload
    assert 'name: TIC 123' in payload
    assert 'pipeline: SPOC' in payload
    assert 'method: pdcsap' in payload
    assert 'filter: TESS' in payload
    assert 'zp_flux' not in payload
    assert 'photcal' not in payload.lower()


def test_csv_export_has_no_metadata_header():
    """CSV must contain data columns only."""
    lcd = _sample_lcd()
    payload = export_curvedash(lcd, 'csv').decode('utf-8')
    assert 'phot' in payload.splitlines()[0]
    assert '# name' not in payload
    assert 'flux_error' in payload.splitlines()[0] or 'phot' in payload.splitlines()[0]


def test_tabular_round_trip_preserves_data_and_ecsv_meta():
    """Exported ECSV/CSV/DAT files should upload back through the bridge."""
    lcd = _sample_lcd()
    for fmt, filename in (
        ('ascii.ecsv', 'lc.ecsv'),
        ('csv', 'lc.csv'),
        ('ascii.commented_header', 'lc.dat'),
    ):
        blob = export_curvedash(lcd, fmt)
        restored = ingest_lightcurve_file(io.BytesIO(blob), filename)
        assert len(restored.lightcurve) == 3
        np.testing.assert_allclose(restored.jd, lcd.jd)
        np.testing.assert_allclose(restored.flux, lcd.flux)
        if fmt == 'ascii.ecsv':
            assert restored.period == lcd.period
            assert restored.epoch == lcd.epoch
            assert restored.metadata.get('authors') == ['SPOC']
            assert restored.metadata.get('flux_origins') == ['pdcsap']
            assert restored.metadata.get('photcal', {}).get('filter_name') == 'TESS'
            assert 'filter_identifier' not in (restored.metadata.get('photcal') or {})


def test_votable_mag_export_uses_mag_ucds():
    """Magnitude-domain export should tag the phot column with phot.mag UCDs."""
    lcd = _sample_lcd()
    apply_phot_domain_view(lcd, True)
    xml = export_curvedash(lcd, VOTABLE_FORMAT_BINARY, profile='tess').decode('utf-8')
    assert 'ucd="phot.mag"' in xml
    assert 'stat.error;phot.mag' in xml


def test_votable_binary_and_text_encodings_differ():
    """Binary and text VOTable exports should use distinct TABLEDATA encodings."""
    lcd = _sample_lcd()
    xml_binary = export_curvedash(lcd, VOTABLE_FORMAT_BINARY, profile='tess').decode('utf-8')
    xml_text = export_curvedash(lcd, VOTABLE_FORMAT_TEXT, profile='tess').decode('utf-8')
    assert 'BINARY' in xml_binary
    assert '<TR>' in xml_text or '<TD>' in xml_text
    assert 'BINARY' not in xml_text.split('<TABLE')[1].split('</TABLE>')[0]


def test_votable_round_trip_still_works():
    """VOTable export remains the standards-compliant path with PhotCal when applicable."""
    lcd = _sample_lcd()
    blob = export_curvedash(lcd, VOTABLE_FORMAT_BINARY, profile='tess')
    volc = VOLightCurve(io.BytesIO(blob))
    restored = volc_to_curvedash(volc, 'lc.vot', preserve_photcal=True)
    assert len(restored.lightcurve) == 3
    assert len(volc) == 3
    assert restored.metadata.get('photcal', {}).get('filter_identifier') == 'TESS/TESS.Red'
