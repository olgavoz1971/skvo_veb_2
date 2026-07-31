"""Download ZTF epoch photometry via ``ztfquery``."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from skvo_veb.lc_providers.ztf import config
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)


def fetch_photometry_by_oid(
    oid: int | str,
    *,
    fetch_quality: str = config.FETCH_QUALITY_RAW,
) -> pd.DataFrame:
    """Downloads epoch photometry for one ZTF OID.

    Args:
        oid (int or str): ZTF object/lightcurve identifier.
        fetch_quality (str): ``raw`` or ``bad_catflags`` (see provider config).

    Returns:
        pandas.DataFrame: Epoch table from ``ztfquery``.

    Raises:
        PipeException: When download fails or returns no rows.
    """
    oid_int = int(oid)
    quality = str(fetch_quality or config.FETCH_QUALITY_RAW).strip().lower()
    if quality not in (config.FETCH_QUALITY_RAW, config.FETCH_QUALITY_BAD_CATFLAGS):
        raise PipeException(
            f"{config.DISPLAY_NAME}: unsupported fetch_quality {fetch_quality!r}. "
            f"Use {config.FETCH_QUALITY_RAW!r} or {config.FETCH_QUALITY_BAD_CATFLAGS!r}."
        )
    try:
        from ztfquery import lightcurve
    except ImportError as exc:
        raise PipeException(
            f"{config.DISPLAY_NAME}: ztfquery is required but is not installed."
        ) from exc

    logger.info(
        "%s ztfquery fetch oid=%s quality=%s",
        config.DISPLAY_NAME,
        oid_int,
        quality,
    )
    try:
        lcq = lightcurve.LCQuery.from_id(str(oid_int), cookies={})
        frame = lcq.data
    except Exception as exc:
        raise PipeException(
            f"{config.DISPLAY_NAME}: lightcurve download failed for oid={oid_int}: {exc}"
        ) from exc

    if frame is None or len(frame) == 0:
        raise PipeException(
            f"{config.DISPLAY_NAME}: no epoch photometry returned for oid={oid_int}."
        )

    if quality == config.FETCH_QUALITY_BAD_CATFLAGS:
        frame = _apply_bad_catflags_mask(frame)

    if frame is None or len(frame) == 0:
        raise PipeException(
            f"{config.DISPLAY_NAME}: no epochs remain after quality filtering "
            f"for oid={oid_int} (quality={quality!r})."
        )
    return frame


def _apply_bad_catflags_mask(frame: pd.DataFrame) -> pd.DataFrame:
    """Removes epochs flagged by ZTF ``catflags`` bit 15 (cloud/moon).

    Args:
        frame (pandas.DataFrame): Raw ``ztfquery`` epoch table.

    Returns:
        pandas.DataFrame: Filtered copy.

    Raises:
        PipeException: When ``catflags`` is missing from the table.
    """
    if "catflags" not in frame.columns:
        raise PipeException(
            f"{config.DISPLAY_NAME}: catflags column missing; cannot apply "
            f"{config.FETCH_QUALITY_BAD_CATFLAGS!r} filtering."
        )
    mask = config.ZTF_BAD_CATFLAGS_MASK
    flags = np.asarray(frame["catflags"], dtype=np.int64)
    keep = (flags & mask) == 0
    filtered = frame.loc[keep].copy()
    logger.info(
        "%s bad_catflags filter kept %s/%s epochs (mask=%s)",
        config.DISPLAY_NAME,
        len(filtered),
        len(frame),
        mask,
    )
    return filtered
