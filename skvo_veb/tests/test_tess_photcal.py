"""Tests for TESS archive photcal resolution and domain conversion."""

from __future__ import annotations

import numpy as np
import pytest

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import export_curvedash
from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD,
    DOMAIN_FLUX,
    DOMAIN_MAG,
    PHOTCAL_KEY_ZP_FLUX,
    PHOTCAL_KEY_ZP_FLUX_UNIT,
    PHOTCAL_KEY_ZP_MAG,
    display_epoch_offset,
)
from skvo_veb.utils.mission_config.tess import (
    QLP_FLUX_UNIT,
    TESS_ELECTRON_S_ZERO_POINT_FLUX,
    TESS_ELECTRON_S_ZERO_POINT_REF_MAG,
    TESS_ELECTRON_S_ZERO_POINT_SOURCE_URL,
    TESS_TIMEORIGIN,
    apply_tess_phot_domain_view,
    apply_upload_cutout_metadata,
    enrich_cutout_curvedash,
    instrument_electron_s_photcal,
    resolve_photcal,
    resolve_tess_photcal,
    validate_tess_magnitude_conversion,
)
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.tess_lc_builder import (
    _tars_ephemeris_from_lightkurve_list,
    _tess_mag_from_lightkurve_list,
)


class _FakeLcMeta:
    """Minimal Lightkurve stand-in exposing ``meta`` for TESSMAG tests."""

    def __init__(self, tess_mag, extra=None):
        self.meta = {"TESSMAG": tess_mag} if tess_mag is not None else {}
        if extra:
            self.meta.update(extra)


def _build_archive_lcd(flux, flux_err, *, authors, photcal, flux_unit, stitched=False):
    """Builds a minimal TESS archive CurveDash for conversion tests."""
    flux = np.asarray(flux, dtype=float)
    flux_err = np.asarray(flux_err, dtype=float)
    jd = np.linspace(2459000.1, 2459000.1 + 0.1 * (len(flux) - 1), len(flux))
    lcd = CurveDash(
        name="TIC 35119266",
        jd=jd,
        flux=flux,
        flux_err=flux_err,
        time_unit="d",
        timescale="tdb",
        flux_unit=flux_unit,
        photcal=photcal,
    )
    lcd.metadata["authors"] = authors
    lcd.metadata["flux_origins"] = ["sap"]
    if stitched:
        lcd.metadata["stitched"] = True
    return lcd


def test_resolve_photcal_spoc_unstitched():
    """SPOC archive curves retain the fixed pipeline zero point."""
    photcal = resolve_photcal(["SPOC"], stitched=False)
    assert photcal[PHOTCAL_KEY_ZP_MAG] == TESS_ELECTRON_S_ZERO_POINT_REF_MAG
    assert photcal[PHOTCAL_KEY_ZP_FLUX] == 1.0
    assert photcal[PHOTCAL_KEY_ZP_FLUX_UNIT] == "electron s-1"


def test_resolve_photcal_qlp_without_tess_mag_passband_only():
    """QLP without TESSMAG stores passband metadata only."""
    photcal = resolve_photcal(["QLP"], stitched=False)
    assert PHOTCAL_KEY_ZP_MAG not in photcal
    assert PHOTCAL_KEY_ZP_FLUX not in photcal
    assert photcal["filter_identifier"] == "TESS/TESS.Red"


def test_resolve_photcal_tars_with_tess_mag():
    """TARS unstitched curves use TESSMAG with dimensionless zero-point flux, like QLP."""
    photcal = resolve_photcal(["TARS"], stitched=False, tess_mag=5.80207)
    assert photcal[PHOTCAL_KEY_ZP_MAG] == pytest.approx(5.80207)
    assert photcal[PHOTCAL_KEY_ZP_FLUX] == 1.0
    assert photcal[PHOTCAL_KEY_ZP_FLUX_UNIT] is None


def test_tars_flux_mag_matches_tessmag_formula():
    """TARS magnitude view follows mag = TESSMAG - 2.5 log10(flux)."""
    tess_mag = 5.80207
    flux = np.array([1.0, 1.1])
    lcd = _build_archive_lcd(
        flux,
        np.array([np.nan, np.nan]),
        authors=["TARS"],
        photcal=resolve_tess_photcal(["TARS"], tess_mag=tess_mag),
        flux_unit=QLP_FLUX_UNIT.to_string(),
    )
    apply_tess_phot_domain_view(lcd, True)
    expected = tess_mag - 2.5 * np.log10(flux)
    np.testing.assert_allclose(lcd.lightcurve["mag"].values, expected, rtol=1e-12)


