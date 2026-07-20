"""Tests for TIMESYS-linked epoch normalisation and export."""

from __future__ import annotations

import io

import pytest

from skvo_veb.utils.lc_bridge import export_curvedash, volc_to_curvedash
from skvo_veb.utils.lc_config import JD_TO_MJD, VOTABLE_FORMAT_BINARY
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve
from skvo_veb.volightcurve.time_reference import (
    absolute_jd_to_time_offset,
    extract_timesys_metadata_from_gavo,
    extract_timesys_registry_from_gavo,
    normalise_table_epoch_to_absolute_jd,
    time_offset_to_absolute_jd,
)
from skvo_veb.volightcurve.lightcurve import _gavo_votable_tree_from_source


def _gaia_style_votable(*, include_epoch: bool = True, second_time_col: bool = False) -> bytes:
    """Builds a Gaia-like VOTable with Gaia-style timeorigin and optional epoch PARAM."""
    epoch_param = ""
    if include_epoch:
        epoch_param = (
            '<PARAM name="epoch" datatype="double" ucd="time.epoch" unit="d" '
            'value="2207.1263399818404"/>'
        )
    second_field = ""
    second_row_cell = ""
    if second_time_col:
        second_field = (
            '<FIELD name="aux_time" datatype="double" ucd="time.epoch" unit="d" ref="ts2"/>'
        )
        second_row_cell = "<TD>1.0</TD>"

    return f"""<?xml version="1.0" encoding="utf-8"?>
<VOTABLE xmlns="http://www.ivoa.net/xml/VOTable/v1.3" version="1.4">
  <RESOURCE>
    <TIMESYS ID="ts" refposition="BARYCENTER" timeorigin="2455197.5" timescale="TCB"/>
    <TIMESYS ID="ts2" refposition="BARYCENTER" timeorigin="2400000.5" timescale="TCB"/>
    <GROUP ID="phot_def" name="photcal">
      <PARAM name="filterIdentifier" datatype="char" arraysize="*" utype="photDM:PhotometryFilter.identifier" value="GAIA/GAIA3.G"/>
      <PARAM name="zeroPointFlux" datatype="double" utype="photDM:PhotCal.zeroPoint.flux.value" value="1.0"/>
      <PARAM name="zeroPointReferenceMagnitude" datatype="double" utype="photDM:PhotCal.zeroPoint.referenceMagnitude.value" value="0.0" unit="mag"/>
      <PARAM name="magnitudeSystem" datatype="char" arraysize="*" utype="photDM:PhotCal.magnitudeSystem.type" value="Vega"/>
      <FIELDref ref="phot"/>
    </GROUP>
    <TABLE name="Gaia epoch test">
      <DESCRIPTION>Epoch TIMESYS linkage test product.</DESCRIPTION>
      <FIELD name="obs_time" datatype="double" ucd="time.epoch" unit="d" ref="ts"/>
      {second_field}
      <FIELD name="phot" datatype="double" ucd="phot.mag;em.opt" unit="mag" ref="phot_def"/>
      <FIELD name="flux_error" datatype="double" ucd="stat.error;phot.mag" unit="mag"/>
      {epoch_param}
      <DATA>
        <TABLEDATA>
          <TR><TD>55197.0</TD>{second_row_cell}<TD>12.34</TD><TD>0.01</TD></TR>
        </TABLEDATA>
      </DATA>
    </TABLE>
  </RESOURCE>
</VOTABLE>
""".encode()


def test_gavo_timesys_registry_extracts_multiple_systems():
    """GAVO TIMESYS walker builds a registry keyed by ``TIMESYS/@ID``."""
    tree = _gavo_votable_tree_from_source(io.BytesIO(_gaia_style_votable()))
    registry = extract_timesys_registry_from_gavo(tree)
    assert set(registry) == {"ts", "ts2"}
    assert registry["ts"].timeorigin == pytest.approx(2455197.5)
    assert registry["ts2"].timeorigin == pytest.approx(2400000.5)
    assert registry["ts"].timescale == "TCB"


def test_gavo_timesys_metadata_maps_table_field_and_param_refs():
    """GAVO walker resolves TABLE FIELD/PARAM ``ref`` attributes."""
    tree = _gavo_votable_tree_from_source(io.BytesIO(_gaia_style_votable()))
    metadata = extract_timesys_metadata_from_gavo(tree)
    assert metadata.field_refs["obs_time"] == "ts"
    assert metadata.param_refs["epoch"] is None
    assert metadata.default_timesys.timeorigin == pytest.approx(2455197.5)


def test_volightcurve_ingest_uses_gavo_timesys_registry():
    """VOLightCurve ingest populates TIMESYS registry via GAVO walkers."""
    volc = VOLightCurve(io.BytesIO(_gaia_style_votable()))
    assert set(volc.timesys_by_id) == {"ts", "ts2"}
    assert volc.field_timesys_ref["obs_time"] == "ts"
    assert volc.timesys.timeorigin == pytest.approx(2455197.5)


def test_time_offset_roundtrip_helpers():
    """Offset and absolute Julian Date helpers are inverse for a given timeorigin."""
    origin = 2455197.5
    offset = 2207.1263399818404
    absolute = time_offset_to_absolute_jd(offset, origin)
    assert absolute == pytest.approx(origin + offset)
    assert absolute_jd_to_time_offset(absolute, origin) == pytest.approx(offset)


def test_normalise_epoch_inherits_obs_time_timesys_when_unreferenced():
    """Unreferenced epoch PARAM uses the observation column TIMESYS."""
    volc = VOLightCurve(io.BytesIO(_gaia_style_votable()))
    absolute = normalise_table_epoch_to_absolute_jd(
        volc,
        volc.table.meta["epoch"],
    )
    assert absolute == pytest.approx(2455197.5 + 2207.1263399818404)


def test_volc_to_curvedash_stores_absolute_epoch_for_gaia_style_product():
    """Ingest converts archive-relative epoch to absolute JD for folding."""
    volc = VOLightCurve(io.BytesIO(_gaia_style_votable()))
    lcd = volc_to_curvedash(volc, "gaia_epoch.vot")
    assert lcd.epoch == pytest.approx(2455197.5 + 2207.1263399818404)


def test_export_rewrites_epoch_with_mjd_timeorigin():
    """Export keeps JD = obs_time + timeorigin true for epoch and obs_time together."""
    gaia_style_origin = 2455197.5
    epoch_offset = 2207.1263399818404
    obs_offset_days = 55197.0

    volc = VOLightCurve(io.BytesIO(_gaia_style_votable()))
    lcd = volc_to_curvedash(volc, "gaia_epoch.vot")

    exported = export_curvedash(lcd, VOTABLE_FORMAT_BINARY)
    roundtrip = VOLightCurve(io.BytesIO(exported))

    exported_epoch = float(roundtrip.table.meta["epoch"])
    exported_obs = float(roundtrip.table["obs_time"][0])
    assert roundtrip.timesys.timeorigin == pytest.approx(JD_TO_MJD)
    assert exported_obs + JD_TO_MJD == pytest.approx(obs_offset_days + gaia_style_origin)
    assert exported_epoch + JD_TO_MJD == pytest.approx(epoch_offset + gaia_style_origin)


def test_conflicting_time_column_timesys_raises_on_ingest():
    """Multiple time columns with different timeorigins must fail clearly."""
    volc = VOLightCurve(io.BytesIO(_gaia_style_votable(second_time_col=True)))
    with pytest.raises(PipeException, match="different TIMESYS timeorigin"):
        volc_to_curvedash(volc, "conflict.vot")
