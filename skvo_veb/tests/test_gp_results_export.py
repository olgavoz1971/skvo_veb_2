"""Tests for GP extrema compact export."""

from __future__ import annotations

import pytest

from skvo_veb.utils.gp.export import (
    gp_compact_extrema_download_name,
    gp_extrema_export_stem,
    gp_suggested_timing_stem,
)
from skvo_veb.utils.gp.results_export import (
    format_compact_extrema_dat,
    scale_limit_flag,
    SCALE_LIMIT_HIT_MAX,
    SCALE_LIMIT_HIT_MIN,
    SCALE_LIMIT_OK,
)


def test_format_compact_extrema_dat_keeps_selected_successes_only():
    """Compact export ignores rejected and failed rows."""
    rows = [
        {"is_fail": False, "jd_peak": 2451000.0, "jd_peak_std": 0.01, "scale_limit_flag": 1},
        {"is_fail": True},
    ]
    include = [True, False]
    body = format_compact_extrema_dat(rows, include, extrema_mode="max")
    assert "2451000.000000" in body
    data = [line for line in body.splitlines() if line and not line.startswith("#")]
    assert len(data) == 1
    cols = data[0].split("\t")
    assert cols[2] == "1"
    assert "# scale_limit:" in body
    assert "# max_half_width_d: none" in body
    header = [line for line in body.splitlines() if line.startswith("# JD_")]
    assert header and header[0].endswith("scale_limit")


def test_format_compact_extrema_dat_stamps_half_width():
    """Compact file records the optional max half-width used for the run."""
    rows = [
        {"is_fail": False, "jd_peak": 2451000.0, "jd_peak_std": 0.01, "scale_limit_flag": 0},
    ]
    body = format_compact_extrema_dat(
        rows, [True], extrema_mode="min", max_half_width_d=0.04
    )
    assert "# max_half_width_d: 0.04" in body


def test_format_compact_extrema_dat_rejects_missing_scale_limit():
    """A kept success row with no scale_limit fails fast."""
    rows = [{"is_fail": False, "jd_peak": 2451000.0, "jd_peak_std": 0.01}]
    with pytest.raises(ValueError, match="missing scale_limit"):
        format_compact_extrema_dat(rows, [True], extrema_mode="max")


def test_scale_limit_flag_matches_badge_slack():
    """Integer codes: 0 ok, 1 hit min, 2 hit max (1% slack)."""
    assert scale_limit_flag(0.05, 0.01, 1.0) == SCALE_LIMIT_OK
    assert scale_limit_flag(0.0101, 0.01, 1.0) == SCALE_LIMIT_HIT_MIN
    assert scale_limit_flag(0.990, 0.01, 1.0) == SCALE_LIMIT_HIT_MAX


def test_gp_extrema_download_names():
    """Export stems normalise a trailing ``.dat`` and keep the GP suffix."""
    assert gp_suggested_timing_stem("NSV807.vot") == "NSV807_gp"
    assert gp_suggested_timing_stem("NSV807_gp.dat") == "NSV807_gp"
    assert gp_suggested_timing_stem(None) == "results_gp"
    assert gp_extrema_export_stem("target_extrema.dat") == "target_extrema"
    assert gp_compact_extrema_download_name("target_extrema") == "target_extrema.dat"
