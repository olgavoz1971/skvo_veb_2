#!/usr/bin/env python3
"""Trace an OGLE lightcurve through every skvo_veb ingestion and export layer.

Downloads the OGLE OCVS V-band product, then prints the data structure at each
pipeline stage so photcal-by-reference (PARAMref) handling can be inspected
without touching application code.

Usage (from repository root)::

    .venv/bin/python scripts/trace_ogle_lightcurve_flow.py

Optional arguments::

    .venv/bin/python scripts/trace_ogle_lightcurve_flow.py --url <accref-url>
    .venv/bin/python scripts/trace_ogle_lightcurve_flow.py --head 5

This script is diagnostic only. It does not modify files or caches.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import textwrap
import urllib.request
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import astropy.io.votable as vot
from astropy.io.votable.tree import ParamRef

from gavo.votable import votparse
from skvo_veb.lc_providers.ogle_ocvs.fetch_accref import fetch_volightcurve_from_accref
from skvo_veb.lc_providers.ogle_ocvs.fetch_metadata import enrich_fetched_volightcurve
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import (
    _extract_photcal_meta,
    _serialise_photcal_group,
    build_votable_kwargs_from_metadata,
    export_curvedash,
    volc_to_curvedash,
)
from skvo_veb.utils.lc_config import VOTABLE_FORMAT_BINARY
from skvo_veb.utils.lc_discovery_load import drop_invalid_photometry_rows
from skvo_veb.volightcurve import VOLightCurve
from skvo_veb.volightcurve.lightcurve import extract_photdm

DEFAULT_OGLE_ACCREF = (
    "https://skvo.science.upjs.sk/ogle/q/sdl/dlget?"
    "ID=ivo://astro.upjs/~?ogle/q/OGLE-SMC-ECL-05425-V"
)

logger = logging.getLogger(__name__)


def _banner(title: str, *, char: str = "=") -> None:
    """Prints a visible section header.

    Args:
        title (str): Section title.
        char (str): Border character.
    """
    line = char * max(72, len(title) + 4)
    print(f"\n{line}\n  {title}\n{line}")


def _json_block(label: str, payload: Any) -> None:
    """Prints a labelled JSON block.

    Args:
        label (str): Block heading.
        payload (Any): JSON-serialisable object.
    """
    print(f"\n{label}:")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _quantity_repr(value: Any) -> str:
    """Formats an Astropy quantity or scalar for display.

    Args:
        value (Any): Quantity or plain scalar.

    Returns:
        str: Human-readable representation.
    """
    if value is None:
        return "None"
    if hasattr(value, "unit"):
        return f"{value!r}"
    return repr(value)


def _describe_photdm_map(label: str, photdms: dict) -> None:
    """Prints PhotDM entries keyed by column name.

    Args:
        label (str): Heading for this map.
        photdms (dict): ``column_name -> PhotDM`` mapping.
    """
    print(f"\n{label} ({len(photdms)} entries):")
    if not photdms:
        print("  (empty)")
        return
    for colname, photdm in photdms.items():
        print(f"  [{colname!r}] {photdm!r}")
        phot_filter = photdm.filter
        photcal = photdm.photcal
        if phot_filter is not None:
            print(
                "    filter.filter_id = "
                f"{phot_filter.filter_id!r}"
            )
            print(
                "    filter.spectral_location = "
                f"{_quantity_repr(phot_filter.spectral_location)}"
            )
        if photcal is not None:
            print(f"    photcal.zp_flux = {_quantity_repr(photcal.zp_flux)}")
            print(f"    photcal.zp_mag = {_quantity_repr(photcal.zp_mag)}")
            print(f"    photcal.mag_sys = {photcal.mag_sys!r}")


def _describe_astropy_table(table, *, head: int) -> None:
    """Prints column and table-level metadata for an Astropy table.

    Args:
        table: ``astropy.table.Table`` instance.
        head (int): Number of data rows to preview.
    """
    print(f"\nTable name: {table.meta.get('name')!r}")
    print(f"Row count: {len(table)}")
    print("\nColumns:")
    for name in table.colnames:
        col = table[name]
        ucd = (col.info.meta or {}).get("ucd", "")
        unit = col.unit
        print(f"  - {name}: unit={unit!r} ucd={ucd!r}")
    print("\nSelected TABLE/PARAM metadata keys:")
    for key in sorted(table.meta):
        if key.startswith("comments"):
            continue
        print(f"  {key} = {table.meta[key]!r}")
    if head > 0 and len(table):
        print(f"\nFirst {head} data rows:")
        print(table[:head])


def _describe_raw_votable_photcal(payload: bytes) -> None:
    """Prints the raw ``photcal`` GROUP from the downloaded VOTable.

    Highlights ``PARAM`` vs ``PARAMref`` entries — OGLE uses references to table
    PARAM elements (``fps_filter_id``, ``zeropoint``, ``ssa_specmid``).

    Args:
        payload (bytes): Raw VOTable bytes.
    """
    tree = vot.parse(io.BytesIO(payload))
    table = tree.get_first_table()
    print("\nReferenced TABLE PARAM elements used by photcal GROUP:")
    for param in table.params:
        print(
            f"  @{param.ID or param.name}: name={param.name!r} "
            f"utype={getattr(param, 'utype', None)!r} "
            f"unit={getattr(param, 'unit', None)!r} value={param.value!r}"
        )

    for resource in tree.resources:
        for group in resource.groups:
            if group.name != "photcal":
                continue
            print("\nphotcal GROUP entries (as parsed by astropy.io.votable):")
            for entry in group.entries:
                cls = type(entry).__name__
                ref = getattr(entry, "ref", None)
                utype = getattr(entry, "utype", None)
                value = getattr(entry, "value", None)
                note = "  <-- PARAMref resolved by GAVO extract_photdm()" if cls == "ParamRef" else ""
                print(
                    f"  {cls}: ref={ref!r} utype={utype!r} value={value!r}{note}"
                )


def _describe_gavo_photdm(payload: bytes) -> None:
    """Prints PhotDM extracted by the GAVO walker (VOLightCurve authority).

    Args:
        payload (bytes): Raw VOTable bytes.
    """
    gavo_tree = votparse.readRaw(io.BytesIO(payload))
    gavo_map = extract_photdm(gavo_tree)
    _describe_photdm_map("extract_photdm() GAVO walker [VOLightCurve PhotDM path]", gavo_map)


def _describe_volightcurve(volc: VOLightCurve, *, head: int) -> None:
    """Prints the ingested VOLightCurve view used by the bridge.

    Args:
        volc (VOLightCurve): Parsed product.
        head (int): Number of rows to preview.
    """
    print(f"\nVOLightCurve repr: {volc!r}")
    print(f"timesys: {volc.timesys!r}")
    print(f"coosys: {volc.coosys!r}")
    print(f"jd0 (timesys.timeorigin): {volc.timesys.jd0}")
    _describe_astropy_table(volc.table, head=head)
    _describe_photdm_map("volc.photdms after VOLightCurve._ingest()", volc.photdms)


def _describe_bridge_photcal(volc: VOLightCurve) -> None:
    """Prints bridge-level photcal serialisation for the primary phot column.

    Args:
        volc (VOLightCurve): Parsed product.
    """
    phot_col = "phot" if "phot" in volc.table.colnames else volc.table.colnames[0]
    photdm = volc.photdms.get(phot_col)
    print(f"\nPrimary photometry column: {phot_col!r}")
    print(f"PhotDM object used by bridge: {photdm!r}")
    serialised = _serialise_photcal_group(photdm, volc.table.meta or {})
    _json_block("_serialise_photcal_group(photdm, table.meta)", serialised)
    _json_block("_extract_photcal_meta(volc, phot_col)", _extract_photcal_meta(volc, phot_col))


def _describe_curvedash(lcd: CurveDash, *, head: int) -> None:
    """Prints CurveDash state after ``volc_to_curvedash``.

    Args:
        lcd (CurveDash): Application lightcurve container.
        head (int): Number of rows to preview.
    """
    print(f"\nCurveDash title: {lcd.title!r}")
    print(f"active_domain: {lcd.active_domain!r}")
    print(f"period: {lcd.period!r}  epoch: {lcd.epoch!r}")
    _json_block("metadata (selected keys)", {
        "photcal": (lcd.metadata or {}).get("photcal"),
        "vo_envelope": (lcd.metadata or {}).get("vo_envelope"),
        "title": (lcd.metadata or {}).get("title"),
    })
    if lcd.lightcurve is None:
        print("\nlightcurve DataFrame: None")
        return
    print(f"\nlightcurve DataFrame columns: {list(lcd.lightcurve.columns)}")
    print(f"Row count: {len(lcd.lightcurve)}")
    if head > 0:
        print(lcd.lightcurve.head(head).to_string())


def _describe_export(lcd: CurveDash) -> VOLightCurve | None:
    """Exports CurveDash and re-ingests the VOTable for comparison.

    Args:
        lcd (CurveDash): Application lightcurve container.

    Returns:
        VOLightCurve or None: Round-tripped exported product, or None when export fails.
    """
    try:
        kwargs = build_votable_kwargs_from_metadata(lcd)
    except Exception as exc:
        print(f"\nbuild_votable_kwargs_from_metadata(lcd) FAILED: {exc}")
        print(
            "Export stops here — inspect Stage 5 photcal metadata and "
            "Stage 2 PARAMref resolution."
        )
        return None

    _json_block("build_votable_kwargs_from_metadata(lcd)", kwargs)
    try:
        exported = export_curvedash(lcd, VOTABLE_FORMAT_BINARY)
    except Exception as exc:
        print(f"\nexport_curvedash(lcd) FAILED: {exc}")
        return None

    print(f"\nExported VOTable size: {len(exported)} bytes")
    roundtrip = VOLightCurve(io.BytesIO(exported))
    print("\nRe-ingested export VOLightCurve:")
    _describe_volightcurve(roundtrip, head=0)
    return roundtrip


def _summary_diagnosis(volc: VOLightCurve, payload: bytes) -> None:
    """Prints a short diagnosis of photcal reference resolution.

    Args:
        volc (VOLightCurve): Parsed archive product.
        payload (bytes): Raw VOTable bytes.
    """
    gavo_tree = votparse.readRaw(io.BytesIO(payload))
    gavo_map = extract_photdm(gavo_tree)

    has_paramref = False
    astro_tree = vot.parse(io.BytesIO(payload))
    for resource in astro_tree.resources:
        for group in resource.groups:
            if group.name != "photcal":
                continue
            has_paramref = any(isinstance(entry, ParamRef) for entry in group.entries)

    ingested = volc.photdms.get("phot")
    gavo = gavo_map.get("phot")

    print(textwrap.dedent(
        f"""
        Quick diagnosis
        ---------------
        - Source uses PARAMref in photcal GROUP: {has_paramref}
        - VOLightCurve PhotDM extractor: extract_photdm() (GAVO walker)
        - Ingested phot.filter_id: {getattr(getattr(ingested, 'filter', None), 'filter_id', None)!r}
        - GAVO extract_photdm filter_id: {getattr(getattr(gavo, 'filter', None), 'filter_id', None)!r}
        - Table meta fps_filter_id: {(volc.table.meta or {}).get('fps_filter_id')!r}
        - Table meta zeropoint: {(volc.table.meta or {}).get('zeropoint')!r}
        - Table meta ssa_specmid: {(volc.table.meta or {}).get('ssa_specmid')!r}
        """
    ).strip())

    if ingested is not None and gavo is not None and ingested != gavo:
        print("\nNOTE: ingested PhotDM differs from a fresh GAVO extract_photdm() call.")


def run_trace(*, accref: str, head: int) -> int:
    """Executes the full layer-by-layer trace.

    Args:
        accref (str): OGLE accref URL.
        head (int): Preview row count per stage.

    Returns:
        int: Process exit code (0 = success).
    """
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    _banner("Stage 0 — Download raw VOTable")
    print(f"URL: {accref}")
    request = urllib.request.Request(accref, headers={"User-Agent": "skvo_veb/trace_script"})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    print(f"Downloaded {len(payload)} bytes")

    _banner("Stage 1 — Raw VOTable photcal GROUP (PARAM / PARAMref)")
    _describe_raw_votable_photcal(payload)

    _banner("Stage 2 — GAVO PhotDM extraction (VOLightCurve authority)")
    _describe_gavo_photdm(payload)

    _banner("Stage 3 — VOLightCurve ingestion (provider fetch_accref path)")
    volc = fetch_volightcurve_from_accref(accref)
    _describe_volightcurve(volc, head=head)

    _banner("Stage 4 — Provider metadata enrichment")
    volc = enrich_fetched_volightcurve(
        volc,
        filter_name="OGLE V",
        object_id="OGLE-SMC-ECL-05425",
    )
    print(f"TABLE name: {volc.table.meta.get('name')!r}")
    print(f"lightcurve_title: {volc.table.meta.get('lightcurve_title')!r}")

    _banner("Stage 5 — Bridge: volc_to_curvedash()")
    lcd = volc_to_curvedash(volc, "OGLE-SMC-ECL-05425_OGLE V.vot", preserve_photcal=True)
    _describe_bridge_photcal(volc)
    _describe_curvedash(lcd, head=head)

    _banner("Stage 6 — Discovery cleanup: drop_invalid_photometry_rows()")
    before = len(lcd.lightcurve) if lcd.lightcurve is not None else 0
    drop_invalid_photometry_rows(lcd)
    after = len(lcd.lightcurve) if lcd.lightcurve is not None else 0
    print(f"Rows before/after: {before} -> {after}")

    _banner("Stage 7 — Session serialisation round-trip")
    serialized = lcd.serialize()
    restored = CurveDash.from_serialized(serialized)
    print(f"Serialised JSON size: {len(serialized)} characters")
    _describe_curvedash(restored, head=min(head, 3))

    _banner("Stage 8 — Export VOTable and re-ingest")
    roundtrip = _describe_export(lcd)

    _banner("Stage 9 — Diagnosis summary")
    _summary_diagnosis(volc, payload)

    _banner("Done")
    print(
        "PhotDM ingestion uses the GAVO walker. Compare Stage 2 and Stage 3 "
        "volc.photdms for consistency."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv (list[str], optional): Command-line arguments.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Trace OGLE lightcurve data through skvo_veb layers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Example:
              .venv/bin/python scripts/trace_ogle_lightcurve_flow.py
            """
        ),
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_OGLE_ACCREF,
        help="OGLE accref URL (default: OGLE-SMC-ECL-05425 V band)",
    )
    parser.add_argument(
        "--head",
        type=int,
        default=3,
        help="Number of data rows to preview at each stage (default: 3)",
    )
    args = parser.parse_args(argv)
    try:
        return run_trace(accref=args.url, head=max(0, args.head))
    except Exception as exc:
        logger.exception("Trace failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
