"""Tests for Discovery catalogue search orchestration."""

import pytest

from skvo_veb.lc_providers.gaia import GaiaDr3Provider, parse_gaia_source_id
from skvo_veb.lc_providers.registry import get_provider
from skvo_veb.utils.lc_discovery_search import (
    SEARCH_MODE_CONE,
    SEARCH_MODE_DIRECT_NAME,
    SEARCH_MODE_SIMBAD_ARCHIVE_ID,
    SEARCH_MODE_SIMBAD_CONE,
    catalog_results_header,
    catalog_results_subtitle,
    radius_to_arcsec,
    run_catalog_search,
    run_catalog_search_for_mission,
)
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.simbad_resolver import SimbadResolveResult


def _fake_simbad(name: str) -> SimbadResolveResult:
    """Builds a deterministic Simbad payload for orchestration tests.

    Args:
        name (str): User query name.

    Returns:
        SimbadResolveResult: Simbad resolve payload with a Gaia cross-id.
    """
    return SimbadResolveResult(
        query_name=name,
        main_id="NAME AA And",
        identifiers=("NAME AA And", "Gaia DR3 2222222222222222222"),
        ra_deg=12.5,
        dec_deg=45.0,
    )


def test_parse_gaia_source_id_variants():
    """Gaia source ids are parsed from common user and Simbad string forms."""
    assert parse_gaia_source_id("Gaia DR3 2222222222222222222") == 2222222222222222222
    assert parse_gaia_source_id("2222222222222222222") == 2222222222222222222
    assert parse_gaia_source_id("AA And") is None


def test_radius_to_arcsec_units():
    """Radius conversion accepts arcsec, arcmin, and deg."""
    assert radius_to_arcsec(10.0, "arcsec") == pytest.approx(10.0)
    assert radius_to_arcsec(1.0, "arcmin") == pytest.approx(60.0)
    assert radius_to_arcsec(1.0, "deg") == pytest.approx(3600.0)


def test_run_catalog_search_coordinates_cone():
    """Coordinate targets run the cone strategy."""
    provider = GaiaDr3Provider()
    outcome = run_catalog_search(
        provider,
        "100 10",
        10.0,
        "arcsec",
    )
    assert outcome.search_mode == SEARCH_MODE_CONE
    assert len(outcome.catalog) == 3


def test_run_catalog_search_direct_gaia_id():
    """Gaia source id strings use direct archive lookup without Simbad."""
    provider = GaiaDr3Provider()
    outcome = run_catalog_search(
        provider,
        "Gaia DR3 2222222222222222222",
        10.0,
        "arcsec",
    )
    assert outcome.search_mode == SEARCH_MODE_DIRECT_NAME
    assert len(outcome.catalog) == 1
    assert outcome.catalog["object_name"][0] == "Gaia DR3 2222222222222222222"
    assert "Magnitude:" not in outcome.resolved_markdown
    assert r"$G_\mathrm{mag}$" in outcome.resolved_markdown
    assert "Survey:" not in outcome.resolved_markdown


def test_run_catalog_search_simbad_gaia_id_before_cone():
    """Generic names with Gaia cross-ids use direct archive lookup before cone fallback."""
    provider = GaiaDr3Provider()
    outcome = run_catalog_search(
        provider,
        "AA And",
        10.0,
        "arcsec",
        simbad_resolver=_fake_simbad,
    )
    assert outcome.search_mode == SEARCH_MODE_SIMBAD_ARCHIVE_ID
    assert len(outcome.catalog) == 1
    assert outcome.archive_match is not None
    assert outcome.archive_match.match_kind == "gaia_source_id"
    assert "NAME AA And" in outcome.resolved_markdown
    assert "Identifiers:" in outcome.resolved_markdown
    assert "lightcurve" not in outcome.resolved_markdown.lower()
    assert "cone search" not in outcome.resolved_markdown.lower()


def test_run_catalog_search_simbad_cone_when_no_archive_id():
    """When Simbad has no mission id, cone search is the fallback for Gaia."""
    provider = GaiaDr3Provider()

    def _simbad_without_gaia(_name: str) -> SimbadResolveResult:
        return SimbadResolveResult(
            query_name="V* DP Peg",
            main_id="V* DP Peg",
            identifiers=("V* DP Peg",),
            ra_deg=100.0,
            dec_deg=10.0,
        )

    outcome = run_catalog_search(
        provider,
        "V* DP Peg",
        10.0,
        "arcsec",
        simbad_resolver=_simbad_without_gaia,
    )
    assert outcome.search_mode == SEARCH_MODE_SIMBAD_CONE
    assert len(outcome.catalog) == 3
    assert "V* DP Peg" in outcome.resolved_markdown
    assert "Position:" not in outcome.resolved_markdown
    assert "ICRS" not in outcome.resolved_markdown
    assert "Filter:" not in outcome.resolved_markdown
    assert "lightcurve" not in outcome.resolved_markdown.lower()
    assert "No direct match" not in outcome.resolved_markdown
    assert catalog_results_header(outcome) == "06:40:00 +10:00:00"


def test_object_card_markdown_for_coordinates():
    """Coordinate targets show coordinates on the object card, not search metadata."""
    provider = GaiaDr3Provider()
    outcome = run_catalog_search(
        provider,
        "100 10",
        10.0,
        "arcsec",
    )
    assert "100 10" in outcome.resolved_markdown
    assert "Position:" not in outcome.resolved_markdown
    assert "ICRS" not in outcome.resolved_markdown
    assert "Filter:" not in outcome.resolved_markdown
    assert "lightcurve" not in outcome.resolved_markdown.lower()
    assert catalog_results_header(outcome) == "06:40:00 +10:00:00"
    assert catalog_results_subtitle(outcome) == "3 catalogue rows"


def test_catalog_results_header_uses_object_name_for_direct_lookup():
    """Direct name or id searches use the target string as the table title."""
    provider = GaiaDr3Provider()
    outcome = run_catalog_search(
        provider,
        "Gaia DR3 2222222222222222222",
        10.0,
        "arcsec",
    )
    assert catalog_results_header(outcome) == "Gaia DR3 2222222222222222222"
    assert catalog_results_subtitle(outcome) == "1 catalogue row"


def test_run_catalog_search_for_mission_unknown():
    """Unknown mission ids raise a user-facing error."""
    with pytest.raises(PipeException, match="Unknown mission"):
        run_catalog_search_for_mission("missing", "100 10", "10", "arcsec")


def test_gaia_pick_archive_id_from_simbad():
    """Gaia provider selects Gaia DR3 ids from Simbad identifier lists."""
    provider = GaiaDr3Provider()
    match = provider.pick_archive_id_from_simbad(_fake_simbad("AA And"))
    assert match is not None
    assert match.archive_id == "2222222222222222222"
    assert match.match_kind == "gaia_source_id"


def test_registry_gaia_provider_direct_id_search():
    """Registry Gaia provider returns one row for a direct source id query."""
    provider = get_provider("gaia")
    table = provider.search_catalog(archive_id="2222222222222222222")
    assert len(table) == 1
