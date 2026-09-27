"""Fetch and convert Discovery catalogue lightcurves for interactive plotting.

Pipeline:

    lc_discovery.fetch(lc_key) → VOTable bytes
    VOLightCurve → volc_to_curvedash() → CurveDash
"""

from __future__ import annotations

import io
import logging

from lc_discovery import fetch
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import valid_photometry_row_mask, volc_to_curvedash
from skvo_veb.utils.lc_config import JD_TO_MJD
from skvo_veb.utils.my_tools import PipeException, sanitize_filename
from volightcurve import VOLightCurve
from volightcurve.time_reference import time_offset_to_absolute_jd

logger = logging.getLogger(__name__)


def catalog_row_for_lc_key(row_data: list[dict] | None, lc_key: str | None) -> dict | None:
    """Returns the catalogue row matching ``lc_key``, if present.

    Args:
        row_data (list[dict], optional): Current AgGrid catalogue rows.
        lc_key (str, optional): Serialised provider fetch handle.

    Returns:
        dict | None: Matching row dict, or ``None`` when not found.
    """
    if not lc_key or not row_data:
        return None
    for row in row_data:
        if row.get('lc_key') == lc_key:
            return row
    return None


def mission_id_from_catalog_row(row: dict | None) -> str | None:
    """Returns the mission slug stamped on an AgGrid catalogue row.

    Args:
        row (dict, optional): Catalogue row.

    Returns:
        str or None: Mission slug when present.
    """
    if not row:
        return None
    mission_id = row.get("mission_id")
    if mission_id:
        return str(mission_id)
    return None


def discovery_export_basename(lcd: CurveDash) -> str:
    """Builds a safe download basename from ``CurveDash`` metadata.

    Args:
        lcd (CurveDash): Loaded discovery lightcurve.

    Returns:
        str: Sanitised filename stem without extension.
    """
    title = (lcd.title or 'lc_discovery').strip()
    return sanitize_filename(f'lc_discovery_{title}')


def fetch_discovery_votable_bytes(
    lc_key: str,
    *,
    force_refresh: bool = False,
) -> bytes:
    """Fetches the mission VOTable product as returned by ``lc_discovery.fetch``.

    This is the archive/enrich bytes before ``VOLightCurve`` or ``CurveDash``.

    Args:
        lc_key (str): Serialised fetch handle from a catalogue row.
        force_refresh (bool): When true, bypass any provider-side cache.

    Returns:
        bytes: VOTable payload.

    Raises:
        PipeException: When the key is missing or fetch fails.
    """
    if not lc_key:
        raise PipeException('Select a catalogue row before loading.')

    try:
        payload = fetch(lc_key, force_refresh=force_refresh)
    except ValueError as exc:
        raise PipeException(str(exc)) from exc
    logger.info(
        'Discovery VOTable bytes lc_key=%s nbytes=%s force_refresh=%s',
        lc_key[:32],
        len(payload),
        force_refresh,
    )
    return payload


def fetch_discovery_volightcurve(
    lc_key: str,
    *,
    force_refresh: bool = False,
) -> VOLightCurve:
    """Fetches a mission lightcurve at the VO layer (no ``CurveDash``).

    Args:
        lc_key (str): Serialised fetch handle from a catalogue row.
        force_refresh (bool): When true, bypass any provider-side cache.

    Returns:
        VOLightCurve: VO-standard lightcurve parsed from ``fetch`` bytes.

    Raises:
        PipeException: When the key is missing or fetch fails.
    """
    payload = fetch_discovery_votable_bytes(lc_key, force_refresh=force_refresh)
    volc = VOLightCurve(io.BytesIO(payload))
    logger.info(
        'Discovery VOLightCurve lc_key=%s n_points=%s',
        lc_key[:32],
        len(volc),
    )
    return volc


def _volc_filename_from_catalog_row(catalog_row: dict) -> str:
    """Builds a bridge filename stem from standard catalogue display columns.

    Args:
        catalog_row (dict): One AgGrid catalogue row dict.

    Returns:
        str: Filename ending in ``.vot`` for ``volc_to_curvedash``.
    """
    object_name = str(catalog_row.get('object_name') or 'object')
    filter_name = str(catalog_row.get('filter_name') or '').strip()
    name_parts = [object_name, filter_name] if filter_name else [object_name]
    return sanitize_filename('_'.join(name_parts)) + '.vot'


