import logging
import re

import lightkurve as lk
import pandas as pd
from astropy.coordinates import SkyCoord
from astropy.table import Table
import astropy.units as u

from skvo_veb.utils import tess_cache as cache
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

CACHE_PREFIX = 'lc_search_metadata'


def parse_native_id_from_target(target: str) -> str | None:
    """
    Parse a native mission identifier directly from a user target string.

    Examples: ``TIC 159717514`` -> ``TIC:159717514``, bare numeric TIC id, ``KIC 123`` -> ``KIC:123``.
    """
    if not target:
        return None
    text = str(target).strip()

    for pattern, prefix in (
        (r'(?i)^TIC\s*(\d+)\s*$', 'TIC'),
        (r'(?i)^KIC\s*(\d+)\s*$', 'KIC'),
        (r'(?i)^EPIC\s*(\d+)\s*$', 'EPIC'),
    ):
        match = re.match(pattern, text)
        if match:
            return f'{prefix}:{match.group(1)}'

    if re.fullmatch(r'\d{6,}', text):
        return f'TIC:{text}'

    return None


def extract_native_id_from_row(row) -> str:
    """
    Extract a deterministic native mission key from one MAST search table row.
    """
    target_name = str(row['target_name']).strip()
    obs_collection = str(row['obs_collection']) if 'obs_collection' in row.colnames else ''
    mission_text = str(row['mission']) if 'mission' in row.colnames else ''

    if obs_collection == 'TESS' or 'TESS' in mission_text:
        tic_digits = re.sub(r'\D', '', target_name)
        if tic_digits:
            return f'TIC:{tic_digits}'

    if obs_collection == 'Kepler' or 'Kepler' in mission_text:
        kic_digits = re.sub(r'\D', '', target_name)
        if kic_digits:
            return f'KIC:{kic_digits}'

    if obs_collection == 'K2' or 'K2' in mission_text:
        epic_digits = re.sub(r'\D', '', target_name)
        if epic_digits:
            return f'EPIC:{epic_digits}'

    return f'{obs_collection or "UNKNOWN"}:{target_name}'


def native_id_to_search_target(native_id: str) -> str:
    """Convert a native cache key back into a Lightkurve search target string."""
    prefix, ident = native_id.split(':', 1)
    if prefix == 'TIC':
        return f'TIC {ident}'
    if prefix == 'KIC':
        return f'KIC {ident}'
    if prefix == 'EPIC':
        return f'EPIC {ident}'
    return ident


def _query_coord_from_inputs(target: str, search_mode: str, resolved_coords: dict | None) -> SkyCoord | None:
    if search_mode == 'resolved_coordinates' and resolved_coords:
        ra = resolved_coords.get('ra')
        dec = resolved_coords.get('dec')
        if ra is not None and dec is not None:
            try:
                return SkyCoord(f'{ra} {dec}', unit=(u.hourangle, u.deg))
            except Exception:
                try:
                    return SkyCoord(f'{ra} {dec}', unit=(u.deg, u.deg))
                except Exception:
                    pass
    if search_mode == 'coordinates_only':
        try:
            return SkyCoord(target, unit=(u.deg, u.deg))
        except Exception:
            try:
                return SkyCoord(target, unit=(u.hourangle, u.deg))
            except Exception:
                pass
    return None


def _row_distance_arcsec(row, query_coord: SkyCoord | None) -> float:
    if 'distance' in row.colnames and row['distance'] is not None:
        try:
            val = row['distance']
            if hasattr(val, 'to'):
                return float(val.to(u.arcsec).value)
            return float(val)
        except Exception:
            pass

    if query_coord is not None and 's_ra' in row.colnames and 's_dec' in row.colnames:
        try:
            row_coord = SkyCoord(ra=row['s_ra'], dec=row['s_dec'], unit=(u.deg, u.deg))
            return row_coord.separation(query_coord).arcsec
        except Exception:
            pass

    return float('inf')


