"""Tests for MAVKA compact export."""

from __future__ import annotations

import pytest

from skvo_veb.utils.mavka.export import (
    format_compact_extrema_dat,
    mavka_compact_extrema_download_name,
    mavka_extrema_export_stem,
    mavka_suggested_timing_stem,
)
from skvo_veb.utils.my_tools import PipeException


def test_mavka_extrema_download_names():
    """Export stems use the approximation method, not a MAVKA suffix."""
    assert mavka_suggested_timing_stem("NSV807.vot", "WSL") == "NSV807_WSL"
    assert mavka_suggested_timing_stem("NSV807_WSAP.dat", "WSAP") == "NSV807_WSAP"
    assert mavka_suggested_timing_stem(None, "AP") == "results_AP"
    assert mavka_extrema_export_stem("target_extrema.dat") == "target_extrema"
    assert mavka_compact_extrema_download_name("target_extrema") == "target_extrema.dat"


def test_format_compact_extrema_dat_keeps_selected_successes_only():
    """Compact export ignores rejected and failed rows."""
    rows = [
        {"is_fail": False, "jd_peak": 2451000.0, "jd_peak_std": 0.01},
        {"is_fail": True},
    ]
    include = [True, False]
    body = format_compact_extrema_dat(rows, include, extrema_mode="min")
    assert body.startswith("# MAVKA Minimum Results")
    assert "# max_half_width_d: none" in body
    assert "2451000.000000" in body
    data = [line for line in body.splitlines() if line and not line.startswith("#")]
    assert len(data) == 1


def test_format_compact_extrema_dat_stamps_period_epoch_comments():
    """Compact file records method beside the MAVKA header, then P/Epoch."""
    rows = [{"is_fail": False, "jd_peak": 2451000.0, "jd_peak_std": 0.01}]
    body = format_compact_extrema_dat(
        rows,
        [True],
        extrema_mode="min",
        period="2.5",
        epoch="58000.1",
        method="WSL",
        max_half_width_d=0.05,
    )
    assert body.startswith("# MAVKA Minimum Results")
    assert "# method: WSL" in body
    assert "# max_half_width_d: 0.05" in body
    assert "# PERIOD = 2.5" in body
    assert "# EPOCH = 58000.1" in body


def test_format_compact_extrema_dat_rejects_success_without_tom():
    """A kept success row with no TOM fails fast instead of writing a blank line."""
    rows = [{"is_fail": False, "jd_peak": None, "jd_peak_std": None}]
    with pytest.raises(PipeException, match="missing TOM"):
        format_compact_extrema_dat(rows, [True], extrema_mode="min")
