"""Tests for tabular lightcurve export and upload round-trips."""

import io

import numpy as np

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import export_curvedash, ingest_lightcurve_file, volc_to_curvedash, apply_phot_domain_view
from skvo_veb.utils.lc_config import DOMAIN_FLUX, EXPORT_FORMATS, VOTABLE_FORMAT_BINARY, VOTABLE_FORMAT_TEXT
from skvo_veb.utils.mission_config.tess import resolve_photcal as resolve_tess_photcal
from volightcurve.lightcurve import VOLightCurve


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


def test_ecsv_export_stores_calibration_metadata():
    """ECSV headers carry flat calibration keywords including PhotCal ZPs."""
    lcd = _sample_lcd()
    payload = export_curvedash(lcd, 'ascii.ecsv').decode('utf-8')
    assert '# meta:' in payload
    assert 'PERIOD' in payload or 'period' in payload.lower()
    assert 'ZP_FLUX' in payload or 'zp_flux' in payload.lower()
    assert 'FILTER' in payload or 'filter' in payload.lower()


def test_csv_export_has_calibration_preamble():
    """CSV carries ``# KEY = value`` calibration lines before the header row."""
    lcd = _sample_lcd()
    payload = export_curvedash(lcd, 'csv').decode('utf-8')
    assert '# JD0' in payload or '#JD0' in payload.replace(' ', '')
    assert 'ZP_FLUX' in payload or 'zp_flux' in payload.lower()
    header = next(line for line in payload.splitlines() if line and not line.startswith('#'))
    assert 'flux' in header
    assert 'flux_err' in header
    assert 'phot' not in header.split(',')


def test_tabular_round_trip_preserves_data_and_calibration():
    """Exported ECSV/CSV/DAT files should upload back with calibration intact."""
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
        assert restored.period == lcd.period
        assert restored.epoch == lcd.epoch
        photcal = restored.metadata.get('photcal') or {}
        assert photcal.get('filter_identifier') == 'TESS/TESS.Red' or photcal.get(
            'filter_name'
        ) == 'TESS'
        assert photcal.get('zp_flux') is not None


def test_processor_path_preserves_narrative_comments_on_dat():
    """Processor-style ingest → export → re-ingest keeps free-text ``#`` notes."""
    from skvo_veb.utils.lc_config import METADATA_KEY_FILE_COMMENTS

    dat = b"""# JD0 = 0
# Observer notes: clear night
# MAG0 = 20.0
# FILTER = V
# jd mag mag_err
2459000.0 12.1 0.01
2459001.0 12.2 0.02
"""
    lcd = ingest_lightcurve_file(io.BytesIO(dat), "proc.dat")
    assert any(
        "Observer notes" in c for c in (lcd.metadata.get(METADATA_KEY_FILE_COMMENTS) or [])
    )
    blob = export_curvedash(lcd, "ascii.commented_header")
    text = blob.decode("utf-8")
    assert "Observer notes: clear night" in text
    assert "# jd mag mag_err" in text or "mag mag_err" in text
    restored = ingest_lightcurve_file(io.BytesIO(blob), "proc_out.dat")
    assert any(
        "Observer notes" in c
        for c in (restored.metadata.get(METADATA_KEY_FILE_COMMENTS) or [])
    )
    assert (restored.metadata.get("photcal") or {}).get("zp_mag") == 20.0
    assert restored.active_domain == "mag"


def test_mag_domain_csv_round_trip_keeps_magnitude():
    """Mag-domain export uses mag/mag_err columns and re-ingests as magnitude."""
    from skvo_veb.utils.lc_config import DOMAIN_MAG

    jd = np.array([2459000.0, 2459000.5, 2459001.0])
    mag = np.array([19.036, 19.114, 19.038])
    lcd = CurveDash(
        jd=jd,
        mag=mag,
        mag_err=np.full_like(mag, 0.05),
        name="OGLE",
        active_domain=DOMAIN_MAG,
        mag_unit="mag",
    )
    lcd.metadata["photcal"] = {
        "filter_identifier": "Generic/Bessell.I",
        "zp_flux": 2415.65,
        "zp_flux_unit": "Jy",
        "zp_mag": 0.0,
        "zp_mag_unit": "mag",
        "mag_sys": "Vega",
    }
    blob = export_curvedash(lcd, "csv")
    text = blob.decode("utf-8")
    header = next(line for line in text.splitlines() if line and not line.startswith("#"))
    assert header.startswith("jd,mag,mag_err")
    assert "phot" not in header
    restored = ingest_lightcurve_file(io.BytesIO(blob), "ogle.csv")
    assert restored.active_domain == DOMAIN_MAG
    np.testing.assert_allclose(restored.mag, mag)


def test_ambiguous_phot_column_defaults_to_magnitude():
    """Bare ``phot`` without unit/UCD ingests as magnitude (Phase 2b)."""
    from skvo_veb.utils.lc_config import DOMAIN_MAG

    dat = b"""# JD0 = 0
# jd phot flux_error
2459000.0 19.036 0.058
2459001.0 19.114 0.055
"""
    lcd = ingest_lightcurve_file(io.BytesIO(dat), "legacy.dat")
    assert lcd.active_domain == DOMAIN_MAG
    np.testing.assert_allclose(lcd.mag, [19.036, 19.114])


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
