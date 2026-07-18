"""Tests for Discovery optional time-bound parsing."""

import pytest

from skvo_veb.utils.lc_config import JD_TO_MJD
from skvo_veb.utils.lc_discovery_time_bounds import (
    DiscoveryTimeBounds,
    parse_discovery_time_bounds,
    parse_discovery_time_value,
)
from skvo_veb.utils.my_tools import PipeException


def test_blank_time_bounds_are_open():
    """Empty earliest and latest fields mean unbounded search window."""
    bounds = parse_discovery_time_bounds("", "mjd", None, "mjd")
    assert bounds == DiscoveryTimeBounds(time_start_mjd=None, time_end_mjd=None)


def test_parse_mjd_and_jd_formats():
    """MJD and JD inputs are normalised to MJD for provider calls."""
    start = parse_discovery_time_value("57123.5", "mjd", bound_kind="min")
    end = parse_discovery_time_value("2457123.5", "jd", bound_kind="max")
    assert start == pytest.approx(57123.5)
    assert end == pytest.approx(2457123.5 - JD_TO_MJD)


def test_parse_date_format_to_mjd():
    """Calendar dates convert to MJD with an inclusive latest-day upper bound."""
    from astropy.time import Time

    start = parse_discovery_time_value("2015-06-01", "date", bound_kind="min")
    end = parse_discovery_time_value("2015-06-01", "date", bound_kind="max")
    expected = float(Time("2015-06-01", format="iso", scale="utc").mjd)
    assert start == pytest.approx(expected)
    assert end == pytest.approx(expected + 1.0)


def test_min_must_not_exceed_max():
    """Invalid windows raise a user-facing validation error."""
    with pytest.raises(PipeException, match="Earliest time must not be later"):
        parse_discovery_time_bounds("58000", "mjd", "57000", "mjd")
