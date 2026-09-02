"""Load light curves for the running-parabola spike (template_timing bridge)."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from paths import ensure_import_paths

ensure_import_paths()

from lc_io import load_lightcurve_frame  # noqa: E402

logger = logging.getLogger(__name__)


def load_full_lightcurve(
    path: Path, *, working_domain: str
) -> tuple[pd.DataFrame, dict]:
    """Load an entire LC into ``jd`` / ``phot`` / ``phot_err`` columns.

    Args:
        path (Path): ``.vot`` / ``.dat`` / … path.
        working_domain (str): ``flux`` or ``mag``.

    Returns:
        tuple: DataFrame and loader metadata.
    """
    path = path.resolve()
    df, meta = load_lightcurve_frame(path, working_domain=working_domain)
    logger.info(
        "Loaded LC %s: %s points, domain=%s (native=%s)",
        path.name,
        len(df),
        meta.get("active_domain"),
        meta.get("native_domain"),
    )
    return df, meta
