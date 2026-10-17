import os
import logging
from functools import lru_cache

import numpy as np
import pandas as pd
import lightkurve
import astropy.units as u
from lightkurve import search_targetpixelfile, search_tesscut, LightkurveError
from astropy.table import Table

from skvo_veb.utils import lightkurve_cache
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
        logger.info(f"get_tpf: Cache HIT for target={target!r}, radius={radius}. 'Search Sector' (TPF) found in local cache.")
    else:
        logger.info(f"get_tpf: Cache MISS for target={target!r}. Querying remote MAST for 'Search Sector' (TPF)...")
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
        logger.info(f"get_ffi: Cache HIT for target={target!r}. 'Search Sector' (FFI) found in local cache.")
    else:
        logger.info(f"get_ffi: Cache MISS for target={target!r}. Querying remote MAST for 'Search Sector' (FFI)...")
        ffi = search_tesscut(target)
        cache.save(ffi, prefix='ffi', target=target)
    repr(ffi)  # Preserve original side-effect/logic if any
    return ffi


def _restore_pixel_search(search_result_di):
    """Rebuilds the Lightkurve search result from its stored dictionary.

    Args:
        search_result_di (dict): Column-wise search result table from the page store.

    Returns:
        lightkurve.SearchResult: The restored search result.
    """
    search_result_table = Table.from_pandas(pd.DataFrame.from_dict(search_result_di))
    return lightkurve.SearchResult(search_result_table)


def fresh_pixel_summary(pixel_args, size):
    """Describes a freshly downloaded cutout for the user.

    Args:
        pixel_args (dict): Selected table row with ``target``, ``mission``, ``author`` and ``exptime``.
        size (int): FFI cutout size in pixels (shown for FFI rows only).

    Returns:
        str: One-sentence message naming target, sector, author, exposure time and cutout size.
    """
    parts = [str(pixel_args['target']), str(pixel_args['mission']), str(pixel_args['author']),
             f"{pixel_args['exptime']} s"]
    if pixel_args.get('author', '') == 'TESScut':
        parts.append(f"{size}x{size} pixels")
    return f"Fresh data downloaded from MAST: {', '.join(parts)}. The cutout is ready on the Plot tab."


def download_selected_pixel(pixel_args, search_result_di, size, fresh_from_mast=False):
    """Retrieves the selected FFI cutout or SPOC TPF.

    Both kinds live only in the shared Lightkurve cache, so every user and worker of the
    server reuses one copy. With ``fresh_from_mast`` the cached copy is replaced by a new
    MAST download.

    Args:
        pixel_args (dict): Selected table row (AgGrid row dict with ``#`` and ``author``).
        search_result_di (dict): Column-wise search result table from the page store.
        size (int): FFI cutout size in pixels (used for FFI rows only).
        fresh_from_mast (bool): Ignore the cached copy and download a new one.

    Returns:
        tuple: ``(pixel_args_out, pixel_data)`` with ``pixel_type`` added to the row.

    Raises:
        ValueError: If the row index is invalid.
        PipeException: If the target position of an FFI row cannot be determined or the
            download fails.
    """
    pixel = _restore_pixel_search(search_result_di)

    row_idx = pixel_args['#']
    if len(pixel) <= row_idx:
        raise ValueError("Invalid selected row index.")

    if pixel_args.get('author', '') == 'TESScut':
        target_name = pixel.target_name[row_idx]
        target_coord = cache.extract_coords(target_name)
        if target_coord is None:
            raise PipeException(f"Cannot determine the position of '{target_name}' to find its cutout.")
        pixel_data = lightkurve_cache.fetch_tesscut_pixel_file(
            pixel, row_idx, size, target_coord, force_fresh=fresh_from_mast)
        pixel_args_out = dict(pixel_args)
        pixel_args_out['pixel_type'] = 'FFI'
    else:
        if fresh_from_mast:
            lightkurve_cache.purge_spoc_tpf(pixel, row_idx)
        path = lightkurve_cache.spoc_tpf_cache_path(pixel, row_idx)
        if os.path.exists(path):
            logger.info(f"download_selected_pixel: SPOC TPF cache HIT. 'Retrieve sector' (SPOC TPF) found in local Lightkurve cache at path={path!r}")
        else:
            logger.info(f"download_selected_pixel: SPOC TPF cache MISS. Retrieving from MAST... 'Retrieve sector' (SPOC TPF) NOT found in local cache.")

        try:
            pixel_data = pixel[row_idx].download()
        except LightkurveError as e:
            logger.warning(f'download_selected_pixel exception: {e}')
            # Clean corrupted cache and retry
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


def _coord_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()


def has_coord(value) -> bool:
    return bool(_coord_text(value))


def has_valid_resolved(resolved_coords, obj_name) -> bool:
    """True when Resolve was run for the current object name and stored coordinates exist."""
    if not resolved_coords or not obj_name:
        return False
    if resolved_coords.get('obj_name') != str(obj_name).strip():
        return False
    return has_coord(resolved_coords.get('ra')) and has_coord(resolved_coords.get('dec'))


