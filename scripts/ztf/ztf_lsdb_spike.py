#!/usr/bin/env python3
"""ZTF Discovery & Retrieval Spike using LSDB (HATS catalogs).

Run with `python -u scripts/ztf_lsdb_spike.py` (the `-u` flag disables
stdout buffering) so that progress prints appear immediately instead of only
after the buffer fills or the process exits - this script has slow network
steps and you want to see WHEN each one starts/finishes.

An extremely simple, non-interactive spike script demonstrating discovery
and retrieval of ZTF data using the brand-new `lsdb` package, which reads
IRSA's "HATS" (Hierarchical Adaptive Tiling Scheme) partitioned Parquet
collections directly from the public AWS S3 bucket - no IRSA login, no
CGI/TAP service, no `ztfquery` involved at all.

Two public HATS collections are used (ZTF DR24, hosted at IPAC/IRSA on AWS):
    - Objects catalog : s3://ipac-irsa-ztf/ztf/enhanced/dr24/objects/hats
                         (one row per object, with COLLAPSED lightcurve
                         metrics only - no per-epoch photometry at all;
                         adaptively partitioned up to high HEALPix orders
                         in dense fields, so cone searches touch small
                         files)
    - Lightcurves cat.: s3://ipac-irsa-ztf/ztf/enhanced/dr24/lc/hats
                         (one row per object, with a NESTED per-epoch
                         "lightcurve" column holding the raw photometry;
                         only partitioned up to HEALPix order 6, so a
                         single partition file can cover ~0.84 sq deg and
                         be MULTIPLE GIGABYTES in size - see the printed
                         warning in Step 2 below)

Two steps, mirroring the other spikes in this folder:

1) Discovery (cone search on the Objects catalog):
   `lsdb.open_catalog(..., search_filter=lsdb.ConeSearch(...))` is LAZY - it
   only reads Parquet footers/metadata to figure out which HEALPix
   partitions intersect the cone. Calling `.compute()` on it then downloads
   ONLY those few small partitions of the (already collapsed, no-epochs)
   Objects table. No per-epoch photometry is ever fetched here.

2) Retrieval (raw lightcurve for one chosen oid):
   The Lightcurves catalog is opened lazily with the SAME cone filter (again
   only touches Parquet metadata), then narrowed further with `id_search()`
   to the single target `oid`. **IMPORTANT FINDING** (this is exactly the
   kind of thing this spike is meant to expose): `id_search()` only prunes
   whole PARTITIONS, not individual rows within a partition. Because the
   Lightcurves catalog is only partitioned down to HEALPix order 6, one
   partition file can hold tens of thousands of objects and their nested
   epoch arrays - in the hardcoded example below that single partition file
   is **~2.15 GB**. So `.compute()` here downloads and decodes the ENTIRE
   ~2.15 GB file just to hand you back the one row for our target oid. This
   is analogous to (arguably worse than) the "download everything in the
   cone" problem found earlier with `ztfquery.lightcurve.LCQuery`, except
   here the inefficiency comes from the catalog's own partitioning
   granularity rather than from the client API.

Coordinates are completely hardcoded for easy debugging.
No console input, no Simbad, no time corrections, no VOTable - just the raw
objects returned by lsdb, ready for you to inspect (and time!) in a debugger.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import lsdb
import s3fs

# Add repository root to python path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ----------------------------------------------------------------------
# HARDCODED PARAMETERS (Perfect for running directly in the debugger)
# ----------------------------------------------------------------------
RA = 316.01949          # RA of V3101 Cyg in degrees (same target as the other ZTF spikes)
DEC = 46.52068          # Dec of V3101 Cyg in degrees
RADIUS_ARCSEC = 5.0     # Search radius in arcseconds

ZTF_OBJECTS_HATS = "s3://ipac-irsa-ztf/ztf/enhanced/dr24/objects/hats"
ZTF_LIGHTCURVES_HATS = "s3://ipac-irsa-ztf/ztf/enhanced/dr24/lc/hats"

OBJECTS_COLUMNS = ["oid", "ra", "dec", "filtercode", "ngoodobsrel", "meanmag", "magrms"]


def _p(*args) -> None:
    """Print with an immediate flush.

    Args:
        *args: Values forwarded to the built-in `print`.
    """
    print(*args, flush=True)


def _report_partition_size(lazy_catalog) -> None:
    """Look up and print the raw S3 file size(s) backing a lazy catalog's partitions.

    Purely a diagnostic side-step (does not affect the actual data returned by
    `.compute()`): it lets you see, BEFORE triggering the real download, how
    much data `.compute()` is about to pull over the network for the
    partition(s) selected so far. Failures here are reported explicitly and
    do not silently swallow errors - they simply mean the diagnostic could
    not be produced.

    Args:
        lazy_catalog: A lazily-opened lsdb Catalog/NestedFrame whose selected
            HEALPix pixels should be inspected.
    """
    try:
        pixels = lazy_catalog.get_healpix_pixels()
        base_dir = str(lazy_catalog.hc_structure.catalog_base_dir).replace("s3://", "")
        fs = s3fs.S3FileSystem(anon=True)
        total_bytes = 0
        for pix in pixels:
            order, pixel = pix.order, pix.pixel
            dir_bucket = (pixel // 10000) * 10000
            partition_dir = f"{base_dir}/dataset/Norder={order}/Dir={dir_bucket}/Npix={pixel}"
            entries = fs.ls(partition_dir, detail=True)
            part_bytes = sum(e.get("size", 0) for e in entries)
            total_bytes += part_bytes
            _p(f"    -> partition Norder={order}/Npix={pixel}: {part_bytes / 1e6:.1f} MB on disk")
        _p(f"    -> TOTAL that .compute() must download+decode for this selection: {total_bytes / 1e6:.1f} MB")
    except Exception as exc:  # noqa: BLE001 - diagnostic only, report explicitly, never hide
        _p(f"    -> [diagnostic] could not determine partition file size(s): {exc!r}")


def main() -> None:
    """Run the two-step ZTF discovery-then-retrieval spike using lsdb/HATS catalogs."""
    _p("========================================================================")
    _p("  ZTF LSDB SPIKE (HATS collections on S3, via lsdb)")
    _p("========================================================================")
    _p(f"Hardcoded Target: RA = {RA} deg, Dec = {DEC} deg, Radius = {RADIUS_ARCSEC} arcsec")

    cone = lsdb.ConeSearch(ra=RA, dec=DEC, radius_arcsec=RADIUS_ARCSEC)

    # ------------------------------------------------------------------
    # STEP 1: Discovery (cone search on the collapsed Objects catalog)
    # ------------------------------------------------------------------
    _p("\n[Step 1] Opening ZTF DR24 Objects HATS catalog with a cone-search filter...")
    t0 = time.perf_counter()
    objects_lazy = lsdb.open_catalog(
        ZTF_OBJECTS_HATS,
        columns=OBJECTS_COLUMNS,
        search_filter=cone,
    )
    t_open = time.perf_counter() - t0
    _p(f"    -> catalog opened lazily in {t_open:.3f}s (no per-epoch data touched yet)")
    _p(f"    -> npartitions intersecting the cone: {objects_lazy.npartitions}")
    _report_partition_size(objects_lazy)
    _p(objects_lazy)  # <--- STOP HERE to inspect the lazy Catalog object itself

    _p("\n[Step 1] Computing (materializing) the discovery result...")
    t0 = time.perf_counter()
    df_discovery = objects_lazy.compute()  # <--- STOP HERE: only collapsed metrics are fetched
    t_compute = time.perf_counter() - t0
    _p(f"    -> compute() took {t_compute:.3f}s, returned {len(df_discovery)} object(s)")

    _p("\nDiscovered Objects Table (collapsed catalog metrics only - NO epochs downloaded):")
    _p("-" * 80)
    _p(df_discovery.to_string(index=False))
    _p("-" * 80)

    if df_discovery.empty:
        _p("No ZTF objects found in this region.")
        return

    # ------------------------------------------------------------------
    # STEP 2: Retrieval (raw lightcurve for one chosen oid, via id_search)
    # ------------------------------------------------------------------
    target_oid = int(df_discovery["oid"].iloc[0])
    _p(f"\n[Step 2] Opening ZTF DR24 Lightcurves HATS catalog (same cone filter)...")
    t0 = time.perf_counter()
    lc_lazy = lsdb.open_catalog(ZTF_LIGHTCURVES_HATS, search_filter=cone)
    t_open_lc = time.perf_counter() - t0
    _p(f"    -> catalog opened lazily in {t_open_lc:.3f}s")
    _p(f"    -> npartitions intersecting the cone: {lc_lazy.npartitions}")

    idx_column = list(lc_lazy.hc_collection.all_indexes.keys())[0]
    _p(f"    -> narrowing to oid={target_oid} via id_search(values={{'{idx_column}': [{target_oid}]}})")
    lc_target_lazy = lc_lazy.id_search(values={idx_column: [target_oid]})

    _p("\n[Step 2] BEFORE downloading, checking the actual partition file size on S3...")
    _p("    (id_search() only prunes whole PARTITIONS, not individual rows within one -")
    _p("     if the Lightcurves catalog is coarsely partitioned, this can be huge)")
    _report_partition_size(lc_target_lazy)
    _p("    -> the compute() call below will fetch+decode ALL of the above, just to")
    _p("       return the single row for our target oid. THIS is the efficiency")
    _p("       question raised for this spike - watch the wall-clock time below.")

    _p(f"\n[Step 2] Computing (downloading) the RAW lightcurve for OID {target_oid} only...")
    t0 = time.perf_counter()
    lc_df = lc_target_lazy.compute()  # <--- STOP HERE IN YOUR DEBUGGER TO INSPECT lc_df / raw_epochs
    t_compute_lc = time.perf_counter() - t0
    _p(f"    -> compute() took {t_compute_lc:.3f}s, returned {len(lc_df)} row(s) (one row per object,"
       " with a nested 'lightcurve' column)")

    raw_epochs = lc_df.iloc[0]["lightcurve"]  # <--- STOP HERE: the raw, nested per-epoch DataFrame
    _p(f"\nSuccessfully retrieved {len(raw_epochs)} raw epochs for OID {target_oid}.")
    _p("\nRaw nested lightcurve DataFrame columns:")
    _p(list(raw_epochs.columns))

    _p("\nFirst 5 Rows of Raw Data:")
    _p("-" * 120)
    _p(raw_epochs.head(5).to_string(index=False))
    _p("-" * 120)

    _p("\nTiming summary (for efficiency investigation):")
    _p(f"    Objects catalog     open(): {t_open:.3f}s   compute(): {t_compute:.3f}s")
    _p(f"    Lightcurve catalog  open(): {t_open_lc:.3f}s   compute(): {t_compute_lc:.3f}s  <-- see partition size above")

    _p("\nSpike completed successfully. Set a breakpoint on the 'raw_epochs =' line to inspect the data.")


if __name__ == "__main__":
    main()
