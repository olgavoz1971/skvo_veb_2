"""Print every ``lc_discovery`` catalogue hit for AA And.

Uses only the public package surface: ``list_missions``, ``search``,
``resolve_target``. Search kinds follow each mission's capability flags.
"""

from __future__ import annotations

from astropy.coordinates import SkyCoord

from lc_discovery import list_missions, resolve_target, search

TARGET_NAME = "AA And"
CONE_RADIUS_ARCSEC = 10.0


def _print_catalog(catalog) -> None:
    """Prints every catalogue row, including opaque ``lc_key``.

    Args:
        catalog (astropy.table.Table): Mission catalogue returned by ``search``.
    """
    if len(catalog) == 0:
        print("  (no rows)")
        return
    catalog.pprint_all()


def search_mission(mission, *, ra_deg: float, dec_deg: float):
    """Searches one mission for AA And using the documented search kinds.

    Tries name lookup, then native ``resolve_target`` plus archive-id search,
    then a cone at the Sesame position. Only kinds allowed by the mission
    capabilities are called.

    Args:
        mission: Descriptor from ``list_missions()``.
        ra_deg (float): ICRS right ascension of AA And in degrees.
        dec_deg (float): ICRS declination of AA And in degrees.

    Returns:
        tuple: ``(kind, catalog)`` where ``kind`` is ``object_name``,
        ``archive_id``, or ``cone``. ``catalog`` may be empty after cone
        search. Returns ``(None, None)`` when the mission accepts none of
        those kinds.
    """
    caps = mission.capabilities
    mission_id = mission.mission_id

    if caps.supports_name_resolve:
        catalog = search(mission_id, object_name=TARGET_NAME)
        if len(catalog) > 0:
            return "object_name", catalog

    if caps.supports_id_lookup:
        match = resolve_target(mission_id, TARGET_NAME)
        if match is not None:
            catalog = search(mission_id, archive_id=match.archive_id)
            if len(catalog) > 0:
                return "archive_id", catalog

    if caps.supports_cone_search:
        catalog = search(
            mission_id,
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            radius_arcsec=CONE_RADIUS_ARCSEC,
        )
        return "cone", catalog

    return None, None


def main() -> None:
    """Resolves AA And and prints catalogue results for every registered mission."""
    coord = SkyCoord.from_name(TARGET_NAME)
    ra_deg = float(coord.ra.deg)
    dec_deg = float(coord.dec.deg)
    print(
        f"{TARGET_NAME}: RA={ra_deg:.8f} deg  Dec={dec_deg:.8f} deg  "
        f"cone radius={CONE_RADIUS_ARCSEC} arcsec"
    )
    print()

    for mission in list_missions():
        caps = mission.capabilities
        print("=" * 72)
        print(f"{mission.display_name}  ({mission.mission_id})")
        print(
            "  capabilities: "
            f"cone={caps.supports_cone_search} "
            f"name={caps.supports_name_resolve} "
            f"id={caps.supports_id_lookup}"
        )
        try:
            kind, catalog = search_mission(
                mission, ra_deg=ra_deg, dec_deg=dec_deg
            )
        except Exception as exc:
            print(f"  search failed: {exc}")
            print()
            continue
        if kind is None:
            print("  no supported search kind")
            print()
            continue
        print(f"  search kind: {kind}  rows: {len(catalog)}")
        _print_catalog(catalog)
        print()


if __name__ == "__main__":
    main()
