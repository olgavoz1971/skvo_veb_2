"""Tests for mission-blind Discovery lightcurve export."""

import io

import pytest

from skvo_veb.lc_providers.catalog_schema import catalog_table_to_row_dicts
from skvo_veb.lc_providers.gaia_debug import GaiaDr3Provider
from skvo_veb.utils.lc_bridge import export_curvedash, volc_to_curvedash
from skvo_veb.utils.lc_config import METADATA_KEY_VO_ENVELOPE, VOTABLE_FORMAT_BINARY
from skvo_veb.utils.lc_discovery_load import curvedash_from_catalog_row
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
    return catalog_table_to_row_dicts(outcome.catalog)[0]


def test_curvedash_preserves_vo_envelope_after_ingest():
    """Ingest stores TIMESYS envelope metadata for later export."""
    row = _first_catalog_row()
    lcd = curvedash_from_catalog_row(row)
    envelope = lcd.metadata.get(METADATA_KEY_VO_ENVELOPE) or {}
    assert envelope.get("timescale") == "TCB"
    assert envelope.get("refposition") == "BARYCENTER"
    assert envelope.get("source_timeorigin") == 2400000.5
    assert envelope.get("table_name")
    assert envelope.get("coosys_system") == "ICRS"
    assert envelope.get("coosys_id") == "system"
    assert float(envelope.get("coosys_epoch")) == 2016.0


def test_export_curvedash_without_profile_emits_valid_votable():
    """Discovery export path uses metadata only — no mission profile."""
    row = _first_catalog_row()
    lcd = curvedash_from_catalog_row(row)
    blob = export_curvedash(lcd, VOTABLE_FORMAT_BINARY)
    volc = VOLightCurve(io.BytesIO(blob))
    assert len(volc) == len(lcd.lightcurve)
    assert volc.timesys.timescale.upper() == "TCB"
    assert volc.timesys.refposition.upper() == "BARYCENTER"
    assert volc.coosys is not None
    assert volc.coosys.system == "ICRS"
    assert float(volc.coosys.epoch) == 2016.0
    assert volc.timesys.timeorigin == pytest.approx(2400000.5)


def test_export_rewrites_timeorigin_for_mjd_obs_time():
    """Archives with non-MJD timeorigin export MJD obs_time with JD_TO_MJD offset."""
    gaia_style_origin = 2455197.5
    obs_offset_days = 55197.0
    expected_mjd = gaia_style_origin + obs_offset_days - 2400000.5

    vot_bytes = f"""<?xml version="1.0" encoding="utf-8"?>
<VOTABLE xmlns="http://www.ivoa.net/xml/VOTable/v1.3" version="1.4">
  <RESOURCE>
    <TIMESYS ID="ts" refposition="BARYCENTER" timeorigin="{gaia_style_origin}" timescale="TCB"/>
    <GROUP ID="phot_def" name="photcal">
      <PARAM name="filterIdentifier" datatype="char" arraysize="*" utype="photDM:PhotometryFilter.identifier" value="GAIA/GAIA3.G"/>
      <PARAM name="zeroPointFlux" datatype="double" utype="photDM:PhotCal.zeroPoint.flux.value" value="1.0"/>
      <PARAM name="zeroPointReferenceMagnitude" datatype="double" utype="photDM:PhotCal.zeroPoint.referenceMagnitude.value" value="0.0" unit="mag"/>
      <PARAM name="magnitudeSystem" datatype="char" arraysize="*" utype="photDM:PhotCal.magnitudeSystem.type" value="Vega"/>
      <FIELDref ref="phot"/>
    </GROUP>
    <TABLE name="Gaia epoch test">
      <DESCRIPTION>Synthetic epoch photometry for timeorigin export test.</DESCRIPTION>
      <FIELD name="obs_time" ID="obs_time" datatype="double" ucd="time.epoch" unit="d" ref="ts"/>
      <FIELD name="phot" ID="phot" datatype="double" ucd="phot.mag;em.opt" unit="mag" ref="phot_def"/>
      <FIELD name="flux_error" ID="flux_error" datatype="double" ucd="stat.error;phot.mag" unit="mag"/>
      <DATA>
        <TABLEDATA>
          <TR><TD>{obs_offset_days}</TD><TD>12.34</TD><TD>0.01</TD></TR>
          <TR><TD>{obs_offset_days + 1.0}</TD><TD>12.35</TD><TD>0.01</TD></TR>
        </TABLEDATA>
      </DATA>
    </TABLE>
  </RESOURCE>
</VOTABLE>
""".encode()

    volc = VOLightCurve(io.BytesIO(vot_bytes))
    lcd = volc_to_curvedash(volc, "gaia_epoch.vot")
    envelope = lcd.metadata.get(METADATA_KEY_VO_ENVELOPE) or {}
    assert envelope.get("source_timeorigin") == gaia_style_origin

    exported = export_curvedash(lcd, VOTABLE_FORMAT_BINARY)
    xml = exported.decode("utf-8", errors="ignore")
    assert 'timeorigin="2400000.5"' in xml
    assert f'timeorigin="{gaia_style_origin}"' not in xml

    roundtrip = VOLightCurve(io.BytesIO(exported))
    assert roundtrip.timesys.timeorigin == pytest.approx(2400000.5)
    assert float(roundtrip.table["obs_time"][0]) == pytest.approx(expected_mjd)
