"""Tests for Discovery catalogue search orchestration."""

import pytest

from skvo_veb.lc_providers.gaia_debug import GaiaDr3Provider
from skvo_veb.lc_providers.shared.gaia_dr3_source_id import parse_gaia_source_id
from skvo_veb.lc_providers.registry import get_provider
from skvo_veb.utils.coord import parse_coord_to_skycoord, skycoord_to_hms_dms
from skvo_veb.utils.lc_discovery_time_bounds import DiscoveryTimeBounds
from skvo_veb.utils.lc_discovery_search import (
    SEARCH_MODE_CONE,
    SEARCH_MODE_DIRECT_NAME,
    SEARCH_MODE_SIMBAD_ARCHIVE_ID,
    SEARCH_MODE_SIMBAD_CONE,
    catalog_results_header,
    catalog_rows_for_aggrid,
    radius_to_arcsec,
    status_no_match_asking_simbad,
    status_querying_archive_id,
    status_querying_cone,
    status_querying_object,
    status_simbad_resolved,
    run_catalog_search,
    run_catalog_search_for_mission,
)
from skvo_veb.lc_providers.gaia_debug.debug_catalog import AA_AND, AB_AND
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.simbad_resolver import SimbadResolveResult

AA_AND_COORDS = f"{AA_AND.ra_deg} {AA_AND.dec_deg}"


def _fake_simbad(name: str) -> SimbadResolveResult:
    """Builds a deterministic Simbad payload for orchestration tests.

    Args:
        name (str): User query name.

    Returns:
        SimbadResolveResult: Simbad resolve payload with a debug Gaia cross-id.
    """
    return SimbadResolveResult(
        query_name=name,
        main_id="NAME AA And",
        identifiers=("NAME AA And", f"Gaia DR3 {AA_AND.source_id}"),
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
    )


def test_parse_gaia_source_id_variants():
    """Gaia source ids are parsed from common user and Simbad string forms."""
    assert parse_gaia_source_id(f"Gaia DR3 {AA_AND.source_id}") == AA_AND.source_id
    assert parse_gaia_source_id(str(AA_AND.source_id)) == AA_AND.source_id
    assert parse_gaia_source_id("AA And") is None


def test_radius_to_arcsec_units():
    """Radius conversion accepts arcsec, arcmin, and deg."""
    assert radius_to_arcsec(10.0, "arcsec") == pytest.approx(10.0)
    assert radius_to_arcsec(1.0, "arcmin") == pytest.approx(60.0)
    assert radius_to_arcsec(1.0, "deg") == pytest.approx(3600.0)


def test_run_catalog_search_coordinates_cone():
    """Coordinate targets run the cone strategy against the debug catalogue."""
    provider = GaiaDr3Provider()
    outcome = run_catalog_search(
        provider,
        AA_AND_COORDS,
        10.0,
        "arcsec",
    )
    assert outcome.search_mode == SEARCH_MODE_CONE
    assert len(outcome.catalog) == 3
    status_messages: list[str] = []
    run_catalog_search(
        provider,
        AA_AND_COORDS,
        10.0,
        "arcsec",
        status_update=status_messages.append,
    )
    assert status_messages == [
        status_querying_cone("Gaia DR3 (debug)", 10.0, "arcsec"),
    ]


def test_run_catalog_search_direct_gaia_id():
    """Gaia source id strings use direct archive lookup without Simbad."""
    provider = GaiaDr3Provider()
    gaia_id_text = f"Gaia DR3 {AA_AND.source_id}"
    outcome = run_catalog_search(
        provider,
        gaia_id_text,
        10.0,
        "arcsec",
    )
    assert outcome.search_mode == SEARCH_MODE_DIRECT_NAME
    assert len(outcome.catalog) == 3
    assert outcome.catalog["object_name"][0] == AA_AND.catalogue_object_name
    status_messages: list[str] = []
    run_catalog_search(
        provider,
        gaia_id_text,
        10.0,
        "arcsec",
        status_update=status_messages.append,
    )
    assert status_messages == [
        status_querying_object("Gaia DR3 (debug)", gaia_id_text),
    ]
    assert "Magnitude:" not in outcome.resolved_markdown
    assert r"$G_\mathrm{mag}$" in outcome.resolved_markdown
    assert "Survey:" not in outcome.resolved_markdown


def test_run_catalog_search_common_name_uses_simbad_not_direct_gaia():
    """Common names are not resolved by the Gaia provider; Simbad supplies the id."""
    provider = GaiaDr3Provider()
    outcome = run_catalog_search(
        provider,
        "AA And",
        10.0,
        "arcsec",
        simbad_resolver=_fake_simbad,
    )
    assert outcome.search_mode == SEARCH_MODE_SIMBAD_ARCHIVE_ID
    assert len(outcome.catalog) == 3
    assert outcome.catalog["object_name"][0] == AA_AND.catalogue_object_name


