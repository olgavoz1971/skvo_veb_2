"""Discovery catalogue AgGrid column definitions driven by mission capabilities."""

from __future__ import annotations

import copy
from typing import Any

from skvo_veb.lc_providers.base import MissionCapabilities
from skvo_veb.lc_providers.registry import get_provider

_LC_DISCOVERY_CELL_CLASS = "lc-discovery-catalog-cell"
_LC_DISCOVERY_NUMERIC_CELL_CLASS = "lc-discovery-catalog-cell-numeric"

_NUMERIC_EXPORT_COL_DEF: dict[str, Any] = {
    "useValueFormatterForExport": False,
}


def _text_column(**col_def: Any) -> dict[str, Any]:
    """Builds a text catalogue column with clipping-friendly cell class.

    Args:
        **col_def: AgGrid column definition fields.

    Returns:
        dict: Column definition including ``cellClass``.
    """
    merged = dict(col_def)
    merged.setdefault("cellClass", _LC_DISCOVERY_CELL_CLASS)
    return merged


def _numeric_column(*, formatter: str, **col_def: Any) -> dict[str, Any]:
    """Builds a numeric catalogue column with display formatter and raw export.

    Display uses a ``dashAgGridFunctions.js`` formatter; clipboard and CSV export
    keep full-precision ``rowData`` (``useValueFormatterForExport=False``).

    Args:
        formatter (str): Registered ``dashAgGridFunctions`` formatter name.
        **col_def: AgGrid column definition fields.

    Returns:
        dict: Column definition with ``valueFormatter`` and export flags.
    """
    merged = dict(col_def)
    merged["valueFormatter"] = {"function": f"{formatter}(params)"}
    merged["cellClass"] = _LC_DISCOVERY_NUMERIC_CELL_CLASS
    merged.update(_NUMERIC_EXPORT_COL_DEF)
    return merged


_CATALOG_COLUMN_DEFS: dict[str, dict[str, Any]] = {
    "distance_arcsec": _numeric_column(
        formatter="lcDiscoveryFmtSep",
        field="distance_arcsec",
        headerName="Sep (″)",
        type="numericColumn",
        sortable=True,
        minWidth=55,
        maxWidth=100,
    ),
    "object_name": _text_column(
        field="object_name",
        headerName="Object",
        sortable=True,
        minWidth=100,
        width=200,
    ),
    "filter_name": _text_column(
        field="filter_name",
        headerName="Filter",
        sortable=True,
        minWidth=80,
        suppressSizeToFit=True,
    ),
    "object_class": _text_column(
        field="object_class",
        headerName="Type",
        sortable=True,
        minWidth=64,
        maxWidth=96,
        suppressSizeToFit=True,
    ),
    "ra_deg": _numeric_column(
        formatter="lcDiscoveryFmtRaDec",
        field="ra_deg",
        headerName="RA",
        type="numericColumn",
        sortable=True,
        minWidth=90,
        suppressSizeToFit=True,
    ),
    "dec_deg": _numeric_column(
        formatter="lcDiscoveryFmtRaDec",
        field="dec_deg",
        headerName="Dec",
        type="numericColumn",
        sortable=True,
        minWidth=90,
        suppressSizeToFit=True,
    ),
    "t_min": _numeric_column(
        formatter="lcDiscoveryFmtMjd",
        field="t_min",
        headerName="t_min",
        type="numericColumn",
        sortable=True,
        width=68,
        minWidth=68,
        suppressSizeToFit=True,
    ),
    "t_max": _numeric_column(
        formatter="lcDiscoveryFmtMjd",
        field="t_max",
        headerName="t_max",
        type="numericColumn",
        sortable=True,
        width=68,
        minWidth=68,
        suppressSizeToFit=True,
    ),
    "mag": _numeric_column(
        formatter="lcDiscoveryFmtMag",
        field="mag",
        headerName="⟨mag⟩",
        type="numericColumn",
        sortable=True,
        minWidth=64,
        maxWidth=80,
        suppressSizeToFit=True,
    ),
    "n_points": _numeric_column(
        formatter="lcDiscoveryFmtNPoints",
        field="n_points",
        headerName="N",
        type="numericColumn",
        sortable=True,
        width=52,
        maxWidth=60,
        suppressSizeToFit=True,
    ),
}

_CATALOG_COLUMN_ORDER: tuple[str, ...] = (
    "distance_arcsec",
    "object_name",
    "filter_name",
    "object_class",
    "ra_deg",
    "dec_deg",
    "t_min",
    "t_max",
    "mag",
    "n_points",
)


def catalog_column_defs_for_capabilities(
    capabilities: MissionCapabilities,
) -> list[dict[str, Any]]:
    """Builds AgGrid ``columnDefs`` for a mission discovery catalogue table.

    Column visibility follows explicit provider capability flags, not whether
    optional fields happen to be empty in one search result.

    Args:
        capabilities (MissionCapabilities): Registered mission feature flags.

    Returns:
        list[dict]: Ordered AgGrid column definitions for the Discovery grid.
    """
    include_fields: set[str] = {
        "distance_arcsec",
        "object_name",
        "filter_name",
        "ra_deg",
        "dec_deg",
        "mag",
    }
    if capabilities.supports_discovery_time_filter:
        include_fields.update({"t_min", "t_max"})
    if capabilities.discovery_catalog_includes_object_class:
        include_fields.add("object_class")
    if capabilities.discovery_catalog_includes_n_points:
        include_fields.add("n_points")

    column_defs: list[dict[str, Any]] = []
    for field in _CATALOG_COLUMN_ORDER:
        if field not in include_fields:
            continue
        column_defs.append(copy.deepcopy(_CATALOG_COLUMN_DEFS[field]))
    return column_defs


def catalog_column_defs_for_mission(mission_id: str) -> list[dict[str, Any]]:
    """Returns discovery catalogue column definitions for a registry mission slug.

    Args:
        mission_id (str): Provider slug from the Discovery mission selector.

    Returns:
        list[dict]: AgGrid column definitions for that mission.

    Raises:
        PipeException: When ``mission_id`` is unknown (via ``get_provider``).
    """
    provider = get_provider(mission_id)
    return catalog_column_defs_for_capabilities(provider.capabilities)
