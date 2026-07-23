#!/usr/bin/env python3
"""Spike: GAVO metadata-only VOTable parse (no BINARY row consumption).

``votparse.readRaw`` fails on some binary VOTables (e.g. TESS exports) because it
must decode every row into the GAVO tree. VO metadata (TIMESYS, photcal GROUP,
PARAMref targets) lives in the XML header; the BINARY block is row payload only.

GAVO ``parse()`` documents that ``DATA`` is *always* yielded as ``tableparser.Rows``
— that cannot be disabled via watchset. However, **not consuming** the ``Rows``
iterator avoids binary decode while still yielding the completed ``V.VOTABLE`` node.

This script compares:

* ``readRaw`` (full parse — baseline, expected to fail on ``bin.vot``)
* metadata-only ``parse(..., {V.VOTABLE})`` with ``Rows`` skipped
* existing GAVO walkers (``extract_timesys_metadata_from_gavo``, ``extract_photdm``)
* astropy ``vot.parse`` TIMESYS / photcal (no PARAMref resolution)

Usage (from repository root)::

    .venv/bin/python scripts/spike_gavo_metadata_parse.py
    .venv/bin/python scripts/spike_gavo_metadata_parse.py --file bin.vot
    .venv/bin/python scripts/spike_gavo_metadata_parse.py --file path/to/ogle.vot

Diagnostic only — does not modify application code.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import textwrap
import traceback
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import astropy.io.votable as vot
from astropy.io.votable.tree import ParamRef
from gavo.votable import tableparser
from gavo.votable import votparse
from gavo.votable.model import VOTable as V

from skvo_veb.volightcurve.lightcurve import extract_photdm
from skvo_veb.volightcurve.time_reference import extract_timesys_metadata_from_gavo

DEFAULT_FIXTURE = _REPO_ROOT / "bin.vot"


def _banner(title: str) -> None:
    """Prints a section header.

    Args:
        title (str): Section title.
    """
    line = "=" * 72
    print(f"\n{line}\n  {title}\n{line}")


def _json_block(label: str, payload: Any) -> None:
    """Prints a labelled JSON block.

    Args:
        label (str): Block heading.
        payload (Any): JSON-serialisable object.
    """
    print(f"\n{label}:")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _resolve_fixture(path: Path) -> Path:
    """Resolves a VOTable path relative to the repository root.

    Args:
        path (Path): User-supplied file path.

    Returns:
        Path: Existing file path.

    Raises:
        SystemExit: When the file cannot be found.
    """
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([_REPO_ROOT / path, _REPO_ROOT / "data" / path.name])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(f"Fixture not found: {path} (tried: {', '.join(map(str, candidates))})")


def gavo_readraw(payload: bytes) -> tuple[Any | None, str | None]:
    """Runs GAVO ``readRaw`` (full parse including row materialisation).

    Args:
        payload (bytes): Raw VOTable bytes.

    Returns:
        tuple: ``(tree, error_message)``.
    """
    try:
        return votparse.readRaw(io.BytesIO(payload)), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def gavo_metadata_tree(
    payload: bytes,
    *,
    watchset: set[type],
    on_rows: str,
) -> tuple[Any | None, str | None, dict[str, int]]:
    """Builds a GAVO tree without consuming ``tableparser.Rows``.

    Args:
        payload (bytes): Raw VOTable bytes.
        watchset (set[type]): GAVO element types to yield on element close.
        on_rows (str): ``skip`` (continue loop) or ``break`` (stop at DATA).

    Returns:
        tuple: ``(last_votable_node, error_message, stats)`` where stats counts
            yielded element types.
    """
    stats: dict[str, int] = {}
    votable_node = None
    last_node = None
    try:
        for element in votparse.parse(io.BytesIO(payload), watchset):
            if isinstance(element, tableparser.Rows):
                stats["Rows"] = stats.get("Rows", 0) + 1
                if on_rows == "break":
                    break
                continue
            name = type(element).__name__
            stats[name] = stats.get(name, 0) + 1
            last_node = element
            if name == "VOTABLE":
                votable_node = element
        return votable_node if votable_node is not None else last_node, None, stats
    except Exception as exc:
        return last_node, f"{type(exc).__name__}: {exc}", stats


def describe_astropy_photcal(payload: bytes) -> None:
    """Prints astropy photcal GROUP entries (PARAMref not resolved).

    Args:
        payload (bytes): Raw VOTable bytes.
    """
    tree = vot.parse(io.BytesIO(payload))
    print("\nAstropy TIMESYS:")
    for timesys in tree.iter_timesys():
        print(
            f"  ID={timesys.ID!r} timescale={timesys.timescale!r} "
            f"timeorigin={timesys.timeorigin!r} refposition={timesys.refposition!r}"
        )

    for resource in tree.resources:
        for group in resource.groups:
            if group.name != "photcal":
                continue
            print("\nAstropy photcal GROUP (PARAMref shown unresolved):")
            for entry in group.entries:
                cls = type(entry).__name__
                ref = getattr(entry, "ref", None)
                utype = getattr(entry, "utype", None)
                value = getattr(entry, "value", None)
                note = "  <-- PARAMref; astropy does not dereference" if cls == "ParamRef" else ""
                print(f"  {cls}: ref={ref!r} utype={utype!r} value={value!r}{note}")


def describe_gavo_walkers(gavo_tree: Any, *, label: str) -> None:
    """Runs TIMESYS and PhotDM GAVO walkers on a parsed tree.

    Args:
        gavo_tree: GAVO ``V.VOTABLE`` root (or last yielded node).
        label (str): Heading prefix for output.
    """
    if gavo_tree is None:
        print(f"\n{label}: no GAVO tree to walk")
        return

    ts_meta = extract_timesys_metadata_from_gavo(gavo_tree)
    phot_map = extract_photdm(gavo_tree)

    _json_block(
        f"{label} — TIMESYS registry",
        {
            ts_id: {
                "timescale": ts.timescale,
                "timeorigin": ts.timeorigin,
                "refposition": ts.refposition,
            }
            for ts_id, ts in ts_meta.registry.items()
        },
    )
    _json_block(f"{label} — FIELD TIMESYS refs", ts_meta.field_refs)

    print(f"\n{label} — extract_photdm ({len(phot_map)} columns):")
    for colname, photdm in phot_map.items():
        filt = photdm.filter.filter_id if photdm.filter else None
        zp_flux = photdm.photcal.zp_flux if photdm.photcal else None
        zp_mag = photdm.photcal.zp_mag if photdm.photcal else None
        print(f"  [{colname!r}] filter={filt!r} zp_flux={zp_flux!r} zp_mag={zp_mag!r}")


def run_spike(*, fixture: Path) -> int:
    """Executes GAVO metadata-only parse experiments.

    Args:
        fixture (Path): Path to a VOTable file.

    Returns:
        int: Process exit code (0 when metadata-only parse succeeds).
    """
    payload = fixture.read_bytes()

    _banner("Fixture")
    print(f"Path: {fixture}")
    print(f"Size: {len(payload)} bytes")

    _banner("Astropy structure (reference — no PARAMref resolution)")
    describe_astropy_photcal(payload)

    _banner("GAVO readRaw — full parse (current _ingest path)")
    full_tree, full_error = gavo_readraw(payload)
    if full_error:
        print(f"FAILED: {full_error}")
    else:
        print("OK")
        describe_gavo_walkers(full_tree, label="readRaw")

    _banner("GAVO parse — metadata-only (skip Rows, watchset={VOTABLE})")
    meta_tree, meta_error, meta_stats = gavo_metadata_tree(
        payload,
        watchset={V.VOTABLE},
        on_rows="skip",
    )
    _json_block("Parse yield stats", meta_stats)
    if meta_error:
        print(f"FAILED: {meta_error}")
    else:
        print(f"Last node type: {type(meta_tree).__name__ if meta_tree else None}")
        describe_gavo_walkers(meta_tree, label="metadata-only")

    _banner("GAVO parse — break at Rows (watchset={VOTABLE, TABLE})")
    break_tree, break_error, break_stats = gavo_metadata_tree(
        payload,
        watchset={V.VOTABLE, V.TABLE},
        on_rows="break",
    )
    _json_block("Parse yield stats", break_stats)
    if break_error:
        print(f"FAILED: {break_error}")
    else:
        print(f"Last node type: {type(break_tree).__name__ if break_tree else None}")
        print("(Breaking early usually leaves no VOTABLE — expected.)")

    _banner("Conclusion")
    print(
        textwrap.dedent(
            """
            GAVO parse() always yields tableparser.Rows at <DATA> (cannot disable).

            Strategy for clean _ingest:
              - Astropy Table.read  → row data
              - GAVO parse(watchset={V.VOTABLE}) → skip Rows (do not list/iterate)
              - _apply_gavo_votable_metadata on the VOTABLE node
              - Do NOT call readRaw on binary mission products

            Verify PARAMref resolution on OGLE/TAP products separately; bin.vot
            uses inline photcal PARAMs, not PARAMref.
            """
        ).strip()
    )

    if meta_error:
        return 1
    if meta_tree is None or type(meta_tree).__name__ != "VOTABLE":
        print("Metadata-only parse did not yield a VOTABLE node.")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv (list[str], optional): Command-line arguments.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Spike GAVO metadata-only VOTable parse (no BINARY row decode).",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="VOTable fixture (default: bin.vot at repo root)",
    )
    args = parser.parse_args(argv)
    fixture = _resolve_fixture(args.file)
    try:
        return run_spike(fixture=fixture)
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