def test_run_catalog_search_simbad_gaia_id_before_cone():
    """Generic names with Gaia cross-ids use direct archive lookup before cone fallback."""
    provider = GaiaDr3Provider()
    outcome = run_catalog_search(
        provider,
        "Alias Not In Debug Catalogue",
        10.0,
        "arcsec",
        simbad_resolver=_fake_simbad,
    )
    assert outcome.search_mode == SEARCH_MODE_SIMBAD_ARCHIVE_ID
    assert len(outcome.catalog) == 3
    assert outcome.archive_match is not None
    assert outcome.archive_match.match_kind == "gaia_source_id"
    assert outcome.archive_match.archive_id == str(AA_AND.source_id)
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
            ra_deg=AB_AND.ra_deg,
            dec_deg=AB_AND.dec_deg,
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
    coord = parse_coord_to_skycoord(f"{AB_AND.ra_deg} {AB_AND.dec_deg}")
    assert catalog_results_header(outcome) == (
        f"{skycoord_to_hms_dms(coord)}, r = 10 arcsec"
    )
    status_messages: list[str] = []
    run_catalog_search(
        provider,
        "V* DP Peg",
        10.0,
        "arcsec",
        simbad_resolver=_simbad_without_gaia,
        status_update=status_messages.append,
    )
    assert status_messages == [
        status_querying_object("Gaia DR3 (debug)", "V* DP Peg"),
        status_no_match_asking_simbad(),
        status_simbad_resolved("V* DP Peg"),
        status_querying_cone(
            "Gaia DR3 (debug)",
            10.0,
            "arcsec",
            simbad_position=True,
        ),
    ]


def test_run_catalog_search_simbad_archive_id_status_sequence():
    """Simbad archive-id lookup publishes concise status-bar steps."""
    provider = GaiaDr3Provider()
    status_messages: list[str] = []
    run_catalog_search(
        provider,
        "Alias Not In Debug Catalogue",
        10.0,
        "arcsec",
        simbad_resolver=_fake_simbad,
        status_update=status_messages.append,
    )
    assert status_messages == [
        status_querying_object("Gaia DR3 (debug)", "Alias Not In Debug Catalogue"),
        status_no_match_asking_simbad(),
        status_simbad_resolved("NAME AA And"),
        status_querying_archive_id("Gaia DR3 (debug)", str(AA_AND.source_id)),
    ]


def test_object_card_markdown_for_coordinates():
    """Coordinate targets show coordinates on the object card, not search metadata."""
    provider = GaiaDr3Provider()
    outcome = run_catalog_search(
        provider,
        AA_AND_COORDS,
        10.0,
        "arcsec",
    )
    assert AA_AND_COORDS in outcome.resolved_markdown
    assert "Position:" not in outcome.resolved_markdown
    assert "ICRS" not in outcome.resolved_markdown
    assert "Filter:" not in outcome.resolved_markdown
    assert "lightcurve" not in outcome.resolved_markdown.lower()
    coord = parse_coord_to_skycoord(AA_AND_COORDS)
    assert catalog_results_header(outcome) == (
        f"{skycoord_to_hms_dms(coord)}, r = 10 arcsec"
    )


def test_catalog_results_header_uses_object_name_for_direct_lookup():
    """Direct name or id searches use the target string as the table title."""
    provider = GaiaDr3Provider()
    gaia_id_text = f"Gaia DR3 {AA_AND.source_id}"
    outcome = run_catalog_search(
        provider,
        gaia_id_text,
        10.0,
        "arcsec",
    )
    assert catalog_results_header(outcome) == gaia_id_text


def test_run_catalog_search_applies_optional_time_bounds():
    """Orchestration forwards parsed MJD limits to the provider search."""
    provider = GaiaDr3Provider()
    bounds = DiscoveryTimeBounds(time_start_mjd=57250.0, time_end_mjd=57260.0)
    outcome = run_catalog_search(
        provider,
        f"{AB_AND.ra_deg} {AB_AND.dec_deg}",
        10.0,
        "arcsec",
        time_bounds=bounds,
    )
    assert len(outcome.catalog) == 3
    assert outcome.time_start_mjd == pytest.approx(57250.0)
    assert outcome.time_end_mjd == pytest.approx(57260.0)


def test_catalog_rows_for_aggrid_formats_display_columns():
    """AgGrid rows round separation and ObsCore time columns for display."""
    provider = GaiaDr3Provider()
    table = provider.search_catalog(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=10.0,
    )
    rows = catalog_rows_for_aggrid(table)
    assert rows[0]["t_min"] == 57100
    assert rows[0]["t_max"] == 57180
    assert all(isinstance(row["t_min"], int) for row in rows)
    assert all(isinstance(row["t_max"], int) for row in rows)
    for row in rows:
        sep = row["distance_arcsec"]
        assert sep == round(sep, 1)


def test_run_catalog_search_for_mission_unknown():
    """Unknown mission ids raise a user-facing error."""
    with pytest.raises(PipeException, match="Unknown mission"):
        run_catalog_search_for_mission("missing", AA_AND_COORDS, "10", "arcsec")


def test_gaia_pick_archive_id_from_simbad():
    """Gaia provider selects debug Gaia DR3 ids from Simbad identifier lists."""
    provider = GaiaDr3Provider()
    match = provider.pick_archive_id_from_simbad(_fake_simbad("AA And"))
    assert match is not None
    assert match.archive_id == str(AA_AND.source_id)
    assert match.match_kind == "gaia_source_id"


def test_registry_gaia_provider_direct_id_search():
    """Registry Gaia provider returns passband rows for a direct source id query."""
    provider = get_provider("gaia")
    table = provider.search_catalog(archive_id=str(AA_AND.source_id))
    assert len(table) == 3
