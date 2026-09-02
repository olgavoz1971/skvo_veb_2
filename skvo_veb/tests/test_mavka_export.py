"""Tests for MAVKA compact and extended export."""

from __future__ import annotations

import io
import zipfile
from unittest.mock import patch

import pytest

from skvo_veb.utils.mavka.export import (
    assign_plot_filenames,
    build_extended_export_zip,
    build_extended_results_tsv,
    fit_export_status,
    format_compact_extrema_dat,
    mavka_compact_extrema_download_name,
    mavka_extended_extrema_download_name,
    mavka_extrema_export_stem,
    mavka_suggested_timing_stem,
)
from skvo_veb.utils.my_tools import PipeException


def _sample_success_entry(
    *,
    jd_peak: float = 2451000.123456,
    jd_min: float = 2450999.0,
    jd_max: float = 2451001.0,
    method: str = "WSAP",
) -> dict:
    """Builds one successful serialised review row for export tests."""
    return {
        "is_fail": False,
        "jd_min": jd_min,
        "jd_max": jd_max,
        "jd_peak": jd_peak,
        "jd_peak_std": 0.001,
        "method": method,
        "rms": 0.012,
        "c4": 2450999.4,
        "c5": 2451000.8,
        "y_ext": 12.01,
        "warning": "The parabolic part is shorter than the uncertainty!",
        "badge_specs": [],
        "figure_json": {"data": [], "layout": {"title": {"text": "test"}}},
    }


def test_fit_export_status_labels():
    """Status reflects failure, rejection, and acceptance."""
    ok = _sample_success_entry()
    assert fit_export_status(ok, True) == "accepted"
    assert fit_export_status(ok, False) == "rejected"
    failed = {"is_fail": True, "jd_min": 1.0, "jd_max": 2.0, "error": "boom"}
    assert fit_export_status(failed, True) == "failed"


def test_mavka_extrema_download_names():
    """Export stems use the approximation method, not a MAVKA suffix."""
    assert mavka_suggested_timing_stem("NSV807.vot", "WSL") == "NSV807_WSL"
    assert mavka_suggested_timing_stem("NSV807_WSAP.dat", "WSAP") == "NSV807_WSAP"
    assert mavka_suggested_timing_stem(None, "AP") == "results_AP"
    assert mavka_extrema_export_stem("target_extrema.dat") == "target_extrema"
    assert mavka_compact_extrema_download_name("target_extrema") == "target_extrema.dat"
    assert (
        mavka_extended_extrema_download_name("target_extrema")
        == "target_extrema_mavka_extrema.zip"
    )


def test_format_compact_extrema_dat_keeps_selected_successes_only():
    """Compact export ignores rejected and failed rows."""
    rows = [
        {"is_fail": False, "jd_peak": 2451000.0, "jd_peak_std": 0.01},
        {"is_fail": True},
    ]
    include = [True, False]
    body = format_compact_extrema_dat(rows, include, extrema_mode="min")
    assert body.startswith("# MAVKA Minimum Results")
    assert "2451000.000000" in body
    assert body.count("\n") == 3


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
    )
    assert body.startswith("# MAVKA Minimum Results")
    assert "# method: WSL" in body
    assert "# PERIOD = 2.5" in body
    assert "# EPOCH = 58000.1" in body


def test_format_compact_extrema_dat_rejects_success_without_tom():
    """A kept success row with no TOM fails fast instead of writing a blank line."""
    rows = [{"is_fail": False, "jd_peak": None, "jd_peak_std": None}]
    with pytest.raises(PipeException, match="missing TOM"):
        format_compact_extrema_dat(rows, [True], extrema_mode="min")


def test_build_extended_results_tsv_uses_method_comment_not_column():
    """Method lives in a ``#`` comment; MJD and method columns are absent."""
    entry = _sample_success_entry()
    plot_files = assign_plot_filenames([entry], [True])
    tsv = build_extended_results_tsv([entry], [True], plot_files)
    lines = tsv.splitlines()
    assert lines[0] == "# Method: WSAP"
    header = lines[1]
    row = lines[2]
    assert "\tmethod\t" not in f"\t{header}\t"
    assert not header.startswith("method")
    assert "mjd_peak" not in header
    assert "mjd_interval_start" not in header
    assert "c4" in header
    assert "warning" in header
    cells = row.split("\t")
    assert cells[0] == "2451000.12345600"
    assert cells[4] == "accepted"
    assert "parabolic part" in cells[9]


@patch(
    "skvo_veb.utils.mavka.export.figure_json_to_png_bytes",
    return_value=b"PNG",
)
def test_build_extended_export_zip_contains_results_and_plots(mock_png):
    """Extended ZIP bundles TSV, README, PNG plots, and failure stubs."""
    success = _sample_success_entry()
    failed = {
        "is_fail": True,
        "jd_min": 2452000.0,
        "jd_max": 2452002.0,
        "error": "Need at least 6 points, got 2",
        "method": "WSAP",
        "badge_specs": [],
    }
    zip_bytes = build_extended_export_zip(
        [success, failed],
        [True, False],
        bundle_folder="nsv807_mavka",
        extrema_mode="min",
        period="2.5",
        epoch="58000.1",
    )
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert "nsv807_mavka/results.tsv" in names
        assert "nsv807_mavka/README.txt" in names
        readme = zf.read("nsv807_mavka/README.txt").decode("utf-8")
        assert "Period (days): 2.5" in readme
        tsv = zf.read("nsv807_mavka/results.tsv").decode("utf-8")
        assert tsv.startswith("# Method: WSAP")
        assert "mjd_peak" not in tsv.splitlines()[1]
        pngs = [n for n in names if n.endswith(".png")]
        assert len(pngs) == 1
        assert any("failed" in n and n.endswith(".txt") for n in names)
    mock_png.assert_called_once()
