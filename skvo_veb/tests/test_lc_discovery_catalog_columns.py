"""Tests for discovery catalogue AgGrid columns vs mission capabilities."""

from __future__ import annotations

from skvo_veb.lc_providers.base import MissionCapabilities
from skvo_veb.lc_providers.registry import get_provider
from skvo_veb.utils.lc_discovery_catalog_columns import (
    catalog_column_defs_for_capabilities,
    catalog_column_defs_for_mission,
)


def _fields(column_defs: list[dict]) -> list[str]:
    return [col["field"] for col in column_defs]


def test_catalog_columns_respect_time_filter_capability():
    """t_min and t_max appear only when discovery time filtering is supported."""
    with_time = catalog_column_defs_for_capabilities(
        MissionCapabilities(
            supports_discovery_time_filter=True,
            discovery_catalog_includes_n_points=True,
        )
    )
    without_time = catalog_column_defs_for_capabilities(
        MissionCapabilities(
            supports_discovery_time_filter=False,
            discovery_catalog_includes_n_points=True,
        )
    )
    assert "t_min" in _fields(with_time)
    assert "t_max" in _fields(with_time)
    assert "t_min" not in _fields(without_time)
    assert "t_max" not in _fields(without_time)


def test_catalog_columns_respect_object_class_capability():
    """Type column appears only when the provider queries classification at discovery."""
    with_class = catalog_column_defs_for_capabilities(
        MissionCapabilities(discovery_catalog_includes_object_class=True)
    )
    without_class = catalog_column_defs_for_capabilities(MissionCapabilities())
    assert "object_class" in _fields(with_class)
    assert "object_class" not in _fields(without_class)


def test_catalog_columns_respect_n_points_capability():
    """N column appears only when epoch counts are part of discovery metadata."""
    with_n = catalog_column_defs_for_capabilities(
        MissionCapabilities(discovery_catalog_includes_n_points=True)
    )
    without_n = catalog_column_defs_for_capabilities(MissionCapabilities())
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
    provider = get_provider("gaia_dr3_veb")
    fields = _fields(catalog_column_defs_for_capabilities(provider.capabilities))
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
