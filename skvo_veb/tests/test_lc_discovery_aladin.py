"""Tests for Lightcurve Discovery Aladin helpers."""

from skvo_veb.utils.lc_discovery_aladin import (
    aladin_fov_degrees,
    aladin_marker_name,
    aladin_target_from_metadata,
    catalog_row_from_cell_clicked,
    catalog_rows_to_aladin_stars,
    find_catalog_row_by_aladin_name,
)
from skvo_veb.utils.lc_discovery_search import SEARCH_MODE_CONE


def test_catalog_rows_to_aladin_stars_uses_aladin_name():
    """Each table row becomes one Aladin marker keyed by its display name."""
    rows = [
        {
            "lc_key": "gaia:1",
            "aladin_name": "Gaia DR3 1 (G)",
            "object_name": "Gaia DR3 1",
            "filter_name": "G",
            "ra_deg": 10.0,
            "dec_deg": 20.0,
        }
    ]
    stars = catalog_rows_to_aladin_stars(rows)
    assert stars == [{"name": "Gaia DR3 1 (G)", "ra": 10.0, "dec": 20.0}]


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


def test_find_catalog_row_by_aladin_name():
    """Aladin marker names round-trip to AgGrid rows."""
    row = {
        "lc_key": "gaia:42",
        "aladin_name": "Gaia DR3 42 (G)",
        "object_name": "Gaia DR3 42",
        "filter_name": "G",
        "ra_deg": 1.0,
        "dec_deg": 2.0,
    }
    assert find_catalog_row_by_aladin_name([row], aladin_marker_name(row)) is row


def test_catalog_row_from_cell_clicked_uses_row_id():
    """AgGrid cell clicks resolve rows through ``getRowId`` / ``lc_key``."""
    row = {
        "lc_key": "gaia:42",
        "aladin_name": "Gaia DR3 42 (G)",
        "ra_deg": 1.0,
        "dec_deg": 2.0,
    }
    resolved = catalog_row_from_cell_clicked({"rowId": "gaia:42"}, [row])
    assert resolved is row
