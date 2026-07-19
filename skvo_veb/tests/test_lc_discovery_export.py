"""Tests for mission-blind Discovery lightcurve export."""

import io

from skvo_veb.lc_providers.catalog_schema import catalog_table_to_row_dicts
from skvo_veb.lc_providers.gaia_debug import GaiaDr3Provider
from skvo_veb.utils.lc_bridge import export_curvedash
from skvo_veb.utils.lc_config import METADATA_KEY_VO_ENVELOPE, VOTABLE_FORMAT_BINARY
from skvo_veb.utils.lc_discovery_load import curvedash_from_catalog_row
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
    return catalog_table_to_row_dicts(outcome.catalog)[0]


def test_curvedash_preserves_vo_envelope_after_ingest():
    """Ingest stores TIMESYS envelope metadata for later export."""
    row = _first_catalog_row()
    lcd = curvedash_from_catalog_row(row)
    envelope = lcd.metadata.get(METADATA_KEY_VO_ENVELOPE) or {}
    assert envelope.get("timescale") == "TCB"
    assert envelope.get("refposition") == "BARYCENTER"
    assert envelope.get("timeorigin") == 2400000.5
    assert envelope.get("table_name")


def test_export_curvedash_without_profile_emits_valid_votable():
    """Discovery export path uses metadata only — no mission profile."""
    row = _first_catalog_row()
    lcd = curvedash_from_catalog_row(row)
    blob = export_curvedash(lcd, VOTABLE_FORMAT_BINARY)
    volc = VOLightCurve(io.BytesIO(blob))
    assert len(volc) == len(lcd.lightcurve)
    assert volc.timesys.timescale.upper() == "TCB"
    assert volc.timesys.refposition.upper() == "BARYCENTER"
