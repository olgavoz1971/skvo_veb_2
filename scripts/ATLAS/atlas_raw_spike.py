#!/usr/bin/env python3
"""ATLAS Raw Lightcurve Discovery & Retrieval Spike.

An extremely simple, non-interactive spike script demonstrating the two-step
process for ATLAS forced photometry:

1. Queue/Discovery: Submit a forced photometry job for a specific coordinate
   (RA, Dec) to the ATLAS Forced Photometry Server queue.
2. Retrieval: Poll the queue until the job is completed, then download the
   raw, uncleaned ASCII table and load it into a pandas DataFrame.

No time corrections, no VO corrections, no VOTable.
Just the raw data as returned by the ATLAS server, ready for debugger inspection.
"""

from __future__ import annotations

import io
import os
import re
import sys
import time
from urllib.parse import urljoin
import pandas as pd
import requests

# ----------------------------------------------------------------------
# HARDCODED PARAMETERS (Perfect for running directly in the debugger)
# ----------------------------------------------------------------------
RA = 316.01949          # RA of V3101 Cyg in degrees (same target as ZTF spikes)
DEC = 46.52068          # Dec of V3101 Cyg in degrees
MJD_MIN = 57000.0       # Minimum MJD (defaults to 57000.0 for full history)
USE_REDUCED = True      # True runs tphot (PSF-fitting) on reduced images (total flux)

BASEURL = "https://fallingstar-data.com/forcedphot"
HOST = "https://fallingstar-data.com"


def get_headers() -> dict[str, str]:
    """Retrieve Authorization headers using ATLASFORCED_SECRET_KEY."""
    token = os.environ.get("ATLASFORCED_SECRET_KEY")
    if not token:
        print("ERROR: ATLAS token not found in environment variable 'ATLASFORCED_SECRET_KEY'.")
        print("Please obtain a token from https://fallingstar-data.com/forcedphot/api-token-auth/")
        print("and set it in your environment: export ATLASFORCED_SECRET_KEY='your_token'")
        sys.exit(1)
    return {"Authorization": f"Token {token}", "Accept": "application/json"}


def abs_url(url: str | None) -> str | None:
    """Resolve relative URLs to absolute URLs."""
    if not url:
        return url
    url_str = str(url)
    return url_str if url_str.startswith("http") else urljoin(HOST + "/", url_str)


def get_task_id(task_url: str | None) -> str | None:
    """Extract the integer task ID from a task URL."""
    m = re.search(r"/(\d+)/?$", task_url or "")
    return m.group(1) if m else None


