"""Gaia DR3 (ARI) TAP ObsCore lightcurve provider."""

from __future__ import annotations

import logging

from astropy.table import Table

from skvo_veb.lc_providers.base import (
    MissionArchiveMatch,
    MissionCapabilities,
    MissionLightcurveProvider,
)
from skvo_veb.lc_providers.catalog_schema import empty_catalog_table
from skvo_veb.lc_providers.gaia_dr3_ari import config
from skvo_veb.lc_providers.gaia_dr3_ari.fetch_access_url import fetch_volightcurve_from_access_url
from skvo_veb.lc_providers.gaia_dr3_ari.fetch_metadata import enrich_fetched_volightcurve
from skvo_veb.lc_providers.gaia_dr3_ari.obscore_catalog import map_obscore_table_to_catalog
from skvo_veb.lc_providers.lc_key import decode_lc_key
from skvo_veb.lc_providers.shared.gaia_dr3_source_id import (
    format_gaia_source_name,
    parse_gaia_source_id,
    pick_gaia_archive_id_from_simbad,
)
from skvo_veb.lc_providers.tap.client import run_tap_sync_query
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.simbad_resolver import SimbadResolveResult
from skvo_veb.volightcurve import VOLightCurve

logger = logging.getLogger(__name__)


class GaiaDr3AriProvider(MissionLightcurveProvider):
    """Gaia DR3 epoch photometry via the Heidelberg ARI TAP ObsCore service."""

    mission_id = config.PROVIDER_ID
    display_name = config.DISPLAY_NAME
    export_profile = config.PROVIDER_ID
    capabilities = MissionCapabilities(
        supports_cone_search=True,
        supports_name_resolve=True,
        supports_id_lookup=True,
        supports_force_refresh=True,
        provides_catalog_epoch_period=True,
    )
    is_mock = False

    def default_search_radius_arcsec(self) -> float:
        """Returns the default cone radius for sky searches.

        Returns:
            float: Default search radius in arcseconds.
        """
        return 5.0

    def pick_archive_id_from_simbad(
        self,
        simbad_result: SimbadResolveResult,
    ) -> MissionArchiveMatch | None:
        """Selects a Gaia DR3 ``obs_id`` from Simbad cross-identifiers.

        Args:
            simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

        Returns:
            MissionArchiveMatch or None: Gaia archive match when recognised.
        """
        return pick_gaia_archive_id_from_simbad(simbad_result)

    def resolve_target_name(self, name: str) -> MissionArchiveMatch | None:
        """Parses Gaia DR3 ``source_id`` strings before Simbad name resolution.

        Args:
            name (str): Raw Target field text from the UI.

        Returns:
            MissionArchiveMatch or None: Gaia archive match when recognised.
        """
        source_id = parse_gaia_source_id(name)
        if source_id is None:
            return None
        label = format_gaia_source_name(source_id)
        return MissionArchiveMatch(
            archive_id=str(source_id),
            match_kind="gaia_source_id",
            matched_label=label,
        )

    def search_catalog(
        self,
        *,
        ra_deg: float | None = None,
        dec_deg: float | None = None,
        radius_arcsec: float | None = None,
        object_name: str | None = None,
        archive_id: str | None = None,
        time_start_mjd: float | None = None,
        time_end_mjd: float | None = None,
        **mission_options,
    ) -> Table:
        """Queries ARI ObsCore for bundled Gaia DR3 epoch photometry products.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Gaia ``source_id`` string from the UI.
            archive_id (str, optional): Gaia ``obs_id`` for direct lookup.
            time_start_mjd (float, optional): Lower time limit in MJD.
            time_end_mjd (float, optional): Upper time limit in MJD.
            **mission_options: Reserved for future provider options.

        Returns:
            astropy.table.Table: Standardised catalogue table (possibly empty).
        """
        obs_id = self._resolve_obs_id(
            archive_id=archive_id,
            object_name=object_name,
        )

        if obs_id is not None:
            adql = config.adql_catalog_by_obs_id(
                obs_id,
                time_start_mjd=time_start_mjd,
                time_end_mjd=time_end_mjd,
            )
            tap_table = run_tap_sync_query(
                config.TAP_URL,
                adql,
                dialect=config.TAP_QUERY_DIALECT,
            )
            return map_obscore_table_to_catalog(
                tap_table,
                provider_id=self.mission_id,
            )

        if ra_deg is not None and dec_deg is not None and radius_arcsec is not None:
            ra, dec, radius = self._require_cone_search(
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                radius_arcsec=radius_arcsec,
            )
            adql = config.adql_catalog_cone(
                ra_deg=ra,
                dec_deg=dec,
                radius_arcsec=radius,
                time_start_mjd=time_start_mjd,
                time_end_mjd=time_end_mjd,
            )
            tap_table = run_tap_sync_query(
                config.TAP_URL,
                adql,
                dialect=config.TAP_QUERY_DIALECT,
            )
            return map_obscore_table_to_catalog(
                tap_table,
                provider_id=self.mission_id,
                centre_ra_deg=ra,
                centre_dec_deg=dec,
            )

        return empty_catalog_table()

    def fetch_lightcurve(self, lc_key: str, *, force_refresh: bool = False) -> VOLightCurve:
        """Downloads one band from a bundled Gaia DR3 epoch photometry VOTable.

        Args:
            lc_key (str): Serialised fetch handle from a catalog row.
            force_refresh (bool): Accepted for API compatibility; no cache yet.

        Returns:
            VOLightCurve: VO-standard single-band lightcurve.

        Raises:
            PipeException: When the key is invalid or download fails.
        """
        if not self.validate_lc_key(lc_key):
            raise PipeException(f"{self.display_name}: invalid lightcurve key.")

        payload = decode_lc_key(lc_key)["payload"]
        access_url = payload.get("access_url")
        table_id = payload.get("table_id")
        filter_name = payload.get("filter_name")
        if not access_url:
            raise PipeException(f"{self.display_name}: lc_key payload missing access_url.")
        if table_id is None:
            raise PipeException(f"{self.display_name}: lc_key payload missing table_id.")
        if not filter_name:
            raise PipeException(f"{self.display_name}: lc_key payload missing filter_name.")

        logger.info(
            "%s fetch access_url=%s table_id=%s force_refresh=%s",
            self.display_name,
            str(access_url)[:64],
            table_id,
            force_refresh,
        )
        volc = fetch_volightcurve_from_access_url(
            str(access_url),
            table_id=int(table_id),
        )
        return enrich_fetched_volightcurve(volc, filter_name=str(filter_name))

    @staticmethod
    def _resolve_obs_id(
        *,
        archive_id: str | None,
        object_name: str | None,
    ) -> int | None:
        """Casts archive or UI text to a Gaia ``obs_id`` when possible.

        Args:
            archive_id (str, optional): Mission-native archive id string.
            object_name (str, optional): Target field text.

        Returns:
            int or None: Parsed Gaia source id.
        """
        for candidate in (archive_id, object_name):
            if candidate is None:
                continue
            source_id = parse_gaia_source_id(str(candidate))
            if source_id is not None:
                return source_id
        return None
