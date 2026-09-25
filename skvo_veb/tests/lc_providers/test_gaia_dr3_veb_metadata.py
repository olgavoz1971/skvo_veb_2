"""Tests for Gaia DR3 VEB provider-specific lightcurve metadata enrichment."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import pytest

from skvo_veb.lc_providers.gaia_dr3_veb.fetch_metadata import enrich_votable
from skvo_veb.utils.lc_bridge import export_curvedash, volc_to_curvedash
from skvo_veb.utils.lc_config import (
    METADATA_KEY_VO_ENVELOPE,
    VO_ENVELOPE_KEY_LIGHTCURVE_TITLE,
    VO_ENVELOPE_KEY_PUBLICATION_ID,
    VO_ENVELOPE_KEY_TABLE_DESCRIPTION,
    VOTABLE_FORMAT_BINARY,
)
from skvo_veb.utils.my_tools import PipeException
from volightcurve import VOLightCurve


def _minimal_veb_bytes(
    *,
    table_name: str = "Gaia DR3 1936512041221649536",
    description: str = "Gaia DR3 epoch photometry from UPJS VEB archive.",
    bibcode: str | None = "2023A&amp;A...674A...1G",
) -> bytes:
    bib_param = ""
    if bibcode:
        bib_param = (
            f'<PARAM name="bibcode" datatype="char" arraysize="*" '
            f'ucd="meta.bib.bibcode" utype="ssa:Curation.Reference" '
            f'value="{bibcode}"/>'
        )
    vot_bytes = f"""<?xml version="1.0" encoding="utf-8"?>
<VOTABLE xmlns="http://www.ivoa.net/xml/VOTable/v1.3" version="1.4">
  <RESOURCE>
    <TIMESYS ID="ts" refposition="BARYCENTER" timeorigin="2455197.5" timescale="TCB"/>
    <GROUP ID="phot_def" name="photcal">
      <PARAM name="filterIdentifier" datatype="char" arraysize="*" utype="photDM:PhotometryFilter.identifier" value="GAIA/GAIA3.G"/>
      <PARAM name="zeroPointFlux" datatype="double" utype="photDM:PhotCal.zeroPoint.flux.value" value="1.0"/>
      <PARAM name="zeroPointReferenceMagnitude" datatype="double" utype="photDM:PhotCal.zeroPoint.referenceMagnitude.value" value="0.0" unit="mag"/>
      <PARAM name="magnitudeSystem" datatype="char" arraysize="*" utype="photDM:PhotCal.magnitudeSystem.type" value="Vega"/>
      <FIELDref ref="phot"/>
    </GROUP>
    <TABLE name="{table_name}">
      <DESCRIPTION>{description}</DESCRIPTION>
      <FIELD name="obs_time" ID="obs_time" datatype="double" ucd="time.epoch" unit="d" ref="ts"/>
      <FIELD name="phot" ID="phot" datatype="double" ucd="phot.mag;em.opt" unit="mag" ref="phot_def"/>
      <FIELD name="flux_error" ID="flux_error" datatype="double" ucd="stat.error;phot.mag" unit="mag"/>
      {bib_param}
      <DATA>
        <TABLEDATA>
          <TR><TD>55197.0</TD><TD>12.34</TD><TD>0.01</TD></TR>
        </TABLEDATA>
      </DATA>
    </TABLE>
  </RESOURCE>
</VOTABLE>
""".encode()
    return vot_bytes


def _parse(payload: bytes) -> VOLightCurve:
    """Parses an enriched VOTable the way the Dash side does.

    Args:
        payload (bytes): Enriched VOTable.

    Returns:
        VOLightCurve: Parsed product.
    """
    return VOLightCurve(io.BytesIO(payload))


def test_veb_gaia_raw_files_replace_jy_flux_zero_point():
    """Gaia DR3 VEB discards the Jy flux zero point on the real products."""
    from pathlib import Path

    expected = {
        Path("/home/voz/projects/UPJS/tmp/g.xml"): ("GAIA/GAIA3.Gbp", 25.3385),
        Path("/home/voz/projects/UPJS/tmp/gg.xml"): ("GAIA/GAIA3.G", 25.6874),
    }
    for path, (filter_id, zp_mag) in expected.items():
        assert path.is_file(), path
        payload = enrich_votable(path.read_bytes())
        volc = _parse(payload)
        photcal = volc.photdms["phot"].photcal
        assert volc.photdms["phot"].filter.filter_id == filter_id
        assert float(photcal.zp_flux.value) == 1.0
        assert photcal._zp_flux_unit_text == "s**-1"
        assert float(photcal.zp_mag.value) == zp_mag
        assert volc.photdms["flux_error"].photcal is photcal
        epoch = [
            element
            for element in ET.fromstring(payload).iter()
            if element.tag.rsplit("}", 1)[-1] == "PARAM" and element.get("name") == "epoch"
        ]
        assert epoch and epoch[0].get("ref") == "ts"


def test_enrich_fetched_volightcurve_keeps_archive_table_name():
    """VEB enrich does not rewrite the archive TABLE name."""
    volc = _parse(enrich_votable(_minimal_veb_bytes()))
    assert volc.table.meta["name"] == "Gaia DR3 1936512041221649536"
    assert "lightcurve_title" not in volc.table.meta
    assert volc.table.meta["facility_name"] == "Gaia"
    assert volc.table.meta["instrument_name"] == "Gaia"


def test_enrich_raises_when_description_missing():
    """Provider enrichment requires TABLE description from the archive product."""
    payload = _minimal_veb_bytes().replace(
        b"<DESCRIPTION>Gaia DR3 epoch photometry from UPJS VEB archive.</DESCRIPTION>",
        b"",
    )
    with pytest.raises(PipeException, match="missing TABLE description"):
        enrich_votable(payload)


def test_veb_metadata_survives_curvedash_plot_title_and_export():
    """Enriched title, description, and bibcode round-trip through CurveDash export."""
    volc = _parse(enrich_votable(_minimal_veb_bytes()))

    lcd = volc_to_curvedash(volc, "veb_g.vot")
    assert lcd.title == "Gaia DR3 1936512041221649536"

    envelope = lcd.metadata.get(METADATA_KEY_VO_ENVELOPE) or {}
    assert envelope.get(VO_ENVELOPE_KEY_LIGHTCURVE_TITLE) == lcd.title
    assert envelope.get(VO_ENVELOPE_KEY_TABLE_DESCRIPTION)
    assert envelope.get(VO_ENVELOPE_KEY_PUBLICATION_ID) == "2023A&A...674A...1G"

    exported = export_curvedash(lcd, VOTABLE_FORMAT_BINARY)
    xml = exported.decode("utf-8", errors="ignore")
    assert 'name="Gaia DR3 1936512041221649536"' in xml
    assert "Gaia DR3 epoch photometry from UPJS VEB archive." in xml
    assert 'name="bibcode"' in xml
    assert "2023A&amp;A...674A...1G" in xml or "2023A&A...674A...1G" in xml

    roundtrip = VOLightCurve(io.BytesIO(exported))
    assert roundtrip.table.meta.get("bibcode") == "2023A&A...674A...1G"
