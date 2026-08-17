"""Tests for GP extrema compact and extended export."""

from __future__ import annotations

import io
import zipfile
from unittest.mock import patch

from skvo_veb.utils.gp.export import (
    gp_compact_extrema_download_name,
    gp_extended_extrema_download_name,
    gp_extrema_export_stem,
)
from skvo_veb.utils.gp.results_export import (
    assign_plot_filenames,
    build_extended_export_zip,
    build_extended_results_tsv,
    figure_json_to_png_bytes,
    fit_export_status,
    format_compact_extrema_dat,
    jd_to_display_mjd,
)
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD


def _sample_success_entry(
    *,
    jd_peak: float = 2451000.123456,
    jd_min: float = 2450999.0,
    jd_max: float = 2451001.0,
    kernel_type: str = "matern",
) -> dict:
    """Builds one successful serialised review row for export tests."""
    return {
        "is_fail": False,
        "jd_min": jd_min,
        "jd_max": jd_max,
        "jd_peak": jd_peak,
        "jd_peak_std": 0.001,
        "kernel_type": kernel_type,
        "length_scale": 0.12,
        "amplitude": 1.5,
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


def test_assign_plot_filenames_uses_png():
    """Plot paths use PNG for successful fits."""
    entry = _sample_success_entry()
    paths = assign_plot_filenames([entry], [True])
    assert paths[0].endswith(".png")


def test_build_extended_results_tsv_includes_interval_mjd_and_fit_params():
    """Extended table carries MJD interval bounds and GP hyper-parameters."""
    entry = _sample_success_entry()
    plot_files = assign_plot_filenames([entry], [True])
    tsv = build_extended_results_tsv([entry], [True], plot_files)
    header, row = tsv.strip().splitlines()
    assert "mjd_interval_start" in header
    assert "length_scale" in header
    cells = row.split("\t")
    assert cells[0] == f"{jd_to_display_mjd(entry['jd_peak'], DEFAULT_EPOCH_JD):.2f}"
    assert cells[1] == "50998.50000000"
    assert cells[2] == "51000.50000000"
    assert cells[7] == "accepted"
    assert cells[8] == "matern"
    assert cells[9] == "0.12000000"


def test_format_compact_extrema_dat_keeps_selected_successes_only():
    """Compact export ignores rejected and failed rows."""
    rows = [
        {"is_fail": False, "jd_peak": 2451000.0, "jd_peak_std": 0.01},
        {"is_fail": True},
    ]
    include = [True, False]
    body = format_compact_extrema_dat(rows, include, extrema_mode="max")
    assert "2451000.000000" in body
    assert body.count("\n") == 3  # header lines + one data row


def test_gp_extrema_download_names():
    """Export stems normalise legacy extensions for dat and zip outputs."""
    assert gp_extrema_export_stem("target_extrema.dat") == "target_extrema"
    assert gp_compact_extrema_download_name("target_extrema") == "target_extrema.dat"
    assert gp_extended_extrema_download_name("target_extrema") == "target_extrema_gp_extrema.zip"


@patch("plotly.graph_objects.Figure.to_image", return_value=b"PNG")
def test_figure_json_to_png_bytes_uses_kaleido_defaults(mock_to_image):
    """Extended export PNGs use Kaleido defaults without upscaling."""
    figure_json_to_png_bytes({"data": [], "layout": {"height": 400}})
    mock_to_image.assert_called_once_with(format="png", engine="kaleido")


@patch(
    "skvo_veb.utils.gp.results_export.figure_json_to_png_bytes",
    return_value=b"PNG",
)
def test_build_extended_export_zip_contains_results_and_plots(mock_png):
    """Extended ZIP bundles TSV, README, PNG plots, and failure stubs."""
    success = _sample_success_entry()
    failed = {
        "is_fail": True,
        "jd_min": 2452000.0,
        "jd_max": 2452002.0,
        "error": "Pipeline failed",
        "badge_specs": [],
    }
    entries = [success, failed]
    include = [False, True]
    payload = build_extended_export_zip(
        entries,
        include,
        bundle_folder="bundle",
        extrema_mode="max",
    )
    mock_png.assert_called_once()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
        assert "bundle/results.tsv" in names
        assert "bundle/README.txt" in names
        plot_names = [n for n in names if n.startswith("bundle/plots/")]
        assert len(plot_names) == 2
        assert any(n.endswith(".png") for n in plot_names)
        assert any(n.endswith("_failed.txt") for n in plot_names)
        tsv = zf.read("bundle/results.tsv").decode("utf-8")
        assert "rejected" in tsv
        assert "failed" in tsv
