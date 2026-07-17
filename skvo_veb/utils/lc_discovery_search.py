"""Search orchestration for the Lightcurve Discovery page."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from skvo_veb.lc_providers.base import MissionArchiveMatch, MissionLightcurveProvider
from skvo_veb.lc_providers.catalog_schema import catalog_table_to_row_dicts
from skvo_veb.lc_providers.registry import get_provider
from skvo_veb.utils.coord import parse_coord_to_skycoord, skycoord_to_hms_dms
from skvo_veb.utils.my_tools import PipeException, safe_float
from skvo_veb.utils.simbad_resolver import SimbadResolveResult, resolve_simbad_name

logger = logging.getLogger(__name__)

SEARCH_MODE_CONE = "cone"
SEARCH_MODE_DIRECT_NAME = "direct_name"
SEARCH_MODE_DIRECT_ARCHIVE_ID = "direct_archive_id"
SEARCH_MODE_SIMBAD_ARCHIVE_ID = "simbad_archive_id"
SEARCH_MODE_SIMBAD_CONE = "simbad_cone"
SEARCH_MODE_SIMBAD_MAIN_NAME = "simbad_main_name"


@dataclass(frozen=True)
class SearchOutcome:
    """Result of a Discovery catalogue search."""

    catalog: Table
    resolved_markdown: str
    search_mode: str
    centre_ra_deg: float | None
    centre_dec_deg: float | None
    user_target: str
    archive_match: MissionArchiveMatch | None = None
    simbad_main_id: str | None = None

    def to_store_dict(self) -> dict:
        """Serialises lightweight metadata for ``dcc.Store``.

        Returns:
            dict: JSON-serialisable search summary without heavy arrays.
        """
        return {
            "search_mode": self.search_mode,
            "centre_ra_deg": self.centre_ra_deg,
            "centre_dec_deg": self.centre_dec_deg,
            "user_target": self.user_target,
            "resolved_markdown": self.resolved_markdown,
            "archive_match": (
                {
                    "archive_id": self.archive_match.archive_id,
                    "match_kind": self.archive_match.match_kind,
                    "matched_label": self.archive_match.matched_label,
                }
                if self.archive_match
                else None
            ),
            "simbad_main_id": self.simbad_main_id,
            "row_count": len(self.catalog),
        }


def radius_to_arcsec(radius_value: float, radius_unit: str) -> float:
    """Converts a UI radius to arcseconds.

    Args:
        radius_value (float): Numeric radius from the tools panel.
        radius_unit (str): ``arcsec``, ``arcmin``, or ``deg``.

    Returns:
        float: Radius in arcseconds.

    Raises:
        PipeException: When the unit is unsupported or the value is invalid.
    """
    unit = str(radius_unit or "arcsec").strip().lower()
    if radius_value <= 0:
        raise PipeException("Search radius must be positive.")
    if unit == "arcsec":
        return float(radius_value)
    if unit == "arcmin":
        return float(radius_value) * 60.0
    if unit == "deg":
        return float(radius_value) * 3600.0
    raise PipeException(f"Unsupported radius unit '{radius_unit}'.")


def parse_discovery_radius(radius_text: str | None, radius_unit: str) -> float:
    """Parses and validates the radius field from the Discovery UI.

    Args:
        radius_text (str, optional): Radius input value.
        radius_unit (str): Unit selector value.

    Returns:
        float: Radius in arcseconds.

    Raises:
        PipeException: When the radius is missing or invalid.
    """
    radius = safe_float(radius_text)
    if radius is None:
        raise PipeException("Search radius is required.")
    return radius_to_arcsec(float(radius), radius_unit)


def _target_is_coordinates(target: str) -> bool:
    """Checks whether the Target field parses as ICRS coordinates.

    Args:
        target (str): Raw Target input.

    Returns:
        bool: True when ``parse_coord_to_skycoord`` succeeds.
    """
    try:
        parse_coord_to_skycoord(target)
        return True
    except (ValueError, TypeError):
        return False


def _position_markdown_lines(ra_deg: float, dec_deg: float) -> list[str]:
    """Formats coordinate lines for the object card.

    Args:
        ra_deg (float): Right ascension in degrees.
        dec_deg (float): Declination in degrees.

    Returns:
        list[str]: Plain-text coordinate lines.
    """
    coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
    return [
        skycoord_to_hms_dms(coord),
        f"{ra_deg:.5f}° {dec_deg:.5f}°",
    ]


def _magnitude_label(row) -> str:
    """Builds a LaTeX magnitude label from catalogue filter metadata.

    Args:
        row: Astropy table row with optional ``filter_name`` / ``filter_identifier``.

    Returns:
        str: LaTeX fragment suitable for ``dcc.Markdown`` with ``mathjax=True``.
    """
    filter_name = str(row["filter_name"]) if "filter_name" in row.colnames else ""
    filter_id = str(row["filter_identifier"]) if "filter_identifier" in row.colnames else ""
    normalised = filter_name.strip().upper()
    if normalised in {"G", "GAIA G"} or filter_id.endswith(".G"):
        return r"$G_\mathrm{mag}$"
    if filter_name:
        band = filter_name.split()[-1]
        return rf"${band}_\mathrm{{mag}}$"
    return r"$m_\mathrm{mag}$"


def _simbad_object_markdown(simbad_result: SimbadResolveResult) -> str:
    """Builds unstructured object-property markdown from a Simbad resolve result.

    Args:
        simbad_result (SimbadResolveResult): Normalised Simbad response.

    Returns:
        str: Free-form markdown for the resolved-target card.
    """
    lines = [simbad_result.query_name]
    if simbad_result.main_id != simbad_result.query_name:
        lines.append(f"Simbad main identifier: {simbad_result.main_id}")
    lines.extend(_position_markdown_lines(simbad_result.ra_deg, simbad_result.dec_deg))
    if simbad_result.identifiers:
        identifier_lines = "\n".join(
            f"- {identifier}" for identifier in simbad_result.identifiers
        )
        lines.append(f"Identifiers:\n{identifier_lines}")
    return "\n\n".join(lines)


def _catalog_object_markdown(user_target: str, catalog: Table) -> str:
    """Builds object-property markdown from the first catalogue row.

    Args:
        user_target (str): Raw Target input.
        catalog (astropy.table.Table): Catalogue table returned by the provider.

    Returns:
        str: Free-form markdown for the resolved-target card.
    """
    lines = [user_target]
    if len(catalog) == 0:
        return "\n\n".join(lines)

    row = catalog[0]
    object_name = str(row["object_name"])
    if object_name and object_name != user_target:
        lines.append(f"Object name: {object_name}")
    lines.extend(
        _position_markdown_lines(float(row["ra_deg"]), float(row["dec_deg"]))
    )
    if "survey" in catalog.colnames and row["survey"]:
        lines.append(str(row["survey"]))
    if "mag" in catalog.colnames and row["mag"] == row["mag"]:
        lines.append(f"{_magnitude_label(row)}: {float(row['mag']):.3f}")
    return "\n\n".join(lines)


def _coordinate_target_markdown(user_target: str, ra_deg: float, dec_deg: float) -> str:
    """Builds object-card markdown for a coordinate Target field.

    Args:
        user_target (str): Raw Target input (coordinates).
        ra_deg (float): Parsed right ascension in degrees.
        dec_deg (float): Parsed declination in degrees.

    Returns:
        str: Free-form markdown for the resolved-target card.
    """
    lines = [user_target]
    lines.extend(_position_markdown_lines(ra_deg, dec_deg))
    return "\n\n".join(lines)


def catalog_results_header(outcome: SearchOutcome) -> str:
    """Builds the catalogue table title for the Search results panel.

    Cone searches show the search centre coordinates; name or id searches show
    the target string used for the query.

    Args:
        outcome (SearchOutcome): Completed search result.

    Returns:
        str: Title text for the results table header.
    """
    if outcome.search_mode in (SEARCH_MODE_CONE, SEARCH_MODE_SIMBAD_CONE):
        if outcome.centre_ra_deg is not None and outcome.centre_dec_deg is not None:
            coord = SkyCoord(
                ra=outcome.centre_ra_deg * u.deg,
                dec=outcome.centre_dec_deg * u.deg,
                frame="icrs",
            )
            return skycoord_to_hms_dms(coord)
    return outcome.user_target


def catalog_results_subtitle(outcome: SearchOutcome) -> str:
    """Builds the catalogue table subtitle (row count only).

    Args:
        outcome (SearchOutcome): Completed search result.

    Returns:
        str: Subtitle text beneath the results table header.
    """
    row_count = len(outcome.catalog)
    if row_count == 0:
        return "No catalogue rows matched this query."
    if row_count == 1:
        return "1 catalogue row"
    return f"{row_count} catalogue rows"


def _finish_outcome(
    *,
    user_target: str,
    search_mode: str,
    catalog: Table,
    resolved_markdown: str,
    centre_ra_deg: float | None = None,
    centre_dec_deg: float | None = None,
    archive_match: MissionArchiveMatch | None = None,
    simbad_main_id: str | None = None,
) -> SearchOutcome:
    """Builds a ``SearchOutcome`` for the UI layer.

    Args:
        user_target (str): Raw Target input.
        search_mode (str): Resolved search strategy identifier.
        catalog (astropy.table.Table): Catalogue table returned by the provider.
        resolved_markdown (str): Object-property markdown for the card.
        centre_ra_deg (float, optional): Centre RA for metadata.
        centre_dec_deg (float, optional): Centre Dec for metadata.
        archive_match (MissionArchiveMatch, optional): Simbad archive id match.
        simbad_main_id (str, optional): Simbad main identifier used on retry.

    Returns:
        SearchOutcome: Completed search result for the UI layer.
    """
    return SearchOutcome(
        catalog=catalog,
        resolved_markdown=resolved_markdown,
        search_mode=search_mode,
        centre_ra_deg=centre_ra_deg,
        centre_dec_deg=centre_dec_deg,
        user_target=user_target,
        archive_match=archive_match,
        simbad_main_id=simbad_main_id,
    )


def run_catalog_search(
    provider: MissionLightcurveProvider,
    target: str,
    radius_value: float,
    radius_unit: str,
    *,
    simbad_resolver: Callable[[str], SimbadResolveResult] | None = None,
) -> SearchOutcome:
    """Runs the agreed Discovery search flow for one mission provider.

    Args:
        provider (MissionLightcurveProvider): Selected mission adapter.
        target (str): Target field text (coordinates or name/id).
        radius_value (float): Numeric radius from the UI field.
        radius_unit (str): Radius unit selector value.
        simbad_resolver (callable, optional): Injectable Simbad resolver for tests.

    Returns:
        SearchOutcome: Catalogue table, markdown summary, and metadata.

    Raises:
        PipeException: When input validation or Simbad resolution fails.
    """
    user_target = str(target or "").strip()
    if not user_target:
        raise PipeException("Please enter a target name or coordinates.")

    radius_arcsec = radius_to_arcsec(radius_value, radius_unit)
    resolve_name = simbad_resolver or resolve_simbad_name
    logger.info(
        "Discovery search started mission=%s target=%r radius=%.3f arcsec.",
        provider.mission_id,
        user_target,
        radius_arcsec,
    )

    if _target_is_coordinates(user_target):
        if not provider.capabilities.supports_cone_search:
            raise PipeException(
                f"{provider.display_name} does not support cone search."
            )
        coord = parse_coord_to_skycoord(user_target)
        logger.info(
            "Target %r parsed as coordinates; running provider cone search.",
            user_target,
        )
        catalog = provider.search_catalog(
            ra_deg=float(coord.ra.deg),
            dec_deg=float(coord.dec.deg),
            radius_arcsec=radius_arcsec,
        )
        ra_deg = float(coord.ra.deg)
        dec_deg = float(coord.dec.deg)
        logger.info(
            "Discovery cone search finished rows=%s centre=(%.5f°, %.5f°).",
            len(catalog),
            ra_deg,
            dec_deg,
        )
        return _finish_outcome(
            user_target=user_target,
            search_mode=SEARCH_MODE_CONE,
            catalog=catalog,
            resolved_markdown=_coordinate_target_markdown(
                user_target, ra_deg, dec_deg
            ),
            centre_ra_deg=ra_deg,
            centre_dec_deg=dec_deg,
        )

    logger.info(
        "Trying direct provider lookup by object name for %r.",
        user_target,
    )
    catalog = provider.search_catalog(object_name=user_target)
    if len(catalog) > 0:
        logger.info(
            "Direct provider lookup matched %s row(s) for %r.",
            len(catalog),
            user_target,
        )
        return _finish_outcome(
            user_target=user_target,
            search_mode=SEARCH_MODE_DIRECT_NAME,
            catalog=catalog,
            resolved_markdown=_catalog_object_markdown(user_target, catalog),
        )

    logger.info("No direct provider match for %r; resolving via Simbad.", user_target)
    simbad_result = resolve_name(user_target)
    simbad_markdown = _simbad_object_markdown(simbad_result)
    archive_match = provider.pick_archive_id_from_simbad(simbad_result)
    if archive_match is not None:
        logger.info(
            "Simbad identifiers include mission archive id %r (%s).",
            archive_match.archive_id,
            archive_match.match_kind,
        )
    else:
        logger.info(
            "No %s archive id found in Simbad identifiers for %r.",
            provider.display_name,
            user_target,
        )
    if archive_match is not None and provider.capabilities.supports_id_lookup:
        logger.info(
            "Trying direct provider lookup by archive id %r.",
            archive_match.archive_id,
        )
        catalog = provider.search_catalog(archive_id=archive_match.archive_id)
        if len(catalog) > 0:
            logger.info(
                "Archive id lookup matched %s row(s) for %r.",
                len(catalog),
                user_target,
            )
            return _finish_outcome(
                user_target=user_target,
                search_mode=SEARCH_MODE_SIMBAD_ARCHIVE_ID,
                catalog=catalog,
                resolved_markdown=simbad_markdown,
                archive_match=archive_match,
                simbad_main_id=simbad_result.main_id,
            )

    if provider.capabilities.supports_cone_search:
        logger.info(
            "Running provider cone search at Simbad position (%.5f°, %.5f°).",
            simbad_result.ra_deg,
            simbad_result.dec_deg,
        )
        catalog = provider.search_catalog(
            ra_deg=simbad_result.ra_deg,
            dec_deg=simbad_result.dec_deg,
            radius_arcsec=radius_arcsec,
        )
        logger.info(
            "Simbad cone search finished rows=%s for %r.",
            len(catalog),
            user_target,
        )
        return _finish_outcome(
            user_target=user_target,
            search_mode=SEARCH_MODE_SIMBAD_CONE,
            catalog=catalog,
            resolved_markdown=simbad_markdown,
            centre_ra_deg=simbad_result.ra_deg,
            centre_dec_deg=simbad_result.dec_deg,
            archive_match=archive_match,
            simbad_main_id=simbad_result.main_id,
        )

    logger.info(
        "Retrying provider lookup with Simbad main identifier %r.",
        simbad_result.main_id,
    )
    catalog = provider.search_catalog(object_name=simbad_result.main_id)
    logger.info(
        "Simbad main-name lookup finished rows=%s for %r.",
        len(catalog),
        user_target,
    )
    return _finish_outcome(
        user_target=user_target,
        search_mode=SEARCH_MODE_SIMBAD_MAIN_NAME,
        catalog=catalog,
        resolved_markdown=simbad_markdown,
        simbad_main_id=simbad_result.main_id,
    )


def run_catalog_search_for_mission(
    mission_id: str,
    target: str,
    radius_text: str | None,
    radius_unit: str,
    *,
    simbad_resolver: Callable[[str], SimbadResolveResult] | None = None,
) -> SearchOutcome:
    """Convenience wrapper resolving the provider then running the search.

    Args:
        mission_id (str): Registered mission slug from the UI.
        target (str): Target field text.
        radius_text (str, optional): Radius input text.
        radius_unit (str): Radius unit selector value.
        simbad_resolver (callable, optional): Injectable Simbad resolver for tests.

    Returns:
        SearchOutcome: Completed search result.
    """
    provider = get_provider(mission_id)
    radius_arcsec = parse_discovery_radius(radius_text, radius_unit)
    logger.info(
        "Discovery search for mission=%r target=%r radius=%.3f arcsec.",
        mission_id,
        target,
        radius_arcsec,
    )
    return run_catalog_search(
        provider,
        target,
        radius_arcsec,
        "arcsec",
        simbad_resolver=simbad_resolver,
    )


def catalog_rows_for_aggrid(catalog: Table) -> list[dict]:
    """Converts a provider catalogue table to AgGrid ``rowData``.

    Args:
        catalog (astropy.table.Table): Validated catalogue table.

    Returns:
        list[dict]: Rows including the display index column ``#``.
    """
    rows = catalog_table_to_row_dicts(catalog)
    return [
        {"#": index + 1, **{key: value for key, value in row.items() if key != "#"}}
        for index, row in enumerate(rows)
    ]
