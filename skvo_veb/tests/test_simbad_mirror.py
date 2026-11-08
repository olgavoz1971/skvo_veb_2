"""Tests for the SIMBAD_MIRROR environment switch."""

import pytest

from skvo_veb.config import Config, configure_simbad_server


def test_simbad_server_defaults_to_cds(monkeypatch):
    """An unset variable keeps the CDS hostname."""
    monkeypatch.delenv("SIMBAD_MIRROR", raising=False)
    assert Config.simbad_server() == "simbad.cds.unistra.fr"


def test_simbad_server_blank_means_cds(monkeypatch):
    """A blank variable is the same as leaving it unset."""
    monkeypatch.setenv("SIMBAD_MIRROR", "  ")
    assert Config.simbad_server() == "simbad.cds.unistra.fr"


def test_simbad_server_selects_harvard(monkeypatch):
    """The harvard key selects the hostname astroquery accepts."""
    monkeypatch.setenv("SIMBAD_MIRROR", "Harvard")
    assert Config.simbad_server() == "simbad.harvard.edu"


def test_simbad_server_rejects_an_unknown_mirror(monkeypatch):
    """A hostname outside the two mirrors fails immediately."""
    monkeypatch.setenv("SIMBAD_MIRROR", "cfa")
    with pytest.raises(ValueError, match="'cfa'"):
        Config.simbad_server()


def test_configure_simbad_server_assigns_the_shared_client(monkeypatch):
    """The module-level Simbad object receives the selected hostname."""
    from astroquery.simbad import Simbad

    previous = Simbad.server
    monkeypatch.setenv("SIMBAD_MIRROR", "harvard")
    try:
        assert configure_simbad_server() == "simbad.harvard.edu"
        assert Simbad.server == "simbad.harvard.edu"
    finally:
        Simbad.server = previous
