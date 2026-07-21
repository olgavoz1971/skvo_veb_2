"""Tests for the OGLE OCVS TAP provider."""

from astropy.table import Table

from skvo_veb.lc_providers.lc_key import decode_lc_key
from skvo_veb.lc_providers.ogle_ocvs import config
from skvo_veb.lc_providers.ogle_ocvs.object_id import (
    normalize_ogle_object_id,
    pick_ogle_archive_id_from_simbad,
)
from skvo_veb.lc_providers.ogle_ocvs.provider import OgleOcvsProvider
from skvo_veb.lc_providers.ogle_ocvs.ssa_catalog import map_ssa_table_to_catalog
from skvo_veb.lc_providers.shared.tap_ssa_row import parse_ssa_location
from skvo_veb.lc_providers.registry import get_provider, list_missions
from skvo_veb.lc_providers.tap.dialect import TapQueryDialect
from skvo_veb.utils.simbad_resolver import SimbadResolveResult


def _sample_ssa_table() -> Table:
    """Builds a TAP SSA table matching the UPJS OGLE service shape."""
    return Table(
        {
            "object_id": ["OGLE-SMC-ECL-05425", "OGLE-SMC-ECL-05425"],
            "accref": [
                "https://skvo.science.upjs.sk/ogle/q/sdl/dlget?ID=ivo://astro.upjs/~?ogle/q/OGLE-SMC-ECL-05425-I",
                "https://skvo.science.upjs.sk/ogle/q/sdl/dlget?ID=ivo://astro.upjs/~?ogle/q/OGLE-SMC-ECL-05425-V",
            ],
            "ssa_dstitle": [
                "OGLE I lightcurve for OGLE-SMC-ECL-05425",
                "OGLE V lightcurve for OGLE-SMC-ECL-05425",
            ],
            "ssa_bandpass": ["I", "V"],
            "ssa_targname": ["OGLE-SMC-ECL-05425", "OGLE-SMC-ECL-05425"],
            "ssa_location": [
                "(17.193708333333312, -72.11341666666681)",
            ]
            * 2,
            "ssa_length": [2312, 2100],
            "ssa_collection": ["OGLE-SMC-ECL", "OGLE-SMC-ECL"],
            "t_min": [55346.431799999904, 55346.431799999904],
            "t_max": [60457.425590000115, 60457.425590000115],
            "mean_mag": [18.784052, 19.123456],
        }
    )


def test_normalize_ogle_object_id_accepts_canonical_form():
    """Canonical archive ids pass through with zero-padded suffix."""
    assert normalize_ogle_object_id("OGLE-SMC-ECL-05425") == "OGLE-SMC-ECL-05425"
    assert normalize_ogle_object_id("ogle-smc-ecl-5425") == "OGLE-SMC-ECL-05425"


def test_normalize_ogle_object_id_fixes_simbad_spacing():
    """Loose Simbad spellings collapse to archive object_id form."""
    assert normalize_ogle_object_id("OGLE SMC-ECL- 5425") == "OGLE-SMC-ECL-05425"
    assert normalize_ogle_object_id("OGLE SMC ECL 5425") == "OGLE-SMC-ECL-05425"


def test_pick_ogle_archive_id_from_simbad():
    """Simbad cross-identifiers with OGLE names map to archive ids."""
    result = SimbadResolveResult(
        query_name="OGLE SMC-ECL- 5425",
        main_id="V* DP Peg",
        ra_deg=0.0,
        dec_deg=0.0,
        identifiers=["OGLE SMC-ECL- 5425", "TYC 1-2-1"],
    )
    match = pick_ogle_archive_id_from_simbad(result)
    assert match is not None
    assert match.archive_id == "OGLE-SMC-ECL-05425"
    assert match.match_kind == "ogle_object_id"


