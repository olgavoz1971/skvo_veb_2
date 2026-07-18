"""Abstract base contract for multi-mission lightcurve providers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from astropy.coordinates import SkyCoord
from astropy.table import Table

from skvo_veb.lc_providers.lc_key import cache_key, validate_lc_key
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.volightcurve import VOLightCurve

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MissionCapabilities:
    """Feature flags describing what a mission provider supports."""

    supports_cone_search: bool = False
    supports_name_resolve: bool = False
    supports_id_lookup: bool = False
    supports_force_refresh: bool = False
    provides_catalog_epoch_period: bool = False


@dataclass(frozen=True)
class MissionDescriptor:
    """Lightweight mission metadata for UI registries."""

    mission_id: str
    display_name: str
    export_profile: str
    capabilities: MissionCapabilities
    is_mock: bool = False


@dataclass(frozen=True)
class MissionArchiveMatch:
    """Mission-native archive identifier selected from a Simbad cross-match."""

    archive_id: str
    match_kind: str
    matched_label: str


class MissionLightcurveProvider(ABC):
    """Mission adapter: catalog search and VO-standard lightcurve fetch."""

    mission_id: str
    display_name: str
    export_profile: str
    capabilities: MissionCapabilities
    is_mock: bool = False

    @abstractmethod
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
        """Returns a standardised catalog table for the requested search.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Catalogue name or identifier.
            archive_id (str, optional): Mission-native archive id for direct lookup.
            time_start_mjd (float, optional): Lower time limit in MJD; ``None`` is
                unbounded below (include all data from the beginning).
            time_end_mjd (float, optional): Upper time limit in MJD; ``None`` is
                unbounded above (include all data to the end).
            **mission_options: Mission-specific options.

        Returns:
            astropy.table.Table: Validated catalog table (possibly empty).
        """

    @abstractmethod
    def fetch_lightcurve(self, lc_key: str, *, force_refresh: bool = False) -> VOLightCurve:
        """Fetches one lightcurve and returns a VO-standard in-memory object.

        Args:
            lc_key (str): Opaque fetch handle from a catalog row.
            force_refresh (bool): When True, bypass provider-local caches.

        Returns:
            VOLightCurve: Parsed VO lightcurve compliant with the skvo_veb profile.
        """

    def resolve_name(self, name: str) -> SkyCoord | None:
        """Resolves an object name to ICRS coordinates when supported.

        Args:
            name (str): User-supplied target name.

        Returns:
            SkyCoord or None: Resolved coordinates, or ``None`` if unsupported.
        """
        return None

    def pick_archive_id_from_simbad(self, simbad_result) -> MissionArchiveMatch | None:
        """Picks this mission's archive identifier from a Simbad resolve result.

        Args:
            simbad_result: ``SimbadResolveResult`` from ``utils.simbad_resolver``.

        Returns:
            MissionArchiveMatch or None: Mission-native id when recognised.
        """
        return None

    def validate_lc_key(self, lc_key: str) -> bool:
        """Checks whether ``lc_key`` belongs to this mission.

        Args:
            lc_key (str): Serialised fetch handle.

        Returns:
            bool: True when the key is valid for this provider.
        """
        return validate_lc_key(lc_key, mission_id=self.mission_id)

    def cache_key(self, lc_key: str) -> str:
        """Returns a normalised fetch cache hash for ``lc_key``.

        Args:
            lc_key (str): Serialised fetch handle.

        Returns:
            str: SHA-256 hex digest.
        """
        if not self.validate_lc_key(lc_key):
            raise PipeException(f"{self.display_name}: invalid lightcurve key.")
        return cache_key(lc_key)

    def default_search_radius_arcsec(self) -> float:
        """Returns the mission default cone radius in arcseconds.

        Returns:
            float: Suggested search radius for the UI.
        """
        return 10.0

    def descriptor(self) -> MissionDescriptor:
        """Builds registry metadata for UI mission selectors.

        Returns:
            MissionDescriptor: Mission identity and capability summary.
        """
        return MissionDescriptor(
            mission_id=self.mission_id,
            display_name=self.display_name,
            export_profile=self.export_profile,
            capabilities=self.capabilities,
            is_mock=self.is_mock,
        )

    def _require_cone_search(
        self,
        *,
        ra_deg: float | None,
        dec_deg: float | None,
        radius_arcsec: float | None,
    ) -> tuple[float, float, float]:
        """Validates cone-search arguments shared by cone-capable missions.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.

        Returns:
            tuple[float, float, float]: Validated ``(ra_deg, dec_deg, radius_arcsec)``.

        Raises:
            PipeException: When required values are missing or invalid.
        """
        if ra_deg is None or dec_deg is None or radius_arcsec is None:
            raise PipeException(
                f"{self.display_name}: cone search requires RA, Dec, and radius."
            )
        try:
            ra = float(ra_deg)
            dec = float(dec_deg)
            radius = float(radius_arcsec)
        except (TypeError, ValueError) as exc:
            raise PipeException(
                f"{self.display_name}: RA, Dec, and radius must be numeric."
            ) from exc
        if radius <= 0:
            raise PipeException(f"{self.display_name}: search radius must be positive.")
        return ra, dec, radius
