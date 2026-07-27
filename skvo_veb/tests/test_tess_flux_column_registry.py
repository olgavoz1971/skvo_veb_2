"""Tests for TESS flux column registry and selection helpers."""

from __future__ import annotations

import numpy as np
import pytest

from skvo_veb.utils.tess_flux_column_registry import (
    FLUX_METHOD_BACKGROUND,
    FLUX_METHOD_DEFAULT,
    UNIT_DIMENSIONLESS,
    UNIT_PHYSICAL_ELECTRON_S,
    apply_flux_column_selection,
    background_available,
    build_flux_radio_options,
    default_flux_option_label,
    get_photometry_spec,
    list_available_photometry_specs,
    merge_flux_radio_options,
    normalize_lc_column,
    storage_flux_unit_for_selection,
)


class _FakeColumn:
    def __init__(self, name, values):
        self.name = name
        self._values = np.asarray(values, dtype=float)

    @property
    def value(self):
        return self._values


class _FakeLc:
    FLUX_ORIGIN = "pdcsap_flux"

    def __init__(self, columns: dict[str, np.ndarray]):
        self._columns = columns
        self.flux = _FakeColumn("pdcsap_flux", columns["pdcsap_flux"])
        self.flux_err = _FakeColumn("pdcsap_flux_err", columns["pdcsap_flux_err"])

    @property
    def columns(self):
        return list(self._columns.keys())

    def __getitem__(self, key):
        return _FakeColumn(key, self._columns[key])


def test_normalize_lc_column_lowercase():
    """Registry names normalise to Lightkurve lowercase."""
    assert normalize_lc_column("SAP_FLUX") == "sap_flux"


def test_qlp_sector_60_lists_det_flux():
    """QLP sector 60 registry includes DET_FLUX."""
    specs = list_available_photometry_specs(
        "QLP",
        60,
        ["sap_flux", "sap_flux_err", "det_flux", "det_flux_err", "sap_bkg", "sap_bkg_err"],
    )
    cols = {normalize_lc_column(s.flux_col) for s in specs}
    assert "det_flux" in cols
    assert "sap_flux" in cols


def test_background_available_spoc():
    """SPOC background columns are detected when present."""
    cols = ["pdcsap_flux", "sap_bkg", "sap_bkg_err"]
    assert background_available("SPOC", cols) is True
    assert background_available("TGLC", cols) is False


def test_build_flux_radio_options_includes_default_and_explicit_columns():
    """Default option coexists with explicit registry photometry column names."""
    colnames = ["pdcsap_flux", "pdcsap_flux_err", "sap_flux", "sap_flux_err"]
    options = build_flux_radio_options(
        "SPOC",
        4,
        colnames=colnames,
        default_origin="pdcsap_flux",
    )
    values = [opt["value"] for opt in options]
    labels = [opt["label"] for opt in options]
    assert labels[0] == "pdcsap_flux(default)"
    assert values[0] == FLUX_METHOD_DEFAULT
    assert "pdcsap_flux" in values
    assert "sap_flux" in values


def test_merge_flux_radio_options_keeps_default_first():
    """Merged multi-row options keep default flux first."""
    a = build_flux_radio_options(
        "SPOC",
        4,
        colnames=["pdcsap_flux", "pdcsap_flux_err", "sap_flux", "sap_flux_err"],
        default_origin="pdcsap_flux",
    )
    b = build_flux_radio_options(
        "QLP",
        60,
        colnames=["sap_flux", "sap_flux_err", "det_flux", "det_flux_err"],
        default_origin="det_flux",
    )
    merged = merge_flux_radio_options([a, b])
    assert merged[0]["value"] == FLUX_METHOD_DEFAULT
    values = {opt["value"] for opt in merged}
    assert "sap_flux" in values
    assert "det_flux" in values


def test_build_flux_radio_options_single_qlp_includes_background():
    """Single-row QLP options include background when columns exist."""
    colnames = ["kspsap_flux", "kspsap_flux_err", "sap_flux", "sap_flux_err", "sap_bkg", "sap_bkg_err"]
    options = build_flux_radio_options(
        "QLP",
        4,
        colnames=colnames,
        default_origin="kspsap_flux",
    )
    values = {opt["value"] for opt in options}
    assert FLUX_METHOD_DEFAULT in values
    assert FLUX_METHOD_BACKGROUND in values
    assert "sap_flux" in values