def main() -> None:
    print("========================================================================")
    print("  ATLAS RAW LIGHTCURVE SPIKE (Forced Photometry Server)")
    print("========================================================================")
    print(f"Hardcoded Target: RA = {RA} deg, Dec = {DEC} deg")
    print(f"Parameters: mjd_min = {MJD_MIN}, use_reduced = {USE_REDUCED}")

    headers = get_headers()

    # Create a requests session
    session = requests.Session()

    # ------------------------------------------------------------------
    # STEP 1: Queue the Job (Discovery/Trigger)
    # ------------------------------------------------------------------
    print("\n[Step 1] Submitting forced photometry job to ATLAS queue...")
    data = {
        "ra": float(RA),
        "dec": float(DEC),
        "send_email": False,
        "use_reduced": USE_REDUCED,
        "mjd_min": float(MJD_MIN)
    }

    try:
        resp = session.post(f"{BASEURL}/queue/", headers=headers, data=data, timeout=30)
        if resp.status_code != 201:
            print(f"Failed to queue job. HTTP Status: {resp.status_code}")
            print(f"Response: {resp.text}")
            return
        
        task_url = abs_url(resp.json().get("url"))
        task_id = get_task_id(task_url)
        print(f"Successfully queued job! Task ID: {task_id}")
        print(f"Task URL: {task_url}")
    except Exception as e:
        print(f"Failed to submit job: {e}")
        return

    # ------------------------------------------------------------------
    # STEP 2: Poll and Retrieve Raw Data
    # ------------------------------------------------------------------
    print("\n[Step 2] Polling job status (checking every 5 seconds)...")
    result_url = None
    start_time = time.time()
    
    while True:
        try:
            resp = session.get(task_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                print(f"Polling warning: HTTP {resp.status_code}. Retrying...")
                time.sleep(5)
                continue
            
            job_data = resp.json()
            finishtime = job_data.get("finishtimestamp")
            start_time_stamp = job_data.get("starttimestamp")
            
            elapsed = time.time() - start_time
            print(f"    Elapsed: {elapsed:.1f}s | Started: {start_time_stamp is not None} | Finished: {finishtime is not None}")
            
            if finishtime:
                result_url = job_data.get("result_url")
                break
                
            time.sleep(5)
        except Exception as e:
            print(f"Polling error: {e}. Retrying...")
            time.sleep(5)

    if not result_url:
        print("Job finished but no result_url was returned.")
        # Try fallback static result URL
        result_url = f"{BASEURL}/static/results/job{task_id}.txt"
        print(f"Trying fallback static URL: {result_url}")
    else:
        result_url = abs_url(result_url)
        print(f"Job finished! Result URL: {result_url}")

    print("\nDownloading raw result text...")
    try:
        r = session.get(result_url, headers=headers, timeout=60)
        if r.status_code != 200:
            # Try fallback static result URL if the main one failed
            fallback_url = f"{BASEURL}/static/results/job{task_id}.txt"
            print(f"Main URL failed (HTTP {r.status_code}). Trying fallback: {fallback_url}")
            r = session.get(fallback_url, headers=headers, timeout=60)
            
        if r.status_code != 200:
            print(f"Failed to download result. HTTP Status: {r.status_code}")
            return
            
        raw_text = r.text
    except Exception as e:
        print(f"Failed to download result: {e}")
        return

    # Print first 15 lines of raw text to "smell" the raw format
    print("\nFirst 15 lines of RAW ASCII text from ATLAS server:")
    print("=" * 100)
    lines = raw_text.splitlines()
    for line in lines[:15]:
        print(line)
    print("=" * 100)

    # Parse raw text into a pandas DataFrame
    print("\nParsing raw text into pandas DataFrame...")
    try:
        # The ATLAS raw file is space-separated
        raw_df = pd.read_csv(io.StringIO(raw_text), sep=r"\s+", engine="python")
    except Exception as e:
        print(f"Failed to parse raw text: {e}")
        return

    # Rename ###MJD to MJD for convenience
    if "###MJD" in raw_df.columns:
        raw_df = raw_df.rename(columns={"###MJD": "MJD"})

    # Save the whole raw data frame into a file for later investigation
    output_filename = f"scripts/ATLAS/atlas_raw_data_RA{RA}_DEC{DEC}.parquet"
    print(f"\nSaving whole raw DataFrame to file: {output_filename} ...")
    try:
        raw_df.to_parquet(output_filename, index=False)
        print("Successfully saved raw data.")
    except Exception as e:
        print(f"Failed to save raw data to file: {e}")

    print(f"\nSuccessfully loaded {len(raw_df)} raw rows.")
    print("\nRaw DataFrame Columns:")
    print(list(raw_df.columns))

    print("\nFirst 5 Rows of Raw DataFrame:")
    print("-" * 120)
    print(raw_df.head(5).to_string(index=False))
    print("-" * 120)

    # Clean up the queued task on the server to be a good citizen
    print("\nCleaning up queued task on server...")
    try:
        session.delete(task_url, headers=headers, timeout=30)
        print("Task deleted successfully from server queue.")
    except Exception as e:
        print(f"Failed to delete task: {e}")

    print("\nSpike completed successfully. You can set a breakpoint on line 160 to inspect 'raw_df'.")


if __name__ == "__main__":
    main()