def test_resolve_photcal_tasoc_passband_only_even_with_tessmag():
    """TASOC TESSMAG is catalogue metadata, not a QLP-style flux zero point."""
    photcal = resolve_photcal(["TASOC"], stitched=False, tess_mag=11.2032)
    assert PHOTCAL_KEY_ZP_MAG not in photcal
    assert PHOTCAL_KEY_ZP_FLUX not in photcal
    assert photcal["filter_identifier"] == "TESS/TESS.Red"


def test_tasoc_rejects_magnitude_conversion():
    """TASOC has no photometric zero point, so magnitude conversion must fail."""
    lcd = _build_archive_lcd(
        [1.0, 1.1],
        [np.nan, np.nan],
        authors=["TASOC"],
        photcal=resolve_tess_photcal(["TASOC"], tess_mag=11.2032),
        flux_unit=QLP_FLUX_UNIT.to_string(),
    )
    with pytest.raises(PipeException, match="zero point"):
        validate_tess_magnitude_conversion(lcd)


def test_archive_flux_unit_ppm_is_dimensionless():
    """FITS ppm is stored as dimensionless; electron / s is kept."""
    from astropy import units as u

    from skvo_veb.utils.mission_config.tess import archive_flux_unit_for_pipeline

    assert archive_flux_unit_for_pipeline(["TASOC"], u.Unit("ppm")) is None
    assert archive_flux_unit_for_pipeline(["TASOC"], u.electron / u.s) == "electron / s"
    assert archive_flux_unit_for_pipeline(["QLP"], u.Unit("ppm")) is None


def test_resolve_photcal_qlp_with_tess_mag():
    """QLP unstitched curves use header TESSMAG with dimensionless zero-point flux."""
    photcal = resolve_photcal(["QLP"], stitched=False, tess_mag=11.42)
    assert photcal[PHOTCAL_KEY_ZP_MAG] == 11.42
    assert photcal[PHOTCAL_KEY_ZP_FLUX] == 1.0
    assert photcal[PHOTCAL_KEY_ZP_FLUX_UNIT] is None


def test_resolve_photcal_qlp_stitched_omits_zero_points():
    """Stitched QLP curves never carry zero points even with TESSMAG."""
    photcal = resolve_photcal(["QLP"], stitched=True, tess_mag=11.42)
    assert PHOTCAL_KEY_ZP_MAG not in photcal


def test_tess_mag_from_lightkurve_list_picks_first_when_consistent():
    """Sector list helper returns TESSMAG when present on downloaded products."""
    lc_list = [_FakeLcMeta(10.5), _FakeLcMeta(10.5)]
    assert _tess_mag_from_lightkurve_list(lc_list) == 10.5


def test_tess_mag_from_lightkurve_list_missing_returns_none():
    """Missing TESSMAG headers yield no QLP zero point input."""
    assert _tess_mag_from_lightkurve_list([_FakeLcMeta(None)]) is None


def test_qlp_flux_mag_flux_roundtrip():
    """QLP flux→mag→flux conversion preserves values through the shared bridge path."""
    flux = np.array([100.0, 200.0, 50.0])
    flux_err = np.array([1.0, 2.0, 0.5])
    lcd = _build_archive_lcd(
        flux,
        flux_err,
        authors=["QLP"],
        photcal=resolve_tess_photcal(["QLP"], tess_mag=11.42),
        flux_unit=QLP_FLUX_UNIT.to_string(),
    )

    apply_tess_phot_domain_view(lcd, True)
    assert lcd.active_domain == DOMAIN_MAG
    mag_after = lcd.lightcurve["mag"].values.copy()
    mag_err_after = lcd.lightcurve["mag_err"].values.copy()

    apply_tess_phot_domain_view(lcd, False)
    assert lcd.active_domain == DOMAIN_FLUX
    np.testing.assert_allclose(lcd.lightcurve["flux"].values, flux, rtol=1e-12)
    np.testing.assert_allclose(lcd.lightcurve["flux_err"].values, flux_err, rtol=1e-12)

    apply_tess_phot_domain_view(lcd, True)
    np.testing.assert_allclose(lcd.lightcurve["mag"].values, mag_after, rtol=1e-12)
    np.testing.assert_allclose(lcd.lightcurve["mag_err"].values, mag_err_after, rtol=1e-12)


def test_qlp_flux_to_mag_matches_tessmag_formula():
    """QLP magnitude view follows mag = TESSMAG - 2.5 log10(flux)."""
    tess_mag = 11.42
    flux = np.array([100.0, 200.0])
    lcd = _build_archive_lcd(
        flux,
        np.array([1.0, 2.0]),
        authors=["QLP"],
        photcal=resolve_tess_photcal(["QLP"], tess_mag=tess_mag),
        flux_unit=QLP_FLUX_UNIT.to_string(),
    )

    apply_tess_phot_domain_view(lcd, True)
    expected = tess_mag - 2.5 * np.log10(flux)
    np.testing.assert_allclose(lcd.lightcurve["mag"].values, expected, rtol=1e-12)


