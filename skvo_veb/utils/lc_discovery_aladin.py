"""Aladin Lite view helpers for Lightcurve Discovery catalogue sync."""

from __future__ import annotations

import logging
import math

from astropy.coordinates import SkyCoord

from skvo_veb.utils.coord import skycoord_to_hms_dms
from skvo_veb.utils.lc_discovery_search import (
    SEARCH_MODE_CONE,
    SEARCH_MODE_SIMBAD_CONE,
    radius_to_arcsec,
)

logger = logging.getLogger(__name__)

DEFAULT_ALADIN_TARGET = "0 0 0 +0 0 0"
DEFAULT_ALADIN_FOV_DEG = 0.1
_MIN_ALADIN_FOV_DEG = 0.01
_CONE_SEARCH_MODES = frozenset({SEARCH_MODE_CONE, SEARCH_MODE_SIMBAD_CONE})


def aladin_marker_name(row: dict) -> str:
    """Returns a stable Aladin marker name for one catalogue row.

    Args:
        row (dict): AgGrid row dict from ``catalog_rows_for_aggrid``.

    Returns:
        str: Marker identifier used for table–map synchronisation.
    """
    explicit_name = row.get("aladin_name")
    if explicit_name:
        return str(explicit_name)

    lc_key = row.get("lc_key")
    if lc_key:
        return str(lc_key)

    object_name = str(row.get("object_name") or "object")
    filter_name = str(row.get("filter_name") or "")
    if filter_name:
        return f"{object_name} ({filter_name})"
    return object_name


def aladin_remount_key(search_metadata: dict | None, rows: list[dict]) -> str:
    """Builds a React remount key so Aladin reloads when catalogue results change.

    The third-party Aladin component only reads ``stars`` during its initial mount;
    changing the ``key`` forces a fresh instance with markers applied.

    Args:
        search_metadata (dict, optional): Serialised search outcome metadata.
        rows (list[dict]): Current AgGrid catalogue rows.

    Returns:
        str: Stable remount key for the current result set.
    """
    parts = [str(len(rows))]
    if isinstance(search_metadata, dict):
        parts.extend(
            [
                str(search_metadata.get("user_target") or ""),
                str(search_metadata.get("search_mode") or ""),
                str(search_metadata.get("row_count") or ""),
            ]
        )
    for row in rows[:3]:
        parts.append(str(row.get("lc_key") or row.get("object_name") or ""))
    return "|".join(parts)


def catalog_rows_to_aladin_stars(rows: list[dict]) -> list[dict]:
    """Builds Aladin ``stars`` payloads from Discovery catalogue rows.

    Args:
        rows (list[dict]): AgGrid ``rowData`` entries.

    Returns:
        list[dict]: Markers with ``name``, ``ra``, and ``dec`` keys.
    """
    stars: list[dict] = []
    for row in rows:
        ra_deg = row.get("ra_deg")
        dec_deg = row.get("dec_deg")
        if ra_deg is None or dec_deg is None:
            continue
        try:
            stars.append(
                {
                    "name": aladin_marker_name(row),
                    "ra": float(ra_deg),
                    "dec": float(dec_deg),
                }
            )
        except (TypeError, ValueError):
            logger.warning(
                "Skipping Aladin marker for row with invalid coordinates: %r",
                row.get("object_name"),
            )
    return stars


def aladin_target_from_metadata(
    search_metadata: dict | None,
    rows: list[dict],
    *,
    precision: int = 1,
) -> str:
    """Chooses an Aladin ``target`` string from search metadata or catalogue rows.

    Args:
        search_metadata (dict, optional): Serialised ``SearchOutcome`` store payload.
        rows (list[dict]): Current AgGrid catalogue rows.
        precision (int): Sexagesimal rounding for the Aladin target string.

    Returns:
        str: HMS/DMS target string understood by Aladin Lite.
    """
    centre_ra = None
    centre_dec = None
    if isinstance(search_metadata, dict):
        centre_ra = search_metadata.get("centre_ra_deg")
        centre_dec = search_metadata.get("centre_dec_deg")

    if centre_ra is not None and centre_dec is not None:
        return _target_from_degrees(float(centre_ra), float(centre_dec), precision=precision)

    if rows:
        ra_values = [float(row["ra_deg"]) for row in rows if row.get("ra_deg") is not None]
        dec_values = [float(row["dec_deg"]) for row in rows if row.get("dec_deg") is not None]
        if ra_values and dec_values:
            return _target_from_degrees(
                sum(ra_values) / len(ra_values),
                sum(dec_values) / len(dec_values),
                precision=precision,
            )

    return DEFAULT_ALADIN_TARGET


