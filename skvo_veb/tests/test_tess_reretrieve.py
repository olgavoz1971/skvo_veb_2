"""Tests for the pieces behind the ReRetrieve button."""

from unittest import mock

import pytest

from skvo_veb.utils import tess_lc_builder
from skvo_veb.utils.my_tools import PipeException

ROW = {'#': 3, 'mission': 'TESS Sector 14', 'year': 2019, 'author': 'SPOC', 'exptime': 120, 'target': '35119266'}


def test_fresh_retrieve_summary_names_target_sector_author_and_exptime():
    text = tess_lc_builder.fresh_retrieve_summary(ROW)
    assert 'TIC 35119266' in text
    assert 'TESS Sector 14' in text
    assert 'SPOC' in text
    assert '120 s' in text


def test_purge_requires_exactly_one_row():
    with pytest.raises(PipeException):
        tess_lc_builder.purge_cached_fits_of_selected_row([], [], {'x': 1})
    with pytest.raises(PipeException):
        tess_lc_builder.purge_cached_fits_of_selected_row([ROW, ROW], [], {'x': 1})


def test_purge_requires_search_store():
    with pytest.raises(PipeException):
        tess_lc_builder.purge_cached_fits_of_selected_row([ROW], [], None)


def test_purge_deletes_cached_fits_of_the_selected_row_index():
    fake_result = object()
    with mock.patch.object(tess_lc_builder.tess_lc_search, 'restore_search_result', return_value=fake_result), \
            mock.patch.object(tess_lc_builder.lightkurve_cache, 'purge_lightkurve_cached_fits',
                              return_value=True) as purge:
        row = tess_lc_builder.purge_cached_fits_of_selected_row([ROW], [], {'x': 1})
    purge.assert_called_once_with(fake_result, 3)
    assert row is ROW