def test_stitched_curve_rejects_magnitude_conversion():
    """Stitched TESS curves must not convert to magnitudes."""
    lcd = _build_archive_lcd(
        [1.0, 2.0],
        [0.1, 0.1],
        authors=["SPOC"],
        photcal=resolve_tess_photcal(["SPOC"]),
        flux_unit="electron s-1",
        stitched=True,
    )
    with pytest.raises(PipeException, match="stitched"):
        validate_tess_magnitude_conversion(lcd)
    with pytest.raises(PipeException, match="stitched"):
        apply_tess_phot_domain_view(lcd, True)


def test_qlp_without_tessmag_rejects_magnitude_conversion():
    """QLP without TESSMAG must not convert to magnitudes."""
    lcd = _build_archive_lcd(
        [100.0, 200.0],
        [1.0, 2.0],
        authors=["QLP"],
        photcal=resolve_tess_photcal(["QLP"]),
        flux_unit=QLP_FLUX_UNIT.to_string(),
    )
    with pytest.raises(PipeException, match="zero point"):
        validate_tess_magnitude_conversion(lcd)
    with pytest.raises(PipeException, match="zero point"):
        apply_tess_phot_domain_view(lcd, True)


def test_qlp_unit_mismatch_refuses_magnitude_conversion():
    """Incompatible ZP / flux-column units refuse conversion (no silent invent)."""
    lcd = _build_archive_lcd(
        [100.0, 200.0],
        [1.0, 2.0],
        authors=["QLP"],
        photcal=resolve_tess_photcal(["QLP"], tess_mag=11.42),
        flux_unit="electron s-1",
    )
    with pytest.raises(PipeException, match="not equivalent"):
        apply_tess_phot_domain_view(lcd, True)
    assert lcd.active_domain == DOMAIN_FLUX
    assert lcd.metadata["photcal"].get(PHOTCAL_KEY_ZP_FLUX_UNIT) is None


def test_passband_only_flux_view_does_not_invent_zero_points():
    """Staying in flux with passband-only photcal must not invent ZPs."""
    from skvo_veb.utils.lc_bridge import apply_phot_domain_view
    from skvo_veb.utils.mission_config.tess import filter_group_meta

    lcd = _build_archive_lcd(
        [100.0, 200.0],
        [1.0, 2.0],
        authors=["user"],
        photcal=filter_group_meta(),
        flux_unit="electron s-1",
    )
    apply_phot_domain_view(lcd, False)
    assert PHOTCAL_KEY_ZP_FLUX not in lcd.metadata["photcal"]
    assert PHOTCAL_KEY_ZP_MAG not in lcd.metadata["photcal"]

    payload = export_curvedash(lcd, "ascii.commented_header").decode("utf-8")
    assert "ZP_FLUX" not in payload
    assert "ZP_MAG" not in payload
    assert "FILTER" in payload or "TESS/TESS.Red" in payload


def test_passband_only_refuses_magnitude_view():
    """Uncalibrated (passband-only) curves must not invent ZPs to reach mag view."""
    from skvo_veb.utils.lc_bridge import apply_phot_domain_view
    from skvo_veb.utils.mission_config.tess import filter_group_meta

    lcd = _build_archive_lcd(
        [100.0, 200.0],
        [1.0, 2.0],
        authors=["user"],
        photcal=filter_group_meta(),
        flux_unit="electron s-1",
    )
    with pytest.raises(PipeException, match="incomplete|zero point|zp_"):
        apply_phot_domain_view(lcd, True)
    assert lcd.active_domain == DOMAIN_FLUX
    assert PHOTCAL_KEY_ZP_FLUX not in lcd.metadata["photcal"]


def test_background_flux_rejects_magnitude_conversion():
    """Background columns must not convert to magnitudes."""
    from skvo_veb.utils.mission_config.tess import validate_tess_magnitude_conversion
    from skvo_veb.utils.my_tools import PipeException

    lcd = _build_archive_lcd(
        [1.0, 2.0],
        [0.1, 0.1],
        authors=["SPOC"],
        photcal=resolve_tess_photcal(["SPOC"]),
        flux_unit="electron s-1",
    )
    lcd.metadata["is_background_flux"] = True
    with pytest.raises(PipeException, match="background"):
        validate_tess_magnitude_conversion(lcd)


