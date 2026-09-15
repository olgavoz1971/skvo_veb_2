"""Tests for the shared lightcurve session cache."""

import pytest

from skvo_veb.utils.lc_session_cache import (
    compose_lc_cache_key,
    has_cached_lc,
    read_serialized_lc,
    reset_lc_user_cache_for_tests,
    write_serialized_lc,
)
from skvo_veb.utils.my_tools import PipeException


@pytest.fixture
def session_cache_dir(tmp_path, monkeypatch):
    """Points the session cache at a temporary directory."""
    monkeypatch.setenv('USER_CACHE_DIR', str(tmp_path))
    reset_lc_user_cache_for_tests()
    yield tmp_path
    reset_lc_user_cache_for_tests()


def test_namespaced_write_round_trip(session_cache_dir):
    """A page namespace stores and loads a payload without leaking to others."""
    write_serialized_lc('lc_discovery', 'tab-a', '{"ok": 1}')
    assert has_cached_lc('lc_discovery', 'tab-a')
    assert read_serialized_lc('lc_discovery', 'tab-a') == '{"ok": 1}'
    assert not has_cached_lc('lc_processor', 'tab-a')


def test_tess_namespace_round_trip(session_cache_dir):
    """TESS archive uses the same namespaced key as other Goal 1 pages."""
    from skvo_veb.utils.lc_session_cache import get_lc_user_cache

    write_serialized_lc('tess_lc_srv', 'tab-tess', 'curve-json')
    assert read_serialized_lc('tess_lc_srv', 'tab-tess') == 'curve-json'
    cache = get_lc_user_cache()
    assert cache.get(compose_lc_cache_key('tess_lc_srv', 'tab-tess')) == 'curve-json'
    assert cache.get('tab-tess_data') is None


def test_missing_entry_fails_fast(session_cache_dir):
    """A missing session must not invent a lightcurve."""
    assert not has_cached_lc('tess_lc_srv', 'missing')
    with pytest.raises(PipeException, match='Session cache is empty'):
        read_serialized_lc('tess_lc_srv', 'missing')
