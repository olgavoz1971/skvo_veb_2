"""Tests for the ASAS-SN Sky Patrol lightcurve provider."""

from __future__ import annotations

import pandas as pd
import pytest
from astropy.table import Table

from skvo_veb.lc_providers.asassn import config
from skvo_veb.lc_providers.asassn.build_volightcurve import build_volightcurve_from_band_table
from skvo_veb.lc_providers.asassn.catalog import map_metadata_table_to_catalog
from skvo_veb.lc_providers.asassn.provider import AsassnProvider
from skvo_veb.lc_providers.catalog_schema import read_discovery_truncation_meta
from skvo_veb.lc_providers.gaia_debug.debug_catalog import AA_AND
from skvo_veb.lc_providers.lc_key import decode_lc_key


def _sample_metadata_df() -> pd.DataFrame:
    """One ``stellar_main`` discovery row for AA And."""
    return pd.DataFrame(
        {
            "asas_sn_id": [85900701048],
            "ra_deg": [AA_AND.ra_deg],
            "dec_deg": [AA_AND.dec_deg],
            "pstarrs_g_mag": [10.898],
            "gaia_id": [AA_AND.source_id],
        }
    )


def test_map_metadata_expands_two_candidate_bands():
    """One metadata row becomes g and V candidate catalogue rows."""
    catalog = map_metadata_table_to_catalog(
        _sample_metadata_df(),
        provider_id=config.PROVIDER_ID,
    )
    assert len(catalog) == 2
    assert set(catalog["filter_name"]) == {config.ASASSN_G_FILTER_NAME, config.ASASSN_V_FILTER_NAME}
    g_rows = catalog[catalog["filter_name"] == config.ASASSN_G_FILTER_NAME]
    assert float(g_rows["mag"][0]) == pytest.approx(10.898)
    v_rows = catalog[catalog["filter_name"] == config.ASASSN_V_FILTER_NAME]
    assert v_rows["mag"].mask.all()
    assert all(catalog["provider_note"] == config.DISCOVERY_CATALOG_PROVIDER_NOTE)


def test_catalog_lc_key_payload():
    """Fetch handle stores canonical asas_sn_id and band."""
    catalog = map_metadata_table_to_catalog(
        _sample_metadata_df(),
        provider_id=config.PROVIDER_ID,
    )
    payload = decode_lc_key(catalog["lc_key"][0])["payload"]
    assert payload == {"asas_sn_id": "85900701048", "band": "g"}


def test_build_volightcurve_from_band_table():
    """Band slice builds a flux-native VOLightCurve with photometry columns."""
    band_df = pd.DataFrame(
        {
            "jd": [2459000.5, 2459001.5],
            "flux": [120.0, 125.0],
            "flux_err": [0.3, 0.4],
        }
    )
    volc = build_volightcurve_from_band_table(
        band_df,
        asas_sn_id=85900701048,
        band_code="g",
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
    )
    assert len(volc) == 2
    assert "phot" in volc.colnames


def test_search_catalog_by_gaia_id(monkeypatch):
    """search_catalog maps mocked metadata to two catalogue rows."""
    provider = AsassnProvider()

    def _fake_gaia(_gaia_id):
        return _sample_metadata_df()

    monkeypatch.setattr(
        "skvo_veb.lc_providers.asassn.provider.fetch_discovery_by_gaia_id",
        _fake_gaia,
    )

    table = provider.search_catalog(object_name=str(AA_AND.source_id))
    assert len(table) == 2


def test_search_catalog_cone_truncation_hint(monkeypatch):
    """Cone search annotates truncation when source count hits the cap."""
    provider = AsassnProvider()
    rows = []
    for index in range(provider.discovery_cone_query_row_limit()):
        rows.append(
            {
                "asas_sn_id": 85900701048 + index,
                "ra_deg": AA_AND.ra_deg,
                "dec_deg": AA_AND.dec_deg,
                "pstarrs_g_mag": 10.0,
            }
        )

    def _fake_cone(**_kwargs):
        return pd.DataFrame(rows)

    monkeypatch.setattr(
        "skvo_veb.lc_providers.asassn.provider.fetch_discovery_cone",
        _fake_cone,
    )

    table = provider.search_catalog(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=10.0,
    )
    assert len(table) == provider.discovery_cone_query_row_limit() * 2
    may_be, detail = read_discovery_truncation_meta(table)
    assert may_be is True
    assert detail is not None
    assert "ASAS-SN sources" in detail


def test_fetch_lightcurve_empty_band(monkeypatch):
    """Fetch fails fast when the candidate band has no photometry rows."""
    provider = AsassnProvider()
    catalog = map_metadata_table_to_catalog(
        _sample_metadata_df(),
        provider_id=config.PROVIDER_ID,
    )
    v_key = catalog[catalog["filter_name"] == config.ASASSN_V_FILTER_NAME]["lc_key"][0]

    photometry = pd.DataFrame(
        {
            "jd": [2459000.5],
            "flux": [120.0],
            "flux_err": [0.3],
            "phot_filter": ["g"],
        }
    )

    monkeypatch.setattr(
        "skvo_veb.lc_providers.asassn.provider.fetch_photometry_by_asas_sn_id",
        lambda _sid: photometry,
    )
    monkeypatch.setattr(
        "skvo_veb.lc_providers.asassn.provider.fetch_epoch_period_for_asas_sn_id",
        lambda _sid: (None, None),
    )
    monkeypatch.setattr(
        "skvo_veb.lc_providers.asassn.provider.fetch_discovery_by_asas_sn_id",
        lambda _sid: _sample_metadata_df(),
    )

    from skvo_veb.utils.my_tools import PipeException

    with pytest.raises(PipeException, match="no observations"):
        provider.fetch_lightcurve(v_key)


def test_fetch_lightcurve_builds_volc(monkeypatch):
    """Fetch downloads photometry, builds VOLightCurve, and enriches metadata."""
    provider = AsassnProvider()
    catalog = map_metadata_table_to_catalog(
        _sample_metadata_df(),
        provider_id=config.PROVIDER_ID,
    )
    g_key = catalog[catalog["filter_name"] == config.ASASSN_G_FILTER_NAME]["lc_key"][0]

    photometry = pd.DataFrame(
        {
            "jd": [2459000.5, 2459001.5],
            "flux": [120.0, 125.0],
            "flux_err": [0.3, 0.4],
            "phot_filter": ["g", "g"],
        }
    )

    monkeypatch.setattr(
        "skvo_veb.lc_providers.asassn.provider.fetch_photometry_by_asas_sn_id",
        lambda _sid: photometry,
    )
    monkeypatch.setattr(
        "skvo_veb.lc_providers.asassn.provider.fetch_epoch_period_for_asas_sn_id",
        lambda _sid: (2459000.0, 0.46),
    )
    monkeypatch.setattr(
        "skvo_veb.lc_providers.asassn.provider.fetch_discovery_by_asas_sn_id",
        lambda _sid: _sample_metadata_df(),
    )

    volc = provider.fetch_lightcurve(g_key)
    assert len(volc) == 2
    assert volc.table.meta.get("mission") == config.PROVIDER_ID
    assert volc.table.meta.get("period") == pytest.approx(0.46)
