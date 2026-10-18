"""Tests for the choice of the photometry column in Discovery light curves."""

from __future__ import annotations

import io

import numpy as np
import pytest

from skvo_veb.utils.lc_bridge import (
    build_votable_kwargs_from_metadata,
    list_photometry_candidates,
    paired_error_column,
    volc_to_curvedash,
)
from skvo_veb.utils.lc_discovery_load import photometry_select_options
from volightcurve import VOLightCurve

_VOTABLE = """<?xml version="1.0" encoding="UTF-8"?>
<VOTABLE version="1.4" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
<RESOURCE type="results">
<TIMESYS ID="ts" refposition="BARYCENTER" timeorigin="2457000" timescale="TDB"/>
<GROUP name="photcal" ID="photcal_sap_flux">
 <PARAM name="filter" datatype="char" arraysize="*" value="TESS" utype="photDM:PhotometryFilter.name"/>
</GROUP>
<GROUP name="photcal" ID="photcal_pdcsap_flux">
 <PARAM name="filter" datatype="char" arraysize="*" value="TESS" utype="photDM:PhotometryFilter.name"/>
</GROUP>
<TABLE>
<DESCRIPTION>All registered flux and background columns are issued.</DESCRIPTION>
<FIELD name="time" datatype="double" unit="d" ucd="time.epoch" ref="ts"/>
<FIELD name="pdcsap_flux" datatype="double" unit="electron/s" ucd="phot.flux" ref="photcal_pdcsap_flux"/>
<FIELD name="pdcsap_flux_err" datatype="double" unit="electron/s" ucd="stat.error;phot.flux" ref="photcal_pdcsap_flux"/>
<FIELD name="sap_flux" datatype="double" unit="electron/s" ucd="phot.flux" ref="photcal_sap_flux"/>
<FIELD name="sap_flux_err" datatype="double" unit="electron/s" ucd="stat.error;phot.flux" ref="photcal_sap_flux"/>
<FIELD name="sap_bkg" datatype="double" unit="electron/s" ucd="instr.background"/>
<DATA><TABLEDATA>
<TR><TD>1.0</TD><TD>100.0</TD><TD>1.0</TD><TD>200.0</TD><TD>2.0</TD><TD>5.0</TD></TR>
<TR><TD>1.1</TD><TD>101.0</TD><TD>1.1</TD><TD>201.0</TD><TD>2.1</TD><TD>5.0</TD></TR>
<TR><TD>1.2</TD><TD>102.0</TD><TD>1.2</TD><TD>202.0</TD><TD>2.2</TD><TD>5.0</TD></TR>
</TABLEDATA></DATA>
</TABLE>
</RESOURCE>
</VOTABLE>
"""


@pytest.fixture
def volc() -> VOLightCurve:
    """Multi-column TESS-style light curve with one photcal group per flux."""
    return VOLightCurve(io.BytesIO(_VOTABLE.encode()))


def test_candidates_list_flux_columns_without_background(volc):
    """Both flux columns are offered; the background column is not."""
    candidates = list_photometry_candidates(volc)
    assert [c["column"] for c in candidates] == ["pdcsap_flux", "sap_flux"]
    assert all(c["domain"] == "flux" for c in candidates)
    assert [c["default"] for c in candidates] == [True, False]
    assert candidates[0]["filter"] == "TESS"


def test_paired_error_column_follows_photcal_reference(volc):
    """Each flux column gets the error column with the same photcal group."""
    assert paired_error_column(volc, "pdcsap_flux") == "pdcsap_flux_err"
    assert paired_error_column(volc, "sap_flux") == "sap_flux_err"


def test_curvedash_default_column_is_unchanged(volc):
    """Without a choice the default column and its errors are used."""
    lcd = volc_to_curvedash(volc, "tess.vot")
    assert np.allclose(lcd.lightcurve["flux"].to_numpy(), [100.0, 101.0, 102.0])
    assert np.allclose(lcd.lightcurve["flux_err"].to_numpy(), [1.0, 1.1, 1.2])


def test_curvedash_chosen_column_takes_its_own_errors(volc):
    """Choosing ``sap_flux`` switches the values and the paired errors together."""
    lcd = volc_to_curvedash(volc, "tess.vot", primary_col="sap_flux")
    assert np.allclose(lcd.lightcurve["flux"].to_numpy(), [200.0, 201.0, 202.0])
    assert np.allclose(lcd.lightcurve["flux_err"].to_numpy(), [2.0, 2.1, 2.2])


def test_curvedash_rejects_non_photometry_column(volc):
    """A background column is not a valid choice."""
    with pytest.raises(ValueError, match="not a photometry column"):
        volc_to_curvedash(volc, "tess.vot", primary_col="sap_bkg")


def test_select_options_label_has_unit_and_filter(volc):
    """The dropdown label shows column, unit and filter."""
    options = photometry_select_options(list_photometry_candidates(volc))
    assert options[0]["value"] == "pdcsap_flux"
    assert options[0]["label"].startswith("pdcsap_flux (")
    assert "TESS" in options[0]["label"]


def test_export_description_names_the_chosen_source_column(volc):
    """The exported description says which source column is kept and what is dropped."""
    lcd = volc_to_curvedash(volc, "tess.vot", primary_col="sap_flux")
    kwargs = build_votable_kwargs_from_metadata(lcd)
    for text in (kwargs["table_description"], kwargs["votable_description"]):
        assert text.startswith("This file holds one photometry series: column 'sap_flux'")
        assert "uncertainty from column 'sap_flux_err'" in text
        assert "not included: pdcsap_flux, pdcsap_flux_err." in text
        assert "All registered flux and background columns are issued." in text


def test_export_description_for_default_column(volc):
    """The default column is described too."""
    lcd = volc_to_curvedash(volc, "tess.vot")
    kwargs = build_votable_kwargs_from_metadata(lcd)
    assert "column 'pdcsap_flux'" in kwargs["table_description"]