def resolve_search_target(obj_name, ra, dec, resolved_coords):
    """
    Decide how to query MAST/cache for Search.

    Returns (target, search_mode) where search_mode is one of:
    - 'object_name': search by catalogue name
    - 'resolved_coordinates': search by coordinates from Resolve for this object
    - 'coordinates_only': search by manually entered RA/DEC (no object name)
    """
    if obj_name and str(obj_name).strip():
        obj = str(obj_name).strip()
        if has_valid_resolved(resolved_coords, obj):
            ra_res = resolved_coords['ra']
            dec_res = resolved_coords['dec']
            target = f"{_coord_text(ra_res)} {_coord_text(dec_res)}"
            return target, 'resolved_coordinates'
        return obj, 'object_name'

    if not has_coord(ra) or not has_coord(dec):
        raise PipeException("Please enter an object name or RA/DEC coordinates.")
    target = f"{_coord_text(ra)} {_coord_text(dec)}"
    return target, 'coordinates_only'


@lru_cache(maxsize=8)
def load_cutout_flux_cube(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Loads a cutout flux cube and cadence timestamps from a local FITS path.

    Args:
        path (str): Absolute path to a TESS cutout FITS file.

    Returns:
        tuple[np.ndarray, np.ndarray]: ``(flux_cube, time_btjd)`` with shape
            ``(n_cadence, ny, nx)`` and length ``n_cadence``.
    """
    pixel_data = lightkurve.targetpixelfile.TessTargetPixelFile(path)
    flux_cube = np.asarray(pixel_data.flux.value, dtype=float)
    if flux_cube.ndim == 2:
        flux_cube = flux_cube[np.newaxis, ...]
    time_values = np.asarray(getattr(pixel_data.time, 'value', pixel_data.time), dtype=float)
    if time_values.ndim == 0:
        time_values = np.array([float(time_values)])
    if time_values.size != flux_cube.shape[0]:
        time_values = np.arange(flux_cube.shape[0], dtype=float)
    return flux_cube, time_values


def select_cutout_display_frame(
    flux_cube: np.ndarray,
    *,
    frame_index: int,
    sum_cadences: bool,
) -> tuple[np.ndarray, int]:
    """Selects the 2D cutout image to display from a cadence stack.

    Args:
        flux_cube (np.ndarray): Flux array with shape ``(n_cadence, ny, nx)``.
        frame_index (int): Cadence index when not summing.
        sum_cadences (bool): When true, return the sum over all cadences.

    Returns:
        tuple[np.ndarray, int]: Display image and the cadence index used for labelling.
    """
    if sum_cadences or flux_cube.shape[0] <= 1:
        return np.sum(flux_cube, axis=0), 0
    clamped = int(max(0, min(frame_index, flux_cube.shape[0] - 1)))
    return flux_cube[clamped], clamped


def cutout_frame_slider_layout(n_cadences: int, sum_cadences: bool) -> dict:
    """Builds Dash slider properties for browsing a TPF cadence stack.

    Args:
        n_cadences (int): Number of cadence frames in the cutout.
        sum_cadences (bool): Whether the UI is in summed-frame mode.

    Returns:
        dict: Slider min/max/value/disabled/marks and container visibility style.
    """
    enabled = n_cadences > 1 and not sum_cadences
    max_idx = max(n_cadences - 1, 0)
    marks = {0: '1', max_idx: str(n_cadences)} if enabled and n_cadences > 1 else None
    return {
        'min': 0,
        'max': max_idx,
        'disabled': not enabled,
        'marks': marks,
        'row_style': {'display': 'block', 'marginTop': '8px'} if enabled else {'display': 'none'},
    }


def format_cutout_pixel_title(
    pixel_metadata: dict,
    *,
    frame_index: int,
    n_cadences: int,
    time_btjd: float | None,
    sum_cadences: bool,
) -> str:
    """Formats the pixel-cutout graph title with optional cadence context.

    Args:
        pixel_metadata (dict): Stored cutout metadata from the download callback.
        frame_index (int): Active cadence index (0-based).
        n_cadences (int): Total number of cadence frames.
        time_btjd (float, optional): BTJD timestamp for the active frame.
        sum_cadences (bool): Whether all cadences are summed in the display.

    Returns:
        str: Title text for the pixel graph.
    """
    base = ' '.join(
        part for part in (
            pixel_metadata.get('lookup_name', ''),
            pixel_metadata.get('target', ''),
            pixel_metadata.get('author', ''),
        )
        if part
    ).strip()
    if sum_cadences and n_cadences > 1:
        return f'{base} (sum of {n_cadences} frames)'
    if n_cadences > 1 and time_btjd is not None:
        return f'{base} (frame {frame_index + 1}/{n_cadences}, BTJD {time_btjd:.4f})'
    return base