def test_parse_ssa_location():
    """Parenthesis sky location syntax parses to RA/Dec degrees."""
    ra, dec = parse_ssa_location("(17.193708333333312, -72.11341666666681)")
    assert ra == 17.193708333333312
    assert dec == -72.11341666666681


def test_map_ssa_table_to_catalog_includes_mean_mag():
    """TAP rows map to catalogue schema with optional mean magnitude column."""
    catalog = map_ssa_table_to_catalog(
        _sample_ssa_table(),
        provider_id=config.PROVIDER_ID,
    )
    assert len(catalog) == 2
    assert set(catalog["filter_name"]) == {"OGLE I", "OGLE V"}
    assert float(catalog["mag"][0]) == 18.784052

    lc_key = catalog["lc_key"][0]
    payload = decode_lc_key(lc_key)["payload"]
    assert payload["accref"].startswith("https://skvo.science.upjs.sk/")
    assert payload["object_id"] == "OGLE-SMC-ECL-05425"


def test_ogle_adql_object_id_query():
    """Direct object_id ADQL uses quoted string equality."""
    adql = config.adql_catalog_by_object_id("OGLE-SMC-ECL-05425")
    assert "FROM ogle.ts_ssa" in adql
    assert "object_id = 'OGLE-SMC-ECL-05425'" in adql
    assert adql.startswith("SELECT ")


def test_ogle_adql_cone_query():
    """Cone ADQL puts the sky point inside the search circle."""
    adql = config.adql_catalog_cone(ra_deg=17.19, dec_deg=-72.11, radius_arcsec=15.0)
    assert "1 = CONTAINS(ssa_location, CIRCLE(" in adql
    assert "'ICRS'" not in adql


def test_ogle_registry_entry():
    """OGLE OCVS provider is registered for Discovery."""
    mission_ids = {item.mission_id for item in list_missions()}
    assert "ogle_ocvs" in mission_ids
    provider = get_provider("ogle_ocvs")
    assert provider.display_name == "OGLE OCVS"
    assert provider.is_mock is False


def test_ogle_search_catalog_by_object_id(monkeypatch):
    """search_catalog normalises loose names and maps TAP rows."""
    provider = OgleOcvsProvider()
    captured: dict[str, str] = {}

    def _fake_tap(_url, adql, *, dialect):
        captured["adql"] = adql
        captured["dialect"] = dialect
        return _sample_ssa_table()

    monkeypatch.setattr(
        "skvo_veb.lc_providers.ogle_ocvs.provider.run_tap_sync_query",
        _fake_tap,
    )

    table = provider.search_catalog(object_name="OGLE SMC-ECL- 5425")
    assert len(table) == 2
    assert captured["dialect"] == TapQueryDialect.ADQL_2_1
    assert "object_id = 'OGLE-SMC-ECL-05425'" in captured["adql"]


def test_ogle_fetch_lightcurve_from_accref(monkeypatch):
    """fetch_lightcurve downloads accref bytes and enriches metadata."""
    provider = OgleOcvsProvider()
    catalog = map_ssa_table_to_catalog(
        _sample_ssa_table(),
        provider_id=config.PROVIDER_ID,
    )
    lc_key = catalog["lc_key"][0]

    class _FakeVolc:
        def __init__(self):
            self.table = type(
                "T",
                (),
                {
                    "meta": {
                        "name": "OGLE-SMC-ECL-05425",
                        "description": "OGLE I-band lightcurve.",
                    }
                },
            )()

        def __len__(self):
            return 2312

    def _fake_fetch(accref, **kwargs):
        assert accref.startswith("https://")
        return _FakeVolc()

    monkeypatch.setattr(
        "skvo_veb.lc_providers.ogle_ocvs.provider.fetch_volightcurve_from_accref",
        _fake_fetch,
    )
    volc = provider.fetch_lightcurve(lc_key)
    assert volc.table.meta["lightcurve_title"] == "OGLE-SMC-ECL-05425 in OGLE I filter"