def pick_closest_native_id(search_result: lk.SearchResult, query_coord: SkyCoord | None = None) -> str:
    """
    From a possibly multi-target cone search, pick the single closest native object.
    """
    table = search_result.table
    if len(table) == 0:
        raise PipeException('No data found')

    best_native_id = None
    best_distance = float('inf')

    for row in table:
        native_id = extract_native_id_from_row(row)
        distance = _row_distance_arcsec(row, query_coord)
        if distance < best_distance:
            best_distance = distance
            best_native_id = native_id

    if best_native_id is None:
        raise PipeException('Could not determine closest target from search results')

    print(f"[SEARCH LC] Cone search narrowed to native_id={best_native_id!r} (closest match)")
    logger.info(f'pick_closest_native_id: selected {best_native_id} at {best_distance} arcsec')
    return best_native_id


def _dominant_native_id(search_result: lk.SearchResult) -> str:
    """Pick the native id that appears most often (non-cone searches with multiple targets)."""
    counts: dict[str, int] = {}
    for row in search_result.table:
        native_id = extract_native_id_from_row(row)
        counts[native_id] = counts.get(native_id, 0) + 1
    return max(counts, key=counts.get)


def fetch_comprehensive_search(native_id: str) -> lk.SearchResult:
    """
    Fetch all available light curves (all sectors, all authors) for a native mission id.
    """
    target = native_id_to_search_target(native_id)
    prefix = native_id.split(':', 1)[0]

    print(f"[SEARCH LC] Querying MAST for comprehensive metadata: native_id={native_id!r}, target={target!r}")
    logger.info(f'fetch_comprehensive_search: target={target!r}, native_id={native_id!r}')

    if prefix == 'TIC':
        result = lk.search_lightcurve(target, mission='TESS')
    elif prefix == 'KIC':
        result = lk.search_lightcurve(target, mission='Kepler')
    elif prefix == 'EPIC':
        result = lk.search_lightcurve(target, mission='K2')
    else:
        result = lk.search_lightcurve(target)

    if len(result) == 0:
        raise PipeException(f'No comprehensive light curves found for {native_id}')

    print(f"[SEARCH LC] MAST returned {len(result)} records for {native_id!r}")
    return result


def search_lightcurves_cached(
    target: str,
    radius: float | None = None,
    search_mode: str = 'object_name',
    resolved_coords: dict | None = None,
) -> tuple[lk.SearchResult, str]:
    """
    Search TESS/Kepler light-curve metadata with a native-id keyed cache.

    Cone searches are filtered to the closest unique object, then a comprehensive
    sector/author query is executed once and cached under the native mission id.
    """
    query_coord = _query_coord_from_inputs(target, search_mode, resolved_coords)

    native_id = parse_native_id_from_target(target)
    is_cone = radius is not None and radius > 0

    if native_id is None:
        print(f"\n[SEARCH LC] Initial MAST lookup: target={target!r}, radius={radius!r}, mode={search_mode}")
        if is_cone:
            initial = lk.search_lightcurve(target, radius=radius)
        else:
            initial = lk.search_lightcurve(target)

        if len(initial) == 0:
            raise PipeException('No data found')

        if is_cone or len({extract_native_id_from_row(r) for r in initial.table}) > 1:
            native_id = pick_closest_native_id(initial, query_coord)
        else:
            native_id = _dominant_native_id(initial)
            print(f"[SEARCH LC] Resolved native_id={native_id!r} from initial search")

    cached = cache.load(CACHE_PREFIX, native_id=native_id)
    if cached is not None:
        print(f"[CACHE HIT] Lightcurve search metadata found for native_id={native_id!r} ({len(cached)} records)")
        logger.info(f'search_lightcurves_cached: cache HIT for {native_id!r}')
        return cached, native_id

    print(f"[CACHE MISS] Lightcurve search metadata NOT cached for native_id={native_id!r}")
    logger.info(f'search_lightcurves_cached: cache MISS for {native_id!r}')

    comprehensive = fetch_comprehensive_search(native_id)
    cache.save(comprehensive, CACHE_PREFIX, native_id=native_id)
    print(f"[CACHE SAVE] Stored {len(comprehensive)} metadata records under native_id={native_id!r}")
    logger.info(f'search_lightcurves_cached: saved {len(comprehensive)} rows for {native_id!r}')

    return comprehensive, native_id


def restore_search_result(search_store: dict) -> lk.SearchResult:
    """Rebuild a Lightkurve SearchResult from a serialized store payload."""
    if not search_store or 'search_result' not in search_store:
        raise PipeException('Search metadata is missing. Run Search first.')
    table = Table.from_pandas(pd.DataFrame.from_dict(search_store['search_result']))
    return lk.SearchResult(table)
