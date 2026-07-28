"""Tests for Gaia DR3 (ARI) multi-table VOTable photcal ingest."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from skvo_veb.lc_providers.shared.gaia_epoch_mag_error import MAG_ERR_FROM_SNR_FACTOR
from skvo_veb.utils.lc_bridge import export_curvedash, volc_to_curvedash
from skvo_veb.utils.lc_config import DOMAIN_FLUX, DOMAIN_MAG, PHOTCAL_KEY_ZP_FLUX, PHOTCAL_KEY_ZP_MAG
from skvo_veb.volightcurve import VOLightCurve
from skvo_veb.volightcurve.lightcurve import _gavo_votable_metadata_tree, extract_photdm

GAIA_ARI_VOT = Path(__file__).resolve().parents[3] / "data" / "gaia_ari.vot"


@pytest.fixture(scope="module")
def gaia_ari_payload() -> bytes:
    """Loads the bundled Gaia DR3 ARI sample VOTable."""
    return GAIA_ARI_VOT.read_bytes()


def test_multi_table_votable_requires_table_id(gaia_ari_payload):
    """Bundled Gaia products fail fast without an explicit table selector."""
    with pytest.raises(ValueError, match="Multiple VOTable tables"):
        VOLightCurve(io.BytesIO(gaia_ari_payload))


def test_extract_photdm_links_field_ref_to_mag(gaia_ari_payload):
    """FIELD/@ref to photcal GROUP/@ID maps photcal onto the mag column."""
    photdms = extract_photdm(_gavo_votable_metadata_tree(gaia_ari_payload))
    assert "mag" in photdms
    photdm = photdms["mag"]
    assert photdm.filter.filter_id == "GAIADR3.G"
    assert float(photdm.photcal.zp_flux.value) == pytest.approx(3296.2)


def test_volightcurve_g_band_ingest(gaia_ari_payload):
    """G-band table ingest attaches photcal to mag and parses 20 epochs."""
    volc = VOLightCurve(io.BytesIO(gaia_ari_payload), table_id=0)
    assert len(volc) == 20
    assert "mag" in volc.photdms
    assert volc.photdms["mag"].filter.filter_id == "GAIADR3.G"


def test_gaia_ari_enrich_uses_source_id_for_title(gaia_ari_payload):
    """ARI titles ignore verbose archive TABLE names and use source_id instead."""
    from skvo_veb.lc_providers.gaia_dr3_ari.fetch_metadata import enrich_fetched_volightcurve

    volc = VOLightCurve(io.BytesIO(gaia_ari_payload), table_id=0)
    enrich_fetched_volightcurve(volc, filter_name="Gaia G")
    assert volc.table.meta["lightcurve_title"] == (
        "Gaia DR3 4090664085620846720 in Gaia G filter"
    )
    assert volc.table.meta["name"] == volc.table.meta["lightcurve_title"]


def test_gaia_ari_mag_err_from_flux_over_error(gaia_ari_payload):
    """ARI enrichment derives mag-native uncertainties and drops archive flux_error."""
    from skvo_veb.lc_providers.gaia_dr3_ari.fetch_metadata import enrich_fetched_volightcurve

    volc = VOLightCurve(io.BytesIO(gaia_ari_payload), table_id=0)
    enrich_fetched_volightcurve(volc, filter_name="Gaia G")
    assert "mag_err" in volc.table.colnames
    assert "flux_error" not in volc.table.colnames

    snr = volc.table["flux_over_error"]
    if hasattr(snr, "value"):
        snr = snr.value
    expected = MAG_ERR_FROM_SNR_FACTOR / np.asarray(snr, dtype=float)
    mag_err = volc.table["mag_err"]
    if hasattr(mag_err, "value"):
        mag_err = mag_err.value
    np.testing.assert_allclose(mag_err, expected, rtol=1e-12)

    lcd = volc_to_curvedash(volc, "gaia_ari_G.vot")
    assert lcd.active_domain == DOMAIN_MAG
    np.testing.assert_allclose(lcd.mag_err.values, expected, rtol=1e-12)
    assert np.all(lcd.mag_err.values < 1.0)


def test_gaia_ari_mag_to_jy_roundtrip(gaia_ari_payload):
    """Mag-first ingest converts to Jy flux and back using anchored photcal."""
    from skvo_veb.lc_providers.gaia_dr3_ari.fetch_metadata import enrich_fetched_volightcurve

    volc = VOLightCurve(io.BytesIO(gaia_ari_payload), table_id=0)
    enrich_fetched_volightcurve(volc, filter_name="Gaia G")

    lcd = volc_to_curvedash(volc, "gaia_ari_G.vot")
    assert lcd.active_domain == DOMAIN_MAG

    photcal = lcd.metadata.get("photcal") or {}
    assert photcal.get(PHOTCAL_KEY_ZP_FLUX) == pytest.approx(3296.2)
    assert photcal.get(PHOTCAL_KEY_ZP_MAG) == pytest.approx(0.0)
    assert lcd.metadata.get("period") == pytest.approx(1.7217551595287013)

    original_mag = lcd.mag.copy()
    lcd.convert_to_flux()
    assert lcd.active_domain == DOMAIN_FLUX
    assert str(lcd.flux_unit).strip() in {"Jy", "jy"}

    lcd.convert_to_mag()
    assert lcd.active_domain == DOMAIN_MAG
    np.testing.assert_allclose(lcd.mag.values, original_mag.values, rtol=1e-12)

    original_mag_err = lcd.mag_err.copy()
    lcd.convert_to_flux()
    lcd.convert_to_mag()
    np.testing.assert_allclose(lcd.mag_err.values, original_mag_err.values, rtol=1e-10)


def test_gaia_ari_export_includes_both_zero_points(gaia_ari_payload):
    """Discovery export writes anchored photcal with flux and reference mag ZPs."""
    from skvo_veb.lc_providers.gaia_dr3_ari.fetch_metadata import enrich_fetched_volightcurve

    volc = VOLightCurve(io.BytesIO(gaia_ari_payload), table_id=0)
    enrich_fetched_volightcurve(volc, filter_name="Gaia G")
    lcd = volc_to_curvedash(volc, "gaia_ari_G.vot")

    votable_bytes = export_curvedash(lcd, "votable", profile=None)
    exported = votable_bytes.decode("utf-8", errors="replace")
    assert "zeroPointFlux" in exported or "zeroPoint.flux" in exported
    assert "zeroPointReferenceMagnitude" in exported or "referenceMagnitude" in exported
    assert "GAIADR3.G" in exported
