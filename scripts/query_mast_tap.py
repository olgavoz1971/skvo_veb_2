import pyvo as vo
from astropy.time import Time
import pandas as pd

def query_mast_timeseries(ra, dec, radius_arcsec, t_start=None, t_end=None):
    """
    Queries the MAST CAOMTAP service for time-series data products (like Kepler, K2, TESS)
    within a specific spatial radius and optional time window.
    
    Parameters:
    -----------
    ra : float
        Right Ascension in decimal degrees (ICRS)
    dec : float
        Declination in decimal degrees (ICRS)
    radius_arcsec : float
        Search radius in arcseconds
    t_start : str or float, optional
        Start time of the observation window. Can be an ISO string (e.g. '2010-01-01') 
        or an MJD float. If None, no lower time bound is applied.
    t_end : str or float, optional
        End time of the observation window. Same format as t_start.
        
    Returns:
    --------
    astropy.table.Table
        The query results containing metadata and access URLs for the light curves.
    """
    # 1. Establish connection to the official MAST CAOM TAP service
    tap_url = "https://mast.stsci.edu/vo-tap/api/v0.1/caom"
    service = vo.dal.TAPService(tap_url)
    
    # 2. Convert radius from arcseconds to degrees for the ADQL query
    radius_deg = radius_arcsec / 3600.0
    
    # 3. Base ADQL query using standard ObsCore columns
    # We filter on 'timeseries' to make sure we only fetch actual light curves
    query = f"""
    SELECT 
        target_name, 
        obs_collection, 
        instrument_name, 
        t_min, 
        t_max, 
        t_exptime,
        access_url, 
        access_format
    FROM ivoa.obscore
    WHERE 
        dataproduct_type = 'timeseries'
        AND CONTAINS(
            POINT('ICRS', s_ra, s_dec), 
            CIRCLE('ICRS', {ra}, {dec}, {radius_deg})
        ) = 1
    """
    
    # 4. Helper function to parse inputs into MJD (which obscore uses for t_min / t_max)
    def to_mjd(t_val):
        if isinstance(t_val, str):
            return Time(t_val).mjd
        return t_val # Assumed already a float/int representing MJD
    
    # 5. Dynamically append time constraints if specified
    if t_start is not None:
        mjd_start = to_mjd(t_start)
        query += f"\n        AND t_min >= {mjd_start}"
        
    if t_end is not None:
        mjd_end = to_mjd(t_end)
        query += f"\n        AND t_max <= {mjd_end}"
        
    # Order by target name and instrument for easier reading
    query += "\n    ORDER BY target_name, obs_collection"
    
    print("Executing ADQL Query on MAST...")
    print(query)
    
    # 6. Execute search synchronously (perfect for fast coordinate lookups)
    result = service.search(query)
    
    return result.to_table()

# ==========================================
# Example Usage
# ==========================================
if __name__ == "__main__":
    # # Example: Querying the sky around Kepler-10 (RA: 290.2913, DEC: 42.5029)
    # # ra_target = 290.2913
    ra_target = 316.01949
    # # dec_target = 42.5029
    dec_target = 46.52068
    # # 316.01949 +46.52068       V3101 Cyg
    search_radius_arcsec = 2.0 # 3 arcseconds

    # # 1. Force pandas to display every single column
    # pd.set_option('display.max_columns', None)
    # # 2. Prevent the output from wrapping to a new line
    # pd.set_option('display.width', 1000)
    # # 3. Stop truncating long strings (like your URLs) in cells
    # pd.set_option('display.max_colwidth', None)

    # # Case A: Without time boundaries
    # print("\n--- Running Query WITHOUT Time Bounds ---")
    # results_all_time = query_mast_timeseries(
    #     ra=ra_target, 
    #     dec=dec_target, 
    #     radius_arcsec=search_radius_arcsec
    # )
    
    # # Display the results
    # if len(results_all_time) > 0:
    #     df = results_all_time.to_pandas()
    #     print(df[['target_name', 'obs_collection', 't_min', 't_max', 'access_url']].head())
    # else:
    #     print("No light curves found.")

    # import sys
    # sys.exit(0)    
    # Case B: With ISO time boundaries (e.g., during the early Kepler Prime Mission)
    print("\n--- Running Query WITH Time Bounds (2009 to 2011) ---")
    results_bounded_time = query_mast_timeseries(
        ra=ra_target, 
        dec=dec_target, 
        radius_arcsec=search_radius_arcsec,
        t_start='2024-07-28',
        t_end='2024-08-28'
    )
    
    if len(results_bounded_time) > 0:
        print(results_bounded_time.to_pandas()[['target_name', 'obs_collection', 't_min', 't_max']].head())
    else:
        print("No light curves found in this time range.")
