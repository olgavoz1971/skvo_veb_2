"""Tests for Step 1 O-C compute, compact ToM parse, and xmgrace export."""

from __future__ import annotations

import pytest

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD
from skvo_veb.utils.oc.compute import compute_step1_oc, cycle_shifts_from_store
from skvo_veb.utils.oc.export import (
    format_oc_dat,
    oc_default_export_stem,
    oc_export_download_name,
    oc_source_filename,
)
from skvo_veb.utils.oc.tom_io import (
    parse_compact_tom_dat,
    toms_from_review_store,
    uploaded_toms_from_store,
)


def test_parse_compact_tom_dat_gp_and_mavka():
    """GP and MAVKA compact files share JD / σ columns after ``#`` comments."""
    gp_text = (
        "# GP Minimum Results\n"
        "# JD_Minimum\tJD_Std\n"
        "2458749.729000\t0.000150\n"
        "2458750.068000\t0.000200\n"
    )
    mavka_text = (
        "# MAVKA Minimum Results\n"
        "# PERIOD = 0.3389614\n"
        "# EPOCH = 57711.3539\n"
        "# JD_Minimum\tJD_Std\n"
        "2458750.068000 0.000200\n"
        "2458749.729000 0.000150\n"
    )
    gp_rows = parse_compact_tom_dat(gp_text)
    mavka_rows = parse_compact_tom_dat(mavka_text)
    assert len(gp_rows) == 2
    assert gp_rows[0]["jd_ext"] == pytest.approx(2458749.729)
    assert gp_rows[0]["sigma_jd"] == pytest.approx(0.000150)
    assert mavka_rows[0]["jd_ext"] == pytest.approx(2458749.729)
    assert [r["jd_ext"] for r in mavka_rows] == [r["jd_ext"] for r in gp_rows]


def test_parse_compact_tom_dat_rejects_empty_and_bad_line():
    """Missing rows and a one-column line fail fast."""
    with pytest.raises(ValueError, match="no ToM data"):
        parse_compact_tom_dat("# JD_Minimum\tJD_Std\n")
    with pytest.raises(ValueError, match="line 2"):
        parse_compact_tom_dat("# header\n2458749.7\n")


def test_toms_from_review_store_keep_marked_only():
    """Unchecked and failed rows are omitted; kept successes are sorted."""
    store = {
        "rows": [
            {"is_fail": False, "jd_peak": 2458750.0, "jd_peak_std": 0.001},
            {"is_fail": True},
            {"is_fail": False, "jd_peak": 2458749.0, "jd_peak_std": 0.002},
        ],
        "include": [False, False, True],
    }
    records = toms_from_review_store(store)
    assert len(records) == 1
    assert records[0]["jd_ext"] == pytest.approx(2458749.0)


def test_toms_from_review_store_empty_keep_set():
    """No kept successes is an explicit error."""
    store = {
        "rows": [{"is_fail": False, "jd_peak": 1.0, "jd_peak_std": 0.1}],
        "include": [False],
    }
    with pytest.raises(ValueError, match="Keep-marked"):
        toms_from_review_store(store)


def test_cycle_shifts_from_store_adds_display_epoch():
    """UI MJD at-times convert to absolute JD with the page epoch offset."""
    shifts = cycle_shifts_from_store(
        [{"at_mjd": 60940.0, "delta_e": 1}, {"at_mjd": 58000.0, "delta_e": -1}],
        display_epoch=DEFAULT_EPOCH_JD,
    )
    assert shifts[0][0] == pytest.approx(DEFAULT_EPOCH_JD + 58000.0)
    assert shifts[0][1] == -1
    assert shifts[1][1] == 1


def test_compute_step1_oc_and_cycle_shift():
    """O-C is residual to T0+E P0; a shift applies for jd_ext >= at_jd."""
    t0 = 2458749.0
    p0 = 1.0
    records = [
        {"jd_ext": t0 + 0.01, "sigma_jd": 0.0001},
        {"jd_ext": t0 + 1.01, "sigma_jd": 0.0002},
    ]
    plain = compute_step1_oc(records, t0_jd=t0, p0=p0, source="gp")
    assert plain["E"] == [0.0, 1.0]
    assert plain["OC"][0] == pytest.approx(0.01)
    assert plain["jd_calc"][0] == pytest.approx(t0)
    shifted = compute_step1_oc(
        records,
        t0_jd=t0,
        p0=p0,
        cycle_shifts=[(t0 + 0.5, 1)],
        source="mavka",
    )
    assert shifted["E"] == [0.0, 2.0]
    assert shifted["OC"][1] == pytest.approx(t0 + 1.01 - (t0 + 2.0 * p0))


def test_format_oc_dat_xmgrace_comments():
    """Export comments start with ``#`` including the column-name line."""
    payload = compute_step1_oc(
        [{"jd_ext": 2458749.01, "sigma_jd": 1.5e-4}],
        t0_jd=2458749.0,
        p0=1.0,
        cycle_shifts=[(2458740.0, 1)],
        source="upload",
    )
    body = format_oc_dat(payload)
    lines = body.splitlines()
    assert lines[0].startswith("# oc_tool:")
    assert "# source: upload" in body
    assert "# cycle_shift: at_jd=" in body
    header = [line for line in lines if line.startswith("# cycle_number")]
    assert header
    data = [line for line in lines if line and not line.startswith("#")]
    assert len(data) == 1
    cols = data[0].split()
    assert cols[0] == "1"
    assert len(cols) == 4
    assert cols[3] == f"{2458749.01:.8f}"
    assert oc_export_download_name("results_oc.dat") == "results_oc.dat"


def test_oc_default_export_stem_from_source_filename():
    """O-C stem follows the ToM-source file, not a later light-curve upload."""
    assert oc_default_export_stem("NSV_807_sector_97.vot") == "NSV_807_sector_97_oc"
    assert oc_default_export_stem("timings_oc.dat") == "timings_oc"
    assert oc_default_export_stem(None) == "results_oc"
    assert (
        oc_source_filename(
            "gp",
            gp_store={"source_filename": "old.vot"},
            mavka_store={"source_filename": "new.vot"},
        )
        == "old.vot"
    )


def test_uploaded_toms_from_store_requires_filename_payload():
    """Legacy list payloads fail fast; dict payloads return records."""
    rows = [{"jd_ext": 1.0, "sigma_jd": 0.1}]
    assert uploaded_toms_from_store({"filename": "a.dat", "records": rows}) == rows
    with pytest.raises(ValueError, match="source filename"):
        uploaded_toms_from_store(rows)


def test_compute_step1_oc_rejects_bad_period():
    """Non-positive P0 fails fast."""
    with pytest.raises(ValueError, match="P0"):
        compute_step1_oc(
            [{"jd_ext": 1.0, "sigma_jd": 0.1}],
            t0_jd=1.0,
            p0=0.0,
            source="gp",
        )
