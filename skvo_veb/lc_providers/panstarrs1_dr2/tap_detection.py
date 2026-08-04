"""TAP fetch for Pan-STARRS1 DR2 detection epoch tables."""

from __future__ import annotations

import logging

from astropy.table import Table

from skvo_veb.lc_providers.panstarrs1_dr2 import config
from skvo_veb.lc_providers.tap.client import run_tap_sync_query
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)


def fetch_detection_table(*, obj_id: int, filter_code: str) -> Table:
    """Downloads epoch photometry for one object and filter.

    Args:
        obj_id (int): Pan-STARRS mean object identifier.
        filter_code (str): Filter code ``g``, ``r``, ``i``, ``z``, or ``y``.

    Returns:
        astropy.table.Table: Detection rows (possibly empty).

    Raises:
        PipeException: When TAP fails or the filter code is invalid.
    """
    band = config.band_spec_for_code(filter_code)
    adql = config.adql_detection_lightcurve(obj_id=int(obj_id), filter_type=band.filter_type)
    try:
        table = run_tap_sync_query(
            config.TAP_URL,
            adql,
            dialect=config.TAP_QUERY_DIALECT,
        )
    except PipeException:
        raise
    except Exception as exc:
        logger.warning(
            "%s detection TAP failed obj_id=%s filter=%s: %s",
            config.DISPLAY_NAME,
            obj_id,
            filter_code,
            exc,
        )
        raise PipeException(
            f"{config.DISPLAY_NAME}: detection query failed for objID={obj_id}."
        ) from exc
    logger.info(
        "%s detection fetch obj_id=%s filter=%s rows=%s",
        config.DISPLAY_NAME,
        obj_id,
        filter_code,
        len(table),
    )
    return table
