"""Standardised catalog table schema for multi-mission lightcurve discovery.

One catalog row represents one plottable lightcurve (not one astrophysical source).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from astropy.table import Table, vstack

logger = logging.getLogger(__name__)

REQUIRED_CATALOG_COLUMNS = (
    "distance_arcsec",
    "ra_deg",
    "dec_deg",
    "object_name",
    "filter_name",
    "lc_key",
)

OPTIONAL_CATALOG_COLUMNS = (
    "filter_identifier",
    "n_points",
    "time_start_mjd",
    "time_end_mjd",
    "mag",
    "survey",
    "provider_note",
    "epoch",
    "period",
)

CATALOG_COLUMN_DTYPES = {
    "distance_arcsec": np.float64,
    "ra_deg": np.float64,
    "dec_deg": np.float64,
    "object_name": object,
    "filter_name": object,
    "lc_key": object,
    "filter_identifier": object,
    "n_points": np.int64,
    "time_start_mjd": np.float64,
    "time_end_mjd": np.float64,
    "mag": np.float64,
    "survey": object,
    "provider_note": object,
    "epoch": np.float64,
    "period": np.float64,
}


def empty_catalog_table() -> Table:
    """Creates an empty catalog table with all standard columns present.

    Returns:
        astropy.table.Table: Empty table with required and optional columns.
    """
    columns = {}
    for name in REQUIRED_CATALOG_COLUMNS + OPTIONAL_CATALOG_COLUMNS:
        dtype = CATALOG_COLUMN_DTYPES[name]
        columns[name] = np.array([], dtype=dtype)
    return Table(columns)


def validate_catalog_table(table: Table) -> Table:
    """Validates and normalises a mission catalog table.

    Args:
        table (astropy.table.Table): Candidate catalog from a provider search.

    Returns:
        astropy.table.Table: Copy with required columns and allowed optional columns.

    Raises:
        TypeError: If ``table`` is not an Astropy ``Table``.
        ValueError: If required columns are missing or unknown columns are present.
    """
    if not isinstance(table, Table):
        raise TypeError(f"Catalog table must be astropy.table.Table, got {type(table)!r}")

    missing = [name for name in REQUIRED_CATALOG_COLUMNS if name not in table.colnames]
    if missing:
        raise ValueError(f"Catalog table missing required columns: {missing}")

    allowed = set(REQUIRED_CATALOG_COLUMNS) | set(OPTIONAL_CATALOG_COLUMNS)
    unknown = [name for name in table.colnames if name not in allowed]
    if unknown:
        raise ValueError(f"Catalog table has unknown columns: {unknown}")

    normalised = table.copy()
    for name in OPTIONAL_CATALOG_COLUMNS:
        if name not in normalised.colnames:
            normalised[name] = np.ma.masked_all(len(normalised), dtype=CATALOG_COLUMN_DTYPES[name])

    ordered = REQUIRED_CATALOG_COLUMNS + OPTIONAL_CATALOG_COLUMNS
    return normalised[ordered]


def catalog_table_to_row_dicts(table: Table) -> list[dict[str, Any]]:
    """Serialises a catalog table to plain dict rows for AgGrid or JSON stores.

    Args:
        table (astropy.table.Table): Validated catalog table.

    Returns:
        list[dict]: One dict per row with native Python scalars.
    """
    validated = validate_catalog_table(table)
    rows: list[dict[str, Any]] = []
    for row in validated:
        record: dict[str, Any] = {}
        for name in validated.colnames:
            value = row[name]
            if isinstance(value, np.generic):
                value = value.item()
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            record[name] = None if value is np.ma.masked else value
        rows.append(record)
    return rows


def catalog_row_to_aggrid_dict(row, *, row_index: int) -> dict[str, Any]:
    """Converts one catalog row to an AgGrid row dict with a display index.

    Args:
        row: Astropy table row or dict-like catalog record.
        row_index (int): Zero-based row index shown in the ``#`` column.

    Returns:
        dict: AgGrid-compatible row payload.
    """
    if hasattr(row, "colnames"):
        payload = {name: row[name] for name in row.colnames}
    else:
        payload = dict(row)

    aggrid_row: dict[str, Any] = {"#": row_index + 1}
    for key, value in payload.items():
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        aggrid_row[key] = None if value is np.ma.masked else value
    return aggrid_row


def append_catalog_rows(base: Table, extra: Table) -> Table:
    """Concatenates two catalog tables after schema validation.

    Args:
        base (astropy.table.Table): Existing catalog (may be empty).
        extra (astropy.table.Table): Rows to append.

    Returns:
        astropy.table.Table: Combined validated catalog.
    """
    if len(base) == 0:
        return validate_catalog_table(extra)
    if len(extra) == 0:
        return validate_catalog_table(base)
    return validate_catalog_table(vstack([validate_catalog_table(base), validate_catalog_table(extra)]))
