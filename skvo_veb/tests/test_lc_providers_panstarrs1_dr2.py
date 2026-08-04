"""Tests for the Pan-STARRS1 DR2 MAST TAP lightcurve provider."""

from __future__ import annotations

import pytest
from astropy.table import Table

from skvo_veb.lc_providers.lc_key import decode_lc_key
from skvo_veb.lc_providers.panstarrs1_dr2 import config
from skvo_veb.lc_providers.panstarrs1_dr2.build_volightcurve import build_volightcurve_from_detections
from skvo_veb.lc_providers.panstarrs1_dr2.mean_object_catalog import map_mean_object_table_to_catalog
from skvo_veb.lc_providers.panstarrs1_dr2.provider import Panstarrs1Dr2Provider
from skvo_veb.lc_providers.panstarrs1_dr2.ps1_names import parse_ps1_obj_id


@pytest.fixture
def provider():
    """Returns a Pan-STARRS1 DR2 provider instance."""
    return Panstarrs1Dr2Provider()


def test_parse_ps1_obj_id_digits():
    """Long digit strings and prefixed ids parse as objID values."""
    assert parse_ps1_obj_id("123456789012345678") == 123456789012345678
    assert parse_ps1_obj_id("PS1 123456789012345678") == 123456789012345678
    assert parse_ps1_obj_id("Pan-STARRS1 123456789012345678") == 123456789012345678
    assert parse_ps1_obj_id("PS J001") is None
    assert parse_ps1_obj_id("999") is None


def test_provider_max_cone_radius_below_mast_limit(provider):
    """Cone radius cap stays inside the MAST PS1 TAP 0.25 deg service limit."""
    assert provider.max_discovery_search_radius_deg() < 0.25
    assert provider.max_discovery_search_radius_deg() == config.MAX_DISCOVERY_SEARCH_RADIUS_DEG


def test_adql_cone_includes_geometry_and_random_id():
    """Cone ADQL uses MAST geometry and randomId ordering."""
    adql = config.adql_mean_objects_cone(ra_deg=10.0, dec_deg=20.0, radius_arcsec=30.0, row_limit=50)
    assert "TOP 50" in adql
    assert "MeanObjectView" in adql
    assert "randomId" in adql
    assert "nDetections > 1" in adql
    assert "objname" not in adql


def test_map_mean_object_expands_bands_with_detections():
    """One mean-object row with g and r detections yields two catalogue rows."""
    tap = Table(
        {
            "objID": [999],
            "raMean": [10.0],
            "decMean": [20.0],
            "ng": [5],
            "nr": [2],
            "ni": [0],
            "nz": [0],
            "ny": [0],
            "gMeanPSFMag": [18.1],
            "rMeanPSFMag": [17.9],
        }
    )
    catalog = map_mean_object_table_to_catalog(
        tap,
        provider_id=config.PROVIDER_ID,
        centre_ra_deg=10.0,
        centre_dec_deg=20.0,
    )
    assert len(catalog) == 2
    assert set(catalog["filter_name"]) == {"PS1 g", "PS1 r"}
    assert catalog["object_name"][0] == "999"
    assert catalog["provider_note"][0] == config.DISCOVERY_CATALOG_PROVIDER_NOTE


def test_map_mean_object_sorts_by_separation():
    """Catalogue rows are ordered by ascending distance from the cone centre."""
    tap = Table(
        {
            "objID": [1, 2],
            "raMean": [10.0, 10.0 + 0.01],
            "decMean": [20.0, 20.0],
            "ng": [1, 1],
            "nr": [0, 0],
            "ni": [0, 0],
            "nz": [0, 0],
            "ny": [0, 0],
        }
    )
    catalog = map_mean_object_table_to_catalog(
        tap,
        provider_id=config.PROVIDER_ID,
        centre_ra_deg=10.0,
        centre_dec_deg=20.0,
    )
    assert len(catalog) == 2
    assert catalog["object_name"][0] == "1"
    assert catalog["object_name"][1] == "2"
    assert catalog["distance_arcsec"][0] < catalog["distance_arcsec"][1]


def test_build_volightcurve_from_detections():
    """Detection table builds flux-native VOLightCurve."""
    det = Table(
        {
            "obsTime": [58000.1, 58001.2],
            "psfFlux": [1e-3, 1.1e-3],
            "psfFluxErr": [1e-4, 1.2e-4],
            "psfQfPerfect": [0.95, 0.99],
        }
    )
    volc = build_volightcurve_from_detections(
        det,
        obj_id=999,
        filter_code="r",
        ra_deg=10.0,
        dec_deg=20.0,
        object_name="999",
    )
    assert len(volc) == 2
    assert "phot" in volc.colnames
    assert "label" not in volc.colnames


