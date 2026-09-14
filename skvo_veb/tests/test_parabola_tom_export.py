"""Tests for parabola ToM compact export stems."""

from skvo_veb.utils.parabola_tom.export import (
    format_compact_extrema_dat,
    parabola_compact_extrema_download_name,
    parabola_extrema_export_stem,
    parabola_suggested_timing_stem,
)


def test_parabola_timing_stems():
    """Export stem is ``{lc}_parabola`` and is not duplicated."""
    assert parabola_suggested_timing_stem("NSV807.vot") == "NSV807_parabola"
    assert parabola_suggested_timing_stem("NSV807_parabola.dat") == "NSV807_parabola"
    assert parabola_suggested_timing_stem(None) == "results_parabola"
    assert parabola_extrema_export_stem("target.dat") == "target"
    assert parabola_compact_extrema_download_name("target") == "target.dat"


def test_format_compact_extrema_dat_keeps_selected_successes_only():
    """Compact export ignores rejected and failed rows."""
    rows = [
        {"is_fail": False, "jd_peak": 2451000.0, "jd_peak_std": 0.01},
        {"is_fail": True},
        {"is_fail": False, "jd_peak": 2451001.0, "jd_peak_std": 0.02},
    ]
    include = [True, False, False]
    body = format_compact_extrema_dat(
        rows, include, extrema_mode="max", use_weights=True, max_half_width_d=0.05
    )
    assert "# Parabola Maximum Results" in body
    assert "# weights: on" in body
    assert "# max_half_width_d: 0.05" in body
    assert "2451000.000000" in body
    assert "2451001.000000" not in body
