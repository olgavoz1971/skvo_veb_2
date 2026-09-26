"""Tests for Discovery catalogue search orchestration."""

import pytest

from lc_discovery.shared.gaia_dr3_source_id import parse_gaia_source_id
from skvo_veb.utils.coord import parse_coord_to_skycoord, skycoord_to_hms_dms
from skvo_veb.utils.lc_discovery_time_bounds import DiscoveryTimeBounds
from skvo_veb.utils.lc_discovery_search import (
    SEARCH_MODE_CONE,
    SEARCH_MODE_DIRECT_NAME,
    SEARCH_MODE_PROVIDER_RESOLVED_ID,
    SEARCH_MODE_SIMBAD_ARCHIVE_ID,
    SEARCH_MODE_SIMBAD_CONE,
    catalog_results_header,
    catalog_results_header_from_store,
    catalog_truncation_notice,
    catalog_truncation_notice_from_store,
    catalog_rows_for_aggrid,
    radius_to_arcsec,
    status_no_match_asking_simbad,
    status_querying_archive_id,
    status_querying_cone,
    status_querying_object,
    status_querying_provider_archive_id,
    status_resolving_provider_name,
    status_simbad_resolved,
    run_catalog_search,
    run_catalog_search_for_mission,
)
from skvo_veb.tests.sample_sources import AA_AND, AB_AND
from lc_discovery.catalog_schema import empty_catalog_table
from skvo_veb.utils.lc_discovery_search import SearchOutcome
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


















def test_catalog_truncation_notice_when_not_truncated():
    """Truncation banner stays hidden unless the provider set the flag."""
    outcome = SearchOutcome(
        catalog=empty_catalog_table(),
        resolved_markdown="",
        search_mode=SEARCH_MODE_CONE,
        centre_ra_deg=0.0,
        centre_dec_deg=0.0,
        user_target="test",
    )
    text, style = catalog_truncation_notice(outcome)
    assert text == ""
    assert style == {"display": "none"}


def test_catalog_truncation_notice_when_truncated():
    """Truncation banner shows provider detail when the cone cap may apply."""
    outcome = SearchOutcome(
        catalog=empty_catalog_table(),
        resolved_markdown="",
        search_mode=SEARCH_MODE_CONE,
        centre_ra_deg=0.0,
        centre_dec_deg=0.0,
        user_target="test",
        catalog_may_be_truncated=True,
        catalog_truncation_detail="Results may be truncated: example.",
    )
    text, style = catalog_truncation_notice(outcome)
    assert "truncated" in text
    assert style == {"display": "block"}


def test_catalog_chrome_from_store_matches_search_outcome():
    """Session restore rebuilds header and truncation from the metadata store."""
    outcome = SearchOutcome(
        catalog=empty_catalog_table(),
        resolved_markdown="Resolved target",
        search_mode=SEARCH_MODE_CONE,
        centre_ra_deg=AA_AND.ra_deg,
        centre_dec_deg=AA_AND.dec_deg,
        user_target=AA_AND_COORDS,
        radius_value=10.0,
        radius_unit="arcsec",
        catalog_may_be_truncated=True,
        catalog_truncation_detail="Results may be truncated: example.",
    )
    payload = outcome.to_store_dict()
    assert catalog_results_header_from_store(payload) == catalog_results_header(outcome)
    assert catalog_truncation_notice_from_store(payload) == catalog_truncation_notice(
        outcome
    )
    assert catalog_results_header_from_store(None) == ""
    text, style = catalog_truncation_notice_from_store(None)
    assert text == ""
    assert style == {"display": "none"}






def test_run_catalog_search_for_mission_unknown():
    """Unknown mission ids raise a user-facing error."""
    with pytest.raises(ValueError, match="Unknown mission"):
        run_catalog_search_for_mission("missing", AA_AND_COORDS, "10", "arcsec")






def test_run_catalog_search_personal_cross_ident_before_simbad(monkeypatch):
    """Personal provider resolves cross-id aliases before Simbad is consulted."""
    from astropy.table import Table

    from lc_discovery.base import MissionArchiveMatch
    from lc_discovery.providers.personal_ts import config
    from lc_discovery.providers.personal_ts.provider import PersonalTsProvider
    from lc_discovery.providers.personal_ts.ssa_catalog import map_ssa_table_to_catalog

    provider = PersonalTsProvider()
    sample_table = map_ssa_table_to_catalog(
        Table(
            {
                "object_id": ["MO_Psc"],
                "accref": ["https://example.test/mo-psc-r"],
                "ssa_bandpass": ["R"],
                "ssa_targname": ["MO_Psc"],
                "ssa_targclass": ["CV*"],
                "ssa_location": ["(351.295, 1.5006)"],
                "ssa_length": [100],
                "ssa_collection": ["PERSONAL"],
                "t_min": [54000.0],
                "t_max": [60000.0],
                "mean_mag": [14.0],
            }
        ),
        provider_id=config.PROVIDER_ID,
    )

    def fake_resolve(_name: str) -> MissionArchiveMatch:
        return MissionArchiveMatch(
            archive_id="MO_Psc",
            match_kind="personal_cross_ident",
            matched_label="MO Psc",
        )

    def fake_search_catalog(**kwargs):
        if kwargs.get("archive_id") == "MO_Psc":
            return sample_table
        from lc_discovery.catalog_schema import empty_catalog_table

        return empty_catalog_table()

    monkeypatch.setattr(provider, "resolve_target_name", fake_resolve)
    monkeypatch.setattr(provider, "search_catalog", fake_search_catalog)

    status_messages: list[str] = []

    def _unexpected_simbad(_name: str):
        raise AssertionError("Simbad should not be called when provider resolves the alias")

    outcome = run_catalog_search(
        provider,
        "MO Psc",
        10.0,
        "arcsec",
        simbad_resolver=_unexpected_simbad,
        status_update=status_messages.append,
    )
    assert outcome.search_mode == SEARCH_MODE_PROVIDER_RESOLVED_ID
    assert len(outcome.catalog) == len(sample_table)
    assert outcome.archive_match is not None
    assert outcome.archive_match.archive_id == "MO_Psc"
    assert status_messages == [
        status_querying_object(config.DISPLAY_NAME, "MO Psc"),
        status_resolving_provider_name(config.DISPLAY_NAME, "MO Psc"),
        status_querying_provider_archive_id(config.DISPLAY_NAME, "MO_Psc"),
    ]
