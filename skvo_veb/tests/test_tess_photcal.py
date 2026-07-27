"""Tests for TESS archive photcal resolution and domain conversion."""

from __future__ import annotations

import numpy as np
import pytest

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import export_curvedash
from skvo_veb.utils.lc_config import (
    DOMAIN_FLUX,
    DOMAIN_MAG,
    PHOTCAL_KEY_ZP_FLUX,
    PHOTCAL_KEY_ZP_FLUX_UNIT,
    PHOTCAL_KEY_ZP_MAG,
)
from skvo_veb.utils.mission_config.tess import (
    QLP_FLUX_UNIT,
    TESS_SPOC_ZERO_POINT_REF_MAG,
    apply_tess_phot_domain_view,
    resolve_photcal,
    resolve_tess_photcal,
    validate_tess_magnitude_conversion,
)
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.tess_lc_builder import _tess_mag_from_lightkurve_list


class _FakeLcMeta:
    """Minimal Lightkurve stand-in exposing ``meta`` for TESSMAG tests."""

    def __init__(self, tess_mag):
        self.meta = {"TESSMAG": tess_mag} if tess_mag is not None else {}


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
    assert photcal[PHOTCAL_KEY_ZP_MAG] == TESS_SPOC_ZERO_POINT_REF_MAG
    assert photcal[PHOTCAL_KEY_ZP_FLUX] == 1.0
    assert photcal[PHOTCAL_KEY_ZP_FLUX_UNIT] == "electron s-1"


def test_resolve_photcal_qlp_without_tess_mag_passband_only():
    """QLP without TESSMAG stores passband metadata only."""
    photcal = resolve_photcal(["QLP"], stitched=False)
    assert PHOTCAL_KEY_ZP_MAG not in photcal
    assert PHOTCAL_KEY_ZP_FLUX not in photcal
    assert photcal["filter_identifier"] == "TESS/TESS.Red"


def test_resolve_photcal_qlp_with_tess_mag():
    """QLP unstitched curves use header TESSMAG with dimensionless zero-point flux."""
    photcal = resolve_photcal(["QLP"], stitched=False, tess_mag=11.42)
    assert photcal[PHOTCAL_KEY_ZP_MAG] == 11.42
    assert photcal[PHOTCAL_KEY_ZP_FLUX] == 1.0
    assert photcal[PHOTCAL_KEY_ZP_FLUX_UNIT] == QLP_FLUX_UNIT.to_string()


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


def test_qlp_unit_mismatch_rejects_magnitude_conversion():
    """Incompatible flux and zero-point units must fail rather than silently convert."""
    lcd = _build_archive_lcd(
        [100.0, 200.0],
        [1.0, 2.0],
        authors=["QLP"],
        photcal=resolve_tess_photcal(["QLP"], tess_mag=11.42),
        flux_unit="electron s-1",
    )
    with pytest.raises(PipeException, match="flux_to_mag failed"):
        apply_tess_phot_domain_view(lcd, True)


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
