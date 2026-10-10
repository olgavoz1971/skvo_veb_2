"""Discovery catalogue AgGrid column definitions driven by mission capabilities."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any

from lc_discovery import list_missions
from skvo_veb.utils.my_tools import PipeException

_EMPTY_CAPABILITIES = SimpleNamespace(
    supports_discovery_time_filter=False,
    discovery_catalog_includes_object_class=False,
    discovery_catalog_includes_n_points=False,
)

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


# Deterministic widths in pixels. Autosizing is not used: it measures only the
# rendered rows and so makes widths depend on what is scrolled into view.
_WIDTH_XS = 52
_WIDTH_S = 60
_WIDTH_M = 72
_WIDTH_L = 84
_WIDTH_XL = 110
_EXTRA_COLUMN_WIDTH = 64
_EXTRA_COLUMN_MIN_WIDTH = 44
_EXTRA_COLUMN_MAX_WIDTH = 120


def _fixed_width(width: int) -> dict[str, int]:
    """Returns width keys that keep a column rigid yet user-resizable.

    Args:
        width (int): Initial width in pixels.

    Returns:
        dict: ``width``, ``minWidth``, and ``maxWidth`` entries.
    """
    return {
        "width": width,
        "minWidth": max(40, width - 16),
        "maxWidth": width + 56,
    }


_CATALOG_COLUMN_DEFS: dict[str, dict[str, Any]] = {
    "object_name": _text_column(
        field="object_name",
        headerName="Object",
        sortable=True,
        # pinned="left",
        **_fixed_width(_WIDTH_XL),
        # flex=1,
        # minWidth=110,
        # maxWidth=220,
    ),
    "distance_arcsec": _numeric_column(
        formatter="lcDiscoveryFmtSep",
        field="distance_arcsec",
        headerName="Sep (\u2033)",
        type="numericColumn",
        sortable=True,
        **_fixed_width(_WIDTH_S),
    ),
    "filter_name": _text_column(
        field="filter_name",
        headerName="Filter",
        sortable=True,
        **_fixed_width(_WIDTH_L),
    ),
    "object_class": _text_column(
        field="object_class",
        headerName="Type",
        sortable=True,
        **_fixed_width(_WIDTH_M),
    ),
    "ra_deg": _numeric_column(
        formatter="lcDiscoveryFmtRaDec",
        field="ra_deg",
        headerName="RA",
        type="numericColumn",
        sortable=True,
        **_fixed_width(_WIDTH_L),
    ),
    "dec_deg": _numeric_column(
        formatter="lcDiscoveryFmtRaDec",
        field="dec_deg",
        headerName="Dec",
        type="numericColumn",
        sortable=True,
        **_fixed_width(_WIDTH_L),
    ),
    "t_min": _numeric_column(
        formatter="lcDiscoveryFmtMjd",
        field="t_min",
        headerName="t_min",
        type="numericColumn",
        sortable=True,
        **_fixed_width(_WIDTH_M),
    ),
    "t_max": _numeric_column(
        formatter="lcDiscoveryFmtMjd",
        field="t_max",
        headerName="t_max",
        type="numericColumn",
        sortable=True,
        **_fixed_width(_WIDTH_M),
    ),
    "mag": _numeric_column(
        formatter="lcDiscoveryFmtMag",
        field="mag",
        headerName="\u27e8mag\u27e9",
        type="numericColumn",
        sortable=True,
        **_fixed_width(_WIDTH_S),
    ),
    "n_points": _numeric_column(
        formatter="lcDiscoveryFmtNPoints",
        field="n_points",
        headerName="N",
        type="numericColumn",
        sortable=True,
        **_fixed_width(_WIDTH_XS),
    ),
}

_CATALOG_COLUMN_ORDER: tuple[str, ...] = (
    "object_name",
    "distance_arcsec",
    "filter_name",
    "object_class",
    "ra_deg",
    "dec_deg",
    "t_min",
    "t_max",
    "mag",
    "n_points",
)


def _extra_column_widths(width: int | None) -> dict[str, int]:
    """Returns width keys for a provider extra column.

    Args:
        width (int, optional): Provider-declared width in pixels.

    Returns:
        dict: ``width``, ``minWidth``, and ``maxWidth`` entries.
    """
    return {
        "width": int(width) if width else _EXTRA_COLUMN_WIDTH,
        "minWidth": _EXTRA_COLUMN_MIN_WIDTH,
        "maxWidth": _EXTRA_COLUMN_MAX_WIDTH,
    }


def catalog_column_defs_for_capabilities(
    capabilities,
) -> list[dict[str, Any]]:
    """Builds AgGrid ``columnDefs`` for a mission discovery catalogue table.

    Column visibility follows explicit capability flags, not whether
    optional fields happen to be empty in one search result.

    Args:
        capabilities: Object with ``supports_discovery_time_filter``,
            ``discovery_catalog_includes_object_class``, and
            ``discovery_catalog_includes_n_points``.

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

    extras = tuple(getattr(capabilities, "catalog_extra_columns", ()) or ())
    extra_after_filter: list[dict[str, Any]] = []
    for extra in extras:
        field = getattr(extra, "field", None)
        header = getattr(extra, "header", None)
        if not field or not header:
            continue
        extra_after_filter.append(
            _text_column(
                field=str(field),
                headerName=str(header),
                sortable=True,
                **_extra_column_widths(getattr(extra, "width", None)),
            )
        )

    column_defs: list[dict[str, Any]] = []
    for field in _CATALOG_COLUMN_ORDER:
        if field not in include_fields:
            continue
        column_defs.append(copy.deepcopy(_CATALOG_COLUMN_DEFS[field]))
        if field == "filter_name":
            column_defs.extend(extra_after_filter)
    return column_defs


def catalog_column_defs_for_mission(mission_id: str) -> list[dict[str, Any]]:
    """Returns discovery catalogue column definitions for a registry mission slug.

    Args:
        mission_id (str): Provider slug from the Discovery mission selector.

    Returns:
        list[dict]: AgGrid column definitions for that mission.

    Raises:
        PipeException: When ``mission_id`` is unknown.
    """
    for item in list_missions():
        if item.mission_id == mission_id:
            return catalog_column_defs_for_capabilities(item.capabilities)

    raise PipeException(f"Unknown mission '{mission_id}'.")


def empty_discovery_catalog_column_defs() -> list[dict[str, Any]]:
    """Returns catalogue columns when no mission is selected.

    Returns:
        list[dict]: Base AgGrid column definitions without optional fields.
    """
    return catalog_column_defs_for_capabilities(_EMPTY_CAPABILITIES)
