"""Tests for Gaia DR3 (ARI) multi-table VOTable photcal ingest."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from volightcurve import VOLightCurve
from volightcurve.lightcurve import _gavo_votable_metadata_tree, extract_photdm

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


def _enriched(payload: bytes, table_id: int = 0):
    """Enriches one band and parses it the way Discovery does."""
    from lc_discovery.providers.gaia_dr3_ari.fetch_metadata import enrich_votable

    return VOLightCurve(io.BytesIO(enrich_votable(payload, table_id=table_id)))


def test_gaia_ari_keeps_archive_table_name(gaia_ari_payload):
    """The selected table keeps its archive name."""
    volc = _enriched(gaia_ari_payload)
    assert volc.table.meta["name"].endswith("G band time series")
    assert "lightcurve_title" not in volc.table.meta


def test_gaia_ari_drops_repeated_columns_and_keeps_photometry(gaia_ari_payload):
    """Repeated columns go. Time, magnitude, flux, and flux error stay."""
    volc = _enriched(gaia_ari_payload)
    assert "band" not in volc.table.colnames
    assert "source_id" not in volc.table.colnames
    assert "pf" not in volc.table.colnames
    assert "mag_err" not in volc.table.colnames
    for name in ("time", "mag", "flux", "flux_error", "flux_over_error"):
        assert name in volc.table.colnames
    assert volc.table.meta["period"] == pytest.approx(1.7217551595287013)


def test_gaia_ari_splits_mag_and_flux_photcal(gaia_ari_payload):
    """Magnitude keeps the Jy zero point. Flux uses 1 in the flux column unit."""
    volc = _enriched(gaia_ari_payload)
    mag = volc.photdms["mag"].photcal
    flux = volc.photdms["flux"].photcal
    assert float(mag.zp_flux.value) == pytest.approx(3296.2)
    assert float(mag.zp_mag.value) == pytest.approx(0.0)
    assert float(flux.zp_flux.value) == pytest.approx(1.0)
    assert str(flux.zp_flux.unit) in {"1 / s", "s**-1"}
    assert float(flux.zp_mag.value) == pytest.approx(25.6874)
    assert volc.photdms["flux_error"].photcal is flux
    assert "flux_over_error" not in volc.photdms or volc.photdms["flux_over_error"].photcal is None


def test_gaia_ari_raw_file_issues_one_g_band_table():
    """The ARI download keeps one band and the G photcal split."""
    from pathlib import Path

    raw = Path("/home/voz/projects/UPJS/tmp/g_ari.xml").read_bytes()
    volc = _enriched(raw, table_id=0)
    assert volc.table.meta["name"] == "Gaia DR3 1704795806820110080 - G band time series"
    assert "BP band" not in volc.table.meta["name"]
    assert volc.photdms["mag"].filter.filter_id == "GAIADR3.G"
    assert float(volc.photdms["flux"].photcal.zp_mag.value) == pytest.approx(25.6874)
    assert "source_id" not in volc.table.colnames
    assert volc.table.meta["period"] == pytest.approx(0.32540451593736336)
