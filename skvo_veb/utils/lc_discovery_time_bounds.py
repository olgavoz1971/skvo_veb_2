"""Optional time-window parsing for Lightcurve Discovery catalogue search."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from astropy.time import Time

from skvo_veb.utils.lc_config import JD_TO_MJD
from skvo_veb.utils.my_tools import PipeException, safe_float

logger = logging.getLogger(__name__)

TIME_FORMAT_MJD = "mjd"
TIME_FORMAT_JD = "jd"
TIME_FORMAT_DATE = "date"


@dataclass(frozen=True)
class DiscoveryTimeBounds:
    """Optional catalogue time limits always expressed in MJD.

    Attributes:
        time_start_mjd (float, optional): Lower bound in MJD. ``None`` means no
            lower limit (include all data from the beginning).
        time_end_mjd (float, optional): Upper bound in MJD. ``None`` means no
            upper limit (include all data to the end).
    """

    time_start_mjd: float | None = None
    time_end_mjd: float | None = None


def parse_discovery_time_value(
    text: str | None,
    time_format: str | None,
    *,
    bound_kind: str,
) -> float | None:
    """Parses one optional Discovery time-bound field to MJD.

    Args:
        text (str, optional): Raw value from the UI entry field.
        time_format (str, optional): Selected format slug (``mjd``, ``jd``, ``date``).
        bound_kind (str): ``min`` for the earliest-time row or ``max`` for latest.

    Returns:
        float or None: Bound in MJD, or ``None`` when the field is blank.

    Raises:
        PipeException: When the value is non-empty but cannot be parsed.
    """
    raw = str(text or "").strip()
    if not raw:
        return None

    fmt = str(time_format or TIME_FORMAT_MJD).strip().lower()
    label = "Earliest time" if bound_kind == "min" else "Latest time"

    if fmt == TIME_FORMAT_MJD:
        value = safe_float(raw)
        if value is None:
            raise PipeException(f"{label} must be a numeric MJD.")
        return float(value)

    if fmt == TIME_FORMAT_JD:
        value = safe_float(raw)
        if value is None:
            raise PipeException(f"{label} must be a numeric JD.")
        return float(value) - JD_TO_MJD

    if fmt == TIME_FORMAT_DATE:
        try:
            instant = Time(raw, format="iso", scale="utc")
        except (ValueError, TypeError) as exc:
            raise PipeException(
                f"{label} must be a calendar date, e.g. 2015-06-01."
            ) from exc
        mjd = float(instant.mjd)
        if bound_kind == "max":
            return mjd + 1.0
        return mjd

    raise PipeException(f"Unsupported time format '{time_format}'.")


def parse_discovery_time_bounds(
    min_text: str | None,
    min_format: str | None,
    max_text: str | None,
    max_format: str | None,
) -> DiscoveryTimeBounds:
    """Parses earliest/latest Discovery UI fields into MJD bounds.

    Blank earliest time means no lower limit; blank latest time means no upper
    limit. Either bound may be set alone (one-sided window).

    Args:
        min_text (str, optional): Earliest-time entry value.
        min_format (str, optional): Earliest-time format selector value.
        max_text (str, optional): Latest-time entry value.
        max_format (str, optional): Latest-time format selector value.

    Returns:
        DiscoveryTimeBounds: Parsed limits in MJD.

    Raises:
        PipeException: When a non-empty field is invalid or min exceeds max.
    """
    time_start_mjd = parse_discovery_time_value(
        min_text,
        min_format,
        bound_kind="min",
    )
    time_end_mjd = parse_discovery_time_value(
        max_text,
        max_format,
        bound_kind="max",
    )
    if (
        time_start_mjd is not None
        and time_end_mjd is not None
        and time_start_mjd > time_end_mjd
    ):
        raise PipeException("Earliest time must not be later than latest time.")
    logger.info(
        "Discovery time bounds parsed start_mjd=%s end_mjd=%s.",
        time_start_mjd,
        time_end_mjd,
    )
    return DiscoveryTimeBounds(
        time_start_mjd=time_start_mjd,
        time_end_mjd=time_end_mjd,
    )
