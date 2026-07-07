import logging
import os
import tempfile

logger = logging.getLogger(__name__)

import pandas
import pandas as pd
# noinspection PyUnresolvedReferences
from astropy.units import deg, hourangle, day, electron, s as sec
from numpy import isnan

from pyasassn.client import SkyPatrolClient

# from skvo_veb.utils.kurve import cook_lightcurve
from skvo_veb.utils.asassn_config import (
    ASASSN_FLUX_UNIT,
    ASASSN_PIPELINE,
    asassn_calibration_catalog,
    resolve_asassn_photcal,
)
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.my_tools import DBException, timeit, PipeException

# http://asas-sn.ifa.hawaii.edu/documentation/getting_started.html
gaia_id_DP_Peg = 1791119426789765632
gaia_id_no_data = 1791119426789765630
gaia_id_no_ephem = 1865212594815600768


def _build_path_to_cache(gaia_id):
    """
    Builds the path to the cached ASAS-SN lightcurve file.
    Automatically creates the parent directory if it does not exist.
    """
    cache_dir = os.getenv('ASASSN_CACHE_DIR')
    if not cache_dir:
        logger.warning('Environmental variable ASASSN_CACHE_DIR is not specified')
        return None
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f'asassn_lc_{gaia_id}.pkl')


def _load_from_cache(gaia_id) -> (pandas.DataFrame | None, float | None, float | None):
    """
    Loads ASAS-SN lightcurve data and metadata from the pickle cache.
    
    If the file is corrupted, logs a warning, deletes the corrupted file, and
    returns None to trigger a fresh download.
    """
    path_to_cached_data = _build_path_to_cache(gaia_id)
    if not path_to_cached_data or not os.path.exists(path_to_cached_data):
        return None, None, None
    try:
        df = pd.read_pickle(path_to_cached_data)
        epoch = df.attrs.get('epoch', None)
        period = df.attrs.get('period', None)
        df.attrs.clear()
        return df, epoch, period,
    except Exception as e:
        logger.warning(f'request_asassn, bad or corrupted pickle file {path_to_cached_data}: {e}')
        if path_to_cached_data and os.path.exists(path_to_cached_data):
            try:
                os.remove(path_to_cached_data)
            except Exception:
                pass
        return None, None, None