def test_resolve_target_name_long_obj_id(provider):
    """Long numeric targets resolve to objID archive lookup."""
    match = provider.resolve_target_name("608067000000000000")
    assert match is not None
    assert match.archive_id == "608067000000000000"
    assert match.match_kind == "ps1_obj_id"


def test_resolve_target_name_rejects_ps_iau_name(provider):
    """PS IAU strings are not resolved (objname TAP lookup disabled)."""
    assert provider.resolve_target_name("PS J123.4+56.7") is None


def test_search_catalog_by_obj_id_object_name(monkeypatch, provider):
    """Direct object_name entry with long objID queries by objID only."""
    mean = Table(
        {
            "objID": [608067000000000000],
            "raMean": [10.0],
            "decMean": [20.0],
            "ng": [1],
            "nr": [0],
            "ni": [0],
            "nz": [0],
            "ny": [0],
        }
    )
    captured = {}

    def _fake_tap(_url, adql, **_kwargs):
        captured["adql"] = adql
        return mean

    monkeypatch.setattr(
        "skvo_veb.lc_providers.panstarrs1_dr2.provider.run_tap_sync_query",
        _fake_tap,
    )
    catalog = provider.search_catalog(object_name="608067000000000000")
    assert "objID = 608067000000000000" in captured["adql"]
    assert "objname" not in captured["adql"]
    assert catalog["object_name"][0] == "608067000000000000"


def test_search_catalog_cone_sorted_by_separation(monkeypatch, provider):
    """Cone discovery returns rows sorted by distance_arcsec."""
    mean = Table(
        {
            "objID": [200, 100],
            "raMean": [10.0 + 0.02, 10.0],
            "decMean": [20.0, 20.0],
            "ng": [1, 1],
            "nr": [0, 0],
            "ni": [0, 0],
            "nz": [0, 0],
            "ny": [0, 0],
        }
    )

    monkeypatch.setattr(
        "skvo_veb.lc_providers.panstarrs1_dr2.provider.run_tap_sync_query",
        lambda *_args, **_kwargs: mean,
    )

    catalog = provider.search_catalog(ra_deg=10.0, dec_deg=20.0, radius_arcsec=15.0)
    assert list(catalog["object_name"]) == ["100", "200"]
    assert catalog["distance_arcsec"][0] <= catalog["distance_arcsec"][1]


def test_search_catalog_cone_mocked(monkeypatch, provider):
    """Cone search maps mocked MeanObjectView rows."""
    mean = Table(
        {
            "objID": [100],
            "raMean": [10.0],
            "decMean": [20.0],
            "ng": [3],
            "nr": [0],
            "ni": [0],
            "nz": [0],
            "ny": [0],
            "gMeanPSFMag": [19.0],
        }
    )

    monkeypatch.setattr(
        "skvo_veb.lc_providers.panstarrs1_dr2.provider.run_tap_sync_query",
        lambda *_args, **_kwargs: mean,
    )

    catalog = provider.search_catalog(ra_deg=10.0, dec_deg=20.0, radius_arcsec=15.0)
    assert len(catalog) == 1
    payload = decode_lc_key(catalog["lc_key"][0])["payload"]
    assert payload["obj_id"] == "100"
    assert payload["filter"] == "g"


def test_fetch_lightcurve_mocked(monkeypatch, provider):
    """Fetch runs detection TAP and builds VOLightCurve."""
    det = Table(
        {
            "obsTime": [58000.5],
            "psfFlux": [2e-3],
            "psfFluxErr": [2e-4],
            "psfQfPerfect": [1.0],
        }
    )
    key = map_mean_object_table_to_catalog(
        Table(
            {
                "objID": [100],
                "raMean": [10.0],
                "decMean": [20.0],
                "ng": [1],
                "nr": [0],
                "ni": [0],
                "nz": [0],
                "ny": [0],
            }
        ),
        provider_id=config.PROVIDER_ID,
    )["lc_key"][0]

    monkeypatch.setattr(
        "skvo_veb.lc_providers.panstarrs1_dr2.provider.fetch_detection_table",
        lambda **_kwargs: det,
    )

    volc = provider.fetch_lightcurve(key)
    assert len(volc) == 1
    assert volc.table.meta.get("mission") == config.PROVIDER_ID
