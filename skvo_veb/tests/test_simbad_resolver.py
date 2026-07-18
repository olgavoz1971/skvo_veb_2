"""Tests for shared Simbad name resolution."""

from unittest.mock import patch

import pytest
from astropy.coordinates import SkyCoord

from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.simbad_resolver import (
    _is_connectivity_error,
    resolve_simbad_name,
)


def test_is_connectivity_error_recognises_connection_failures():
    """Network-related exceptions must not be reported as missing objects."""
    assert _is_connectivity_error(ConnectionError("Connection refused"))
    assert _is_connectivity_error(TimeoutError("timed out"))
    assert _is_connectivity_error(OSError("Network is unreachable"))


def test_is_connectivity_error_does_not_flag_unknown_object_messages():
    """Generic resolution failures without network hints stay non-connectivity."""
    assert not _is_connectivity_error(ValueError("Unknown identifier"))


def test_resolve_simbad_name_reports_connectivity_failure():
    """Offline Simbad queries must not claim the target is unknown to Simbad."""
    with patch("astroquery.simbad.Simbad.query_object", side_effect=ConnectionError("Network is unreachable")):
        with patch("astroquery.simbad.Simbad.query_objectids", side_effect=ConnectionError("Network is unreachable")):
            with patch(
                "astropy.coordinates.SkyCoord.from_name",
                side_effect=ConnectionError("Network is unreachable"),
            ):
                with pytest.raises(PipeException, match="Cannot reach Simbad or Sesame"):
                    resolve_simbad_name("V433 Aql")


def test_resolve_simbad_name_reports_not_found_when_queries_are_empty():
    """An empty Simbad response online is reported as not found, not connectivity."""
    empty_table = type("EmptyTable", (), {"__len__": lambda self: 0})()

    with patch("astroquery.simbad.Simbad.query_object", return_value=empty_table):
        with patch("astroquery.simbad.Simbad.query_objectids", return_value=empty_table):
            with patch(
                "astropy.coordinates.SkyCoord.from_name",
                side_effect=ValueError("Unknown target"),
            ):
                with pytest.raises(PipeException, match="was not found in Simbad or Sesame"):
                    resolve_simbad_name("Definitely Missing Object XYZ")


def test_resolve_simbad_name_returns_result_when_query_object_succeeds():
    """Successful Simbad rows are normalised into a resolve result."""
    from astropy.table import Table

    table = Table(
        {
            "main_id": ["V* V433 Aql"],
            "ra": [300.31486616483],
            "dec": [15.293276736829998],
        }
    )

    with patch("astroquery.simbad.Simbad.query_object", return_value=table):
        with patch("astroquery.simbad.Simbad.query_objectids", return_value=Table({"id": ["V* V433 Aql"]})):
            outcome = resolve_simbad_name("V433 Aql")

    assert outcome.main_id == "V* V433 Aql"
    assert outcome.ra_deg == pytest.approx(300.31486616483)
    assert isinstance(SkyCoord(ra=outcome.ra_deg, dec=outcome.dec_deg, unit="deg"), SkyCoord)
