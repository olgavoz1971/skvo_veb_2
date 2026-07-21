"""Fetch OGLE OCVS lightcurves from SSA ``accref`` product URLs."""

from __future__ import annotations

import io
import logging
import urllib.error
import urllib.request

from skvo_veb.lc_providers.ogle_ocvs import config
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SEC = 120


def fetch_volightcurve_from_accref(
    accref: str,
    *,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
    provider_label: str | None = None,
) -> VOLightCurve:
    """Downloads one lightcurve VOTable from an SSA ``accref`` URL.

    Args:
        accref (str): Absolute HTTP(S) URL to the lightcurve product.
        timeout_sec (float): Network read timeout in seconds.
        provider_label (str, optional): Mission display name for log messages.

    Returns:
        VOLightCurve: Parsed VO-standard lightcurve.

    Raises:
        PipeException: When the URL is missing or the download/parse fails.
    """
    url = str(accref or "").strip()
    if not url:
        raise PipeException("Lightcurve accref URL is empty.")

    label = provider_label or config.DISPLAY_NAME

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "skvo_veb/lc_providers"})
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = response.read()
    except urllib.error.URLError as exc:
        logger.warning("%s accref download failed url=%s: %s", label, url, exc)
        raise PipeException(f"Failed to download lightcurve from accref: {exc}") from exc

    try:
        volc = VOLightCurve(io.BytesIO(payload))
    except Exception as exc:
        logger.warning("%s accref VOTable parse failed url=%s: %s", label, url, exc)
        raise PipeException(f"Downloaded accref is not a valid lightcurve: {exc}") from exc

    logger.info("%s fetched lightcurve from accref url=%s n_points=%s", label, url, len(volc))
    return volc
