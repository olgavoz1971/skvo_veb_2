"""Tests for removing the cached sector list of one object."""

from unittest import mock

import pytest

from skvo_veb.utils import tess_cache, tess_lc_search


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Point the TESS cache at a temporary directory."""
    monkeypatch.setenv('TESS_CACHE_DIR', str(tmp_path))
    return tmp_path


def test_delete_cached_search_removes_saved_sector_list(cache_dir):
    tess_cache.save({'rows': 3}, tess_lc_search.CACHE_PREFIX, native_id='TIC:123')
    assert tess_cache.load(tess_lc_search.CACHE_PREFIX, native_id='TIC:123') is not None

    assert tess_lc_search.delete_cached_search('TIC:123') is True
    assert tess_cache.load(tess_lc_search.CACHE_PREFIX, native_id='TIC:123') is None


def test_delete_cached_search_reports_nothing_cached(cache_dir):
    assert tess_lc_search.delete_cached_search('TIC:999') is False


def test_delete_cached_search_keeps_other_objects(cache_dir):
    tess_cache.save({'rows': 1}, tess_lc_search.CACHE_PREFIX, native_id='TIC:1')
    tess_cache.save({'rows': 2}, tess_lc_search.CACHE_PREFIX, native_id='TIC:2')

    tess_lc_search.delete_cached_search('TIC:1')

    assert tess_cache.load(tess_lc_search.CACHE_PREFIX, native_id='TIC:2') == {'rows': 2}


def test_resolve_native_id_remembers_answer_and_skips_second_mast_query(cache_dir):
    with mock.patch.object(
        tess_lc_search, '_resolve_native_id_from_mast', return_value='TIC:42'
    ) as from_mast:
        first = tess_lc_search.resolve_native_id('  Some   Star ', radius=5.0)
        second = tess_lc_search.resolve_native_id('some star', radius=5.0)
    assert first == second == 'TIC:42'
    assert from_mast.call_count == 1


def test_native_id_lookup_is_keyed_by_radius_and_mode(cache_dir):
    with mock.patch.object(
        tess_lc_search, '_resolve_native_id_from_mast', side_effect=['TIC:1', 'TIC:2']
    ):
        a = tess_lc_search.resolve_native_id('star', radius=5.0)
        b = tess_lc_search.resolve_native_id('star', radius=None)
    assert (a, b) == ('TIC:1', 'TIC:2')


def test_delete_cached_native_id_forces_new_mast_query(cache_dir):
    with mock.patch.object(
        tess_lc_search, '_resolve_native_id_from_mast', side_effect=['TIC:1', 'TIC:2']
    ):
        assert tess_lc_search.resolve_native_id('star') == 'TIC:1'
        assert tess_lc_search.delete_cached_native_id('star') is True
        assert tess_lc_search.resolve_native_id('star') == 'TIC:2'


def test_resolve_native_id_parses_tic_without_mast_query():
    with mock.patch.object(tess_lc_search.lk, 'search_lightcurve') as search:
        assert tess_lc_search.resolve_native_id('TIC 159717514') == 'TIC:159717514'
    search.assert_not_called()
