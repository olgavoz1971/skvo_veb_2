"""Tests for Gaia DR3 (ARI) multi-table VOTable photcal ingest."""

from __future__ import annotations

import io

import pytest

from volightcurve import VOLightCurve


def _enriched(payload: bytes, table_id: int = 0):
    """Enriches one band and parses it the way Discovery does."""
    from lc_discovery.providers.gaia_dr3_ari.fetch_metadata import enrich_votable

    return VOLightCurve(io.BytesIO(enrich_votable(payload, table_id=table_id)))


def test_gaia_ari_raw_file_issues_one_g_band_table():
    """The ARI download keeps one band and the G photcal split."""
    from pathlib import Path

    raw = Path("/home/voz/projects/UPJS/tmp/g_ari.xml").read_bytes()
    volc = _enriched(raw, table_id=0)
    assert volc.table.meta["name"] == "Gaia DR3 1704795806820110080 - G band time series"
    assert "BP band" not in volc.table.meta["name"]
    assert volc.photdms["mag"].filter.filter_id == "GAIADR3.G"
    assert float(volc.photdms["flux"].photcal.zp_mag.value) == pytest.approx(25.6874)
    assert "source_id" not in volc.table.colnames
    assert volc.table.meta["period"] == pytest.approx(0.32540451593736336)
