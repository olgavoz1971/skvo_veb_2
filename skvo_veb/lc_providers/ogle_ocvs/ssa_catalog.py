"""Map OGLE OCVS SSA TAP rows onto the shared discovery catalogue schema."""

from __future__ import annotations

import logging
import re
from typing import Any

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from skvo_veb.lc_providers.catalog_schema import empty_catalog_table, validate_catalog_table
from skvo_veb.lc_providers.lc_key import encode_lc_key

logger = logging.getLogger(__name__)

_SSA_LOCATION_PATTERN = re.compile(
    r"^[\[\(]\s*"
    r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*[, ]\s*"
    r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*"
    r"[\]\)]$"
)


def parse_ssa_location(value: Any) -> tuple[float, float] | None:
    """Parses ``ssa_location`` text ``(RA_DEG, DEC_DEG)`` into degrees.

    Args:
        value: SSA location field from a TAP row.

    Returns:
        tuple[float, float] or None: ``(ra_deg, dec_deg)`` when parseable.
    """
    if value is None:
        return None
    text = str(value).strip()
    match = _SSA_LOCATION_PATTERN.match(text)
    if not match:
        logger.warning("Unrecognised ssa_location format: %r", text)
        return None
    return float(match.group(1)), float(match.group(2))


def _row_value(row, key: str) -> Any:
    """Returns a catalogue field from an Astropy row or dict.

    Args:
        row: TAP result row.
        key (str): Column name.

    Returns:
        Any: Cell value or ``None``.
    """
    if hasattr(row, "colnames"):
        if key not in row.colnames:
            return None
        value = row[key]
    else:
        value = row.get(key)
    if value is None:
        return None
    try:
        import numpy as np

        if isinstance(value, np.generic):
            value = value.item()
        if value is np.ma.masked:
            return None
    except Exception:
        pass
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _format_filter_name(bandpass: str | None) -> str:
    """Builds a display filter label from SSA ``ssa_bandpass``.

    Args:
        bandpass (str, optional): Raw passband code (e.g. ``I``, ``V``).

    Returns:
        str: Human-readable filter label for the catalogue table.
    """
    code = str(bandpass or "").strip()
    if not code:
        return "unknown"
    if code.upper().startswith("OGLE"):
        return code
    return f"OGLE {code}"


def map_ssa_row_to_catalog_dict(
    row,
    *,
    provider_id: str,
    distance_arcsec: float,
) -> dict[str, Any] | None:
    """Converts one OGLE SSA TAP row to a standard discovery catalogue row dict.

    Args:
        row: TAP result row with SSA columns.
        provider_id (str): Registry slug stored in ``lc_key``.
        distance_arcsec (float): Separation from the search centre in arcseconds.

    Returns:
        dict or None: Standard catalogue row, or ``None`` when ``accref`` is missing.
    """
    accref = _row_value(row, "accref")
    if not accref:
        return None

    location = parse_ssa_location(_row_value(row, "ssa_location"))
    if location is None:
        return None
    ra_deg, dec_deg = location

    object_id = str(_row_value(row, "object_id") or _row_value(row, "ssa_targname") or "unknown")
    filter_name = _format_filter_name(_row_value(row, "ssa_bandpass"))
    dstitle = _row_value(row, "ssa_dstitle")
    collection = _row_value(row, "ssa_collection")
    n_points = _row_value(row, "ssa_length")
    mean_mag = _row_value(row, "mean_mag")

    lc_key = encode_lc_key(
        provider_id,
        {
            "accref": str(accref),
            "filter_name": filter_name,
            "object_id": object_id,
        },
    )

    catalog_row: dict[str, Any] = {
        "distance_arcsec": float(distance_arcsec),
        "ra_deg": ra_deg,
        "dec_deg": dec_deg,
        "object_name": object_id,
        "filter_name": filter_name,
        "lc_key": lc_key,
        "t_min": _row_value(row, "t_min"),
        "t_max": _row_value(row, "t_max"),
        "survey": str(collection) if collection else "OGLE",
        "provider_note": str(dstitle) if dstitle else None,
    }
    if n_points is not None:
        try:
            catalog_row["n_points"] = int(n_points)
        except (TypeError, ValueError):
            pass
    if mean_mag is not None:
        try:
            catalog_row["mag"] = float(mean_mag)
        except (TypeError, ValueError):
            pass
    return catalog_row


def map_ssa_table_to_catalog(
    tap_table: Table,
    *,
    provider_id: str,
    centre_ra_deg: float | None = None,
    centre_dec_deg: float | None = None,
) -> Table:
    """Maps a TAP SSA result table onto the shared discovery catalogue schema.

    Args:
        tap_table (astropy.table.Table): Raw TAP query result.
        provider_id (str): Registry slug for ``lc_key`` encoding.
        centre_ra_deg (float, optional): Search centre RA for separation.
        centre_dec_deg (float, optional): Search centre Dec for separation.

    Returns:
        astropy.table.Table: Validated catalogue table (possibly empty).
    """
    if len(tap_table) == 0:
        return empty_catalog_table()

    centre = None
    if centre_ra_deg is not None and centre_dec_deg is not None:
        centre = SkyCoord(
            ra=float(centre_ra_deg) * u.deg,
            dec=float(centre_dec_deg) * u.deg,
            frame="icrs",
        )

    rows: list[dict[str, Any]] = []
    for row in tap_table:
        location = parse_ssa_location(_row_value(row, "ssa_location"))
        if location is None:
            continue
        ra_deg, dec_deg = location
        if centre is not None:
            source = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
            distance_arcsec = centre.separation(source).to_value(u.arcsec)
        else:
            distance_arcsec = 0.0

        catalog_row = map_ssa_row_to_catalog_dict(
            row,
            provider_id=provider_id,
            distance_arcsec=distance_arcsec,
        )
        if catalog_row is not None:
            rows.append(catalog_row)

    if not rows:
        return empty_catalog_table()
    return validate_catalog_table(Table(rows))
