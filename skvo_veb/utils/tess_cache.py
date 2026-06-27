import dill
import logging
import tarfile
import os
import hashlib
import tempfile
import re
from os import getenv

from astropy.coordinates import SkyCoord
import astropy.units as u

# Configure logging path and level
logging.basicConfig(filename=getenv('APP_LOG'), level=logging.INFO)

import lightkurve
from lightkurve import TessTargetPixelFile, TessLightCurve

# Caching Tolerances for matching coordinates and cutout field size
COORD_TOLERANCE_DEG = 0.02  # ~1.2 arcminutes (about 3-4 TESS pixels)
SIZE_TOLERANCE = 1         # size tolerance for FFI cutouts (in pixels)


def extract_coords(val):
    """
    Attempts to extract an astropy SkyCoord from a string or object.
    Supports names like 'AA And', decimal coordinates '85.48 -23.14', sexagesimal etc.
    """
    if not val:
        return None
    val_str = str(val).strip()
    
    # 1. Check if we already have it in decimal format (e.g. "85.482810 -23.142525")
    # This is extremely common for TESS targets
    try:
        m = re.match(r'^([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)$', val_str)
        if m:
            ra = float(m.group(1))
            dec = float(m.group(2))
            return SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg))
    except Exception:
        pass

    # 2. Try general coordinate string parsing (handles space or colon separated values)
    for unit in [(u.deg, u.deg), (u.hourangle, u.deg)]:
        try:
            return SkyCoord(val_str, unit=unit)
        except Exception:
            pass

    # 3. Try resolving via SkyCoord.from_name
    try:
        return SkyCoord.from_name(val_str)
    except Exception as e:
        logging.debug(f"SkyCoord.from_name failed for '{val_str}': {e}")
        
    # 4. As a final fallback, try our Simbad query directly
    try:
        from astroquery.simbad import Simbad
        result = Simbad.query_object(val_str)
        if result is not None and len(result) > 0:
            coord = SkyCoord(ra=result['ra'][0], dec=result['dec'][0], unit=(u.deg, u.deg))
            return coord
    except Exception as e:
        logging.warning(f"Simbad query fallback failed in tess_cache for '{val_str}': {e}")
        
    return None


def _find_cached_file(prefix, extension='dill', **kwargs):
    """
    Scans the cache directory to find an existing cached file that matches the 
    requested prefix, extension, non-coordinate parameters, and has coordinates
    within the configured COORD_TOLERANCE_DEG (taking into account the pole effect 
    via Astropy SkyCoord separation).
    
    If multiple candidate files exist within tolerance, returns the one with the 
    smallest angular separation.
    """
    cache_dir = os.getenv('TESS_CACHE_DIR')
    if not cache_dir or not os.path.exists(cache_dir):
        return None

    # Resolve coordinates for the requested target
    target_val = kwargs.get('target') or kwargs.get('target_name')
    if not target_val:
        return None
        
    requested_coord = extract_coords(target_val)
    if requested_coord is None:
        return None

    # Extract non-coordinate parameters and size
    non_coord_kwargs = {k: v for k, v in kwargs.items() if k not in ('target', 'target_name')}
    requested_size = non_coord_kwargs.pop('size', None)
    requested_nc_hash = hashlib.md5(str(sorted(non_coord_kwargs.items())).encode()).hexdigest()

    best_file_path = None
    min_separation = float('inf')

    # Scan the cache directory for matching files
    try:
        for fname in os.listdir(cache_dir):
            if not fname.startswith(f"{prefix}_ra_") or not fname.endswith(f".{extension}"):
                continue
                
            # Pattern matching format: prefix_ra_..._dec_...[_size_...]_nc_HASH.ext
            pattern = rf"^{prefix}_ra_([+-]?\d+(?:\.\d+)?|nan)_dec_([+-]?\d+(?:\.\d+)?|nan)_(?:size_(\d+)_)?nc_([0-9a-f]+)\.{extension}$"
            match = re.match(pattern, fname)
            if not match:
                continue
                
            cached_ra_str, cached_dec_str, cached_size_str, cached_nc_hash = match.groups()
            
            # Check non-coordinate parameters hash
            if cached_nc_hash != requested_nc_hash:
                continue
                
            # Check size if applicable
            if requested_size is not None:
                if cached_size_str is None:
                    continue
                cached_size = int(cached_size_str)
                if abs(cached_size - int(requested_size)) > SIZE_TOLERANCE:
                    continue
            else:
                if cached_size_str is not None:
                    continue

            # Convert cached coordinates to SkyCoord
            try:
                cached_coord = SkyCoord(ra=float(cached_ra_str), dec=float(cached_dec_str), unit=(u.deg, u.deg))
            except Exception:
                continue

            # Calculate angular separation (handles convergence at poles correctly!)
            separation = requested_coord.separation(cached_coord).deg
            if separation <= COORD_TOLERANCE_DEG:
                if separation < min_separation:
                    min_separation = separation
                    best_file_path = os.path.join(cache_dir, fname)
    except Exception as e:
        logging.error(f"Error scanning cache directory: {e}")

    if best_file_path:
        logging.info(f"Smarter Caching MATCH found! {best_file_path} is within {min_separation:.6f} deg of requested {target_val}")
    return best_file_path