def drop_invalid_photometry_rows(lcd: CurveDash) -> None:
    """Removes rows with missing photometry in the lightcurve's active domain.

    Flux-native curves drop rows with non-finite or masked ``flux``; magnitude-native
    curves drop rows with non-finite or masked ``mag``. Uncertainty columns are not
    used for this decision. Uses the same rule as export via ``valid_photometry_row_mask``.

    Args:
        lcd (CurveDash): Loaded lightcurve instance to mutate in place.
    """
    if lcd.lightcurve is None:
        return

    keep = valid_photometry_row_mask(lcd)
    lcd.lightcurve = lcd.lightcurve.loc[keep].reset_index(drop=True)


def apply_catalog_folding_hints(lcd: CurveDash, catalog_row: dict) -> None:
    """Applies optional standard catalogue folding hints onto ``CurveDash``.

    Uses schema columns documented in ``docs/mission_lightcurve_providers.md``
    (§5.2): ``period`` (days) and ``epoch`` (full JD).

    Args:
        lcd (CurveDash): Target instance to mutate in place.
        catalog_row (dict): Catalogue row dict from search results.
    """
    period = catalog_row.get('period')
    epoch = catalog_row.get('epoch')
    if period is not None:
        lcd.period = float(period)
        lcd.period_unit = 'd'
    if epoch is not None:
        lcd.epoch = time_offset_to_absolute_jd(float(epoch), JD_TO_MJD)


def curvedash_from_catalog_row(
    catalog_row: dict,
    *,
    force_refresh: bool = False,
) -> CurveDash:
    """Fetches and converts one catalogue row to ``CurveDash``.

    Args:
        catalog_row (dict): One AgGrid catalogue row dict with ``lc_key``.
        force_refresh (bool): When true, bypass any provider-side cache.

    Returns:
        CurveDash: Application lightcurve ready for plotting.

    Raises:
        PipeException: When the row is incomplete or fetch fails.
    """
    lc_key = catalog_row.get('lc_key')
    if not lc_key:
        raise PipeException('Catalogue row is missing lc_key.')

    volc = fetch_discovery_volightcurve(
        lc_key,
        force_refresh=force_refresh,
    )
    lcd = volc_to_curvedash(
        volc,
        _volc_filename_from_catalog_row(catalog_row),
        preserve_photcal=True,
    )
    apply_catalog_folding_hints(lcd, catalog_row)
    drop_invalid_photometry_rows(lcd)
    return lcd


def load_discovery_lightcurve(
    mission_id: str,
    lc_key: str,
    *,
    object_name: str | None = None,
    filter_name: str | None = None,
    period_days: float | None = None,
    epoch_mjd: float | None = None,
    force_refresh: bool = False,
) -> CurveDash:
    """Fetches a catalogue lightcurve when only ``lc_key`` fields are available.

    Prefer :func:`curvedash_from_catalog_row` when the full catalogue row dict
    is available. This wrapper rebuilds a minimal row dict for compatibility.

    Args:
        mission_id (str): Selected mission slug from the UI (cross-check only).
        lc_key (str): Serialised fetch handle from a catalogue row.
        object_name (str, optional): Catalogue object label for titling.
        filter_name (str, optional): Filter or band label for titling.
        period_days (float, optional): Catalogue period in days, when known.
        epoch_mjd (float, optional): Catalogue folding epoch in MJD, when known.
        force_refresh (bool): When true, bypass any provider-side cache.

    Returns:
        CurveDash: Deserialisable lightcurve ready for session storage.

    Raises:
        PipeException: When the mission, key, or fetch fails validation.
    """
    if not mission_id:
        raise PipeException('Select a mission before loading a lightcurve.')
    if not lc_key:
        raise PipeException('Select a catalogue row before loading.')

    catalog_row = {
        'lc_key': lc_key,
        'object_name': object_name,
        'filter_name': filter_name,
        'mission_id': mission_id,
    }
    if period_days is not None:
        catalog_row['period'] = period_days
    if epoch_mjd is not None:
        catalog_row['epoch'] = epoch_mjd

    return curvedash_from_catalog_row(catalog_row, force_refresh=force_refresh)
