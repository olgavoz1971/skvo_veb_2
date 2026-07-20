"""Fetch OGLE OCVS lightcurves from SSA ``accref`` product URLs."""

from __future__ import annotations

import io
import logging
import urllib.error
import urllib.request

from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SEC = 120


def fetch_volightcurve_from_accref(
    accref: str,
    *,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
) -> VOLightCurve:
    """Downloads one lightcurve VOTable from an SSA ``accref`` URL.

    Args:
        accref (str): Absolute HTTP(S) URL to the lightcurve product.
        timeout_sec (float): Network read timeout in seconds.

    Returns:
        VOLightCurve: Parsed VO-standard lightcurve.

    Raises:
        PipeException: When the URL is missing or the download/parse fails.
    """
    url = str(accref or "").strip()
    if not url:
        raise PipeException("Lightcurve accref URL is empty.")

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "skvo_veb/lc_providers"})
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = response.read()
    except urllib.error.URLError as exc:
        logger.warning("OGLE accref download failed url=%s: %s", url, exc)
        raise PipeException(f"Failed to download lightcurve from accref: {exc}") from exc

    try:
        volc = VOLightCurve(io.BytesIO(payload))
    except Exception as exc:
        logger.warning("OGLE accref VOTable parse failed url=%s: %s", url, exc)
        raise PipeException(f"Downloaded accref is not a valid lightcurve: {exc}") from exc

    logger.info("OGLE fetched lightcurve from accref url=%s n_points=%s", url, len(volc))
    return volc