def test_qlp_export_includes_zero_point_when_tess_mag_in_photcal():
    """VOTable export emits PhotCal zero points for QLP when photcal carries TESSMAG."""
    lcd = _build_archive_lcd(
        [12.5, 12.6],
        [0.01, 0.02],
        authors=["QLP"],
        photcal=resolve_tess_photcal(["QLP"], tess_mag=11.42),
        flux_unit=QLP_FLUX_UNIT.to_string(),
    )

    xml = export_curvedash(lcd, "votable_binary", profile="tess").decode("utf-8")
    assert "zeroPointReferenceMagnitude" in xml
    assert "11.42" in xml
    assert 'name="zeroPointFlux"' in xml
    assert "electron" not in xml.split("zeroPointFlux")[1].split("zeroPointReferenceMagnitude")[0]


def test_tars_ephemeris_expressed_as_mjd_offset():
    """TARS TMIN1 (BTJD) is stored as JD and shown as MJD on the archive page."""
    lc = _FakeLcMeta(
        5.80207,
        extra={"PER1": 1.613495, "TMIN1": 1738.8690186},
    )
    period, epoch_jd = _tars_ephemeris_from_lightkurve_list([lc])
    assert period == pytest.approx(1.613495)
    expected_jd = 1738.8690186 + TESS_TIMEORIGIN
    assert epoch_jd == pytest.approx(expected_jd)
    assert display_epoch_offset(epoch_jd, DEFAULT_EPOCH_JD) == pytest.approx(
        expected_jd - DEFAULT_EPOCH_JD
    )


def test_instrument_photcal_matches_spoc_and_cutout():
    """SPOC archive photcal and cutout enrich share the electron s-1 zero point."""
    spoc = resolve_photcal(["SPOC"], stitched=False)
    instrument = instrument_electron_s_photcal()
    assert spoc == instrument
    assert instrument[PHOTCAL_KEY_ZP_MAG] == TESS_ELECTRON_S_ZERO_POINT_REF_MAG
    assert instrument[PHOTCAL_KEY_ZP_FLUX] == TESS_ELECTRON_S_ZERO_POINT_FLUX

    from skvo_veb.utils.lc_config import (
        METADATA_KEY_FILE_COMMENTS,
        METADATA_KEY_VO_ENVELOPE,
        VO_ENVELOPE_KEY_TABLE_DESCRIPTION,
    )

    lcd = CurveDash(
        name="TIC 1",
        jd=np.array([2459000.1, 2459000.2]),
        flux=np.array([100.0, 101.0]),
        flux_err=np.array([1.0, 1.0]),
        time_unit="d",
        timescale="tdb",
        flux_unit="electron s-1",
        active_domain=DOMAIN_FLUX,
    )
    enrich_cutout_curvedash(lcd, {"pixel_type": "FFI"}, 4, "threshold")
    assert lcd.metadata["photcal"] == instrument
    desc = " ".join(lcd.metadata.get(METADATA_KEY_FILE_COMMENTS) or [])
    envelope = lcd.metadata.get(METADATA_KEY_VO_ENVELOPE) or {}
    desc = f"{desc} {envelope.get(VO_ENVELOPE_KEY_TABLE_DESCRIPTION, '')}"
    assert "20.44" in desc
    assert TESS_ELECTRON_S_ZERO_POINT_SOURCE_URL in desc


def test_upload_cutout_keeps_existing_zero_points():
    """Uploaded cutouts with a ZP pair keep them; missing ZPs get the instrument pair."""
    lcd = CurveDash(
        name="TIC 1",
        jd=np.array([2459000.1, 2459000.2]),
        flux=np.array([100.0, 101.0]),
        flux_err=np.array([1.0, 1.0]),
        time_unit="d",
        timescale="tdb",
        flux_unit="electron s-1",
        photcal={PHOTCAL_KEY_ZP_FLUX: 1.0, PHOTCAL_KEY_ZP_MAG: 19.0},
    )
    apply_upload_cutout_metadata(lcd)
    assert lcd.metadata["photcal"][PHOTCAL_KEY_ZP_MAG] == 19.0

    lcd_old = CurveDash(
        name="TIC 1",
        jd=np.array([2459000.1, 2459000.2]),
        flux=np.array([100.0, 101.0]),
        flux_err=np.array([1.0, 1.0]),
        time_unit="d",
        timescale="tdb",
        flux_unit="electron s-1",
        photcal={"filter_identifier": "TESS/TESS.Red"},
    )
    apply_upload_cutout_metadata(lcd_old)
    assert lcd_old.metadata["photcal"][PHOTCAL_KEY_ZP_MAG] == TESS_ELECTRON_S_ZERO_POINT_REF_MAG
