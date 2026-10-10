"""Tests for Lightcurve Discovery Aladin and selection helpers."""

import pytest

from skvo_veb.utils.lc_discovery_aladin import (
    aladin_fov_degrees,
    aladin_marker_name,
    aladin_target_from_metadata,
    catalog_rows_to_aladin_stars,
    rows_for_source,
    selection_after_map_click,
)
from skvo_veb.utils.lc_discovery_search import SEARCH_MODE_CONE


def _row(lc_key, object_name, ra=10.0, dec=-5.0):
    """Builds a minimal catalogue row dict for tests."""
    return {
        "lc_key": lc_key,
        "object_name": object_name,
        "ra_deg": ra,
        "dec_deg": dec,
    }


TESS_A = _row("tess:a", "TIC 1")
TESS_B = _row("tess:b", "TIC 1")
GAIA_G = _row("gaia:g", "Gaia DR3 1", 1.0, 2.0)
GAIA_ONE = _row("gaia:one", "Gaia DR3 2", 3.0, 4.0)
ROWS = [TESS_A, TESS_B, GAIA_G, GAIA_ONE]


def test_marker_name_is_object_name_not_lc_key():
    """The sky source identity is object_name, never lc_key."""
    assert aladin_marker_name(TESS_A) == "TIC 1"
    with pytest.raises(ValueError):
        aladin_marker_name({"lc_key": "x"})


def test_one_marker_per_source():
    """Products of one source share a single marker."""
    stars = catalog_rows_to_aladin_stars(ROWS)
    assert [star["name"] for star in stars] == ["TIC 1", "Gaia DR3 1", "Gaia DR3 2"]
    assert stars[0] == {"name": "TIC 1", "ra": 10.0, "dec": -5.0}


def test_rows_for_source_and_first_index():
    """Rows group by object_name in table order."""
    assert rows_for_source(ROWS, "TIC 1") == [TESS_A, TESS_B]
    assert rows_for_source(ROWS, "nope") == []
    assert rows_for_source(ROWS, None) == []


def test_map_click_keeps_selection_of_same_source():
    """A selected row of the clicked source stays selected."""
    assert selection_after_map_click(ROWS, "TIC 1", [TESS_B]) is None


def test_map_click_selects_first_row_of_source():
    """A clicked source selects its first row, also for multi-row sources."""
    assert selection_after_map_click(ROWS, "TIC 1", None) == [TESS_A]
    assert selection_after_map_click(ROWS, "TIC 1", [GAIA_G]) == [TESS_A]
    assert selection_after_map_click(ROWS, "Gaia DR3 2", [TESS_A]) == [GAIA_ONE]


def test_map_click_unknown_source_fails():
    """A source without rows raises instead of guessing."""
    with pytest.raises(ValueError):
        selection_after_map_click(ROWS, "nope", None)


def test_aladin_target_prefers_search_centre():
    """Cone-search metadata supplies the Aladin target centre."""
    metadata = {"centre_ra_deg": 300.0, "centre_dec_deg": 15.0}
    target = aladin_target_from_metadata(metadata, [])
    assert "300" not in target  # sexagesimal, not decimal
    assert "+" in target or "-" in target


def test_aladin_fov_uses_cone_radius_diameter():
    """Cone searches map UI radius to an Aladin FOV diameter in degrees."""
    metadata = {
        "search_mode": SEARCH_MODE_CONE,
        "radius_value": 2.0,
        "radius_unit": "arcmin",
    }
    assert aladin_fov_degrees(metadata, []) == 2.0 * 120.0 / 3600.0