def _store_in_cache(source_id, df: pandas.DataFrame, epoch: float | None = None, period: float | None = None):
    """
    Saves ASAS-SN lightcurve data and metadata to the pickle cache atomically.
    
    Uses a temporary file and atomic rename pattern to prevent file corruption
    and race conditions under concurrent process environments.
    """
    path_to_cached_data = _build_path_to_cache(source_id)
    if not path_to_cached_data:
        return
    cache_dir = os.path.dirname(path_to_cached_data)
    
    with tempfile.NamedTemporaryFile(dir=cache_dir, delete=False, suffix='.tmp') as tmp_file:
        temp_path = tmp_file.name
        
    try:
        df.attrs['epoch'] = epoch
        df.attrs['period'] = period
        df.to_pickle(temp_path)
        os.replace(temp_path, path_to_cached_data)
    except Exception as e:
        logger.error(f'Store ASAS-SN lightcurve in cache failed for {path_to_cached_data}: {e}')
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@timeit
def load_asassn_lightcurve(gaia_id: int | None = None, source_id: str | None = None,
                           band='g', force_update=False) -> CurveDash:
    epoch = None
    period = None
    lc_df = None
    if gaia_id is None and source_id is None:
        raise PipeException('load_asassn_lightcurve: both input names are None')
    caching_name = gaia_id if gaia_id is not None else source_id.upper()

    if not force_update:
        lc_df, epoch, period = _load_from_cache(caching_name)
        if lc_df is not None and lc_df.empty:
            raise DBException(f'{caching_name} was not found in the cached ASAS-SN database\n'
                              f'Consider forcing a fetch if the data is really needed')
    if lc_df is None:  # Try to load it from the remote database:
        try:
            client = SkyPatrolClient()
        except Exception as e:
            logger.error('request_asassn SkyPatrolClient exception', e)
            raise PipeException('load_asassn_lightcurve: both input names are None')
        try:
            # # res = client.query_list(gaia_id, catalog='stellar_main', id_col='gaia_id', download=True)
            if gaia_id is not None:
                res = client.adql_query(f'SELECT asas_sn_id, epoch, period FROM stellar_main '
                                        f'JOIN aavsovsx USING(asas_sn_id) WHERE gaia_id = {gaia_id}',
                                        download=True)
                if hasattr(res, 'catalog_info'):
                    # res.catalog_info.replace({float('nan'): None}, inplace=True)
                    epoch = getattr(res.catalog_info, 'epoch', [None])[0]
                    period = getattr(res.catalog_info, 'period', [None])[0]
                    # epoch = None if epoch is None or (isinstance(epoch, float) and isnan(epoch)) else epoch
                    epoch = 0 if epoch is None or (isinstance(epoch, float) and isnan(epoch)) else epoch
                    period = None if period is None or (isinstance(period, float) and isnan(period)) else period
            elif source_id is not None:
                res = client.simbad_lookup(source_id, download=True)
                try:
                    # asas_sn_id = res.ids[0]
                    asas_sn_id = res.data['asas_sn_id'][0]
                    res_params = client.adql_query(f'SELECT epoch, period '
                                                   f'FROM aavsovsx WHERE asas_sn_id = {asas_sn_id}',
                                                   download=False)
                    epoch = res_params.get('epoch')[0]
                    period = res_params.get('period')[0]
                    epoch = 0 if epoch is None or (isinstance(epoch, float) and isnan(epoch)) else epoch
                    period = None if period is None or (isinstance(period, float) and isnan(period)) else period
                except Exception as e:
                    logger.warning(f'load_asassn_lightcurve: asas_sn_id did not extracted: {e}')
            else:
                raise PipeException('load_asassn_lightcurve: both input names are None')
            logger.info('Lightcurve is ready')
            if hasattr(res, 'data'):
                lc_df = res.data
            if lc_df is None or lc_df.empty:
                _store_in_cache(caching_name, pd.DataFrame())
                logger.warning(f'load_asassn_lightcurve: The source {caching_name} '
                                f'was not found in the ASAS-SN database')
                raise DBException(f'The source {caching_name} was not found in the ASAS-SN database')
            # if hasattr(res, 'catalog_info'):
            #     # res.catalog_info.replace({float('nan'): None}, inplace=True)
            #     epoch = getattr(res.catalog_info, 'epoch', [None])[0]
            #     period = getattr(res.catalog_info, 'period', [None])[0]
            #     # epoch = None if epoch is None or (isinstance(epoch, float) and isnan(epoch)) else epoch
            #     epoch = 0 if epoch is None or (isinstance(epoch, float) and isnan(epoch)) else epoch
            #     period = None if period is None or (isinstance(period, float) and isnan(period)) else period
        except DBException:
            raise
        except Exception as e:
            logger.warning(f'request_asassn request lightcurve exception {e}')
            raise DBException(f'It seems that the star {caching_name} was not found in the ASAS-SN database')
        # client.catalogs.master_list
        _store_in_cache(caching_name, lc_df, epoch, period)

    # mask = lc_df['phot_filter']
    try:
        df = lc_df[lc_df['phot_filter'] == band][['jd', 'flux', 'flux_err']]
        if df.empty:
            raise DBException(f'It seems that the star {caching_name} has no observations with {band} filter')
        if os.getenv('CUT_ASASSN'):  # for debugging
            df = df[:5]

        lcd = CurveDash(
            gaia_id=gaia_id,
            jd=df['jd'],
            flux=df['flux'],
            flux_err=df['flux_err'],
            band=band,
            flux_unit=ASASSN_FLUX_UNIT,
            photcal=resolve_asassn_photcal(band),
            timescale='hjd',
            epoch=epoch,
            period=period,
            period_unit=str(day),
        )
        lcd.metadata['authors'] = [ASASSN_PIPELINE]
        lcd.metadata['calibration_catalog'] = asassn_calibration_catalog(band)

        # lc = cook_lightcurve(df, timescale='tcg',
        #                              flux_unit='', flux_err_unit='',
        #                              epoch_jd=epoch, period_day=period)
        # period_unit = None if not period else 'day'
        # metadata = {'gaia_id': gaia_id, 'epoch': epoch, 'period': period, 'period_unit': period_unit, 'band': band}
    except DBException:
        raise
    except Exception as e:
        logger.error(f'load_asassn_lightcurve exception: {type(e).__name__} {e}')
        raise PipeException(f'{caching_name}: ASAS-SN data structure is invalid')
    return lcd


if __name__ == '__main__':
    from skvo_veb.logging_config import configure_logging

    configure_logging()
    try:
        test_lcd = load_asassn_lightcurve(gaia_id_no_ephem, band='V')
        logger.info('%s', test_lcd.metadata)
    except Exception as ee:
        logger.exception('load_asassn_lightcurve failed: %s', ee)
    logger.info('AHA!')