def aladin_fov_degrees(
    search_metadata: dict | None,
    rows: list[dict],
    *,
    min_fov_deg: float = _MIN_ALADIN_FOV_DEG,
) -> float:
    """Estimates an Aladin field-of-view in degrees for a catalogue result set.

    Cone searches use twice the requested radius (diameter). Other searches derive
    a padded span from the catalogue row positions.

    Args:
        search_metadata (dict, optional): Serialised ``SearchOutcome`` store payload.
        rows (list[dict]): Current AgGrid catalogue rows.
        min_fov_deg (float): Lower bound when the computed span is tiny.

    Returns:
        float: Aladin ``fov`` value in degrees.
    """
    if isinstance(search_metadata, dict) and search_metadata.get("search_mode") in _CONE_SEARCH_MODES:
        radius_value = search_metadata.get("radius_value")
        radius_unit = search_metadata.get("radius_unit")
        if radius_value is not None and radius_unit:
            try:
                radius_arcsec = radius_to_arcsec(float(radius_value), str(radius_unit))
                return max(min_fov_deg, 2.0 * radius_arcsec / 3600.0)
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid radius metadata for Aladin FOV: value=%r unit=%r",
                    radius_value,
                    radius_unit,
                )

    if not rows:
        return DEFAULT_ALADIN_FOV_DEG

    ra_values = [float(row["ra_deg"]) for row in rows if row.get("ra_deg") is not None]
    dec_values = [float(row["dec_deg"]) for row in rows if row.get("dec_deg") is not None]
    if not ra_values or not dec_values:
        return DEFAULT_ALADIN_FOV_DEG

    ra_span = max(ra_values) - min(ra_values)
    dec_span = max(dec_values) - min(dec_values)
    span_deg = max(ra_span, dec_span)
    if span_deg <= 0.0:
        return max(min_fov_deg, DEFAULT_ALADIN_FOV_DEG / 2.0)

    padded = span_deg * 1.5
    return max(min_fov_deg, min(padded, 5.0))


def aladin_selected_star_from_row(row: dict) -> dict:
    """Builds an Aladin ``selectedStar`` payload from one AgGrid row.

    Args:
        row (dict): Selected AgGrid catalogue row.

    Returns:
        dict: ``selectedStar`` payload with ``name``, ``ra``, and ``dec``.
    """
    return {
        "name": aladin_marker_name(row),
        "ra": float(row["ra_deg"]),
        "dec": float(row["dec_deg"]),
    }


def find_catalog_row_by_aladin_name(rows: list[dict], marker_name: str) -> dict | None:
    """Finds the catalogue row matching an Aladin marker name.

    Args:
        rows (list[dict]): Current AgGrid ``rowData``.
        marker_name (str): Marker ``name`` from Aladin ``selectedStar``.

    Returns:
        dict or None: Matching row when found.
    """
    if not marker_name:
        return None
    for row in rows:
        if aladin_marker_name(row) == marker_name:
            return row
    return None


def catalog_row_from_cell_clicked(
    cell_clicked: dict | None,
    row_data: list[dict],
) -> dict | None:
    """Resolves a catalogue row from an AgGrid ``cellClicked`` event payload.

    Args:
        cell_clicked (dict, optional): AgGrid ``cellClicked`` event data.
        row_data (list[dict]): Current AgGrid ``rowData``.

    Returns:
        dict or None: Matching catalogue row when found.
    """
    if not cell_clicked or not row_data:
        return None

    row_id = cell_clicked.get("rowId")
    if row_id is not None:
        for row in row_data:
            if row.get("lc_key") == row_id:
                return row

    row_index = cell_clicked.get("rowIndex")
    if isinstance(row_index, int) and 0 <= row_index < len(row_data):
        return row_data[row_index]
    return None


def _target_from_degrees(ra_deg: float, dec_deg: float, *, precision: int) -> str:
    """Formats ICRS degrees as an Aladin HMS/DMS target string.

    Args:
        ra_deg (float): Right ascension in degrees.
        dec_deg (float): Declination in degrees.
        precision (int): Sexagesimal rounding passed to ``skycoord_to_hms_dms``.

    Returns:
        str: Aladin target string.
    """
    if not (math.isfinite(ra_deg) and math.isfinite(dec_deg)):
        return DEFAULT_ALADIN_TARGET
    coord = SkyCoord(ra=ra_deg, dec=dec_deg, unit="deg", frame="icrs")
    return skycoord_to_hms_dms(coord, precision=precision)
