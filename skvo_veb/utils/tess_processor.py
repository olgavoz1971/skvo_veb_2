import os
import logging
import numpy as np
import pandas as pd
import lightkurve
import astropy.units as u
from lightkurve import search_targetpixelfile, search_tesscut, LightkurveError
from astropy.table import Table

from skvo_veb.utils import tess_cache as cache
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

def get_tpf(target, radius=10):
    """
    Get target pixel file from cache or MAST.
    Logs explicitly if cache is used or if remote MAST is queried.
    """
    tpf = cache.load('tpf', target=target, radius=radius)
    if tpf is not None:
        print(f"[CACHE HIT] 'Search Sector' (TPF) found in local cache for target={target!r}, radius={radius}")
        logger.info(f"get_tpf: Cache HIT for target={target!r}, radius={radius}")
    else:
        print(f"[CACHE MISS] 'Search Sector' (TPF) NOT found in local cache. Querying remote MAST for target={target!r}, radius={radius}...")
        logger.info(f"get_tpf: Cache MISS for target={target!r}. Querying remote MAST.")
        tpf = search_targetpixelfile(target=target, mission='TESS', radius=radius)
        cache.save(tpf, 'tpf', target=target, radius=radius)
    repr(tpf)  # Preserve original side-effect/logic if any
    return tpf


def get_ffi(target):
    """
    Get full frame image from cache or MAST.
    Logs explicitly if cache is used or if remote MAST is queried.
    """
    ffi = cache.load('ffi', target=target)
    if ffi is not None:
        print(f"[CACHE HIT] 'Search Sector' (FFI) found in local cache for target={target!r}")
        logger.info(f"get_ffi: Cache HIT for target={target!r}")
    else:
        print(f"[CACHE MISS] 'Search Sector' (FFI) NOT found in local cache. Querying remote MAST for target={target!r}...")
        logger.info(f"get_ffi: Cache MISS for target={target!r}. Querying remote MAST.")
        ffi = search_tesscut(target)
        cache.save(ffi, prefix='ffi', target=target)
    repr(ffi)  # Preserve original side-effect/logic if any
    return ffi


def download_selected_pixel(pixel_args, search_result_di, size):
    """
    Downloads selected pixel data based on SearchResult and target size.
    With AgGrid, pixel_args is directly the selected row dict.
    Logs explicitly if cache is used or if remote MAST is queried.
    """
    # Restore SearchResults
    search_result_table = Table.from_pandas(pd.DataFrame.from_dict(search_result_di))
    pixel = lightkurve.SearchResult(search_result_table)
    
    row_idx = pixel_args['#']
    if len(pixel) <= row_idx:
        raise ValueError("Invalid selected row index.")
        
    if pixel_args.get('author', '') == 'TESScut':
        kwargs = {
            'target_name': pixel.target_name[row_idx],
            'mission': pixel.mission[row_idx],
            'size': size
        }
        pixel_data = cache.load_ffi_fits(**kwargs)
        if pixel_data is not None:
            print(f"[CACHE HIT] 'Download Sector' (FFI FITS) found in local cache for target_name={kwargs['target_name']!r}, size={size}")
            logger.info(f"download_selected_pixel: Cache HIT for FFI cutout.")
        else:
            print(f"[CACHE MISS] 'Download Sector' (FFI FITS) NOT found in local cache. Querying remote MAST cutout service for target_name={kwargs['target_name']!r}, size={size}...")
            logger.info(f"download_selected_pixel: Cache MISS for FFI cutout. Querying remote MAST.")
            pixel_data = pixel[row_idx].download(cutout_size=size)
            cache.save_ffi_fits(pixel_data, **kwargs)
        pixel_args_out = dict(pixel_args)
        pixel_args_out['pixel_type'] = 'FFI'
    else:
        # Check if SPOC TPF exists in lightkurve cache
        download_dir = pixel[row_idx]._default_download_dir()
        table = pixel[row_idx].table
        path = os.path.join(
            download_dir.rstrip("/"),
            "mastDownload",
            table["obs_collection"][0],
            table["obs_id"][0],
            table["productFilename"][0],
        )
        if os.path.exists(path):
            print(f"[CACHE HIT] 'Download Sector' (SPOC TPF) found in local Lightkurve cache at path={path!r}")
            logger.info(f"download_selected_pixel: SPOC TPF cache HIT at {path}")
        else:
            print(f"[CACHE MISS] 'Download Sector' (SPOC TPF) NOT found in local cache. Querying remote MAST for SPOC TPF...")
            logger.info(f"download_selected_pixel: SPOC TPF cache MISS. Downloading from MAST.")

        try:
            pixel_data = pixel[row_idx].download()
        except LightkurveError as e:
            logger.warning(f'download_selected_pixel exception: {e}')
            # Clean corrupted cache and retry
            # Build the filename of cached lightcurve. See lightkurve/search.py
            logger.warning(f'Removing corrupted cache: {path}')
            if os.path.isfile(path):
                os.remove(path)
            pixel_data = pixel[row_idx].download()

        pixel_args_out = dict(pixel_args)
        pixel_args_out['pixel_type'] = 'TPF'

    return pixel_args_out, pixel_data


