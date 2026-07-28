"""Tests for the Gaia DR3 (AIP) TAP epoch-photometry provider."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from astropy.table import Table

from skvo_veb.lc_providers.gaia_dr3_aip import config
from skvo_veb.lc_providers.gaia_dr3_aip.catalog import map_prefetched_sources_to_catalog
from skvo_veb.lc_providers.gaia_dr3_aip.epoch_photometry import (
    band_point_count,
    band_time_bounds,
    cache_dict_from_tap_table,
    extract_band_lightcurve,
)
from skvo_veb.lc_providers.gaia_dr3_aip.provider import GaiaDr3AipProvider
from skvo_veb.lc_providers.gaia_dr3_aip.vari_metadata import (
    PeriodKind,
    period_days_from_value,
    pick_vari_route,
    route_sources_by_vari_table,
)
from skvo_veb.lc_providers.lc_key import decode_lc_key
from skvo_veb.lc_providers.tap.dialect import TapQueryDialect
from skvo_veb.utils.lc_bridge import volc_to_curvedash
from skvo_veb.utils.lc_config import DOMAIN_MAG, PHOTCAL_KEY_ZP_FLUX, PHOTCAL_KEY_ZP_MAG

GAIA_AIP_VOT = Path(__file__).resolve().parents[2] / "data" / "gaia_aip.vot"
SAMPLE_SOURCE_ID = 10655814178816


@pytest.fixture(scope="module")
def gaia_aip_epoch_table() -> Table:
    """Loads the bundled Gaia@AIP epoch-photometry sample VOTable."""
    return Table.read(GAIA_AIP_VOT, format="votable")


@pytest.fixture(scope="module")
def gaia_aip_epoch_payload(gaia_aip_epoch_table) -> dict:
    """Serialises the sample epoch row for prefetch tests."""
    return cache_dict_from_tap_table(gaia_aip_epoch_table)[SAMPLE_SOURCE_ID]


@pytest.fixture
def prefetch_cache_tmp(tmp_path, monkeypatch):
    """Redirects AIP prefetch storage to a temporary directory."""
    monkeypatch.setattr(config, "PREFETCH_CACHE_DIR", tmp_path)
    return tmp_path


def test_aip_adql_source_by_id():
    """Direct source lookup joins classifier result and filters epoch photometry."""
    adql = config.adql_gaia_source_by_id(SAMPLE_SOURCE_ID)
    assert "FROM gaiadr3.gaia_source AS gs" in adql
    assert "LEFT JOIN gaiadr3.vari_classifier_result AS vcr" in adql
    assert "vcr.best_class_name" in adql
    assert f"gs.source_id = {SAMPLE_SOURCE_ID}" in adql
    assert "gs.has_epoch_photometry = 'True'" in adql


def test_aip_adql_cone_query():
    """Cone search uses ICRS geometry on gaia_source sky columns with class join."""
    adql = config.adql_gaia_source_cone(ra_deg=274.587, dec_deg=-21.707, radius_arcsec=180.0)
    assert "CONTAINS(POINT('ICRS', gs.ra, gs.dec), CIRCLE('ICRS'" in adql
    assert "LEFT JOIN gaiadr3.vari_classifier_result AS vcr" in adql
    assert "gs.has_epoch_photometry = 'True'" in adql
    adql_limited = config.adql_gaia_source_cone(
        ra_deg=274.587,
        dec_deg=-21.707,
        radius_arcsec=180.0,
        row_limit=100,
    )
    assert "SELECT TOP 100 " in adql_limited


def test_aip_adql_epoch_photometry_batch():
    """Epoch photometry query selects bundled array columns."""
    adql = config.adql_epoch_photometry_for_source_ids([SAMPLE_SOURCE_ID, 123])
    assert "FROM gaiadr3.epoch_photometry" in adql
    assert "g_transit_time" in adql
    assert f"source_id IN ({SAMPLE_SOURCE_ID}, 123)" in adql


def test_aip_tap_dialect_is_adql_20():
    """AIP provider declares ADQL 2.0 for the Gaia@AIP TAP service."""
    assert config.TAP_QUERY_DIALECT == TapQueryDialect.ADQL_2_0


def test_extract_g_band_from_sample(gaia_aip_epoch_payload):
    """Sample epoch row yields 16 valid G-band epochs with MJD times."""
    time_mjd, mag, mag_err = extract_band_lightcurve(gaia_aip_epoch_payload, band_code="G")
    assert len(time_mjd) == 16
    assert len(mag) == 16
    assert np.all(np.isfinite(mag))
    assert np.all(np.isfinite(mag_err))
    assert np.all(mag_err > 0.0)
    t_min, t_max = band_time_bounds(gaia_aip_epoch_payload, band_code="G")
    assert t_min == pytest.approx(float(np.min(time_mjd)))
    assert t_max == pytest.approx(float(np.max(time_mjd)))


def test_map_prefetched_source_to_three_bands(gaia_aip_epoch_payload):
    """One prefetched source expands to G, BP, and RP catalogue rows."""
    source_table = Table(
        {
            "source_id": [SAMPLE_SOURCE_ID],
            "ra": [274.5873003514723],
            "dec": [-21.706522062249086],
            "phot_g_mean_mag": [20.45],
        }
    )
    catalog = map_prefetched_sources_to_catalog(
        source_table,
        {SAMPLE_SOURCE_ID: gaia_aip_epoch_payload},
        provider_id=config.PROVIDER_ID,
    )
    assert len(catalog) == 3
    assert set(catalog["filter_name"]) == {"Gaia G", "Gaia BP", "Gaia RP"}
    assert all(catalog["n_points"] > 0)
    assert catalog["mag"][catalog["filter_name"] == "Gaia G"][0] == pytest.approx(20.45)


def test_aip_catalog_lc_key_payload(gaia_aip_epoch_payload):
    """Catalogue rows store source_id, band, and sky position for fetch."""
    source_table = Table(
        {
            "source_id": [SAMPLE_SOURCE_ID],
            "ra": [274.587],
            "dec": [-21.707],
            "phot_g_mean_mag": [20.45],
        }
    )
    catalog = map_prefetched_sources_to_catalog(
        source_table,
        {SAMPLE_SOURCE_ID: gaia_aip_epoch_payload},
        provider_id=config.PROVIDER_ID,
    )
    payload = decode_lc_key(catalog["lc_key"][0])["payload"]
    assert payload["source_id"] == str(SAMPLE_SOURCE_ID)
    assert payload["band"] == "G"
    assert payload["filter_name"] == "Gaia G"


def test_map_prefetched_source_includes_class_and_period(gaia_aip_epoch_payload):
    """Catalogue rows carry classifier class and routed variability period."""
    source_table = Table(
        {
            "source_id": [SAMPLE_SOURCE_ID],
            "ra": [274.5873003514723],
            "dec": [-21.706522062249086],
            "phot_g_mean_mag": [20.45],
            "best_class_name": ["RR Lyrae Candidatel"],
        }
    )
    catalog = map_prefetched_sources_to_catalog(
        source_table,
        {SAMPLE_SOURCE_ID: gaia_aip_epoch_payload},
        provider_id=config.PROVIDER_ID,
        period_by_source={SAMPLE_SOURCE_ID: 0.5123},
    )
    assert list(catalog["object_class"]) == ["RR Lyrae Candidatel"] * len(catalog)
    assert all(value == pytest.approx(0.5123) for value in catalog["period"])


def test_vari_route_picks_first_true_flag():
    """First true vari_summary flag selects the specialised vari table route."""
    summary = Table(
        {
            "source_id": [123],
            "in_vari_cepheid": [False],
            "in_vari_rrlyrae": [True],
            "in_vari_eclipsing_binary": [True],
            "in_vari_long_period_variable": [False],
            "in_vari_ms_oscillator": [False],
            "in_vari_short_timescale": [False],
            "in_vari_rotation_modulation": [False],
            "in_vari_planetary_transit": [False],
            "in_vari_compact_companion": [False],
            "in_vari_agn": [False],
            "in_vari_microlensing": [False],
        }
    )
    route = pick_vari_route(summary[0])
    assert route is not None
    assert route.table_name == "gaiadr3.vari_rrlyrae"
    grouped = route_sources_by_vari_table(summary)
    assert grouped == {"gaiadr3.vari_rrlyrae": [123]}


def test_period_days_from_frequency():
    """Frequency columns convert to period in days."""
    assert period_days_from_value(2.0, period_kind=PeriodKind.FREQUENCY) == pytest.approx(0.5)


def test_aip_search_catalog_prefetches_epoch_rows(monkeypatch, prefetch_cache_tmp):
    """search_catalog runs source, vari, and epoch photometry TAP queries."""
    provider = GaiaDr3AipProvider()
    calls: list[str] = []

    def _fake_tap(_url, adql, *, dialect):
        calls.append(adql)
        if "gaiadr3.gaia_source" in adql:
            return Table(
                {
                    "source_id": [SAMPLE_SOURCE_ID],
                    "ra": [274.587],
                    "dec": [-21.707],
                    "phot_g_mean_mag": [20.45],
                    "best_class_name": ["RR Lyrae Candidatel"],
                }
            )
        if "gaiadr3.vari_summary" in adql:
            return Table(
                {
                    "source_id": [SAMPLE_SOURCE_ID],
                    "in_vari_cepheid": [False],
                    "in_vari_rrlyrae": [True],
                    "in_vari_eclipsing_binary": [False],
                    "in_vari_long_period_variable": [False],
                    "in_vari_ms_oscillator": [False],
                    "in_vari_short_timescale": [False],
                    "in_vari_rotation_modulation": [False],
                    "in_vari_planetary_transit": [False],
                    "in_vari_compact_companion": [False],
                    "in_vari_agn": [False],
                    "in_vari_microlensing": [False],
                }
            )
        if "gaiadr3.vari_rrlyrae" in adql:
            return Table({"source_id": [SAMPLE_SOURCE_ID], "pf": [0.5123]})
        return Table.read(GAIA_AIP_VOT, format="votable")

    monkeypatch.setattr(
        "skvo_veb.lc_providers.gaia_dr3_aip.provider.run_tap_sync_query",
        _fake_tap,
    )

    catalog = provider.search_catalog(object_name=str(SAMPLE_SOURCE_ID))
    assert len(catalog) == 3
    assert list(catalog["object_class"]) == ["RR Lyrae Candidatel"] * len(catalog)
    assert all(value == pytest.approx(0.5123) for value in catalog["period"])
    assert any("gaiadr3.gaia_source" in call for call in calls)
    assert any("gaiadr3.vari_summary" in call for call in calls)
    assert any("gaiadr3.vari_rrlyrae" in call for call in calls)
    assert any("gaiadr3.epoch_photometry" in call for call in calls)
    assert (prefetch_cache_tmp / f"{SAMPLE_SOURCE_ID}.json").is_file()


def test_aip_fetch_lightcurve_from_prefetch(
    monkeypatch,
    prefetch_cache_tmp,
    gaia_aip_epoch_payload,
):
    """fetch_lightcurve builds a magnitude-native curve from prefetched arrays."""
    from skvo_veb.lc_providers.gaia_dr3_aip.prefetch_store import store_epoch_photometry

    provider = GaiaDr3AipProvider()
    payload = dict(gaia_aip_epoch_payload)
    payload["object_class"] = "RR Lyrae Candidatel"
    payload["period_days"] = 0.5123
    store_epoch_photometry(SAMPLE_SOURCE_ID, payload)

    source_table = Table(
        {
            "source_id": [SAMPLE_SOURCE_ID],
            "ra": [274.5873003514723],
            "dec": [-21.706522062249086],
            "phot_g_mean_mag": [20.45],
        }
    )
    catalog = map_prefetched_sources_to_catalog(
        source_table,
        {SAMPLE_SOURCE_ID: gaia_aip_epoch_payload},
        provider_id=config.PROVIDER_ID,
    )
    g_row = catalog[catalog["filter_name"] == "Gaia G"][0]
    volc = provider.fetch_lightcurve(g_row["lc_key"])
    assert len(volc) == band_point_count(gaia_aip_epoch_payload, band_code="G")
    phot_col = "mag" if "mag" in volc.photdms else "phot"
    assert volc.photdms[phot_col].filter.filter_id == "GAIADR3.G"
    assert volc.table.meta.get("period") == pytest.approx(0.5123)
    assert volc.table.meta.get("object_class") == "RR Lyrae Candidatel"

    lcd = volc_to_curvedash(volc, "gaia_aip_G.vot")
    assert lcd.active_domain == DOMAIN_MAG
    photcal = lcd.metadata.get("photcal") or {}
    assert photcal.get(PHOTCAL_KEY_ZP_FLUX) == pytest.approx(3296.2)
    assert photcal.get(PHOTCAL_KEY_ZP_MAG) == pytest.approx(0.0)
