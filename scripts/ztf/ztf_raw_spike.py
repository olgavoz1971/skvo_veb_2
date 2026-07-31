#!/usr/bin/env python3
"""ZTF Raw Lightcurve Discovery & Retrieval Spike.

An extremely simple, non-interactive spike script demonstrating the correct,
lightweight VO-compliant two-step process:

1. Discovery (TAP Query): Query the ZTF Objects Table (ztf_objects_dr24) using
   astroquery.ipac.irsa to find matching OIDs and metadata.
   --> CRITICAL: This downloads ZERO lightcurves/epochs, making it extremely fast.

2. Retrieval (ztfquery): Download the raw lightcurve for a specific chosen OID
   using ztfquery.lightcurve.LCQuery.from_id().
   --> This downloads only the requested lightcurve.

Coordinates and parameters are completely hardcoded for easy debugging.
No console inputs, no Simbad, no VO corrections, no VOTable.
Just raw pandas DataFrames for you to inspect in the debugger.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd

# Add repository root to python path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from astroquery.ipac.irsa import Irsa
from ztfquery import lightcurve

# ----------------------------------------------------------------------
# HARDCODED PARAMETERS (Perfect for running directly in the debugger)
# ----------------------------------------------------------------------
RA = 316.01949          # RA of V3101 Cyg in degrees
DEC = 46.52068          # Dec of V3101 Cyg in degrees
RADIUS_ARCSEC = 5.0     # Search radius in arcseconds


def main() -> None:
    print("========================================================================")
    print("  ZTF RAW LIGHTCURVE SPIKE (TAP + ztfquery)")
    print("========================================================================")
    print(f"Hardcoded Target: RA = {RA} deg, Dec = {DEC} deg, Radius = {RADIUS_ARCSEC} arcsec")

    # ------------------------------------------------------------------
    # STEP 1: Discovery (TAP query on Objects Table - ZERO lightcurves downloaded)
    # ------------------------------------------------------------------
    print("\n[Step 1] Running Discovery via IRSA TAP (Objects Table)...")
    
    radius_deg = RADIUS_ARCSEC / 3600.0
    query = f"""
    SELECT oid, ra, dec, filtercode, nobsrel, meanmag, magrms
    FROM ztf_objects_dr24
    WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {RA}, {DEC}, {radius_deg})) = 1
    """
    
    try:
        res = Irsa.query_tap(query=query)
        if res is None or len(res) == 0:
            print("No ZTF objects found in this region.")
            return
        df_discovery = res.to_table().to_pandas()
    except Exception as e:
        print(f"TAP query failed: {e}")
        return

    print("\nDiscovered Objects Table (Pre-computed catalog metrics only - NO epochs downloaded):")
    print("-" * 80)
    print(df_discovery.to_string(index=False))
    print("-" * 80)

    # ------------------------------------------------------------------
    # STEP 2: Retrieval (Download by OID via ztfquery)
    # ------------------------------------------------------------------
    # We pick the first discovered OID
    target_oid = str(df_discovery["oid"].iloc[0])
    print(f"\n[Step 2] Retrieving Raw Lightcurve for OID: {target_oid}...")

    # We pass cookies={} to bypass the IRSA login prompt and query anonymously
    lcq_retrieval = lightcurve.LCQuery.from_id(target_oid, cookies={})
    raw_data = lcq_retrieval.data  # <--- STOP HERE IN YOUR DEBUGGER TO INSPECT THE RAW DATAFRAME!

    print(f"\nSuccessfully retrieved {len(raw_data)} raw epochs.")
    print("\nRaw DataFrame Columns:")
    print(list(raw_data.columns))

    print("\nFirst 5 Rows of Raw Data:")
    print("-" * 120)
    print(raw_data.head(5).to_string(index=False))
    print("-" * 120)

    print("\nSpike completed successfully. You can set a breakpoint on line 73 to inspect 'raw_data'.")


if __name__ == "__main__":
    main()
