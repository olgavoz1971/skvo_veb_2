#!/usr/bin/env python3
"""Trace a local VOTable file through skvo_veb ingestion and export layers.

Loads a binary or XML VOTable from disk (default: ``bin.vot`` at repository root),
then prints the data structure at each pipeline stage so GAVO vs Astropy parsing
and the upload path can be inspected without running the Dash app.

Usage (from repository root)::

    .venv/bin/python scripts/trace_votable_ingest_flow.py

Optional arguments::

    .venv/bin/python scripts/trace_votable_ingest_flow.py --file data/my_curve.vot
    .venv/bin/python scripts/trace_votable_ingest_flow.py --head 5 --export

This script is diagnostic only. It does not modify files or caches.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import textwrap
import traceback
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import astropy.io.votable as vot
from astropy.io.votable import is_votable
from astropy.table import Table

from gavo.votable import votparse
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_bridge import (
    _extract_photcal_meta,
    _serialise_photcal_group,
    build_votable_kwargs_from_metadata,
    export_curvedash,
    ingest_lightcurve_file,
    volc_to_curvedash,
)
from skvo_veb.utils.lc_config import VOTABLE_FORMAT_BINARY
from skvo_veb.volightcurve import VOLightCurve
from skvo_veb.volightcurve.lightcurve import extract_photdm
from skvo_veb.volightcurve.time_reference import extract_timesys_metadata_from_gavo

DEFAULT_VOTABLE = _REPO_ROOT / "bin.vot"

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
            print(f"    filter.filter_id = {phot_filter.filter_id!r}")
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


def _describe_astropy_votable_tree(payload: bytes) -> None:
    """Prints TIMESYS, photcal GROUP, and TABLE metadata from astropy.io.votable.

    Args:
        payload (bytes): Raw VOTable bytes.
    """
    tree = vot.parse(io.BytesIO(payload))
    print("\nTIMESYS blocks (astropy iter_timesys):")
    found_ts = False
    for timesys in tree.iter_timesys():
        found_ts = True
        print(
            f"  ID={timesys.ID!r} timescale={timesys.timescale!r} "
            f"timeorigin={timesys.timeorigin!r} refposition={timesys.refposition!r}"
        )
    if not found_ts:
        print("  (none)")

    print("\nCOOSYS blocks (astropy iter_coosys):")
    found_cs = False
    for coosys in tree.iter_coosys():
        found_cs = True
        print(
            f"  ID={coosys.ID!r} system={coosys.system!r} epoch={coosys.epoch!r}"
        )
    if not found_cs:
        print("  (none)")

    table = tree.get_first_table()
    print("\nTABLE FIELD refs:")
    for field in table.fields:
        ref = getattr(field, "ref", None)
        if ref or field.name in ("obs_time", "phot", "flux_error"):
            print(
                f"  {field.name!r}: ref={ref!r} unit={getattr(field, 'unit', None)!r} "
                f"ucd={getattr(field, 'ucd', None)!r}"
            )

    print("\nTABLE PARAM elements:")
    for param in table.params:
        print(
            f"  @{param.ID or param.name}: name={param.name!r} "
            f"ref={getattr(param, 'ref', None)!r} value={param.value!r}"
        )

    for resource in tree.resources:
        for group in resource.groups:
            if group.name != "photcal":
                continue
            print("\nphotcal GROUP (astropy):")
            for entry in group.entries:
                cls = type(entry).__name__
                ref = getattr(entry, "ref", None)
                utype = getattr(entry, "utype", None)
                value = getattr(entry, "value", None)
                print(f"  {cls}: ref={ref!r} utype={utype!r} value={value!r}")


def _try_gavo_readraw(payload: bytes) -> tuple[Any | None, str | None]:
    """Attempts GAVO ``readRaw`` and returns the tree or an error message.

    Args:
        payload (bytes): Raw VOTable bytes.

    Returns:
        tuple: ``(gavo_tree, error_message)`` — tree is ``None`` when parsing fails.
    """
    try:
        return votparse.readRaw(io.BytesIO(payload)), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _describe_gavo_metadata(payload: bytes) -> None:
    """Prints GAVO TIMESYS and PhotDM extraction results.

    Args:
        payload (bytes): Raw VOTable bytes.
    """
    gavo_tree, error = _try_gavo_readraw(payload)
    if error:
        print(f"\nGAVO readRaw FAILED: {error}")
        return

    print("\nGAVO readRaw: OK")
    ts_meta = extract_timesys_metadata_from_gavo(gavo_tree)
    _json_block(
        "TIMESYS registry (extract_timesys_metadata_from_gavo)",
        {
            ts_id: {
                "timescale": ts.timescale,
                "timeorigin": ts.timeorigin,
                "refposition": ts.refposition,
            }
            for ts_id, ts in ts_meta.registry.items()
        },
    )
    _json_block("FIELD TIMESYS refs", ts_meta.field_refs)
    _json_block("PARAM TIMESYS refs", ts_meta.param_refs)
    _describe_photdm_map("extract_photdm() GAVO walker", extract_photdm(gavo_tree))


def _describe_volightcurve(volc: VOLightCurve, *, head: int) -> None:
    """Prints the ingested VOLightCurve view used by the bridge.

    Args:
        volc (VOLightCurve): Parsed product.
        head (int): Number of rows to preview.
    """
    print(f"\nVOLightCurve repr: {volc!r}")
    print(f"timesys: {volc.timesys!r}")
    print(f"timesys_by_id keys: {sorted(volc.timesys_by_id)}")
    print(f"field_timesys_ref: {volc.field_timesys_ref!r}")
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
    try:
        serialised = _serialise_photcal_group(photdm, volc.table.meta or {})
        _json_block("_serialise_photcal_group(photdm, table.meta)", serialised)
        _json_block("_extract_photcal_meta(volc, phot_col)", _extract_photcal_meta(volc, phot_col))
    except Exception as exc:
        print(f"\nPhotcal serialisation FAILED: {type(exc).__name__}: {exc}")


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


def _describe_export(lcd: CurveDash) -> None:
    """Exports CurveDash and re-ingests the VOTable for comparison.

    Args:
        lcd (CurveDash): Application lightcurve container.
    """
    try:
        kwargs = build_votable_kwargs_from_metadata(lcd)
    except Exception as exc:
        print(f"\nbuild_votable_kwargs_from_metadata(lcd) FAILED: {exc}")
        return

    _json_block("build_votable_kwargs_from_metadata(lcd)", kwargs)
    try:
        exported = export_curvedash(lcd, VOTABLE_FORMAT_BINARY)
    except Exception as exc:
        print(f"\nexport_curvedash(lcd) FAILED: {exc}")
        return

    print(f"\nExported VOTable size: {len(exported)} bytes")
    try:
        roundtrip = VOLightCurve(io.BytesIO(exported))
    except Exception as exc:
        print(f"\nRe-ingest of export FAILED: {exc}")
        return
    print("\nRe-ingested export VOLightCurve:")
    _describe_volightcurve(roundtrip, head=0)


def _summary_diagnosis(payload: bytes, volc: VOLightCurve | None) -> None:
    """Prints a short diagnosis comparing Astropy and GAVO metadata paths.

    Args:
        payload (bytes): Raw VOTable bytes.
        volc (VOLightCurve or None): Parsed product when ingestion succeeded.
    """
    astro_tree = vot.parse(io.BytesIO(payload))
    astro_ts = next(iter(astro_tree.iter_timesys()), None)
    gavo_tree, gavo_error = _try_gavo_readraw(payload)

    gavo_ts = None
    if gavo_tree is not None:
        gavo_ts = extract_timesys_metadata_from_gavo(gavo_tree).default_timesys

    ingested_ts = volc.timesys if volc is not None else None

    print(textwrap.dedent(
        f"""
        Quick diagnosis
        ---------------
        - File detected as VOTable (is_votable): {is_votable(io.BytesIO(payload))}
        - Astropy Table.read row count: {len(Table.read(io.BytesIO(payload), format='votable'))}
        - GAVO readRaw: {'FAILED — ' + gavo_error if gavo_error else 'OK'}
        - Astropy TIMESYS: {None if astro_ts is None else (
            f"timescale={astro_ts.timescale!r} timeorigin={astro_ts.timeorigin!r}"
        )}
        - GAVO default TIMESYS: {None if gavo_ts is None else (
            f"timescale={gavo_ts.timescale!r} timeorigin={gavo_ts.timeorigin!r}"
        )}
        - VOLightCurve timesys: {None if ingested_ts is None else (
            f"timescale={ingested_ts.timescale!r} timeorigin={ingested_ts.timeorigin!r}"
        )}
        """
    ).strip())

    if gavo_error and astro_ts is not None and ingested_ts is not None:
        if (
            ingested_ts.timescale != astro_ts.timescale
            or float(ingested_ts.timeorigin or 0) != float(astro_ts.timeorigin or 0)
        ):
            print(
                "\nNOTE: Ingested TIMESYS does not match astropy.io.votable "
                "(GAVO failure likely dropped metadata)."
            )


def _stage_result(label: str, func) -> Any:
    """Runs a stage callable and prints failures without aborting the trace.

    Args:
        label (str): Stage description for error output.
        func: Zero-argument callable.

    Returns:
        Any: Callable return value, or ``None`` on failure.
    """
    try:
        return func()
    except Exception as exc:
        print(f"\n{label} FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return None


def run_trace(*, votable_path: Path, head: int, do_export: bool) -> int:
    """Executes the full layer-by-layer trace for a local VOTable file.

    Args:
        votable_path (Path): Path to the input ``.vot`` file.
        head (int): Preview row count per stage.
        do_export (bool): When True, run export round-trip after bridge ingest.

    Returns:
        int: Process exit code (0 = full ingest success, 1 = failure).
    """
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if not votable_path.is_file():
        print(f"File not found: {votable_path}", file=sys.stderr)
        return 1

    payload = votable_path.read_bytes()
    ingest_ok = False
    volc: VOLightCurve | None = None
    lcd: CurveDash | None = None

    _banner("Stage 0 — Load local VOTable")
    print(f"Path: {votable_path}")
    print(f"Size: {len(payload)} bytes")
    print(f"is_votable: {is_votable(io.BytesIO(payload))}")

    _banner("Stage 1 — Astropy VOTable tree (structure / TIMESYS / photcal)")
    _describe_astropy_votable_tree(payload)

    _banner("Stage 2 — Astropy Table.read (table data authority)")
    table = Table.read(io.BytesIO(payload), format="votable")
    _describe_astropy_table(table, head=head)

    _banner("Stage 3 — GAVO readRaw + metadata walkers")
    _describe_gavo_metadata(payload)

    _banner("Stage 4 — VOLightCurve ingestion")
    volc = _stage_result("VOLightCurve", lambda: VOLightCurve(votable_path))
    if volc is not None:
        _describe_volightcurve(volc, head=head)

    _banner("Stage 5 — Upload path: ingest_lightcurve_file()")
    lcd = _stage_result(
        "ingest_lightcurve_file",
        lambda: ingest_lightcurve_file(votable_path, votable_path.name),
    )
    if lcd is not None:
        ingest_ok = True
        _describe_curvedash(lcd, head=head)
        if volc is not None:
            _describe_bridge_photcal(volc)

    if do_export and lcd is not None:
        _banner("Stage 6 — Export VOTable and re-ingest")
        _describe_export(lcd)

    _banner("Stage 7 — Diagnosis summary")
    _summary_diagnosis(payload, volc)

    _banner("Done")
    if ingest_ok:
        print("Upload-path ingest succeeded.")
        return 0

    print("Upload-path ingest FAILED — inspect stages above (GAVO readRaw is a common breakpoint).")
    return 1


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv (list[str], optional): Command-line arguments.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Trace local VOTable ingestion through skvo_veb layers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              .venv/bin/python scripts/trace_votable_ingest_flow.py
              .venv/bin/python scripts/trace_votable_ingest_flow.py --file bin.vot --head 5
              .venv/bin/python scripts/trace_votable_ingest_flow.py --export
            """
        ),
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_VOTABLE,
        help=f"Path to VOTable file (default: {DEFAULT_VOTABLE.name} at repo root)",
    )
    parser.add_argument(
        "--head",
        type=int,
        default=3,
        help="Number of data rows to preview at each stage (default: 3)",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Also run export_curvedash() and re-ingest the exported VOTable",
    )
    args = parser.parse_args(argv)

    votable_path = args.file if args.file.is_absolute() else _REPO_ROOT / args.file
    try:
        return run_trace(votable_path=votable_path, head=max(0, args.head), do_export=args.export)
    except Exception as exc:
        logger.exception("Trace failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
