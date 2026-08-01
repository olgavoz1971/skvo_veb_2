"""JD interval list parsing for the GP O-C page."""

import logging

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