def test_apply_flux_column_selection_default_keeps_lc_flux():
    """Default selection keeps Lightkurve author default flux."""
    lc = _FakeLc(
        {
            "pdcsap_flux": [1.0, 2.0],
            "pdcsap_flux_err": [0.1, 0.1],
            "sap_flux": [3.0, 4.0],
            "sap_flux_err": [0.2, 0.2],
        }
    )
    origin, is_background = apply_flux_column_selection(lc, "SPOC", 4, FLUX_METHOD_DEFAULT)
    assert origin == "pdcsap_flux"
    assert is_background is False


def test_apply_flux_column_selection_sap_flux():
    """Explicit sap_flux selection assigns lc.flux from registry column."""
    lc = _FakeLc(
        {
            "pdcsap_flux": [1.0, 2.0],
            "pdcsap_flux_err": [0.1, 0.1],
            "sap_flux": [3.0, 4.0],
            "sap_flux_err": [0.2, 0.2],
        }
    )
    origin, is_background = apply_flux_column_selection(lc, "SPOC", 4, "sap_flux")
    assert origin == "sap_flux"
    assert np.allclose(lc.flux.value, [3.0, 4.0])
    assert is_background is False


def test_apply_flux_column_selection_background_spoc():
    """Background selection uses SAP_BKG columns for SPOC."""
    lc = _FakeLc(
        {
            "pdcsap_flux": [1.0, 2.0],
            "pdcsap_flux_err": [0.1, 0.1],
            "sap_bkg": [0.5, 0.6],
            "sap_bkg_err": [0.01, 0.01],
        }
    )
    origin, is_background = apply_flux_column_selection(lc, "SPOC", 4, FLUX_METHOD_BACKGROUND)
    assert origin == "sap_bkg"
    assert is_background is True
    assert np.allclose(lc.flux.value, [0.5, 0.6])


def test_apply_flux_column_selection_missing_column_raises():
    """Missing registry column raises instead of silently falling back."""
    lc = _FakeLc({"pdcsap_flux": [1.0], "pdcsap_flux_err": [0.1]})
    with pytest.raises(ValueError, match="not present"):
        apply_flux_column_selection(lc, "SPOC", 4, "sap_flux")


def test_effective_flux_method_for_selection_multi_row_forces_default():
    """Multi-row builds ignore a stale single-row flux radio value."""
    from skvo_veb.utils.tess_lc_builder import effective_flux_method_for_selection

    rows = [{"#": 0, "author": "QLP"}, {"#": 1, "author": "QLP"}]
    assert (
        effective_flux_method_for_selection(rows, None, "sap_flux")
        == FLUX_METHOD_DEFAULT
    )
    assert (
        effective_flux_method_for_selection(rows, None, FLUX_METHOD_BACKGROUND)
        == FLUX_METHOD_DEFAULT
    )


def test_build_flux_radio_options_gsfc_eleanor_lite():
    """GSFC-ELEANOR-LITE shows corr_flux(default) and explicit registry columns."""
    colnames = [
        "corr_flux",
        "raw_flux",
        "flux_err",
        "raw_flux_err",
        "pca_flux",
        "flux_bkg",
    ]
    options = build_flux_radio_options(
        "GSFC-ELEANOR-LITE",
        14,
        colnames=colnames,
        default_origin="corr_flux",
    )
    labels = [opt["label"] for opt in options]
    values = [opt["value"] for opt in options]
    assert labels[0] == "corr_flux(default)"
    assert "raw_flux" in values
    assert "pca_flux" in values
    assert FLUX_METHOD_BACKGROUND in values


def test_default_flux_option_label_requires_column_name():
    """Bare 'default' labels are rejected without a Lightkurve column name."""
    with pytest.raises(ValueError, match="column name"):
        default_flux_option_label()


def test_storage_flux_unit_for_selection():
    """Unit labels follow registry calibration types."""
    assert storage_flux_unit_for_selection("SPOC", FLUX_METHOD_DEFAULT) == UNIT_PHYSICAL_ELECTRON_S
    assert storage_flux_unit_for_selection("QLP", FLUX_METHOD_DEFAULT) == UNIT_DIMENSIONLESS
    assert storage_flux_unit_for_selection("SPOC", FLUX_METHOD_BACKGROUND) == UNIT_PHYSICAL_ELECTRON_S
    assert storage_flux_unit_for_selection("QLP", FLUX_METHOD_BACKGROUND) == UNIT_DIMENSIONLESS
    spec = get_photometry_spec("SPOC", 4, "sap_flux")
    assert spec.calibration == "physical"
