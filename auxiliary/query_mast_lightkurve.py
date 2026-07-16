from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.time import Time
from astroquery.mast import Observations
import lightkurve as lk
import pickle


def search_missions_lightkurve(ra, dec, radius_arcsec=3, 
            t_start=None, t_end=None, how='overlap'):
    """
        Searches MAST for Kepler, K2, and TESS light curves using Lightkurve,
        filtering results based on how the light curve's time interval relates
        to the user's specified [t_start, t_end] interval.
        
        Parameters:
        -----------
        ra, dec : float
            Coordinates in decimal degrees.
        radius_arcsec : float
            Search radius in arcseconds
        t_start : str or float, optional
            Start time of user interval (ISO string or MJD float).
        t_end : str or float, optional
            End time of user interval (ISO string or MJD float).
        how : str, default 'overlap'
            Defines how the light curve's time span must relate to the [t_start, t_end] window:
            - 'overlap'  : Light curve has any overlap with the window (Default).
            - 'within'   : Light curve is completely inside your window.
            - 'contains' : Light curve fully covers your window.
    """
    coords = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg), frame='icrs')
    
    print(f"Searching MAST for Kepler/K2/TESS {cutout_type} within {radius_arcsec} arcseconds...")
    
    # Perform the search
    search_results = lk.search_lightcurve(coords, radius=radius_arcsec)
    
    if len(search_results) == 0:
        print("No light curves found in this region.")
        return None
        
    # Apply optional time filtering
    if t_start is not None or t_end is not None:
        filtered_rows = []
        
        # Parse user boundaries into astropy Time objects
        u_start = Time(t_start) if isinstance(t_start, (str, float, int)) and t_start is not None else None
        u_end = Time(t_end) if isinstance(t_end, (str, float, int)) and t_end is not None else None
        
        table = search_results.table
        for idx, row in enumerate(table):
            # Convert light curve observation boundaries from MJD
            l_start = Time(row['t_min'], format='mjd')
            l_end = Time(row['t_max'], format='mjd')
            
            keep = False
            
            # Case A: Both bounds are specified by the user (strict interval-to-interval checks)
            if u_start is not None and u_end is not None:
                if how == 'overlap':
                    # Intervals overlap if the start of each is before or equal to the end of the other
                    if l_start <= u_end and l_end >= u_start:
                        keep = True
                        
                elif how == 'within':
                    # Light curve is completely nested inside user bounds
                    if l_start >= u_start and l_end <= u_end:
                        keep = True
                        
                elif how == 'contains':
                    # User bounds are completely nested inside the light curve
                    if l_start <= u_start and l_end >= u_end:
                        keep = True
                else:
                    raise ValueError(f"Unknown time_interval relation: '{how}'. Use 'overlap', 'within', or 'inside'")
            
            # Case B: Open-ended time filter (only one user bound was provided)
            else:
                keep = True
                if u_start is not None and l_end < u_start:
                    keep = False  # Light curve ended before our search started
                if u_end is not None and l_start > u_end:
                    keep = False  # Light curve started after our search ended

            if keep:
                filtered_rows.append(idx)
        
        # Filter the search results collection
        search_results = search_results[filtered_rows]
        
    return search_results

 
