"""Tests for retired ``CurveDash.download`` (Ticket 8 Phase 3)."""

from __future__ import annotations

import numpy as np
import pytest

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_config import DOMAIN_FLUX
from skvo_veb.utils.my_tools import PipeException


def test_curvedash_download_is_retired():
    """``CurveDash.download`` must raise and point callers to ``export_curvedash``."""
    lcd = CurveDash(
        jd=np.array([2459000.0, 2459001.0]),
        flux=np.array([1.0, 1.1]),
        flux_err=np.array([0.01, 0.01]),
        active_domain=DOMAIN_FLUX,
        flux_unit="electron s-1",
    )
    with pytest.raises(PipeException, match="export_curvedash") as exc_info:
        lcd.download("ascii.ecsv")
    assert "retired" in str(exc_info.value).lower()
