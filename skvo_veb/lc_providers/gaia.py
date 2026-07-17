"""Mock/template Gaia DR3 lightcurve provider for Lightcurve Discovery development.

This adapter returns synthetic catalog rows and epoch photometry. It demonstrates
the provider contract without remote VO queries. Replace internals with pyvo /
Gaia archive access in a later step; keep the public API unchanged.
"""

from __future__ import annotations

import io
import logging
import re

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from skvo_veb.lc_providers.base import (
    MissionArchiveMatch,
    MissionCapabilities,
    MissionLightcurveProvider,
)
from skvo_veb.lc_providers.catalog_schema import empty_catalog_table, validate_catalog_table
from skvo_veb.lc_providers.lc_key import decode_lc_key, encode_lc_key
from skvo_veb.utils.lc_config import JD_TO_MJD
from skvo_veb.utils.mission_config import gaia as gaia_config
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.simbad_resolver import SimbadResolveResult
from skvo_veb.volightcurve import VOLightCurve, write_vo_lightcurve

logger = logging.getLogger(__name__)

_GAIA_ID_PATTERN = re.compile(r"^\d{10,22}$")
_GAIA_PREFIX_PATTERN = re.compile(
    r"^\s*(?:Gaia\s*DR\s*3|GAIADR3)\s*([0-9]{10,22})\s*$",
    re.IGNORECASE,
)

_MOCK_SOURCE_OFFSETS = (
    {"source_id": 1111111111111111111, "delta_ra_arcsec": 0.0, "delta_dec_arcsec": 0.0, "g_mag": 12.34},
    {"source_id": 2222222222222222222, "delta_ra_arcsec": 2.5, "delta_dec_arcsec": -1.2, "g_mag": 14.08},
    {"source_id": 3333333333333333333, "delta_ra_arcsec": -4.0, "delta_dec_arcsec": 3.1, "g_mag": 15.72},
)

_MOCK_SOURCE_BY_ID = {entry["source_id"]: entry for entry in _MOCK_SOURCE_OFFSETS}


def parse_gaia_source_id(text: str | None) -> int | None:
    """Parses a Gaia DR3 ``source_id`` from a user or Simbad identifier string.

    Args:
        text (str, optional): Raw identifier such as ``Gaia DR3 123…`` or digits.

    Returns:
        int or None: Gaia source id when recognised.
    """
    if text is None:
        return None
    candidate = str(text).strip()
    if not candidate:
        return None
    prefix_match = _GAIA_PREFIX_PATTERN.match(candidate)
    if prefix_match:
        return int(prefix_match.group(1))
    compact = candidate.replace(" ", "")
    if _GAIA_ID_PATTERN.match(compact):
        return int(compact)
    return None


