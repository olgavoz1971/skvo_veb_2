"""Tests for Discovery fetch helpers used by the Light curve tab."""

from __future__ import annotations

import pytest

from skvo_veb.utils.lc_discovery_load import fetch_discovery_votable_bytes
from skvo_veb.utils.my_tools import PipeException


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