def process_lightcurve_computation(pixel_data_path, mask_list, sub_bkg,
                                  flatten, show_trend, flatten_window, 
                                  flatten_break_gap, flatten_order):
    """
    Process pixel data to extract time, flux, and error arrays.
    All scientific computation is isolated here.
    """
    pixel_data = lightkurve.targetpixelfile.TessTargetPixelFile(pixel_data_path)

    if mask_list is None:
        logger.warning('No aperture mask provided')
        raise PipeException('No aperture mask provided')
        
    mask = np.array(mask_list)
    if mask.sum() < 1:
        logger.warning('No valid aperture mask provided')
        raise PipeException('No valid aperture mask provided')

    lc = pixel_data.to_lightcurve(aperture_mask=mask)
    quality_mask = lc['quality'] == 0  # mask by TESS quality
    lc = lc[quality_mask]
    
    jd = lc.time.value
    flux_unit = str(lc.flux.unit)
    flux_err = lc.flux_err
    flux_correction = []

    if sub_bkg:
        flux_correction.append('backgrounded')
        bkg = pixel_data.estimate_background(aperture_mask='background')
        flux = lc.flux - bkg.flux[quality_mask] * mask.sum() * u.pix
    else:
        flux = lc.flux

    if flatten:
        flux_correction.append('flattened')
        lc.flux = flux
        if show_trend:
            _, trend = lc.flatten(window_length=flatten_window,
                                  break_tolerance=flatten_break_gap,
                                  polyorder=flatten_order,
                                  return_trend=True)
            flux = trend.flux
            flux_correction.append('Trend')
        else:
            lc_flattened = lc.flatten(window_length=flatten_window,
                                      break_tolerance=flatten_break_gap,
                                      polyorder=flatten_order)
            flux = lc_flattened.flux
            flux_err = lc_flattened.flux_err

    return jd, flux, flux_err, flux_unit, flux_correction, lc.sector, lc.LABEL


def resolve_object_coordinates(name: str) -> tuple[str, str]:
    """
    Resolve object name to RA and DEC coordinates (sexagesimal format) using Simbad with Sesame fallback.
    """
    if not name or not name.strip():
        raise ValueError("Object name is empty.")
    
    from astroquery.simbad import Simbad
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    
    try:
        result = Simbad.query_object(name.strip())
    except Exception as e:
        logger.warning(f"Simbad query failed for {name}: {e}")
        # Try SkyCoord.from_name as fallback
        try:
            coord = SkyCoord.from_name(name.strip())
            ra_str = coord.ra.to_string(unit=u.hourangle, sep=':', pad=True, precision=2)
            dec_str = coord.dec.to_string(unit=u.deg, sep=':', alwayssign=True, pad=True, precision=2)
            return ra_str, dec_str
        except Exception as e2:
            raise PipeException(f"Failed to resolve coordinates for '{name}' via Simbad or Sesame: {e2}")
            
    if result is None or len(result) == 0:
        # Fallback to SkyCoord.from_name
        try:
            coord = SkyCoord.from_name(name.strip())
            ra_str = coord.ra.to_string(unit=u.hourangle, sep=':', pad=True, precision=2)
            dec_str = coord.dec.to_string(unit=u.deg, sep=':', alwayssign=True, pad=True, precision=2)
            return ra_str, dec_str
        except Exception as e2:
            raise PipeException(f"Object '{name}' not found in Simbad or Sesame.")
            
    try:
        ra_val = result['ra'][0]
        dec_val = result['dec'][0]
        coord = SkyCoord(ra=ra_val, dec=dec_val, unit=(u.deg, u.deg))
        ra_str = coord.ra.to_string(unit=u.hourangle, sep=':', pad=True, precision=2)
        dec_str = coord.dec.to_string(unit=u.deg, sep=':', alwayssign=True, pad=True, precision=2)
        return ra_str, dec_str
    except Exception as e:
        logger.warning(f"Failed to parse Simbad coordinates: {e}")
        raise PipeException(f"Error parsing coordinates for '{name}'.")