class GaiaDr3Provider(MissionLightcurveProvider):
    """Template Gaia DR3 provider with deterministic mock search/fetch data."""

    mission_id = gaia_config.MISSION_ID
    display_name = "Gaia DR3 (mock)"
    export_profile = gaia_config.MISSION_ID
    capabilities = MissionCapabilities(
        supports_cone_search=True,
        supports_id_lookup=True,
        supports_force_refresh=True,
    )
    is_mock = True

    def default_search_radius_arcsec(self) -> float:
        """Returns the template default cone radius.

        Returns:
            float: Default search radius in arcseconds.
        """
        return 10.0

    def pick_archive_id_from_simbad(self, simbad_result: SimbadResolveResult) -> MissionArchiveMatch | None:
        """Selects a Gaia DR3 source id from Simbad cross-identifiers.

        Args:
            simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

        Returns:
            MissionArchiveMatch or None: Gaia source id when present in Simbad ids.
        """
        for identifier in simbad_result.identifiers:
            source_id = parse_gaia_source_id(identifier)
            if source_id is None:
                continue
            label = gaia_config.format_source_name(source_id)
            return MissionArchiveMatch(
                archive_id=str(source_id),
                match_kind="gaia_source_id",
                matched_label=label,
            )
        return None

    def search_catalog(
        self,
        *,
        ra_deg: float | None = None,
        dec_deg: float | None = None,
        radius_arcsec: float | None = None,
        object_name: str | None = None,
        archive_id: str | None = None,
        **mission_options,
    ) -> Table:
        """Returns mock Gaia DR3 catalogue rows for cone or direct-id queries.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Gaia id string or other mission-specific name.
            archive_id (str, optional): Gaia ``source_id`` for direct lookup.
            **mission_options: Reserved for future Gaia-specific filters.

        Returns:
            astropy.table.Table: Standardised catalog table (possibly empty).
        """
        if archive_id is not None:
            source_id = parse_gaia_source_id(str(archive_id))
            if source_id is None:
                return empty_catalog_table()
            return self._catalog_by_source_id(source_id)

        if object_name:
            source_id = parse_gaia_source_id(object_name)
            if source_id is not None:
                return self._catalog_by_source_id(source_id)
            return empty_catalog_table()

        if ra_deg is not None and dec_deg is not None and radius_arcsec is not None:
            return self._catalog_cone(ra_deg=ra_deg, dec_deg=dec_deg, radius_arcsec=radius_arcsec)

        return empty_catalog_table()

    def _catalog_by_source_id(self, source_id: int) -> Table:
        """Builds a direct-id mock catalogue row for one Gaia source.

        Args:
            source_id (int): Gaia DR3 source identifier.

        Returns:
            astropy.table.Table: One-row catalogue or empty when unsupported.
        """
        template = _MOCK_SOURCE_BY_ID.get(source_id)
        if template is not None:
            ra_deg = 100.0 + template["delta_ra_arcsec"] / 3600.0
            dec_deg = 10.0 + template["delta_dec_arcsec"] / 3600.0
            g_mag = template["g_mag"]
            distance_arcsec = 0.0
        else:
            ra_deg = 180.0 + (source_id % 1000) * 0.001
            dec_deg = -20.0 + (source_id % 997) * 0.001
            g_mag = 12.0 + (source_id % 50) * 0.05
            distance_arcsec = np.nan

        row = self._build_catalog_row(
            source_id=source_id,
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            g_mag=g_mag,
            distance_arcsec=distance_arcsec,
            provider_note="Mock Gaia DR3 direct source_id lookup",
        )
        return validate_catalog_table(Table([row]))

    def _catalog_cone(self, *, ra_deg: float, dec_deg: float, radius_arcsec: float) -> Table:
        """Returns mock sources within a cone around the supplied centre.

        Args:
            ra_deg (float): Cone centre right ascension in degrees.
            dec_deg (float): Cone centre declination in degrees.
            radius_arcsec (float): Cone radius in arcseconds.

        Returns:
            astropy.table.Table: Standardised catalog table (possibly empty).
        """
        ra, dec, radius = self._require_cone_search(
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            radius_arcsec=radius_arcsec,
        )
        centre = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
        rows = []
        for template in _MOCK_SOURCE_OFFSETS:
            source_coord = centre.spherical_offsets_by(
                template["delta_ra_arcsec"] * u.arcsec,
                template["delta_dec_arcsec"] * u.arcsec,
            )
            separation = centre.separation(source_coord).to_value(u.arcsec)
            if separation > radius:
                continue
            rows.append(
                self._build_catalog_row(
                    source_id=template["source_id"],
                    ra_deg=float(source_coord.ra.deg),
                    dec_deg=float(source_coord.dec.deg),
                    g_mag=template["g_mag"],
                    distance_arcsec=separation,
                    provider_note="Mock Gaia DR3 cone search row",
                )
            )
        if not rows:
            return empty_catalog_table()
        return validate_catalog_table(Table(rows))

    def _build_catalog_row(
        self,
        *,
        source_id: int,
        ra_deg: float,
        dec_deg: float,
        g_mag: float,
        distance_arcsec: float,
        provider_note: str,
    ) -> dict:
        """Builds one standardised catalogue row dict for the mock provider.

        Args:
            source_id (int): Gaia source identifier.
            ra_deg (float): Source right ascension in degrees.
            dec_deg (float): Source declination in degrees.
            g_mag (float): Mock G-band magnitude.
            distance_arcsec (float): Separation from search centre in arcseconds.
            provider_note (str): Row annotation for the UI.

        Returns:
            dict: Row payload matching the shared catalogue schema.
        """
        band = gaia_config.GAIA_G_BAND
        lc_key = encode_lc_key(
            self.mission_id,
            {
                "source_id": source_id,
                "band": band,
                "ra_deg": ra_deg,
                "dec_deg": dec_deg,
            },
        )
        return {
            "distance_arcsec": distance_arcsec,
            "ra_deg": ra_deg,
            "dec_deg": dec_deg,
            "object_name": gaia_config.format_source_name(source_id),
            "filter_name": gaia_config.GAIA_G_FILTER_NAME,
            "lc_key": lc_key,
            "filter_identifier": gaia_config.GAIA_G_FILTER_IDENTIFIER,
            "n_points": 24,
            "mag": g_mag,
            "survey": gaia_config.GAIA_SURVEY,
            "provider_note": provider_note,
        }

    def fetch_lightcurve(self, lc_key: str, *, force_refresh: bool = False) -> VOLightCurve:
        """Builds a synthetic Gaia G-band lightcurve for the requested ``lc_key``.

        Args:
            lc_key (str): Serialised fetch handle from a catalog row.
            force_refresh (bool): Accepted for API compatibility; mock data is deterministic.

        Returns:
            VOLightCurve: VO-standard lightcurve parsed from generated VOTable bytes.
        """
        if not self.validate_lc_key(lc_key):
            raise PipeException(f"{self.display_name}: invalid lightcurve key.")

        document = decode_lc_key(lc_key)
        payload = document["payload"]
        source_id = payload.get("source_id")
        band = payload.get("band", gaia_config.GAIA_G_BAND)
        ra_deg = payload.get("ra_deg", 0.0)
        dec_deg = payload.get("dec_deg", 0.0)
        if source_id is None:
            raise PipeException(f"{self.display_name}: lc_key payload missing source_id.")

        table = _build_mock_epoch_table(source_id=int(source_id))
        buffer = io.BytesIO()
        write_vo_lightcurve(
            buffer,
            table,
            **gaia_config.build_fetch_votable_kwargs(
                source_id=source_id,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                band=band,
            ),
        )
        buffer.seek(0)
        volc = VOLightCurve(buffer)
        logger.info(
            "Gaia mock fetch source_id=%s band=%s n_points=%s force_refresh=%s",
            source_id,
            band,
            len(volc),
            force_refresh,
        )
        return volc


def _build_mock_epoch_table(source_id: int) -> Table:
    """Creates deterministic mock Gaia epoch photometry for one source.

    Args:
        source_id (int): Gaia source identifier used to seed the synthetic curve.

    Returns:
        astropy.table.Table: Table with ``obs_time``, ``phot``, and ``flux_error``.
    """
    rng = np.random.default_rng(source_id % (2**32))
    n_points = 24
    base_mjd = 59000.0 + (source_id % 1000) * 0.01
    obs_time = base_mjd + np.sort(rng.uniform(0.0, 400.0, n_points))
    base_mag = 12.0 + (source_id % 97) * 0.01
    phot = base_mag + 0.08 * np.sin(np.linspace(0.0, 4.0 * np.pi, n_points))
    phot += rng.normal(0.0, 0.01, n_points)
    flux_error = np.clip(rng.normal(0.015, 0.004, n_points), 0.005, None)

    table = Table()
    table["obs_time"] = obs_time
    table["phot"] = phot
    table["flux_error"] = flux_error
    table.meta["time_unit_note"] = f"MJD with origin {JD_TO_MJD}"
    return table
