"""Tests for Discovery lightcurve loading utilities."""

from skvo_veb.lc_providers.catalog_schema import catalog_table_to_row_dicts
from skvo_veb.lc_providers.gaia_debug import GaiaDr3Provider
from skvo_veb.utils.lc_discovery_load import (
    catalog_row_for_lc_key,
    curvedash_from_catalog_row,
    fetch_discovery_volightcurve,
    mission_id_from_lc_key,
)
from skvo_veb.utils.lc_discovery_search import run_catalog_search
from skvo_veb.utils.mission_config.gaia_debug_catalog import AA_AND
from skvo_veb.volightcurve import VOLightCurve


def _first_catalog_row():
    provider = GaiaDr3Provider()
    outcome = run_catalog_search(
        provider,
        str(AA_AND.source_id),
        10.0,
        "arcsec",
    )
    assert len(outcome.catalog) > 0
    return catalog_table_to_row_dicts(outcome.catalog)[0]


def test_catalog_row_for_lc_key_finds_matching_row():
    row = _first_catalog_row()
    row_data = [row, {"lc_key": "other"}]
    assert catalog_row_for_lc_key(row_data, row["lc_key"]) == row
    assert catalog_row_for_lc_key(row_data, "missing") is None


def test_mission_id_from_lc_key_reads_embedded_slug():
    row = _first_catalog_row()
    assert mission_id_from_lc_key(row["lc_key"]) == "gaia"


def test_fetch_discovery_volightcurve_returns_volightcurve():
    row = _first_catalog_row()
    volc = fetch_discovery_volightcurve(row["lc_key"])
    assert isinstance(volc, VOLightCurve)
    assert len(volc) > 0


def test_curvedash_from_catalog_row_returns_points():
    row = _first_catalog_row()
    lcd = curvedash_from_catalog_row(row)
    assert lcd.lightcurve is not None
    assert len(lcd.lightcurve) > 0
    assert lcd.period is not None or row.get("period") is None
