"""Tests for COOSYS ingest, envelope preservation, and VOTable export round-trip."""

from __future__ import annotations

import io

import numpy as np
from astropy.table import Table

from skvo_veb.utils.lc_bridge import export_curvedash, volc_to_curvedash
from skvo_veb.utils.lc_config import METADATA_KEY_VO_ENVELOPE, VOTABLE_FORMAT_BINARY
from skvo_veb.volightcurve import VOLightCurve, write_vo_lightcurve

MINIMAL_VOT_WITH_COOSYS = b"""<?xml version="1.0" encoding="utf-8"?>
<VOTABLE xmlns="http://www.ivoa.net/xml/VOTable/v1.3" version="1.4">
  <RESOURCE>
    <COOSYS ID="system" epoch="2016.0" system="ICRS"/>
    <TIMESYS ID="ts" refposition="BARYCENTER" timeorigin="2400000.5" timescale="TCB"/>
    <GROUP ID="phot_def" name="photcal">
      <PARAM name="filterIdentifier" datatype="char" arraysize="*" utype="photDM:PhotometryFilter.identifier" value="GAIA/GAIA3.G"/>
      <PARAM name="zeroPointFlux" datatype="double" utype="photDM:PhotCal.zeroPoint.flux.value" value="1.0"/>
      <PARAM name="zeroPointReferenceMagnitude" datatype="double" utype="photDM:PhotCal.zeroPoint.referenceMagnitude.value" value="0.0" unit="mag"/>
      <PARAM name="magnitudeSystem" datatype="char" arraysize="*" utype="photDM:PhotCal.magnitudeSystem.type" value="Vega"/>
      <FIELDref ref="phot"/>
    </GROUP>
    <TABLE name="Gaia DR3 test">
      <DESCRIPTION>Synthetic Gaia DR3 test lightcurve for COOSYS round-trip.</DESCRIPTION>
      <FIELD name="obs_time" ID="obs_time" datatype="double" ucd="time.epoch" unit="d" ref="ts"/>
      <FIELD name="phot" ID="phot" datatype="double" ucd="phot.mag;em.opt" unit="mag" ref="phot_def"/>
      <FIELD name="flux_error" ID="flux_error" datatype="double" ucd="stat.error;phot.mag" unit="mag"/>
      <PARAM name="ra" datatype="double" ucd="pos.eq.ra" value="346.345"/>
      <PARAM name="dec" datatype="double" ucd="pos.eq.dec" value="47.676"/>
      <DATA>
        <TABLEDATA>
          <TR><TD>56889.65</TD><TD>12.34</TD><TD>0.01</TD></TR>
          <TR><TD>56890.65</TD><TD>12.35</TD><TD>0.01</TD></TR>
        </TABLEDATA>
      </DATA>
    </TABLE>
  </RESOURCE>
</VOTABLE>
"""


def test_volightcurve_ingest_extracts_coosys():
    """Ingest reads COOSYS from a VOTable into VOLightCurve.coosys."""
    volc = VOLightCurve(io.BytesIO(MINIMAL_VOT_WITH_COOSYS))
    assert volc.coosys is not None
    assert volc.coosys.coosys_id == "system"
    assert volc.coosys.system == "ICRS"
    assert float(volc.coosys.epoch) == 2016.0


def test_write_vo_lightcurve_emits_coosys_when_requested():
    """write_vo_lightcurve writes COOSYS only when coordinate metadata is supplied."""
    table = Table()
    table["obs_time"] = np.array([59000.1, 59000.2])
    table["phot"] = np.array([12.5, 12.6])
    table["flux_error"] = np.array([0.01, 0.02])

    buf = io.BytesIO()
    write_vo_lightcurve(
        output_stream_or_path=buf,
        table_data=table,
        table_name="Test source",
        filter_identifier="GAIA/GAIA3.G",
        coosys_id="system",
        coosys_system="ICRS",
        coosys_epoch=2016.0,
        binary=False,
    )
    xml = buf.getvalue().decode("utf-8")
    assert "COOSYS" in xml
    assert 'system="ICRS"' in xml
    assert 'epoch="2016.0"' in xml

    buf_no_cs = io.BytesIO()
    write_vo_lightcurve(
        output_stream_or_path=buf_no_cs,
        table_data=table,
        table_name="Test source",
        filter_identifier="GAIA/GAIA3.G",
        binary=False,
    )
    assert "COOSYS" not in buf_no_cs.getvalue().decode("utf-8")


def test_coosys_survives_curvedash_export_roundtrip():
    """Discovery-style ingest stores COOSYS in vo_envelope and export round-trips it."""
    volc = VOLightCurve(io.BytesIO(MINIMAL_VOT_WITH_COOSYS))
    lcd = volc_to_curvedash(volc, "gaia_test.vot")
    envelope = lcd.metadata.get(METADATA_KEY_VO_ENVELOPE) or {}
    assert envelope.get("coosys_system") == "ICRS"
    assert envelope.get("coosys_id") == "system"
    assert float(envelope.get("coosys_epoch")) == 2016.0

    exported = export_curvedash(lcd, VOTABLE_FORMAT_BINARY)
    roundtrip = VOLightCurve(io.BytesIO(exported))
    assert roundtrip.coosys is not None
    assert roundtrip.coosys.system == "ICRS"
    assert roundtrip.coosys.coosys_id == "system"
    assert float(roundtrip.coosys.epoch) == 2016.0
