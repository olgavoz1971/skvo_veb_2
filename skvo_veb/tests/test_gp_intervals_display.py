"""Interval registry labels vs export (JD storage, axis-aware display)."""

from skvo_veb.utils.gp.intervals import (
    format_interval_display_pair,
    format_intervals_download,
)

JD0 = 2400000.5
JD_START = 2459000.123456
JD_END = 2459010.654321


def test_format_interval_display_pair_mjd():
    """Registry shows MJD offset when the prep plot uses MJD."""
    s, e = format_interval_display_pair(
        JD_START,
        JD_END,
        time_axis_mode="mjd",
        display_epoch=JD0,
    )
    assert s == f"{JD_START - JD0:.6f}"
    assert e == f"{JD_END - JD0:.6f}"


def test_format_intervals_download_keeps_full_jd():
    """Download/export stays absolute Julian Date."""
    body = format_intervals_download([[JD_START, JD_END]])
    assert str(JD_START) in body
    assert str(JD_END) in body
    assert "58999" not in body or str(JD_START) in body
