"""OGLE OCVS TAP lightcurve provider (UPJS SSA + accref fetch)."""

from __future__ import annotations

import logging

from astropy.table import Table

from skvo_veb.lc_providers.base import (
    MissionArchiveMatch,
    MissionCapabilities,
    MissionLightcurveProvider,
)
from skvo_veb.lc_providers.catalog_schema import empty_catalog_table
from skvo_veb.lc_providers.lc_key import decode_lc_key
from skvo_veb.lc_providers.ogle_ocvs import config
from skvo_veb.lc_providers.ogle_ocvs.fetch_accref import fetch_volightcurve_from_accref
from skvo_veb.lc_providers.ogle_ocvs.fetch_metadata import enrich_fetched_volightcurve
from skvo_veb.lc_providers.ogle_ocvs.object_id import (
    normalize_ogle_object_id,
    pick_ogle_archive_id_from_simbad,
)
from skvo_veb.lc_providers.ogle_ocvs.ssa_catalog import map_ssa_table_to_catalog
from skvo_veb.lc_providers.tap.client import run_tap_sync_query
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.simbad_resolver import SimbadResolveResult
from skvo_veb.volightcurve import VOLightCurve

logger = logging.getLogger(__name__)


class OgleOcvsProvider(MissionLightcurveProvider):
    """OGLE eclipsing variables via the UPJS ``ogle.ts_ssa`` TAP table."""

    mission_id = config.PROVIDER_ID
    display_name = config.DISPLAY_NAME
    export_profile = config.PROVIDER_ID
    capabilities = MissionCapabilities(
        supports_cone_search=True,
        supports_id_lookup=True,
        supports_force_refresh=True,
    )
    is_mock = False

    def default_search_radius_arcsec(self) -> float:
        """Returns the default cone radius for sky searches.

        Returns:
            float: Default search radius in arcseconds.
        """
        return 15.0

    def pick_archive_id_from_simbad(
        self,
        simbad_result: SimbadResolveResult,
    ) -> MissionArchiveMatch | None:
        """Selects an OGLE ``object_id`` from Simbad cross-identifiers.

        Args:
            simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

        Returns:
            MissionArchiveMatch or None: OGLE archive match when recognised.
        """
        return pick_ogle_archive_id_from_simbad(simbad_result)

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
        """Queries ``ogle.ts_ssa`` for plottable OGLE lightcurve products.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): OGLE ``object_id`` or loose Simbad spelling.
            archive_id (str, optional): OGLE ``object_id`` for direct lookup.
            time_start_mjd (float, optional): Lower time limit in MJD.
            time_end_mjd (float, optional): Upper time limit in MJD.
            **mission_options: Reserved for future provider options.

        Returns:
            astropy.table.Table: Standardised catalog table (possibly empty).
        """
        object_id = self._resolve_object_id(
            archive_id=archive_id,
            object_name=object_name,
        )

        if object_id is not None:
            adql = config.adql_catalog_by_object_id(
                object_id,
                time_start_mjd=time_start_mjd,
                time_end_mjd=time_end_mjd,
            )
            tap_table = run_tap_sync_query(
                config.TAP_URL,
                adql,
                dialect=config.TAP_QUERY_DIALECT,
            )
            return map_ssa_table_to_catalog(
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
            return map_ssa_table_to_catalog(
                tap_table,
                provider_id=self.mission_id,
                centre_ra_deg=ra,
                centre_dec_deg=dec,
            )

        return empty_catalog_table()

    def fetch_lightcurve(self, lc_key: str, *, force_refresh: bool = False) -> VOLightCurve:
        """Downloads one lightcurve from the SSA row ``accref`` URL.

        Args:
            lc_key (str): Serialised fetch handle from a catalog row.
            force_refresh (bool): Accepted for API compatibility; no cache yet.

        Returns:
            VOLightCurve: VO-standard lightcurve from the remote product URL.

        Raises:
            PipeException: When the key is invalid or download fails.
        """
        if not self.validate_lc_key(lc_key):
            raise PipeException(f"{self.display_name}: invalid lightcurve key.")

        payload = decode_lc_key(lc_key)["payload"]
        accref = payload.get("accref")
        if not accref:
            raise PipeException(f"{self.display_name}: lc_key payload missing accref.")

        filter_name = payload.get("filter_name")
        if not filter_name:
            raise PipeException(f"{self.display_name}: lc_key payload missing filter_name.")

        logger.info(
            "OGLE OCVS fetch accref=%s force_refresh=%s",
            str(accref)[:64],
            force_refresh,
        )
        volc = fetch_volightcurve_from_accref(str(accref))
        return enrich_fetched_volightcurve(
            volc,
            filter_name=str(filter_name),
            object_id=payload.get("object_id"),
        )

    @staticmethod
    def _resolve_object_id(
        *,
        archive_id: str | None,
        object_name: str | None,
    ) -> str | None:
        """Normalises archive or UI text to an OGLE ``object_id`` when possible.

        Args:
            archive_id (str, optional): Mission-native archive id string.
            object_name (str, optional): Target field text.

        Returns:
            str or None: Canonical OGLE object id.
        """
        for candidate in (archive_id, object_name):
            if candidate is None:
                continue
            object_id = normalize_ogle_object_id(str(candidate))
            if object_id is not None:
                return object_id
        return None