def _get_cache_filename(prefix, extension='dill', **kwargs):
    """
    Generates a deterministic and unique cache filename based on a prefix and parameters.

    If coordinates are resolvable, embeds coordinates and other metadata in the filename
    to support smarter, tolerance-aware caching lookups. Otherwise, falls back to a 
    standard MD5-hash filename.

    Parameters:
    -----------
    prefix : str
        The type identifier of cached data (e.g., 'tpf', 'ffi', 'lc').
    extension : str, optional
        The file extension to append (default is 'dill').
    **kwargs : dict
        Arbitrary query or query-defining parameters (e.g., target, radius).

    Returns:
    --------
    str or None
        The absolute path to the designated cache file, or None if TESS_CACHE_DIR is not set.
    """
    cache_dir = os.getenv('TESS_CACHE_DIR')
    if not cache_dir:
        logging.warning('Environmental variable TESS_CACHE_DIR is not specified')
        return None
    
    # Ensure the cache folder exists to avoid FileNotFoundError on write
    os.makedirs(cache_dir, exist_ok=True)
    
    target_val = kwargs.get('target') or kwargs.get('target_name')
    if target_val:
        coord = extract_coords(target_val)
        if coord is not None:
            non_coord_kwargs = {k: v for k, v in kwargs.items() if k not in ('target', 'target_name')}
            size_val = non_coord_kwargs.pop('size', None)
            nc_hash = hashlib.md5(str(sorted(non_coord_kwargs.items())).encode()).hexdigest()
            
            if size_val is not None:
                fname = f"{prefix}_ra_{coord.ra.deg:.6f}_dec_{coord.dec.deg:.6f}_size_{size_val}_nc_{nc_hash}.{extension}"
            else:
                fname = f"{prefix}_ra_{coord.ra.deg:.6f}_dec_{coord.dec.deg:.6f}_nc_{nc_hash}.{extension}"
            return os.path.join(cache_dir, fname)
    
    # Fallback to pure MD5 hash of all parameters if coordinates are not resolvable
    stable_args_str = str(sorted(kwargs.items()))
    hashed_args = hashlib.md5(stable_args_str.encode()).hexdigest()
    unique_key = f"{prefix}_{hashed_args}.{extension}"
    cache_file_path = os.path.join(cache_dir, unique_key)
    
    logging.debug(f"Resolved cache path for {prefix} (args: {kwargs}) -> {cache_file_path}")
    return cache_file_path


