"""Tests for shared lightcurve provider base behaviour."""

from __future__ import annotations

from skvo_veb.lc_providers.base import DEFAULT_MAX_DISCOVERY_CATALOG_ROWS
from skvo_veb.lc_providers.gaia_dr3_ari.provider import GaiaDr3AriProvider
from skvo_veb.lc_providers.tap.adql import adql_top_limit_clause


def test_default_max_discovery_catalog_rows():
    """Providers inherit a default cone-search row cap of 100."""
    provider = GaiaDr3AriProvider()
    assert provider.max_discovery_catalog_rows() == DEFAULT_MAX_DISCOVERY_CATALOG_ROWS
    assert DEFAULT_MAX_DISCOVERY_CATALOG_ROWS == 100


def test_adql_top_limit_clause():
    """ADQL TOP prefix is omitted unless a positive limit is supplied."""
    assert adql_top_limit_clause(None) == ""
    assert adql_top_limit_clause(100) == "TOP 100 "
