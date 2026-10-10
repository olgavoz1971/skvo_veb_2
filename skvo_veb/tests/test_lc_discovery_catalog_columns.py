"""Tests for discovery catalogue AgGrid columns vs mission capabilities."""

from __future__ import annotations

from types import SimpleNamespace

from skvo_veb.utils.lc_discovery_catalog_columns import (
    catalog_column_defs_for_capabilities,
    catalog_column_defs_for_mission,
)


def _caps(**kwargs):
    defaults = dict(
        supports_discovery_time_filter=False,
        discovery_catalog_includes_object_class=False,
        discovery_catalog_includes_n_points=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _fields(column_defs: list[dict]) -> list[str]:
    return [col["field"] for col in column_defs]


def test_catalog_columns_respect_time_filter_capability():
    """t_min and t_max appear only when discovery time filtering is supported."""
    with_time = catalog_column_defs_for_capabilities(
        _caps(
            supports_discovery_time_filter=True,
            discovery_catalog_includes_n_points=True,
        )
    )
    without_time = catalog_column_defs_for_capabilities(
        _caps(
            supports_discovery_time_filter=False,
            discovery_catalog_includes_n_points=True,
        )
    )
    assert "t_min" in _fields(with_time)
    assert "t_max" in _fields(with_time)
    assert "t_min" not in _fields(without_time)
    assert "t_max" not in _fields(without_time)


def test_catalog_columns_respect_object_class_capability():
    """Type column appears only when the mission reports classification at discovery."""
    with_class = catalog_column_defs_for_capabilities(
        _caps(discovery_catalog_includes_object_class=True)
    )
    without_class = catalog_column_defs_for_capabilities(_caps())
    assert "object_class" in _fields(with_class)
    assert "object_class" not in _fields(without_class)


def test_catalog_extra_columns_append_after_filter():
    """Provider extras appear after Filter with the declared headers."""
    extras = (
        SimpleNamespace(field="extra_a", header="A"),
        SimpleNamespace(field="extra_b", header="B"),
    )
    defs = catalog_column_defs_for_capabilities(
        _caps(catalog_extra_columns=extras)
    )
    fields = _fields(defs)
    assert fields[fields.index("filter_name") + 1] == "extra_a"
    assert fields[fields.index("filter_name") + 2] == "extra_b"
    by_field = {col["field"]: col for col in defs}
    assert by_field["extra_a"]["headerName"] == "A"
    assert by_field["extra_b"]["headerName"] == "B"


def test_tess_catalog_extra_columns():
    """TESS discovery shows Sector, Exp, and Author; other missions do not."""
    tess_fields = _fields(catalog_column_defs_for_mission("tess"))
    i = tess_fields.index("filter_name")
    assert tess_fields[i + 1 : i + 4] == ["sector", "exp", "author"]
    asassn_fields = _fields(catalog_column_defs_for_mission("asassn"))
    assert "sector" not in asassn_fields
    assert "exp" not in asassn_fields
    assert "author" not in asassn_fields


def test_catalog_columns_respect_n_points_capability():
    """N column appears only when epoch counts are part of discovery metadata."""
    with_n = catalog_column_defs_for_capabilities(
        _caps(discovery_catalog_includes_n_points=True)
    )
    without_n = catalog_column_defs_for_capabilities(_caps())
    assert "n_points" in _fields(with_n)
    assert "n_points" not in _fields(without_n)


def test_panstarrs1_dr2_catalog_columns():
    """Pan-STARRS1 DR2 hides time bounds and type; shows N."""
    fields = _fields(catalog_column_defs_for_mission("panstarrs1_dr2"))
    assert "n_points" in fields
    assert "t_min" not in fields
    assert "object_class" not in fields


def test_asassn_catalog_columns():
    """ASAS-SN discovery omits time, type, and N columns."""
    fields = _fields(catalog_column_defs_for_mission("asassn"))
    assert "t_min" not in fields
    assert "object_class" not in fields
    assert "n_points" not in fields


def test_gaia_veb_catalog_columns():
    """Gaia VEB SSA discovery includes time coverage, type, and N."""
    fields = _fields(catalog_column_defs_for_mission("gaia_dr3_veb"))
    assert "t_min" in fields
    assert "object_class" in fields
    assert "n_points" in fields


def test_gaia_ari_catalog_columns():
    """Gaia ARI includes type but not time-filter columns or N at discovery."""
    fields = _fields(catalog_column_defs_for_mission("gaia_dr3_ari"))
    assert "object_class" in fields
    assert "t_min" not in fields
    assert "n_points" not in fields


def test_numeric_catalog_columns_use_display_formatters_and_raw_export():
    """Numeric columns format for display but export full-precision row values."""
    column_defs = catalog_column_defs_for_mission("gaia_dr3_veb")
    by_field = {col["field"]: col for col in column_defs}
    ra_col = by_field["ra_deg"]
    assert ra_col["valueFormatter"] == {"function": "lcDiscoveryFmtRaDec(params)"}
    assert ra_col["useValueFormatterForExport"] is False
    assert ra_col["cellClass"] == "lc-discovery-catalog-cell-numeric"


def test_object_column_is_first_and_widths_are_fixed():
    """Object is first and unpinned; other columns have deterministic widths."""
    defs = catalog_column_defs_for_capabilities(_caps())
    assert defs[0]["field"] == "object_name"
    assert "pinned" not in defs[0]
    assert defs[1]["field"] == "distance_arcsec"
    assert "pinned" not in defs[1]
    for col in defs[1:]:
        assert col["width"] >= col["minWidth"]
        assert col["width"] <= col["maxWidth"]


def test_extra_column_width_is_provider_declared_or_narrow_default():
    """Extras use the declared width, else the narrow host default."""
    extras = (
        SimpleNamespace(field="extra_a", header="A", width=56),
        SimpleNamespace(field="extra_b", header="B"),
    )
    defs = catalog_column_defs_for_capabilities(_caps(catalog_extra_columns=extras))
    by_field = {col["field"]: col for col in defs}
    assert by_field["extra_a"]["width"] == 56
    assert by_field["extra_b"]["width"] == 64
