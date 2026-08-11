"""JD interval list parsing for the GP O-C page."""

import logging

from skvo_veb.utils.lc_config import TIME_AXIS_DATE, normalize_time_axis_mode
from skvo_veb.utils.lc_figure import absolute_jd_to_plot_x

logger = logging.getLogger(__name__)


def load_intervals(file_obj):
    """Load two-column JD interval pairs from a text stream.

    Skips blank lines and lines starting with ``#``. Each data line must contain
    exactly two floats: interval start and end (Julian Date).

    Args:
        file_obj: Text or binary stream opened for reading.

    Returns:
        list: ``[[jd_start, jd_end], ...]`` sorted by start time is left to callers.
    """
    logger.info("Loading intervals from file_obj...")
    result = []
    for line in file_obj:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        a, b = map(float, line.split())
        result.append([a, b])
    return result


def format_interval_display_pair(
    jd_start: float,
    jd_end: float,
    *,
    time_axis_mode: str,
    display_epoch: float,
    timescale: str | None = None,
) -> tuple[str, str]:
    """Formats one interval for the registry using the prep plot time axis.

    Intervals are always stored as absolute Julian Date; only the UI label
    follows ``gp_time_axis_switch`` (MJD offset or calendar date).

    Args:
        jd_start (float): Interval start in absolute JD.
        jd_end (float): Interval end in absolute JD.
        time_axis_mode (str): ``mjd`` or ``date`` (same as prep plot).
        display_epoch (float): MJD reference subtracted on the MJD axis.
        timescale (str, optional): ``TIMESYS/@timescale`` for date mode.

    Returns:
        tuple[str, str]: ``(start_label, end_label)`` for display.
    """
    mode = normalize_time_axis_mode(time_axis_mode)
    x0 = absolute_jd_to_plot_x(
        jd_start, mode, display_epoch, timescale=timescale
    )
    x1 = absolute_jd_to_plot_x(
        jd_end, mode, display_epoch, timescale=timescale
    )
    if mode == TIME_AXIS_DATE:
        return (_format_plot_date_label(x0), _format_plot_date_label(x1))
    return (f"{float(x0):.6f}", f"{float(x1):.6f}")


def _format_plot_date_label(value) -> str:
    """Turns a Plotly calendar x value into a compact date string.

    Args:
        value: ``datetime.datetime`` or parseable date string.

    Returns:
        str: ISO-like date label for the registry row.
    """
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def format_intervals_download(intervals):
    """Format interval list for export (matches GP page download layout).

    Args:
        intervals (list): List of ``[start_jd, end_jd]`` pairs.

    Returns:
        str: File body with header comment and whitespace-separated columns.
    """
    content = "# Interval_Start  Interval_End\n"
    for start, end in intervals:
        content += f"{start:<20} {end:<20}\n"
    return content
