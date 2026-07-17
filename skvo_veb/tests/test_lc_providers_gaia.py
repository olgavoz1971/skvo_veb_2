"""Tests for the mock Gaia DR3 mission provider."""

import io

import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord

from skvo_veb.lc_providers.gaia import GaiaDr3Provider
from skvo_veb.lc_providers.lc_key import decode_lc_key, encode_lc_key
from skvo_veb.lc_providers.registry import get_provider, list_missions
from skvo_veb.utils.mission_config.gaia import GAIA_G_FILTER_IDENTIFIER
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve


def test_registry_lists_gaia_mock_mission():
    """Gaia mock provider is registered for UI discovery."""
    missions = list_missions()
    assert len(missions) == 1
    assert missions[0].mission_id == "gaia"
    assert missions[0].is_mock is True


def test_gaia_search_catalog_returns_standard_rows():
    """Cone search returns validated catalog rows inside the radius."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(ra_deg=100.0, dec_deg=10.0, radius_arcsec=10.0)
    assert len(table) == 3
    assert table["filter_name"][0] == "Gaia G"
    assert table["distance_arcsec"][0] < 1e-6


def test_gaia_search_catalog_direct_source_id():
    """Direct Gaia source id lookup returns one catalogue row without cone search."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(object_name="2222222222222222222")
    assert len(table) == 1
    assert table["object_name"][0] == "Gaia DR3 2222222222222222222"


def test_gaia_search_catalog_respects_radius_cutoff():
    """Cone search returns fewer rows when the radius is reduced."""
    provider = GaiaDr3Provider()
    full = provider.search_catalog(ra_deg=100.0, dec_deg=10.0, radius_arcsec=10.0)
    narrow = provider.search_catalog(ra_deg=100.0, dec_deg=10.0, radius_arcsec=2.0)
    assert len(full) == 3
    assert len(narrow) == 1


def test_gaia_fetch_lightcurve_returns_volightcurve():
    """Fetch emits VO-standard data that round-trips through VOLightCurve."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(ra_deg=12.0, dec_deg=45.0, radius_arcsec=10.0)
    lc_key = table["lc_key"][0]
    volc = provider.fetch_lightcurve(lc_key)
    assert isinstance(volc, VOLightCurve)
    assert len(volc) == 24
    assert "obs_time" in volc.colnames
    assert "phot" in volc.colnames
    assert volc.photdms["phot"].filter.filter_id == GAIA_G_FILTER_IDENTIFIER


def test_gaia_lc_key_round_trip():
    """Catalog lc_key encodes mission payload for fetch."""
    lc_key = encode_lc_key(
        "gaia",
        {"source_id": 1111111111111111111, "band": "G", "ra_deg": 12.0, "dec_deg": 45.0},
    )
    document = decode_lc_key(lc_key)
    assert document["mission_id"] == "gaia"
    assert document["payload"]["source_id"] == 1111111111111111111


def test_get_provider_unknown_mission_raises():
    """Registry rejects unknown mission identifiers."""
    with pytest.raises(PipeException, match="Unknown mission"):
        get_provider("unknown-mission")


def test_gaia_separation_uses_spherical_offsets():
    """Mock source offsets are computed with Astropy spherical offsets."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(ra_deg=0.0, dec_deg=0.0, radius_arcsec=10.0)
    centre = SkyCoord(0.0 * u.deg, 0.0 * u.deg, frame="icrs")
    target = SkyCoord(table["ra_deg"][1] * u.deg, table["dec_deg"][1] * u.deg, frame="icrs")
    expected = centre.separation(target).to_value(u.arcsec)
    assert table["distance_arcsec"][1] == pytest.approx(expected)
