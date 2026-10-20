"""Tests for Step 1 O-C compute, compact ToM parse, and xmgrace export."""

from __future__ import annotations

import pytest

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD
from skvo_veb.utils.oc.compute import (
    absolute_jd_to_display_mjd,
    at_mjd_from_oc_click,
    compute_step1_oc,
    cycle_shifts_from_store,
)
from skvo_veb.utils.oc.export import (
    format_oc_dat,
    oc_default_export_stem,
    oc_default_export_stem_for_source,
    oc_export_download_name,
    oc_source_filename,
)
from skvo_veb.utils.oc.tom_io import (
    parse_compact_tom_contents,
    parse_compact_tom_dat,
    toms_from_review_store,
    uploaded_toms_from_store,
)


def test_parse_compact_tom_dat_gp_and_mavka():
    """GP and MAVKA compact files share JD / σ columns after ``#`` comments."""
    gp_text = (
        "# GP Minimum Results\n"
        "# scale_limit: 0=ok 1=length_scale_min 2=length_scale_max\n"
        "# JD_Minimum\tJD_Std\tscale_limit\n"
        "2458749.729000\t0.000150\t1\n"
        "2458750.068000\t0.000200\t0\n"
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
    _, gp_meta = parse_compact_tom_contents(gp_text)
    _, mavka_meta = parse_compact_tom_contents(mavka_text)
    assert gp_meta[0] == "# GP Minimum Results"
    assert "# PERIOD = 0.3389614" in mavka_meta


def test_parse_compact_tom_dat_rejects_empty_and_bad_line():
    """Missing rows and a one-column line fail fast."""
    with pytest.raises(ValueError, match="no ToM data"):
        parse_compact_tom_dat("# JD_Minimum\tJD_Std\n")
    with pytest.raises(ValueError, match="line 2"):
        parse_compact_tom_dat("# header\n2458749.7\n")


def test_parse_compact_tom_nan_sigma_is_json_safe():
    """Processor rough ToMs with ``nan`` σ store as ``None`` and survive Plot."""
    import json

    from dash._utils import to_json

    from skvo_veb.utils.oc.tom_io import records_to_arrays

    text = (
        "# Rough Maximum times\n"
        "# JD_Maximum\n"
        "# JD_Std\n"
        "2458079.9442799999  nan\n"
        "2458079.9737935960  nan\n"
    )
    records, _meta = parse_compact_tom_contents(text)
    assert records[0]["sigma_jd"] is None
    restored = json.loads(to_json({"filename": "rough.dat", "records": records}))
    assert restored["records"][0]["sigma_jd"] is None
    _jd, sigma = records_to_arrays(restored["records"])
    assert sigma[0] != sigma[0]  # NaN for maths
    payload = compute_step1_oc(
        restored["records"],
        t0_jd=2458079.9,
        p0=0.3,
        source="upload",
    )
    assert payload["sigma_jd"][0] is None
    assert all(s is None for s in payload["sigma_jd"])


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


def test_format_oc_dat_copies_uploaded_tom_comments():
    """O-C export keeps every ``#`` line from the uploaded ToM file."""
    payload = compute_step1_oc(
        [{"jd_ext": 2458749.01, "sigma_jd": 1.5e-4}],
        t0_jd=2458749.0,
        p0=1.0,
        source="upload",
    )
    payload["source_metadata_lines"] = [
        "# MAVKA Minimum Results",
        "# method: WSL",
        "# PERIOD = 0.33",
        "# JD_Minimum\tJD_Std",
    ]
    body = format_oc_dat(payload)
    assert "# source: upload" in body
    assert "# MAVKA Minimum Results" in body
    assert "# method: WSL" in body
    assert "# PERIOD = 0.33" in body
    assert "# JD_Minimum\tJD_Std" in body


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
    assert (
        oc_default_export_stem_for_source(
            "gp",
            gp_store={"source_filename": "NSV807.vot"},
        )
        == "NSV807_gp_oc"
    )
    assert (
        oc_default_export_stem_for_source(
            "mavka",
            mavka_store={"source_filename": "NSV807.vot", "method": "WSL"},
        )
        == "NSV807_WSL_oc"
    )
    assert (
        oc_default_export_stem_for_source(
            "parabola",
            parabola_store={"source_filename": "NSV807.vot"},
        )
        == "NSV807_parabola_oc"
    )
    assert (
        oc_default_export_stem_for_source(
            "upload",
            uploaded={"filename": "R_TESS_min_all.dat"},
        )
        == "R_TESS_min_all_oc"
    )


def test_uploaded_toms_from_store_requires_filename_payload():
    """Legacy list payloads fail fast; dict payloads return records."""
    rows = [{"jd_ext": 1.0, "sigma_jd": 0.1}]
    assert uploaded_toms_from_store({"filename": "a.dat", "records": rows}) == rows
    with pytest.raises(ValueError, match="source filename"):
        uploaded_toms_from_store(rows)


def test_oc_figure_title_hover_and_top_axis_use_mjd():
    """Card title names the source; the figure itself has no title or annotation."""
    from skvo_veb.pages.gp_for_oc import _build_oc_figure, _oc_source_title
    from skvo_veb.components.extrema_modeller_appearance import page_time_label
    from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD as jd0

    scale = page_time_label()
    assert _oc_source_title("gp") == "O-C (GP)"
    assert _oc_source_title("mavka") == "O-C (MAVKA)"
    assert _oc_source_title("parabola") == "O-C (parabola)"
    assert _oc_source_title("upload") == "O-C (upload)"
    payload = compute_step1_oc(
        [{"jd_ext": 2458749.729, "sigma_jd": 1.5e-4}],
        t0_jd=2458749.0,
        p0=1.0,
        source="gp",
    )
    fig = _build_oc_figure(payload)
    title_text = fig.layout.title.text if fig.layout.title else None
    assert title_text in (None, "")
    assert fig.layout.annotations in ((), None) or len(fig.layout.annotations) == 0
    assert fig.layout.xaxis2.title.text == f"Calculated {scale}"
    assert fig.layout.xaxis2.matches == "x"
    hover = fig.data[0].hovertemplate
    assert f"{scale} obs" in hover
    assert "jd_obs" not in hover
    mjd_obs = fig.data[0].customdata[0][1]
    assert mjd_obs == pytest.approx(2458749.729 - jd0)
    dummy_on_x2 = [tr for tr in fig.data if getattr(tr, "xaxis", None) == "x2"]
    assert dummy_on_x2 == []


def test_absolute_jd_to_display_mjd():
    """Display MJD is absolute JD minus the page epoch offset."""
    assert absolute_jd_to_display_mjd(2458749.729, DEFAULT_EPOCH_JD) == pytest.approx(
        2458749.729 - DEFAULT_EPOCH_JD
    )


def test_at_mjd_from_oc_click_reads_observed_mjd():
    """Click customdata column 1 is observed MJD for the At ≥ field."""
    click = {"points": [{"customdata": [12.0, 58749.729, 58749.0, 1e-4, 8.6]}]}
    assert at_mjd_from_oc_click(click) == pytest.approx(58749.729)


def test_at_mjd_from_oc_click_from_e_and_residual():
    """Without customdata, observed MJD is T0 + E×P0 + (O-C), then offset."""
    payload = {
        "t0_jd": 2458749.0,
        "p0": 1.0,
    }
    click = {"points": [{"x": 2.0, "y": 0.003}]}
    assert at_mjd_from_oc_click(
        click, payload, display_epoch=DEFAULT_EPOCH_JD
    ) == pytest.approx(2458749.0 + 2.0 + 0.003 - DEFAULT_EPOCH_JD)


def test_at_mjd_from_oc_click_rejects_empty():
    """A click without a point fails fast."""
    from skvo_veb.components.extrema_modeller_appearance import page_time_label

    with pytest.raises(ValueError, match="No O-C point"):
        at_mjd_from_oc_click(None)
    with pytest.raises(ValueError, match=f"missing observed {page_time_label()}"):
        at_mjd_from_oc_click({"points": [{"customdata": [1.0]}]})


def test_compute_step1_oc_rejects_bad_period():
    """Non-positive P0 fails fast."""
    with pytest.raises(ValueError, match="P0"):
        compute_step1_oc(
            [{"jd_ext": 1.0, "sigma_jd": 0.1}],
            t0_jd=1.0,
            p0=0.0,
            source="gp",
        )


def _rows(*pairs):
    """Builds ToM records from ``(jd_ext, sigma_jd)`` pairs."""
    return [{"jd_ext": jd, "sigma_jd": sigma} for jd, sigma in pairs]


def test_append_merges_sorts_tags_and_skips_exact_duplicates():
    """Appended ToMs are merged, tagged by file, sorted; exact duplicates skipped."""
    from skvo_veb.utils.oc.tom_io import append_upload_store, new_upload_store

    first = new_upload_store("a.dat", _rows((10.0, 0.1), (30.0, 0.1)), ["# a"])
    store, added, skipped = append_upload_store(
        first, "b.dat", _rows((20.0, 0.2), (30.0, 0.1), (30.0, 0.3)), ["# b"]
    )
    assert (added, skipped) == (2, 1)
    assert [row["jd_ext"] for row in store["records"]] == [10.0, 20.0, 30.0, 30.0]
    assert [row["source"] for row in store["records"]] == ["a.dat", "b.dat", "a.dat", "b.dat"]
    assert store["filename"] == "merged"
    assert store["metadata_lines"] == [
        "# ---- source file: a.dat ----",
        "# a",
        "# ---- source file: b.dat ----",
        "# b",
    ]


def test_append_to_nothing_equals_new_load_and_all_duplicates_change_nothing():
    """First append starts the list; re-appending the same rows adds nothing."""
    from skvo_veb.utils.oc.tom_io import append_upload_store, upload_summary_text

    store, added, skipped = append_upload_store(None, "a.dat", _rows((1.0, None)), [])
    assert (added, skipped, store["filename"]) == (1, 0, "a.dat")
    again, added, skipped = append_upload_store(store, "b.dat", _rows((1.0, None)), [])
    assert (added, skipped) == (0, 1)
    assert [entry["name"] for entry in again["files"]] == ["a.dat"]
    assert upload_summary_text(again) == "a.dat"


def test_append_rejects_legacy_list_store():
    """A store without file names cannot be extended silently."""
    from skvo_veb.utils.oc.tom_io import append_upload_store

    with pytest.raises(ValueError, match="old format"):
        append_upload_store(_rows((1.0, 0.1)), "b.dat", _rows((2.0, 0.1)), [])


def test_merged_store_names_export_merged_oc_and_summary():
    """Merged timings export as merged_oc and are summarised by count."""
    from skvo_veb.utils.oc.tom_io import append_upload_store, new_upload_store, upload_summary_text

    store, _, _ = append_upload_store(
        new_upload_store("a.dat", _rows((1.0, 0.1)), []), "b.dat", _rows((2.0, 0.1)), []
    )
    assert oc_default_export_stem_for_source("upload", uploaded=store) == "merged_oc"
    assert upload_summary_text(store) == "2 files, 2 ToMs"


def test_compute_carries_point_source_and_figure_colours_sources():
    """O-C points are coloured per source with the same marker size."""
    from skvo_veb.pages.gp_for_oc import OC_SOURCE_COLOURS, _build_oc_figure

    records = [
        {"jd_ext": 2458749.0, "sigma_jd": 1e-4, "source": "a.dat"},
        {"jd_ext": 2458750.02, "sigma_jd": None, "source": "b.dat"},
        {"jd_ext": 2458751.0, "sigma_jd": 1e-4, "source": "a.dat"},
    ]
    payload = compute_step1_oc(records, t0_jd=2458749.0, p0=1.0, source="upload")
    assert payload["point_source"] == ["a.dat", "b.dat", "a.dat"]
    fig = _build_oc_figure(payload)
    colours = {trace.name: trace.marker.color for trace in fig.data}
    assert colours == {"a.dat": OC_SOURCE_COLOURS[0], "b.dat": OC_SOURCE_COLOURS[1]}
    assert all(trace.marker.size == 8 for trace in fig.data)
    assert fig.layout.showlegend is False


def test_single_source_figure_keeps_default_colour_and_no_legend():
    """One source plots exactly as before: default colour, no legend."""
    from skvo_veb.pages.gp_for_oc import _build_oc_figure

    records = [{"jd_ext": 2458749.0, "sigma_jd": 1e-4, "source": "a.dat"}]
    fig = _build_oc_figure(compute_step1_oc(records, t0_jd=2458749.0, p0=1.0, source="upload"))
    assert fig.layout.showlegend is False
    assert all(trace.marker.color is None for trace in fig.data)
    assert [trace.name for trace in fig.data] == ["O-C"]


def _upload_contents(text: str) -> str:
    """Encodes text like a ``dcc.Upload`` data URL."""
    import base64

    return "data:text/plain;base64," + base64.b64encode(text.encode()).decode()


def test_upload_callback_merges_several_files_and_names_bad_file():
    """Several files merge into one store; a bad file stops the whole batch."""
    from skvo_veb.pages.gp_for_oc import upload_oc_toms

    a = _upload_contents("2458750.0 0.001\n2458751.0 0.001\n")
    b = _upload_contents("2458751.0 0.001\n2458752.0 0.001\n")
    out = upload_oc_toms([a, b], ["a.dat", "b.dat"], False, None)
    store = out[0]
    assert store["filename"] == "merged"
    assert [r["jd_ext"] for r in store["records"]] == [
        2458750.0,
        2458751.0,
        2458752.0,
    ]
    assert out[5] is not None  # one duplicate skipped

    bad = _upload_contents("not a timing file\n")
    out = upload_oc_toms([a, bad], ["a.dat", "bad.dat"], False, None)
    assert out[0] is dash_no_update()
    assert "bad.dat" in str(out[2])


def dash_no_update():
    """Returns Dash's ``no_update`` sentinel."""
    from dash import no_update

    return no_update
