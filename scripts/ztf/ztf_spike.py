#!/usr/bin/env python3
"""ZTF Lightcurve Discovery & Retrieval Spike.

An isolated, simple, and metadata-rich spike script to demonstrate the two-step
process of ZTF data handling:
1. Discovery (via name resolution or cone search) to get catalog metadata.
2. Retrieval (downloading a specific lightcurve and visualizing it).

This script is self-contained and runs purely in the terminal.
"""

from __future__ import annotations

import os
import sys
import io
import requests
import pandas as pd
import numpy as np
from pathlib import Path

# Add repository root to python path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from astroquery.ipac.irsa import Irsa
from astroquery.simbad import Simbad
from astropy.coordinates import SkyCoord
import astropy.units as u

# Standard ZTF bands mapping
_ZTF_BANDS = {1: "ztf-g", 2: "ztf-r", 3: "ztf-i"}


def banner(title: str, char: str = "=") -> None:
    """Prints a section banner."""
    line = char * max(72, len(title) + 4)
    print(f"\n{line}\n  {title}\n{line}")


def resolve_object_name(name: str) -> dict | None:
    """Resolves an object name using Simbad and returns coordinates and object type."""
    print(f"\nResolving name '{name}' via Simbad...")
    try:
        # Request standard fields and object type
        Simbad.add_votable_fields('otype', 'otypedef')
        res = Simbad.query_object(name)
        if res is None or len(res) == 0:
            print("Simbad could not resolve this name.")
            return None
        
        row = res[0]
        main_id = str(row['main_id'])
        ra_deg = float(row['ra'])
        dec_deg = float(row['dec'])
        
        # Get object type description if available
        otype_desc = "Unknown"
        if 'otypedef.otype_longname' in row.colnames:
            otype_desc = str(row['otypedef.otype_longname'])
        elif 'otype' in row.colnames:
            otype_desc = str(row['otype'])
            
        return {
            "main_id": main_id,
            "ra": ra_deg,
            "dec": dec_deg,
            "otype": otype_desc
        }
    except Exception as e:
        print(f"Simbad resolution failed: {e}")
        return None


def discover_ztf_objects(ra: float, dec: float, radius_arcsec: float) -> pd.DataFrame:
    """Performs a TAP cone search on ztf_objects_dr24 to discover ZTF objects."""
    radius_deg = radius_arcsec / 3600.0
    print(f"Querying IRSA TAP for ZTF objects within {radius_arcsec} arcsec...")
    
    # We query the collapsed-lightcurve objects table for DR24
    query = f"""
    SELECT oid, ra, dec, filtercode, nobsrel, meanmag, magrms
    FROM ztf_objects_dr24
    WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {radius_deg})) = 1
    """
    try:
        res = Irsa.query_tap(query=query)
        if res is None or len(res) == 0:
            return pd.DataFrame()
        return res.to_table().to_pandas()
    except Exception as e:
        print(f"TAP query failed: {e}")
        return pd.DataFrame()


def discover_ztf_by_oid(oid: int) -> pd.DataFrame:
    """Queries IRSA TAP for a specific ZTF OID."""
    print(f"Querying IRSA TAP for ZTF OID {oid}...")
    query = f"""
    SELECT oid, ra, dec, filtercode, nobsrel, meanmag, magrms
    FROM ztf_objects_dr24
    WHERE oid = {oid}
    """
    try:
        res = Irsa.query_tap(query=query)
        if res is None or len(res) == 0:
            return pd.DataFrame()
        return res.to_table().to_pandas()
    except Exception as e:
        print(f"TAP query failed: {e}")
        return pd.DataFrame()


def download_lightcurve(oid: int) -> pd.DataFrame:
    """Downloads the full ZTF lightcurve directly from the IRSA API."""
    print(f"\nDownloading lightcurve for OID {oid} from IRSA...")
    url = 'https://irsa.ipac.caltech.edu/cgi-bin/ZTF/nph_light_curves'
    params = {
        'ID': oid,
        'FORMAT': 'csv'
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"IRSA API returned status code {resp.status_code}")
            return pd.DataFrame()
        
        # Check if we got actual data or an error message
        text = resp.text
        if text.startswith("No light curves found"):
            print("No light curves found for this OID.")
            return pd.DataFrame()
            
        df = pd.read_csv(io.StringIO(text))
        return df
    except Exception as e:
        print(f"Failed to download lightcurve: {e}")
        return pd.DataFrame()


