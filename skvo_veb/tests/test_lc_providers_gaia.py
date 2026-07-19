"""Tests for the Gaia DR3 debug mission provider."""

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord

from skvo_veb.lc_providers.gaia_debug import GaiaDr3Provider
from skvo_veb.lc_providers.lc_key import decode_lc_key, encode_lc_key
from skvo_veb.lc_providers.registry import get_provider, list_missions
from skvo_veb.utils.mission_config.gaia import GAIA_G_FILTER_IDENTIFIER
from skvo_veb.utils.mission_config.gaia_debug_catalog import (
    AA_AND,
    AB_AND,
    V433_AQL,
)
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve


def test_registry_lists_gaia_providers():
    """Gaia debug and VEB providers are registered for UI discovery."""
    missions = list_missions()
    mission_ids = {item.mission_id for item in missions}
    assert mission_ids == {"gaia", "gaia_dr3_veb"}

    by_id = {item.mission_id: item for item in missions}
    assert by_id["gaia"].is_mock is True
    assert by_id["gaia"].display_name == "Gaia DR3 (debug)"
    assert by_id["gaia_dr3_veb"].is_mock is False
    assert by_id["gaia_dr3_veb"].display_name == "Gaia DR3 VEB"


def test_gaia_search_catalog_respects_time_bounds():
    """Cone search filters debug SSA products by optional MJD limits."""
    provider = GaiaDr3Provider()
    all_rows = provider.search_catalog(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=10.0,
    )
    assert len(all_rows) == 3

    middle_only = provider.search_catalog(
        ra_deg=AB_AND.ra_deg,
        dec_deg=AB_AND.dec_deg,
        radius_arcsec=10.0,
        time_start_mjd=57250.0,
        time_end_mjd=57260.0,
    )
    assert len(middle_only) == 3
    assert set(middle_only["filter_name"]) == {"Gaia G", "Gaia BP", "Gaia RP"}
    assert all(
        name == AB_AND.catalogue_object_name for name in middle_only["object_name"]
    )

    upper_bound_only = provider.search_catalog(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=10.0,
        time_end_mjd=57150.0,
    )
    assert len(upper_bound_only) == 3
    assert upper_bound_only["object_name"][0] == AA_AND.catalogue_object_name

    lower_bound_only = provider.search_catalog(
        ra_deg=V433_AQL.ra_deg,
        dec_deg=V433_AQL.dec_deg,
        radius_arcsec=10.0,
        time_start_mjd=57300.0,
    )
    assert len(lower_bound_only) == 3
    assert lower_bound_only["object_name"][0] == V433_AQL.catalogue_object_name


def test_gaia_search_catalog_returns_standard_rows():
    """Cone search at AA And returns one SSA row per passband."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=10.0,
    )
    assert len(table) == 3
    assert set(table["filter_name"]) == {"Gaia G", "Gaia BP", "Gaia RP"}
    assert table["t_min"][0] == pytest.approx(57100.0)
    assert table["t_max"][0] == pytest.approx(57180.0)
    assert table["distance_arcsec"][0] < 1e-6
    assert table["period"][0] == pytest.approx(AA_AND.period_for_band("G"))


def test_gaia_search_catalog_direct_source_id():
    """Direct Gaia source id lookup returns three passband products."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(object_name=str(AA_AND.source_id))
    assert len(table) == 3
    assert table["object_name"][0] == AA_AND.catalogue_object_name


def test_gaia_search_catalog_rejects_common_names():
    """Gaia catalogue lookup accepts source_id strings only, not common names."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(object_name="AA And")
    assert len(table) == 0
    table = provider.search_catalog(object_name="V* AA And")
    assert len(table) == 0


def test_gaia_search_catalog_unknown_source_returns_empty():
    """Unknown Gaia source ids do not synthesise placeholder catalogue rows."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(object_name="9999999999999999999")
    assert len(table) == 0


def test_gaia_search_catalog_empty_cone_off_catalogue():
    """Sky regions without debug sources return an empty table."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(ra_deg=100.0, dec_deg=10.0, radius_arcsec=10.0)
    assert len(table) == 0


def test_gaia_search_catalog_respects_radius_cutoff():
    """Cone search returns fewer SSA products when the radius is reduced."""
    provider = GaiaDr3Provider()
    centre_ra = (AA_AND.ra_deg + AB_AND.ra_deg) / 2.0
    centre_dec = (AA_AND.dec_deg + AB_AND.dec_deg) / 2.0
    full = provider.search_catalog(
        ra_deg=centre_ra,
        dec_deg=centre_dec,
        radius_arcsec=3600.0 * 11.0,
    )
    narrow = provider.search_catalog(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=2.0,
    )
    assert len(full) == 6
    assert len(narrow) == 3


def test_gaia_fetch_lightcurve_returns_volightcurve():
    """Fetch emits VO-standard data that round-trips through VOLightCurve."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(object_name=str(AA_AND.source_id))
    lc_key = table["lc_key"][0]
    volc = provider.fetch_lightcurve(lc_key)
    assert isinstance(volc, VOLightCurve)
    assert len(volc) == 48
    assert "obs_time" in volc.colnames
    assert "phot" in volc.colnames
    assert volc.photdms["phot"].filter.filter_id == GAIA_G_FILTER_IDENTIFIER


def test_gaia_fetch_rejects_unknown_source_id():
    """Fetch refuses source ids outside the debug micro-catalogue."""
    provider = GaiaDr3Provider()
    lc_key = encode_lc_key(
        "gaia",
        {"source_id": 9999999999999999999, "band": "G", "ra_deg": 0.0, "dec_deg": 0.0},
    )
    with pytest.raises(PipeException, match="not in the debug catalogue"):
        provider.fetch_lightcurve(lc_key)


def test_gaia_lc_key_round_trip():
    """Catalog lc_key encodes mission payload for fetch."""
    lc_key = encode_lc_key(
        "gaia",
        {
            "source_id": AA_AND.source_id,
            "band": "G",
            "ra_deg": AA_AND.ra_deg,
            "dec_deg": AA_AND.dec_deg,
        },
    )
    document = decode_lc_key(lc_key)
    assert document["mission_id"] == "gaia"
    assert document["payload"]["source_id"] == AA_AND.source_id


def test_get_provider_unknown_mission_raises():
    """Registry rejects unknown mission identifiers."""
    with pytest.raises(PipeException, match="Unknown mission"):
        get_provider("unknown-mission")


def test_gaia_separation_uses_real_source_coordinates():
    """Cone search separations are computed from real debug-source positions."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=10.0,
    )
    centre = SkyCoord(AA_AND.ra_deg * u.deg, AA_AND.dec_deg * u.deg, frame="icrs")
    target = SkyCoord(table["ra_deg"][0] * u.deg, table["dec_deg"][0] * u.deg, frame="icrs")
    expected = centre.separation(target).to_value(u.arcsec)
    assert table["distance_arcsec"][0] == pytest.approx(expected)


def test_v433_aql_lightcurve_has_no_declared_period():
    """V433 Aql debug products are non-periodic in the catalogue metadata."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(object_name=str(V433_AQL.source_id))
    assert len(table) == 3
    assert np.all(np.ma.getmaskarray(table["period"]))