def _save_atomically(filename, write_func):
    """
    Writes data to a temporary file in the target directory and renames it atomically.

    This prevents file corruption and race conditions under concurrent process environments
    (such as Apache multi-threaded workers) because the operating system renames the temporary 
    file in a single atomic filesystem transaction.

    Parameters:
    -----------
    filename : str
        The final target path for the cache file.
    write_func : callable
        A function or lambda that accepts a file path (str) and handles the actual writing.
    """
    if not filename:
        return
    cache_dir = os.path.dirname(filename)
    
    # Create temporary file in the same directory to guarantee atomic move on the same filesystem
    with tempfile.NamedTemporaryFile(dir=cache_dir, delete=False, suffix='.tmp') as tmp_file:
        temp_path = tmp_file.name
    
    try:
        write_func(temp_path)
        os.replace(temp_path, filename)
    except Exception as e:
        logging.error(f"Atomic cache write failed for {filename}: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise e


def save(data, prefix, **kwargs):
    """
    Saves a Python object to the cache using dill serialization in an atomic, process-safe manner.

    Parameters:
    -----------
    data : any
        The object or dataset to be serialized.
    prefix : str
        The identifier name for the cache prefix.
    **kwargs : dict
        Query boundaries or metadata used to compute the unique filename.
    """
    filename = _get_cache_filename(prefix, **kwargs)
    if not filename:
        return

    def write_dill(path):
        with open(path, "wb") as f:
            dill.dump(data, f)

    _save_atomically(filename, write_dill)


def save_tpf_fits(data, **kwargs):
    """
    Saves TESS Target Pixel File (TPF) data into the cache as a FITS file atomically.

    Parameters:
    -----------
    data : TessTargetPixelFile
        The TESS Target Pixel File object.
    **kwargs : dict
        Metadata representing the target star boundaries.
    """
    prefix = 'tpf_data'
    filename = _get_cache_filename(prefix, extension='fits', **kwargs)
    if not filename:
        return
    _save_atomically(filename, lambda path: data.to_fits(path, overwrite=True))


def load_tpf_fits(**kwargs):
    """
    Loads TessTargetPixelFile data from the public FITS cache with smart coordinate-aware lookup.

    If the file exists but is corrupted (causing reader exception), it automatically 
    deletes the corrupted cache file and returns None to trigger a fresh download.

    Parameters:
    -----------
    **kwargs : dict
        Parameters defining the Target Pixel File identity.

    Returns:
    --------
    TessTargetPixelFile or None
        The loaded target pixel file object, or None if not cached or corrupted.
    """
    prefix = 'tpf_data'
    filename = _find_cached_file(prefix, extension='fits', **kwargs)
    if not filename:
        filename = _get_cache_filename(prefix, extension='fits', **kwargs)
        
    if filename and os.path.exists(filename):
        try:
            return TessTargetPixelFile(str(filename))
        except Exception as e:
            logging.warning(f"FITS Cache corruption detected in {filename}. Deleting file. Error: {e}")
            try:
                os.remove(filename)
            except Exception:
                pass
    return None


def load_ffi_fits(**kwargs):
    """
    Loads Full Frame Image (FFI) cutout pixel data from the public FITS cache with smart coordinate-aware lookup.

    If the file exists but is corrupted, deletes the corrupted file on disk and returns None.

    Parameters:
    -----------
    **kwargs : dict
        Parameters defining the FFI cutout identity.

    Returns:
    --------
    TessTargetPixelFile or None
        The loaded cutout data, or None if not cached or corrupted.
    """
    prefix = 'ffi_data'
    filename = _find_cached_file(prefix, extension='fits', **kwargs)
    if not filename:
        filename = _get_cache_filename(prefix, extension='fits', **kwargs)
        
    if filename and os.path.exists(filename):
        try:
            return TessTargetPixelFile(str(filename))
        except Exception as e:
            logging.warning(f"FITS Cache corruption detected in {filename}. Deleting file. Error: {e}")
            try:
                os.remove(filename)
            except Exception:
                pass
    return None


def save_ffi_fits(data, **kwargs):
    """
    Saves Full Frame Image (FFI) cutout pixel data into the cache as a FITS file atomically.

    Parameters:
    -----------
    data : TessTargetPixelFile
        The FFI cutout data to save.
    **kwargs : dict
        Metadata defining the FFI cutout boundaries.
    """
    prefix = 'ffi_data'
    filename = _get_cache_filename(prefix, extension='fits', **kwargs)
    if not filename:
        return
    _save_atomically(filename, lambda path: data.to_fits(path, overwrite=True))


def save_lc_fits(data, **kwargs):
    """
    Saves a TESS Light Curve into the cache as a FITS file atomically.

    Parameters:
    -----------
    data : TessLightCurve
        The TESS light curve data object to save.
    **kwargs : dict
        Metadata representing the target star and extraction parameters.
    """
    prefix = 'lc'
    filename = _get_cache_filename(prefix, extension='fits', **kwargs)
    if not filename:
        return
    _save_atomically(filename, lambda path: data.to_fits(path, overwrite=True))


def load_lc_fits(**kwargs):
    """
    Loads TessLightCurve data from the public FITS cache with smart coordinate-aware lookup.

    If the file is corrupted, automatically deletes it and returns None.

    Parameters:
    -----------
    **kwargs : dict
        Metadata defining the target lightcurve.

    Returns:
    --------
    TessLightCurve or None
        The loaded light curve object, or None if not cached or corrupted.
    """
    prefix = 'lc'
    filename = _find_cached_file(prefix, extension='fits', **kwargs)
    if not filename:
        filename = _get_cache_filename(prefix, extension='fits', **kwargs)
        
    if filename and os.path.exists(filename):
        try:
            return TessLightCurve.read(str(filename))
        except Exception as e:
            logging.warning(f"FITS Cache corruption detected in {filename}. Deleting file. Error: {e}")
            try:
                os.remove(filename)
            except Exception:
                pass
    return None


def load(prefix, **kwargs):
    """
    Loads Python objects from the public cache using dill deserialization.
    Supports smart, tolerance-aware coordinate and size lookup.

    If deserialization fails due to a corrupted file, deletes the file from disk 
    and returns None to trigger a safe recalculation / redownload.

    Parameters:
    -----------
    prefix : str
        The cache prefix identifier.
    **kwargs : dict
        Metadata defining the uniqueness of the cache entry.

    Returns:
    --------
    any or None
        The loaded Python object, or None if not cached or corrupted.
    """
    filename = _find_cached_file(prefix, extension='dill', **kwargs)
    if not filename:
        filename = _get_cache_filename(prefix, extension='dill', **kwargs)
        
    if filename and os.path.exists(filename):
        try:
            with open(filename, "rb") as f:
                return dill.load(f)
        except Exception as e:
            logging.warning(f"Cache corruption detected in {filename}. Deleting file. Error: {e}")
            try:
                os.remove(filename)
            except Exception:
                pass
    return None


def save_lightcurve_collection(lc_collection, tar_filename):
    """
    Saves a collection of lightcurves into a single tar archive safely.

    This function utilizes a secure, process-isolated temporary directory for
    intermediate FITS files. It also packages the output into a temporary archive 
    and performs an atomic file replacement at the end, eliminating process 
    collisions in multi-threaded production servers.

    Parameters:
    -----------
    lc_collection : list of TessLightCurve
        The light curve collection objects to archive.
    tar_filename : str
        The target filepath of the tar archive to create.
    """
    if not tar_filename:
        return

    tar_dir = os.path.dirname(tar_filename)
    if tar_dir:
        os.makedirs(tar_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        # Generate temp tar file in target directory to ensure atomic swap on same filesystem
        with tempfile.NamedTemporaryFile(dir=tar_dir or '.', delete=False, suffix='.tmp') as tmp_file:
            temp_tar_path = tmp_file.name

        try:
            with tarfile.open(temp_tar_path, "w") as tar:
                for i, lc in enumerate(lc_collection):
                    lc_filename = os.path.join(temp_dir, f"lightcurve_{i}.fits")
                    lc.to_fits().writeto(lc_filename)
                    tar.add(lc_filename, arcname=f"lightcurve_{i}.fits")
            os.replace(temp_tar_path, tar_filename)
        except Exception as e:
            logging.error(f"Failed to write lightcurve collection atomically: {e}")
            if os.path.exists(temp_tar_path):
                try:
                    os.remove(temp_tar_path)
                except Exception:
                    pass
            raise e


def load_lightcurve_collection(tar_filename):
    """
    Loads a archived collection of lightcurves from a single tar file.

    If the archive is missing or corrupted, returns an empty collection list.

    Parameters:
    -----------
    tar_filename : str
        The absolute filepath to the tar archive.

    Returns:
    --------
    list of LightCurve
        A list of loaded light curve objects.
    """
    lc_collection = []
    if not tar_filename or not os.path.exists(tar_filename):
        return lc_collection

    try:
        with tarfile.open(tar_filename, "r") as tar:
            for member in tar.getmembers():
                if member.isfile():
                    with tar.extractfile(member) as file:
                        lc = lightkurve.LightCurve.read(file)
                        lc_collection.append(lc)
    except Exception as e:
        logging.warning(f"Failed to read lightcurve collection from {tar_filename}. Error: {e}")
        try:
            os.remove(tar_filename)
        except Exception:
            pass
    return lc_collection


def delete_target_cache(target, radius=None, size=None):
    """
    Finds and deletes all cached files that match the requested target within COORD_TOLERANCE_DEG.

    This scans the cache directory, parses embedded coordinates from filenames, and removes matching
    files. It also computes fallback hashes for the exact target name/radius/size and removes those,
    ensuring thorough cleanup of sector lists, pixel files, and light curves.

    Parameters:
    -----------
    target : str
        The target name or coordinate string.
    radius : float, optional
        The search radius.
    size : int, optional
        The cutout size.

    Returns:
    --------
    int
        The number of successfully deleted cache files.
    """
    cache_dir = os.getenv('TESS_CACHE_DIR')
    if not cache_dir or not os.path.exists(cache_dir):
        logging.warning("TESS_CACHE_DIR is not configured or does not exist.")
        return 0

    deleted_count = 0
    requested_coord = extract_coords(target)

    # 1. Scan and delete matching coordinate-aware files
    if requested_coord is not None:
        try:
            for fname in os.listdir(cache_dir):
                # Pattern covers: {prefix}_ra_..._dec_...[_size_...]_nc_HASH.ext
                pattern = r"^.+_ra_([+-]?\d+(?:\.\d+)?|nan)_dec_([+-]?\d+(?:\.\d+)?|nan)_.*$"
                match = re.match(pattern, fname)
                if not match:
                    continue

                cached_ra_str, cached_dec_str = match.groups()
                try:
                    cached_coord = SkyCoord(ra=float(cached_ra_str), dec=float(cached_dec_str), unit=(u.deg, u.deg))
                except Exception:
                    continue

                # Compute separation and check against tolerance
                separation = requested_coord.separation(cached_coord).deg
                if separation <= COORD_TOLERANCE_DEG:
                    file_path = os.path.join(cache_dir, fname)
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            deleted_count += 1
                            logging.info(f"Clean Cache: Deleted coordinate-matched file {file_path}")
                        except Exception as e:
                            logging.error(f"Clean Cache: Failed to delete {file_path}: {e}")
        except Exception as e:
            logging.error(f"Clean Cache: Error scanning directory for coordinate-aware files: {e}")

    # 2. Compute exact fallback hashes and delete those files as well
    # Try multiple common prefixes and extension patterns
    fallback_candidates = []
    prefixes = ['tpf', 'ffi', 'tpf_data', 'ffi_data', 'lc']
    for prefix in prefixes:
        # Build kwargs corresponding to each prefix's typical cache signature
        kwargs_variants = []
        if prefix in ('tpf', 'tpf_data'):
            kwargs_variants.append({'target': target, 'radius': radius or 11})
            kwargs_variants.append({'target_name': target, 'radius': radius or 11})
        elif prefix in ('ffi', 'ffi_data'):
            kwargs_variants.append({'target': target})
            kwargs_variants.append({'target_name': target, 'size': size or 11})
        else:
            kwargs_variants.append({'target': target})
            kwargs_variants.append({'target_name': target})

        for variant in kwargs_variants:
            for ext in ('dill', 'fits'):
                fpath = _get_cache_filename(prefix, extension=ext, **variant)
                if fpath:
                    fallback_candidates.append(fpath)

    # De-duplicate fallback candidates
    fallback_candidates = list(set(fallback_candidates))

    for fpath in fallback_candidates:
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
                deleted_count += 1
                logging.info(f"Clean Cache: Deleted fallback-hashed file {fpath}")
            except Exception as e:
                logging.error(f"Clean Cache: Failed to delete {fpath}: {e}")

    logging.info(f"Clean Cache: Successfully completed cleanup for target={target!r}. Total files deleted: {deleted_count}")
    return deleted_count