def ascii_plot(times: np.ndarray, values: np.ndarray, width: int = 65, height: int = 15) -> str:
    """Generates a beautiful magnitude vs. time ASCII plot (inverted magnitude scale)."""
    if len(times) == 0 or len(values) == 0:
        return "No data to plot."
    
    t_min, t_max = np.min(times), np.max(times)
    v_min, v_max = np.min(values), np.max(values)
    
    t_range = t_max - t_min if t_max != t_min else 1.0
    v_range = v_max - v_min if v_max != v_min else 1.0
    
    grid = [[" " for _ in range(width)] for _ in range(height)]
    
    for t, v in zip(times, values):
        x = int((t - t_min) / t_range * (width - 1))
        # Invert magnitude scale: brighter (smaller values) at the top
        y = int((v_max - v) / v_range * (height - 1))
        grid[y][x] = "*"
        
    lines = []
    lines.append(f"Brighter ({v_min:.3f}) " + "_" * (width - 12))
    for r in range(height):
        row_str = "".join(grid[r])
        lines.append(f"| {row_str} |")
    lines.append("Fainter  (" + f"{v_max:.3f}) " + "_" * (width - 12))
    lines.append(" " * 9 + f"Time (HMJD): {t_min:.3f} " + " " * (width - 29) + f"{t_max:.3f}")
    return "\n".join(lines)


def display_objects_table(df: pd.DataFrame, center_ra: float | None = None, center_dec: float | None = None) -> None:
    """Prints a clean, formatted table of discovered ZTF objects."""
    if df.empty:
        print("No ZTF objects found.")
        return
        
    # Calculate distance if center coordinates are provided
    if center_ra is not None and center_dec is not None:
        c_search = SkyCoord(center_ra * u.deg, center_dec * u.deg, frame="icrs")
        c_objs = SkyCoord(df["ra"].to_numpy() * u.deg, df["dec"].to_numpy() * u.deg, frame="icrs")
        df["dist_arcsec"] = c_search.separation(c_objs).arcsecond
        df = df.sort_values("dist_arcsec").reset_index(drop=True)
    else:
        df["dist_arcsec"] = np.nan
        
    print("\nDiscovered ZTF Objects (DR24):")
    print("-" * 90)
    print(f"{'Index':<5} | {'ZTF OID':<16} | {'Filter':<6} | {'N_Epochs':<8} | {'Mean Mag':<8} | {'Mag RMS':<8} | {'Dist (arcsec)':<12}")
    print("-" * 90)
    for idx, row in df.iterrows():
        dist_str = f"{row['dist_arcsec']:.2f}" if not np.isnan(row['dist_arcsec']) else "N/A"
        print(f"{idx:<5} | {int(row['oid']):<16} | {row['filtercode']:<6} | {int(row['nobsrel']):<8} | {row['meanmag']:<8.3f} | {row['magrms']:<8.3f} | {dist_str:<12}")
    print("-" * 90)


def inspect_lightcurve(df: pd.DataFrame, oid: int) -> None:
    """Parses, analyzes, and visualizes a downloaded ZTF lightcurve."""
    if df.empty:
        return
        
    # Filter out bad observations (catflags != 0)
    clean_df = df[df["catflags"] == 0].copy()
    n_total = len(df)
    n_clean = len(clean_df)
    
    # Calculate HMJD from HJD
    # HMJD = HJD - 2400000.5
    df["hmjd"] = df["hjd"] - 2400000.5
    clean_df["hmjd"] = clean_df["hjd"] - 2400000.5
    
    t_min = df["hmjd"].min()
    t_max = df["hmjd"].max()
    duration = t_max - t_min
    
    # Get band name
    fid = df["filtercode"].iloc[0] if "filtercode" in df.columns else "unknown"
    
    banner(f"LIGHTCURVE METADATA FOR OID {oid}")
    print(f"Data Collection:      ZTF Public Data Release 24 (DR24)")
    print(f"Facility / Site:      Palomar Observatory (P48 Telescope)")
    print(f"Instrument:           ZTF Camera")
    print(f"Filter / Band:        {fid}")
    print(f"Total Epochs:         {n_total}")
    print(f"Clean Epochs (cat=0): {n_clean} ({n_clean/n_total*100:.1f}%)")
    print(f"Start Time (HMJD):    {t_min:.5f}")
    print(f"End Time (HMJD):      {t_max:.5f}")
    print(f"Time Span (Duration): {duration:.2f} days (~{duration/365.25:.1f} years)")
    
    print("\nFirst 5 Rows of Raw Lightcurve Data:")
    print("-" * 80)
    print(df[["mjd", "hjd", "hmjd", "mag", "magerr", "catflags"]].head(5).to_string(index=False))
    print("-" * 80)
    
    # ASCII Plot
    banner("ASCII LIGHTCURVE VISUALISATION (HMJD vs Mag)")
    print(ascii_plot(clean_df["hmjd"].to_numpy(), clean_df["mag"].to_numpy()))
    
    # VO Metadata Description
    banner("COMPLIANT IVOA VOTABLE METADATA SPECIFICATION")
    print("This is how we would describe this lightcurve in a VO-compliant VOTable:")
    print(f"""
  <TIMESYS ID="ts" refposition="HELIOCENTER" timescale="UTC" timeorigin="2400000.5" />
  
  <GROUP ID="phot_def" name="photcal">
    <PARAM name="filterIdentifier" value="ZTF/{fid}" utype="photDM:PhotometryFilter.identifier" ucd="meta.id;instr.filter" />
    <PARAM name="magnitudeSystem" value="AB" utype="photDM:PhotCal.magnitudeSystem.type" ucd="meta.code" />
  </GROUP>
  
  <PARAM name="facility_name" value="Palomar Observatory" utype="ssa:DataID.Facility" ucd="meta.id;instr.tel" />
  <PARAM name="instrument_name" value="ZTF Camera" utype="ssa:DataID.Instrument" ucd="meta.id;instr" />
  <PARAM name="obs_collection" value="ZTF DR24" utype="ssa:DataID.Collection" ucd="meta.id" />
  
  <FIELD name="obs_time" ID="obs_time" ucd="time.epoch" unit="d" ref="ts" description="Time in Heliocentric Modified Julian Date (HMJD)" />
  <FIELD name="phot" ID="phot" ucd="phot.mag" unit="mag" ref="phot_def" description="Calibrated AB Magnitude" />
  <FIELD name="flux_error" ID="flux_error" ucd="stat.error;phot.mag" unit="mag" description="Magnitude Uncertainty" />
    """)


