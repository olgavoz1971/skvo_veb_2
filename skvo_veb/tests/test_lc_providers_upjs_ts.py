"""Tests for the UPJŠ time-series TAP provider."""

import numpy as np
from astropy.table import Table

from skvo_veb.lc_providers.lc_key import decode_lc_key
from skvo_veb.lc_providers.registry import get_provider, list_missions
from skvo_veb.lc_providers.upjs_ts import config
from skvo_veb.lc_providers.upjs_ts.provider import UpjsTsProvider
from skvo_veb.lc_providers.upjs_ts.resolve_target import resolve_upjs_target_name
from skvo_veb.lc_providers.upjs_ts.ssa_catalog import map_ssa_table_to_catalog


def _sample_upjs_ssa_table() -> Table:
    """Builds a TAP SSA table matching the UPJŠ service shape."""
    return Table(
        {
            "object_id": ["3716", "3716"],
            "accref": [
                "https://skvo.science.upjs.sk/upjs_ts/q/sdl/dlget?ID=example-v",
                "https://skvo.science.upjs.sk/upjs_ts/q/sdl/dlget?ID=example-r",
            ],
            "ssa_bandpass": ["V", "R"],
            "ssa_targname": [
                "Gaia DR3 1866728237239754112",
                "Gaia DR3 1866728237239754112",
            ],
            "ssa_targclass": ["RR*", "RR*"],
            "ssa_location": [np.array([289.432, 36.102]), np.array([289.432, 36.102])],
            "ssa_length": [800, 790],
            "ssa_collection": ["UPJS", "UPJS"],
            "t_min": [54000.0, 54000.0],
            "t_max": [60000.0, 60000.0],
            "mean_mag": [13.94, 14.1],
        }
    )


def test_map_upjs_ssa_table_uses_ssa_targname_for_object_name():
    """Catalogue rows show Gaia DR3 SSA labels rather than internal object ids."""
    catalog = map_ssa_table_to_catalog(
        _sample_upjs_ssa_table(),
        provider_id=config.PROVIDER_ID,
    )
    assert len(catalog) == 2
    assert catalog["object_name"][0] == "Gaia DR3 1866728237239754112"
    assert catalog["object_class"][0] == "RR*"


def test_upjs_adql_gaia_targname_query():
    """Gaia DR3 ADQL selects on indexed ssa_targname."""
    adql = config.adql_catalog_by_ssa_targname("Gaia DR3 1866728237239754112")
    assert "FROM upjs_ts.ts_ssa" in adql
    assert "ssa_targname = 'Gaia DR3 1866728237239754112'" in adql


def test_upjs_adql_objects_simbad_case_insensitive():
    """Objects-table ADQL uses UPPER for case-insensitive Simbad matching."""
    adql = config.adql_objects_by_simbad_name("bd+76   642")
    assert "FROM upjs_ts.objects" in adql
    assert "UPPER(simbad_name) = UPPER(" in adql


def test_resolve_upjs_target_name_skips_gaia_labels():
    """Inner resolver leaves Gaia DR3 strings to direct ssa_targname search."""
    assert resolve_upjs_target_name("Gaia DR3 1866728237239754112") is None
    assert resolve_upjs_target_name("1866728237239754112") is None


def test_resolve_upjs_target_name_uses_objects_table(monkeypatch):
    """Simbad and VSX names resolve to object_id via upjs_ts.objects."""
    objects_table = Table(
        {
            "object_id": ["1"],
            "gaia_name": ["1656754192432536832"],
            "simbad_name": ["BD+76   642"],
            "vsx_name": [""],
        }
    )

    def fake_tap(url, adql, dialect=None):
        if "upjs_ts.objects" in adql and "simbad_name" in adql:
            return objects_table
        return Table(names=["object_id", "gaia_name", "simbad_name", "vsx_name"])

    monkeypatch.setattr(
        "skvo_veb.lc_providers.upjs_ts.cross_ident.run_tap_sync_query",
        fake_tap,
    )

    match = resolve_upjs_target_name("bd+76   642")
    assert match is not None
    assert match.archive_id == "1"
    assert match.match_kind == "upjs_simbad_name"


def test_upjs_registry_entry():
    """UPJŠ TS provider is registered for Discovery."""
    mission_ids = {item.mission_id for item in list_missions()}
    assert "upjs_ts" in mission_ids
    provider = get_provider("upjs_ts")
    assert provider.display_name == "UPJŠ TS"


def test_upjs_search_catalog_by_gaia_name(monkeypatch):
    """Direct Gaia DR3 labels query ts_ssa by ssa_targname."""
    provider = UpjsTsProvider()
    captured: dict[str, str] = {}

    def fake_tap(url, adql, dialect=None):
        captured["adql"] = adql
        return _sample_upjs_ssa_table()

    monkeypatch.setattr(
        "skvo_veb.lc_providers.upjs_ts.provider.run_tap_sync_query",
        fake_tap,
    )

    catalog = provider.search_catalog(object_name="Gaia DR3 1866728237239754112")
    assert "ssa_targname = 'Gaia DR3 1866728237239754112'" in captured["adql"]
    assert len(catalog) == 2

    lc_key = catalog["lc_key"][0]
    payload = decode_lc_key(lc_key)["payload"]
    assert payload["object_id"] == "3716"
