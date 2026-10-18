"""Tests for Discovery fetch helpers used by the Light curve tab."""

from __future__ import annotations

import pytest

from skvo_veb.utils.lc_discovery_load import fetch_discovery_votable_bytes
from skvo_veb.utils.lc_session_cache import reset_lc_user_cache_for_tests
from skvo_veb.utils.my_tools import PipeException


@pytest.fixture(autouse=True)
def _isolated_user_cache(tmp_path, monkeypatch):
    """Points the shared server cache at a temporary directory for each test."""
    monkeypatch.setenv("USER_CACHE_DIR", str(tmp_path))
    reset_lc_user_cache_for_tests()
    yield
    reset_lc_user_cache_for_tests()


def test_fetch_discovery_votable_bytes_requires_lc_key():
    """Missing fetch handle is a user-facing error."""
    with pytest.raises(PipeException, match="Select a catalogue row"):
        fetch_discovery_votable_bytes("")


def test_fetch_discovery_votable_bytes_maps_value_error(monkeypatch):
    """Package ``ValueError`` becomes ``PipeException``."""
    import skvo_veb.utils.lc_discovery_load as load_mod

    def _fail(_lc_key, force_refresh=False):
        raise ValueError("bad key")

    monkeypatch.setattr(load_mod, "fetch", _fail)
    with pytest.raises(PipeException, match="bad key"):
        fetch_discovery_votable_bytes("opaque-key")


def test_fetch_discovery_votable_bytes_returns_payload(monkeypatch):
    """The helper returns ``fetch`` bytes unchanged."""
    import skvo_veb.utils.lc_discovery_load as load_mod

    monkeypatch.setattr(load_mod, "fetch", lambda _key, force_refresh=False: b"<VOTABLE/>")
    assert fetch_discovery_votable_bytes("opaque-key") == b"<VOTABLE/>"


def test_fetch_discovery_votable_bytes_uses_server_cache(monkeypatch):
    """A second call reads the cache and does not call the provider again."""
    import skvo_veb.utils.lc_discovery_load as load_mod

    calls = []

    def _fetch(_key, force_refresh=False):
        calls.append(force_refresh)
        return b"<VOTABLE>" + str(len(calls)).encode() + b"</VOTABLE>"

    monkeypatch.setattr(load_mod, "fetch", _fetch)
    first = fetch_discovery_votable_bytes("opaque-key")
    second = fetch_discovery_votable_bytes("opaque-key")
    assert first == second
    assert calls == [False]


def test_fetch_discovery_votable_bytes_force_refresh_replaces_cache(monkeypatch):
    """``force_refresh`` calls the provider and replaces the cached bytes."""
    import skvo_veb.utils.lc_discovery_load as load_mod

    calls = []

    def _fetch(_key, force_refresh=False):
        calls.append(force_refresh)
        return b"v" + str(len(calls)).encode()

    monkeypatch.setattr(load_mod, "fetch", _fetch)
    assert fetch_discovery_votable_bytes("opaque-key") == b"v1"
    assert fetch_discovery_votable_bytes("opaque-key", force_refresh=True) == b"v2"
    assert fetch_discovery_votable_bytes("opaque-key") == b"v2"
    assert calls == [False, True]


def test_fetch_discovery_votable_bytes_does_not_cache_failures(monkeypatch):
    """A failed fetch leaves nothing in the cache."""
    import skvo_veb.utils.lc_discovery_load as load_mod

    state = {"fail": True}

    def _fetch(_key, force_refresh=False):
        if state["fail"]:
            raise ValueError("archive down")
        return b"ok"

    monkeypatch.setattr(load_mod, "fetch", _fetch)
    with pytest.raises(PipeException, match="archive down"):
        fetch_discovery_votable_bytes("opaque-key")
    state["fail"] = False
    assert fetch_discovery_votable_bytes("opaque-key") == b"ok"
