"""Tests for reading coordinate strings in the TESS cache layer."""

import pytest

from skvo_veb.utils import tess_cache


@pytest.mark.parametrize('text', [
    '23:05:22.84 +47:40:34.72',
    '23 05 22.84 +47 40 34.72',
    '23h05m22.84s +47d40m34.72s',
])
def test_sexagesimal_ra_is_read_as_hours(text):
    coord = tess_cache.extract_coords(text)
    assert coord.ra.deg == pytest.approx(346.345167, abs=1e-5)
    assert coord.dec.deg == pytest.approx(47.676311, abs=1e-5)


def test_decimal_pair_is_read_as_degrees():
    coord = tess_cache.extract_coords('85.482810 -23.142525')
    assert coord.ra.deg == pytest.approx(85.48281)
    assert coord.dec.deg == pytest.approx(-23.142525)


def test_resolve_format_matches_lightkurve_cutout_file_name_position():
    """The Resolve output must land on the position stored in the cutout file name."""
    from skvo_veb.utils import lightkurve_cache
    import astropy.units as u
    from astropy.coordinates import SkyCoord

    coord = tess_cache.extract_coords('23:05:22.84 +47:40:34.72')
    file_coord = SkyCoord(ra=346.345167 * u.deg, dec=47.676311 * u.deg)
    assert coord.separation(file_coord).deg < lightkurve_cache.TESSCUT_MATCH_TOLERANCE_DEG