def main() -> None:
    import io
    banner("ZTF LIGHTCURVE DISCOVERY & RETRIEVAL SPIKE")
    print("An isolated, simple terminal tool for exploring and retrieving ZTF lightcurves.")
    
    while True:
        print("\nMain Menu:")
        print("1. Discover ZTF Objects by Name (Simbad)")
        print("2. Discover ZTF Objects by Coordinates (Cone Search)")
        print("3. Discover ZTF Objects by direct ZTF OID")
        print("4. Exit")
        
        try:
            choice = input("\nEnter choice (1-4): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break
            
        if choice == "4":
            print("Exiting.")
            break
            
        df = pd.DataFrame()
        center_ra, center_dec = None, None
        
        if choice == "1":
            name = input("Enter object name (e.g., V3101 Cyg, AA And): ").strip()
            if not name:
                continue
            resolved = resolve_object_name(name)
            if resolved:
                print(f"\nResolved Name: {resolved['main_id']}")
                print(f"Coordinates:   RA = {resolved['ra']:.5f} deg, Dec = {resolved['dec']:.5f} deg")
                print(f"Object Type:   {resolved['otype']}")
                center_ra, center_dec = resolved['ra'], resolved['dec']
                df = discover_ztf_objects(center_ra, center_dec, radius_arcsec=5.0)
                display_objects_table(df, center_ra, center_dec)
                
        elif choice == "2":
            try:
                ra_str = input("Enter RA (deg): ").strip()
                dec_str = input("Enter Dec (deg): ").strip()
                rad_str = input("Enter Radius (arcsec, default 5.0): ").strip()
                
                center_ra = float(ra_str)
                center_dec = float(dec_str)
                radius = float(rad_str) if rad_str else 5.0
                
                df = discover_ztf_objects(center_ra, center_dec, radius)
                display_objects_table(df, center_ra, center_dec)
            except ValueError:
                print("Invalid numerical input.")
                continue
                
        elif choice == "3":
            oid_str = input("Enter ZTF OID: ").strip()
            if not oid_str:
                continue
            try:
                oid = int(oid_str)
                df = discover_ztf_by_oid(oid)
                display_objects_table(df)
            except ValueError:
                print("Invalid OID.")
                continue
        else:
            print("Invalid choice.")
            continue
            
        if not df.empty:
            try:
                ans = input("\nWould you like to retrieve and inspect a lightcurve?\nEnter the OID to retrieve (or press Enter to return to menu): ").strip()
                if ans:
                    oid_to_fetch = int(ans)
                    lc_df = download_lightcurve(oid_to_fetch)
                    inspect_lightcurve(lc_df, oid_to_fetch)
            except ValueError:
                print("Invalid OID.")
            except Exception as e:
                print(f"Error: {e}")


if __name__ == "__main__":
    aaa = discover_ztf_objects(ra=0, dec=0, radius_arcsec=600)
    pass
    # main()
