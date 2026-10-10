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
_SOURCE_SPREAD_WARN_ARCSEC = 10.0
_CONE_SEARCH_MODES = frozenset({SEARCH_MODE_CONE, SEARCH_MODE_SIMBAD_CONE})


def aladin_marker_name(row: dict) -> str:
    """Returns the sky-source identity of one catalogue row.

    The source is ``object_name``; it names the Aladin marker and groups table
    rows of one star. The product identity for Retrieve is ``lc_key``, never this.

    Args:
        row (dict): AgGrid row dict from ``catalog_rows_for_aggrid``.

    Returns:
        str: ``object_name`` of the row.

    Raises:
        ValueError: When the row has no ``object_name``.
    """
    object_name = row.get("object_name")
    if not object_name:
        raise ValueError("Catalogue row is missing object_name.")
    return str(object_name)


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
        parts.append(str(row.get("lc_key") or ""))
    return "|".join(parts)


def catalog_rows_to_aladin_stars(rows: list[dict]) -> list[dict]:
    """Builds Aladin ``stars`` payloads from Discovery catalogue rows.

    One marker is emitted per source (``object_name``) using the position of its
    first row. A later row of the same source more than ``_SOURCE_SPREAD_WARN_ARCSEC``
    away is logged as a provider contract violation.

    Args:
        rows (list[dict]): AgGrid ``rowData`` entries.

    Returns:
        list[dict]: Markers with ``name``, ``ra``, and ``dec`` keys.
    """
    stars: list[dict] = []
    by_name: dict[str, dict] = {}
    for row in rows:
        ra_deg = row.get("ra_deg")
        dec_deg = row.get("dec_deg")
        if ra_deg is None or dec_deg is None:
            continue
        name = aladin_marker_name(row)
        ra_val = float(ra_deg)
        dec_val = float(dec_deg)
        known = by_name.get(name)
        if known is not None:
            separation = SkyCoord(
                ra=known["ra"], dec=known["dec"], unit="deg", frame="icrs"
            ).separation(SkyCoord(ra=ra_val, dec=dec_val, unit="deg", frame="icrs"))
            if separation.arcsec > _SOURCE_SPREAD_WARN_ARCSEC:
                logger.warning(
                    "Source %r has rows %.1f arcsec apart; one object_name must "
                    "identify one sky position.",
                    name,
                    separation.arcsec,
                )
            continue
        star = {"name": name, "ra": ra_val, "dec": dec_val}
        by_name[name] = star
        stars.append(star)
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


def rows_for_source(rows: list[dict], source_name: str | None) -> list[dict]:
    """Lists the catalogue rows that belong to one sky source.

    Args:
        rows (list[dict]): Current AgGrid ``rowData``.
        source_name (str, optional): Source identity (``object_name``).

    Returns:
        list[dict]: Rows with that ``object_name``, in table order.
    """
    if not source_name:
        return []
    return [row for row in rows if aladin_marker_name(row) == source_name]


def selection_after_map_click(
    rows: list[dict],
    source_name: str,
    selected_rows: list[dict] | None,
) -> list[dict] | None:
    """Decides the table selection after a click on a map marker.

    A selected row that already belongs to the source stays selected; otherwise
    the first row of the source is selected so the user always sees a marked row.

    Args:
        rows (list[dict]): Current AgGrid ``rowData``.
        source_name (str): Clicked marker name (``object_name``).
        selected_rows (list[dict], optional): Currently selected table rows.

    Returns:
        list[dict] or None: New ``selectedRows`` value, or ``None`` when the
        current selection already belongs to the source and must stay.

    Raises:
        ValueError: When the source has no row in ``rows``.
    """
    if selected_rows and aladin_marker_name(selected_rows[0]) == source_name:
        return None
    source_rows = rows_for_source(rows, source_name)
    if not source_rows:
        raise ValueError(f"No catalogue row for source {source_name!r}.")
    return [source_rows[0]]


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