def search_missions_ffi(ra, dec, t_start=None, t_end=None, how='overlap'):
    """
        Searches MAST for Kepler, K2, and TESS light curves using Lightkurve,
        filtering results based on how the light curve's time interval relates
        to the user's specified [t_start, t_end] interval.
        
        Parameters:
        -----------
        ra, dec : float
            Coordinates in decimal degrees.
        t_start : str or float, optional
            Start time of user interval (ISO string or MJD float).
        t_end : str or float, optional
            End time of user interval (ISO string or MJD float).
        how : str, default 'overlap'
            Defines how the light curve's time span must relate to the [t_start, t_end] window:
            - 'overlap'  : Light curve has any overlap with the window (Default).
            - 'within'   : Light curve is completely inside your window.
            - 'contains' : Light curve fully covers your window.
    """

    coords = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg), frame='icrs')
    
    print(f"Searching MAST for Kepler/K2/TESS FFI for {coords}...")
    
    # Perform the FFI search. Unfortunatelly we can not use there LightKurve module -- 
    # it surprisingly does not provides t_max (it provides somhow t_min only)
    observations = Observations.query_criteria(
            coordinates=coords,
            radius="0 deg",
            obs_collection="TESS",
            dataproduct_type="image",   # FFI-derived products, not 2-min TPFs
        )
    # sectors = observations['sequence_number'] 

    if len(observations) == 0:
        print("No FFI found for these coordinates")
        return None
        
    # Apply optional time filtering
    if t_start is not None or t_end is not None:
        filtered_rows = []
        
        # Parse user boundaries into astropy Time objects
        u_start = Time(t_start) if isinstance(t_start, (str, float, int)) and t_start is not None else None
        u_end = Time(t_end) if isinstance(t_end, (str, float, int)) and t_end is not None else None

        for idx, row in enumerate(observations):
            # Convert light curve observation boundaries from MJD
            l_start = Time(row['t_min'], format='mjd')
            l_end = Time(row['t_max'], format='mjd')
            
            keep = False
            
            # Case A: Both bounds are specified by the user (strict interval-to-interval checks)
            if u_start is not None and u_end is not None:
                if how == 'overlap':
                    # Intervals overlap if the start of each is before or equal to the end of the other
                    if l_start <= u_end and l_end >= u_start:
                        keep = True
                        
                elif how == 'within':
                    # Light curve is completely nested inside user bounds
                    if l_start >= u_start and l_end <= u_end:
                        keep = True
                        
                elif how == 'contains':
                    # User bounds are completely nested inside the light curve
                    if l_start <= u_start and l_end >= u_end:
                        keep = True
                else:
                    raise ValueError(f"Unknown time_interval relation: '{how}'. Use 'overlap', 'within', or 'inside'")
            
            # Case B: Open-ended time filter (only one user bound was provided)
            else:
                keep = True
                if u_start is not None and l_end < u_start:
                    keep = False  # Light curve ended before our search started
                if u_end is not None and l_start > u_end:
                    keep = False  # Light curve started after our search ended

            if keep:
                filtered_rows.append(idx)
        
        # Filter the search results collection
        observations = observations[filtered_rows]
        
    return observations


if __name__ == "__main__":
    ra_target = 316.01949
    dec_target = 46.52068
    radius = 2.0 # arcseconds

    # Fetch Kepler & TESS data from 2018 onwards (which captures TESS data)
    t_start = '2018-01-01'
    t_end = '2024-12-31'
    how = 'overlap'
    cutout_type = 'ffi'
    load_from_file = True    
    output_filename_base = f'{ra_target:.3f}_{dec_target:.3f}_{cutout_type}_{t_start}_{t_end}_{how}'  

    
    if load_from_file:
        with open(f'{output_filename_base}.pkl', 'rb') as f:
            observations = pickle.load(f)
        print(f"Restored a functional Observations object containing {len(observations)} rows")
    else:
        observations = search_missions_ffi(
                ra=ra_target, 
                dec=dec_target,
                t_start=t_start,
                t_end=t_end,
                how=how
            )
        with open(f'{output_filename_base}.pkl', 'wb') as f:
                        pickle.dump(observations, f)
        print(f"Fully functional Observations table frozen to {output_filename_base}.pkl")

    print(observations['obs_collection', 's_ra', 's_dec', 'sequence_number', 't_min', 't_max', 'distance'])

    import sys
    sys.exit(0)

    selected_columns = ['obs_collection','provenance_name','project','s_ra','s_dec',
        'dataproduct_type', 'calib_level','t_min','t_max','t_exptime', 'distance', 
        'exptime', 'size', 'author','mission', 'year']

    if load_from_file:
        # Reopen the file in another script or session
        with open(f'{output_filename_base}.pkl', 'rb') as f:
            results = pickle.load(f)
        print(f"Restored a functional object containing {len(results)} rows")

    else:
        results = search_missions_lightkurve(
            ra=ra_target, 
            dec=dec_target, 
            radius_arcsec=radius,
            t_start=t_start,
            t_end=t_end,
            how=how
        )
        results.table[selected_columns].write(
            f'{output_filename_base}.ecsv', format='ascii.ecsv', overwrite=True)
        print("Selected columns saved to lightkurve_subset.ecsv")
        
        with open(f'{output_filename_base}.pkl', 'wb') as f:
                    pickle.dump(results, f)
        print(f"Fully functional SearchResult frozen to {output_filename_base}.pkl")
        
    
    if results and len(results) > 0:
        print(f"\nFound {len(results)} matching light curves:")
        results.table.pprint(max_lines=-1)              
        
    # light_curves = results.download_all()
    import matplotlib.pyplot as plt
    print('Pick up some, download and plot it')
    mask = (results.table['t_exptime'] > 180) & (results.table['author'] == 'TESS-SPOC') & (results.table['year'] == 2022)
    if mask.sum() > 0:
        lc = results[mask][0].download()
        lc.plot()
        plt.show()

