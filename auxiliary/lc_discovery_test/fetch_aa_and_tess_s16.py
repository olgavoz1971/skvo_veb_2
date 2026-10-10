"""Download TESS-SPOC and QLP sector-16 light curves for AA And.

Uses the public ``lc_discovery`` surface (``search``, ``fetch``). Catalogue
rows are filtered on issued columns only; ``lc_key`` is passed to ``fetch``
unparsed. Issued VOTable bytes are written as-is.
"""

from __future__ import annotations

import re
from pathlib import Path

from astropy.coordinates import SkyCoord
from astropy.table import Table

from lc_discovery import fetch, list_missions, search

TARGET_NAME = "AA And"
MISSION_ID = "tess"
SECTOR = 16
AUTHORS = frozenset({"TESS-SPOC", "QLP"})
CONE_RADIUS_ARCSEC = 21.0
OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "aa_and_tess_sector16"
_SECTOR_IN_FILTER_NAME = re.compile(r"sector\s+(\d+)", re.IGNORECASE)


def _require_tess_mission() -> None:
    """Raises when TESS archive is not registered for public search.

    Raises:
        SystemExit: If ``tess`` is absent from ``list_missions()``.
    """
    mission_ids = {item.mission_id for item in list_missions()}
    if MISSION_ID not in mission_ids:
        raise SystemExit(
            "Mission 'tess' is not registered in lc_discovery.list_missions()."
        )


def _sector_from_filter_name(filter_name: str) -> int | None:
    """Reads the sector number from a TESS catalogue ``filter_name``.

    Args:
        filter_name (str): Value such as ``TESS TESS-SPOC sector 16 1800 s``.

    Returns:
        int or None: Sector when the label matches the provider spelling.
    """
    match = _SECTOR_IN_FILTER_NAME.search(str(filter_name))
    if match is None:
        return None
    return int(match.group(1))


def _select_sector16_ffi_rows(catalog: Table) -> Table:
    """Keeps TESS-SPOC and QLP rows for sector 16.

    Args:
        catalog (astropy.table.Table): Full TESS archive catalogue for the cone.

    Returns:
        astropy.table.Table: Filtered rows.
    """
    keep = []
    for row in catalog:
        author = str(row["survey"]).strip()
        sector = _sector_from_filter_name(str(row["filter_name"]))
        keep.append(author in AUTHORS and sector == SECTOR)
    return catalog[keep]


def _output_stem(row) -> str:
    """Builds a filesystem-safe stem from catalogue labels.

    Args:
        row: One catalogue row.

    Returns:
        str: Filename stem without extension.
    """
    raw = f"{row['object_name']}_{row['filter_name']}"
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")
    return cleaned or "tess_product"


def main() -> None:
    """Searches TESS for AA And and writes matching issued VOTables."""
    _require_tess_mission()
    coord = SkyCoord.from_name(TARGET_NAME)
    ra_deg = float(coord.ra.deg)
    dec_deg = float(coord.dec.deg)
    print(
        f"{TARGET_NAME}: RA={ra_deg:.8f} deg  Dec={dec_deg:.8f} deg  "
        f"cone radius={CONE_RADIUS_ARCSEC} arcsec"
    )

    catalog = search(
        MISSION_ID,
        ra_deg=ra_deg,
        dec_deg=dec_deg,
        radius_arcsec=CONE_RADIUS_ARCSEC,
    )
    selected = _select_sector16_ffi_rows(catalog)
    print(f"TESS catalogue rows in cone: {len(catalog)}")
    print(f"TESS-SPOC and QLP sector {SECTOR} rows: {len(selected)}")
    if len(selected) == 0:
        raise SystemExit(
            f"No TESS-SPOC or QLP catalogue rows for {TARGET_NAME} sector {SECTOR}."
        )

    names = {str(row["object_name"]) for row in selected}
    if len(names) != 1:
        raise SystemExit(
            f"Cone matched more than one TIC for {TARGET_NAME}: {sorted(names)}."
        )

    selected.pprint_all()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing issued VOTables under {OUTPUT_DIR}")

    for row in selected:
        lc_key = str(row["lc_key"])
        dest = OUTPUT_DIR / f"{_output_stem(row)}.vot"
        print(f"Fetching {row['filter_name']} -> {dest.name}")
        payload = fetch(lc_key)
        dest.write_bytes(payload)
        print(f"  wrote {len(payload)} bytes")


if __name__ == "__main__":
    main()
