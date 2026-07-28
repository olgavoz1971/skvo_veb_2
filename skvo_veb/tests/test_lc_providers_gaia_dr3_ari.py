"""Tests for the Gaia DR3 (ARI) TAP ObsCore provider."""

from __future__ import annotations

from pathlib import Path

import pytest
from astropy.table import Table

from skvo_veb.lc_providers.gaia_dr3_ari import config
from skvo_veb.lc_providers.gaia_dr3_ari.obscore_catalog import map_obscore_table_to_catalog
from skvo_veb.lc_providers.gaia_dr3_ari.provider import GaiaDr3AriProvider
from skvo_veb.lc_providers.gaia_debug.debug_catalog import AA_AND
from skvo_veb.lc_providers.lc_key import decode_lc_key
from skvo_veb.lc_providers.tap.dialect import TapQueryDialect


def _sample_obscore_table() -> Table:
    """Builds one ObsCore row matching the ARI bundled-product shape."""
    return Table(
        {
            "s_ra": [AA_AND.ra_deg],
            "s_dec": [AA_AND.dec_deg],
            "t_min": [56889.6511],
            "t_max": [57887.5337],
            "t_xel": [20],
            "access_url": ["https://example.test/gaia_dr3_epoch.vot"],
            "obs_id": [str(AA_AND.source_id)],
        }
    )


def test_map_obscore_table_expands_to_three_bands():
    """One ObsCore hit produces G, BP, and RP catalogue rows."""
    catalog = map_obscore_table_to_catalog(
        _sample_obscore_table(),
        provider_id=config.PROVIDER_ID,
    )
    assert len(catalog) == 3
    assert set(catalog["filter_name"]) == {"Gaia G", "Gaia BP", "Gaia RP"}
    assert all(catalog["n_points"] == 20)
    assert all(catalog["provider_note"] == config.N_POINTS_PROVIDER_NOTE)


def test_obscore_catalog_lc_key_payload():
    """Each catalogue row stores access_url, band, and table_id for fetch."""
    catalog = map_obscore_table_to_catalog(
        _sample_obscore_table(),
        provider_id=config.PROVIDER_ID,
    )
    payload = decode_lc_key(catalog["lc_key"][0])["payload"]
    assert payload["access_url"] == "https://example.test/gaia_dr3_epoch.vot"
    assert payload["band"] == "G"
    assert payload["table_id"] == 0
    assert payload["filter_name"] == "Gaia G"


def test_ari_adql_obs_id_query():
    """Direct obs_id ADQL 2.0 targets ivoa.ObsCore with collection filters."""
    adql = config.adql_catalog_by_obs_id(AA_AND.source_id)
    assert "FROM ivoa.ObsCore" in adql
    assert f"obs_id = '{AA_AND.source_id}'" in adql
    assert "obs_collection = 'gaiadr3'" in adql
    assert "dataproduct_type = 'timeseries'" in adql


def test_ari_adql_cone_query():
    """Cone ADQL 2.0 uses ICRS POINT/CIRCLE geometry on ObsCore sky columns."""
    adql = config.adql_catalog_cone(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=10.0,
    )
    assert "CONTAINS(POINT('ICRS', s_ra, s_dec), CIRCLE('ICRS'" in adql
    assert f"CIRCLE('ICRS', {AA_AND.ra_deg}, {AA_AND.dec_deg}," in adql


def test_ari_tap_dialect_is_adql_20():
    """ARI provider declares ADQL 2.0 for the Heidelberg TAP service."""
    assert config.TAP_QUERY_DIALECT == TapQueryDialect.ADQL_2_0


def test_ari_search_catalog_by_source_id(monkeypatch):
    """search_catalog maps one ObsCore row to three standard catalogue products."""
    provider = GaiaDr3AriProvider()
    captured: dict[str, str] = {}

    def _fake_tap(_url, adql, *, dialect):
        captured["dialect"] = dialect
        captured["adql"] = adql
        return _sample_obscore_table()

    monkeypatch.setattr(
        "skvo_veb.lc_providers.gaia_dr3_ari.provider.run_tap_sync_query",
        _fake_tap,
    )

    table = provider.search_catalog(object_name=str(AA_AND.source_id))
    assert len(table) == 3
    assert captured["dialect"] == TapQueryDialect.ADQL_2_0
    assert f"obs_id = '{AA_AND.source_id}'" in captured["adql"]


def test_ari_fetch_lightcurve_local_sample(monkeypatch):
    """fetch_lightcurve downloads one band from the bundled sample VOTable."""
    provider = GaiaDr3AriProvider()
    sample_path = Path(__file__).resolve().parents[2] / "data" / "gaia_ari.vot"
    payload = sample_path.read_bytes()

    def _fake_urlopen(request, timeout=0):
        class _Resp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return _Resp()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen,
    )

    catalog = map_obscore_table_to_catalog(
        _sample_obscore_table(),
        provider_id=config.PROVIDER_ID,
    )
    lc_key = catalog["lc_key"][0]
    volc = provider.fetch_lightcurve(lc_key)
    assert len(volc) == 20
    assert volc.photdms["mag"].filter.filter_id == "GAIADR3.G"
    assert float(volc.photdms["mag"].photcal.zp_mag.value) == 0.0
    assert volc.table.meta.get("period") == pytest.approx(1.7217551595287013)

