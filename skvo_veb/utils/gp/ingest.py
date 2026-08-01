"""Lightcurve upload helpers for the GP page (shared bridge ingest)."""

import io
import logging

from skvo_veb.utils.lc_bridge import ingest_volightcurve_file, pack_volc_to_json

logger = logging.getLogger(__name__)


def pack_uploaded_lightcurve(decoded: bytes, filename: str) -> str:
    """Ingest user bytes through the canonical bridge and serialise for ``dcc.Store``.

    Args:
        decoded (bytes): Raw file content after base64 decode.
        filename (str): Original filename (used for format detection).

    Returns:
        str: JSON transport string from ``pack_volc_to_json``.
    """
    file_obj = io.BytesIO(decoded)
    volc = ingest_volightcurve_file(file_obj, filename)
    logger.info("Packed upload %s (%s rows)", filename, len(volc.table))
    return pack_volc_to_json(volc)
