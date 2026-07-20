"""Fetch and convert Discovery catalogue lightcurves for interactive plotting.

Pipeline (see ``docs/lightcurve_data_flow.md`` and ``docs/mission_lightcurve_providers.md``):

    provider.fetch_lightcurve(lc_key) → VOLightCurve
    volc_to_curvedash() → CurveDash

No Dash imports. No mission-specific parsing beyond the provider registry and
standard catalogue columns (``period``, ``epoch``).
"""

from __future__ import annotations

import logging

from skvo_veb.lc_providers.lc_key import decode_lc_key
from skvo_veb.lc_providers.registry import get_provider
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import volc_to_curvedash
from skvo_veb.utils.lc_config import DOMAIN_FLUX, DOMAIN_MAG, JD_TO_MJD
from skvo_veb.utils.my_tools import PipeException, sanitize_filename
from skvo_veb.volightcurve import VOLightCurve
from skvo_veb.volightcurve.time_reference import time_offset_to_absolute_jd

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


def mission_id_from_lc_key(lc_key: str) -> str:
    """Reads the mission slug embedded in an ``lc_key`` document.

    Args:
        lc_key (str): Serialised fetch handle from a catalogue row.

    Returns:
        str: Registered mission slug (e.g. ``gaia``).
    """
    return decode_lc_key(lc_key)['mission_id']


def discovery_export_basename(lcd: CurveDash) -> str:
    """Builds a safe download basename from ``CurveDash`` metadata.

    Args:
        lcd (CurveDash): Loaded discovery lightcurve.

    Returns:
        str: Sanitised filename stem without extension.
    """
    title = (lcd.title or 'lc_discovery').strip()
    return sanitize_filename(f'lc_discovery_{title}')


def fetch_discovery_volightcurve(lc_key: str, *, force_refresh: bool = False) -> VOLightCurve:
    """Fetches a mission lightcurve at the VO layer (no ``CurveDash``).

    Args:
        lc_key (str): Serialised fetch handle from a catalogue row.
        force_refresh (bool): When true, bypass any provider-side cache.

    Returns:
        VOLightCurve: VO-standard lightcurve from the mission provider.

    Raises:
        PipeException: When the key is invalid or fetch fails validation.
    """
    if not lc_key:
        raise PipeException('Select a catalogue row before loading.')

    mission_id = mission_id_from_lc_key(lc_key)
    provider = get_provider(mission_id)
    if not provider.validate_lc_key(lc_key):
        raise PipeException(f'{provider.display_name}: invalid lightcurve key.')

    volc = provider.fetch_lightcurve(lc_key, force_refresh=force_refresh)
    logger.info(
        'Discovery fetch mission=%s lc_key=%s n_points=%s force_refresh=%s',
        mission_id,
        lc_key[:32],
        len(volc),
        force_refresh,
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

    Flux-native curves drop rows with non-finite ``flux``; magnitude-native curves
    drop rows with non-finite ``mag``. Matches the post-ingest cleanup previously
    hard-coded for flux-only missions in Discovery.

    Args:
        lcd (CurveDash): Loaded lightcurve instance to mutate in place.
    """
    if lcd.lightcurve is None:
        return

    phot_col = "mag" if lcd.active_domain == DOMAIN_MAG else "flux"
    if phot_col not in lcd.lightcurve.columns:
        raise PipeException(
            f"Discovery lightcurve active domain {lcd.active_domain!r} "
            f"is missing expected column {phot_col!r}."
        )
    lcd.lightcurve.dropna(subset=[phot_col], inplace=True)


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


def curvedash_from_catalog_row(catalog_row: dict, *, force_refresh: bool = False) -> CurveDash:
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

    volc = fetch_discovery_volightcurve(lc_key, force_refresh=force_refresh)
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

    key_mission = mission_id_from_lc_key(lc_key)
    if key_mission != mission_id:
        raise PipeException(
            f'Lightcurve key mission ({key_mission!r}) does not match '
            f'the selected mission ({mission_id!r}).'
        )

    catalog_row = {
        'lc_key': lc_key,
        'object_name': object_name,
        'filter_name': filter_name,
    }
    if period_days is not None:
        catalog_row['period'] = period_days
    if epoch_mjd is not None:
        catalog_row['epoch'] = epoch_mjd

    return curvedash_from_catalog_row(catalog_row, force_refresh=force_refresh)
