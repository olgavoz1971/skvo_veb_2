"""Tests for Discovery lightcurve loading utilities."""

import io

import pytest

from skvo_veb.lc_providers.catalog_schema import catalog_table_to_row_dicts
from skvo_veb.lc_providers.gaia_debug import GaiaDr3Provider
from skvo_veb.utils.lc_bridge import export_curvedash
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, DOMAIN_MAG, JD_TO_MJD, VOTABLE_FORMAT_BINARY, display_epoch_offset
from skvo_veb.utils.lc_discovery_load import (
    catalog_row_for_lc_key,
    curvedash_from_catalog_row,
    drop_invalid_photometry_rows,
    fetch_discovery_volightcurve,
    mission_id_from_lc_key,
)
from skvo_veb.utils.lc_discovery_search import run_catalog_search
from skvo_veb.lc_providers.gaia_debug.debug_catalog import AA_AND
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


def test_gaia_debug_catalog_epoch_displays_as_mjd_offset():
    """Catalogue epoch must become absolute JD, not double-subtract JD_TO_MJD."""
    row = _first_catalog_row()
    expected_mjd = AA_AND.band_models["G"].epoch_mjd
    assert row["epoch"] == pytest.approx(expected_mjd + JD_TO_MJD)

    lcd = curvedash_from_catalog_row(row)
    assert lcd.epoch == pytest.approx(expected_mjd + JD_TO_MJD)
    assert display_epoch_offset(lcd.epoch, DEFAULT_EPOCH_JD) == pytest.approx(expected_mjd)

    exported = export_curvedash(lcd, VOTABLE_FORMAT_BINARY)
    roundtrip = VOLightCurve(io.BytesIO(exported))
    assert float(roundtrip.table.meta["epoch"]) == pytest.approx(expected_mjd)


def test_drop_invalid_photometry_rows_mag_domain():
    """Magnitude-native curves drop NaN mag rows, not flux."""
    from skvo_veb.utils.curve_dash import CurveDash

    lcd = CurveDash(
        jd=[57000.0, 57001.0, 57002.0],
        mag=[18.5, float("nan"), 18.7],
        mag_err=[0.01, 0.01, 0.01],
        active_domain=DOMAIN_MAG,
    )
    drop_invalid_photometry_rows(lcd)
    assert len(lcd.lightcurve) == 2
    assert "mag" in lcd.lightcurve.columns
    assert "flux" not in lcd.lightcurve.columns
