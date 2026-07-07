import logging

logger = logging.getLogger(__name__)

import astropy.units as u
# noinspection PyUnresolvedReferences
from astropy.units import deg, hourangle, day, electron
import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extensions
import psycopg2.extras
from astropy.coordinates import Angle
from pandas import DataFrame

from skvo_veb.utils import ask_simbad
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.coord import deg_to_asec, parse_coord_to_skycoord
from skvo_veb.utils.my_tools import DBException, timeit, PipeException, is_like_gaia_id

path_to_test_data = 'test_data/'

psql_table_photo = 'lightcurves_gaia'
psql_table_prop_gaia = 'veb_prop_gaia'
psql_table_prop_new = 'veb_prop_new'
psql_table_veb_parameters = 'veb_parameters'
psql_table_main = 'main_gaia_data'
psql_table_cross_ident = 'cross_ident'
# psql_table_lamost = 'lamost'
psql_table_lamost = 'lamost_dr10'

jd0_gaia = 2455197.5
# Photometric zero points:
# https://www.cosmos.esa.int/web/gaia/dr3-passbands#GGBPGRP
ZP_G_Vega = 25.6873668671
ZP_G_Vega_err = 0.0027553202
ZP_Bp_Vega = 25.3385422158
ZP_Bp_Vega_err = 0.0027901700
ZP_Rp_Vega = 24.7478955012
ZP_Rp_Vega_err = 0.0037793818

@timeit
def request_coord_cone(coord_str: str, rad_arcmin, catalogue) -> tuple[DataFrame, dict]:
    """
    performs cone search of VEB in a local database by ra,dec coordinates within rad_deg circle
    :param catalogue: Gaia, Tess, Kepler etc.
    :param coord_str:
    :param rad_arcmin:
    :return: found sources as a pandas DataFrame
    """

    def _main_name(x):
        return x['vsx'] if x['vsx'] is not None else x['simbad'] if x['simbad'] is not None \
            else f'Gaia DR3 {x["gaia_id"]}'

    try:
        sky_coords = parse_coord_to_skycoord(coord_str)
        ra_deg, dec_deg = sky_coords.ra.deg, sky_coords.dec.deg
        rows = _request_coord_cone(ra_deg, dec_deg, float(rad_arcmin))
        if len(rows) == 0:
            error_str = f'Nothing was found within {rad_arcmin}arc min radius '
            raise DBException(error_str)
        df = pd.DataFrame(rows)  # , columns=['id', 'coordequ', 'dist', 'Gmag'])
        if getenv('DEBUG_LOCAL'):
            df['Identifier'] = df['gaia_id'].apply(_debug_get_main_identifier)
        else:
            # df['Identifier'] = df.vsx if df.vsx is not None else df.simbad if df.simbad is not None else 'Gaia DR3
            # '+ df["gaia_id"].astype('string')
            df['Identifier'] = df[['simbad', 'vsx', 'gaia_id']].apply(_main_name, axis=1)
            df.dist = deg_to_asec(df.dist)

        # df['coordequ'] = df['coordequ'].apply(coord.coordequ_to_hms_dms_str, args=[1])
        df['ra'] = Angle(df.ra, unit=u.rad).to_string(unit=hourangle, sep=':', pad=True, precision=1)
        df['dec'] = Angle(df.dec, unit=u.rad).to_string(unit=deg, sep=':', alwayssign=True, pad=True, precision=1)
        df['RA DEC'] = df['ra'] + ' ' + df['dec']
        df.drop(['ra', 'dec'], axis=1, inplace=True)
        # df.rename(columns={'coordequ': 'RA DEC', 'g_mag': 'Mag G'}, inplace=True)
        df.rename(columns={'g_mag': 'Mag G'}, inplace=True)

        tooltip_di = {'RA DEC': 'ICRS coordinates [hms, dms]',
                      'dist': 'distance from the centre [asec]', 'Mag G': 'magnitude'}

        df['catalogue'] = catalogue  # todo This is a stub Use catalogue into the DB request
        # todo "df.astype" -- trick against truncating long integer in the dash table
        return df.astype({'gaia_id': 'string'}), tooltip_di
        # todo Can I perform this smarter?
        # https://community.plotly.com/t/dash-datatable-large-number-formatting/53085
    except Exception as e:
        # raise DBException(e)
        logger.info(e)
        raise


@timeit
def extract_gaia_id(source_id: str):
    if getenv('DEBUG_LOCAL'):
        return 1234567
    conn = psycopg2.connect(
        host=getenv("DB_HOST"),
        dbname=getenv("DB_NAME"),
        user=getenv("DB_USER"),
        password=getenv("DB_PASS")
    )
    cursor = conn.cursor()
    # name = '%' + '%'.join(source_id.split())
    name = '\m' + source_id + '\M'      # to catch  "V* EY Oph"
    # name = source_id.strip().replace(' ', '%')
    # psql_str = (f'select gaia_id,simbad,vsx from {psql_table_cross_ident} '
    #             f'where simbad ilike \'{name}\' or vsx ilike \'{name}\'')
    # psql_str = (f'select gaia_id,simbad,vsx from {psql_table_cross_ident} '
    #             f'where simbad ilike %s or vsx ilike %s')
    psql_str = (f'select gaia_id,simbad,vsx from {psql_table_cross_ident} '
                f'where simbad ~*  %s or vsx ~*  %s')
    cursor.execute(psql_str, (name, name))
    rows = cursor.fetchall()
    conn.commit()
    if len(rows) < 1:
        return None
    elif len(rows) > 1:
        list_of_id = [row[0] for row in rows]
        n_max = 10
        raise DBException(f'Ambiguous query: did you mean one of Gaia DR3 {list_of_id[:n_max]} stars?')
    return rows[0][0]


@timeit
def _request_coord_cone(ra_deg: float, dec_deg: float, rad_arcmin: float):
    psql_str1 = f'select set_sphere_output(\'RAD\')'

    psql_str2 = (f'select m.gaia_id as gaia_id, long(coordequ) as ra, lat(coordequ) as dec, coordequ <-> '
                 f'spoint \'(%sd,%sd)\' as dist,'
                 f'g_mag, vsx, simbad '
                 f'from {psql_table_main} as m join {psql_table_cross_ident} as ci on m.gaia_id = ci.gaia_id '
                 f'where coordequ <@ scircle '
                 f'\'<(%sd,%sd),%sd>\' order by dist')

    if getenv('DEBUG_LOCAL'):
        return _debug_load_test_cone()

    # O, no!!!!!
    # logging.error(f'_request_coord_cone host={getenv("DB_HOST")} '
    #               f'dbname={getenv("DB_NAME")} '
    #               f'user={getenv("DB_USER")} '
    #               f'password= {getenv("DB_PASS")}')

    conn = psycopg2.connect(
        host=getenv("DB_HOST"),
        dbname=getenv("DB_NAME"),
        user=getenv("DB_USER"),
        password=getenv("DB_PASS")
    )

    cursor_di = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # returns results as a dictionary
    cursor_di.execute(psql_str1)
    _ = cursor_di.fetchall()
    cursor_di.execute(psql_str2, (ra_deg, dec_deg, ra_deg, dec_deg, rad_arcmin / 60))
    rows_di = cursor_di.fetchall()
    # column_names = [descr.name for descr in cursor.description]
    # pd.DataFrame(rows, columns=column_names)
    return rows_di


@timeit
def _request_cross_ident(gaia_id: int, cursor: psycopg2.extras.RealDictCursor) -> dict:
    # cursor.execute(f'select gaia_id,simbad,vsx from {psql_table_cross_ident} where gaia_id = {gaia_id}')
    cursor.execute(f'select gaia_id,simbad,vsx from {psql_table_cross_ident} where gaia_id = %s', (gaia_id,))
    row = cursor.fetchone()
    if row is None:
        return {'gaia_id': gaia_id, 'simbad': None, 'vsx': None}
    return dict(row)


@timeit
def _request_veb_prop_gaia(gaia_id: int, cursor: psycopg2.extras.RealDictCursor) -> dict:
    # cursor.execute(f'select * from {psql_table_prop_gaia} where gaia_id = {gaia_id}')
    cursor.execute(f'select * from {psql_table_prop_gaia} where gaia_id = %s', (gaia_id,))
    # column_names = [descr.name for descr in cursor.description]
    row = cursor.fetchone()
    if row is None:
        raise DBException(f'The source with {gaia_id=} not found in {psql_table_prop_gaia}')
    return dict(row)


def _request_lamost(gaia_id: int, cursor: psycopg2.extras.RealDictCursor) -> dict:
    # todo
    # cursor.execute(f'select * from {psql_table_lamost} where gaia_id = {gaia_id}')
    logger.debug('_request_lamost')
    cursor.execute(f'select * from {psql_table_lamost} where gaia_id = %s', (gaia_id,))
    # column_names = [descr.name for descr in cursor.description]
    row = cursor.fetchone()
    if row is None:
        logger.warning(f'The source with {gaia_id=} not found in {psql_table_lamost}')
        return {}
    return dict(row)


@timeit
def request_photometric_params_image(gaia_id: int) -> str:  # 2024355117565654016
    import base64
    if getenv('DEBUG_LOCAL'):
        return _debug_photometric_params_image(gaia_id)  # todo DEBUG
    conn = psycopg2.connect(
        host=getenv("DB_HOST"),
        dbname=getenv("DB_NAME"),
        user=getenv("DB_USER"),
        password=getenv("DB_PASS")
    )
    cursor = conn.cursor()
    # cursor.execute(f'select gaia_id, graph from {psql_table_prop_new} where gaia_id = {gaia_id}')
    cursor.execute(f'select gaia_id, graph from {psql_table_prop_new} where gaia_id = %s', (gaia_id,))
    row = cursor.fetchone()
    try:
        image_bin = row[1]
    except Exception as e:
        conn.commit()
        logger.warning(f'request_photometric_params_image exception: {e}')
        raise DBException(f'The graph of {gaia_id=} not found in {psql_table_prop_new} table')
    finally:
        conn.commit()
    return 'data:image/png;base64,' + base64.b64encode(image_bin).decode('utf-8')


@timeit
def _request_veb_prop_new(gaia_id: int, cursor: psycopg2.extras.RealDictCursor) -> dict:  # 2024355117565654016
    # cursor.execute(f'select gaia_id, spot, type, time_ref, predicted, fitted, absolute from {psql_table_prop_new} '
    #                f'where gaia_id = {gaia_id}')
    cursor.execute(f'select gaia_id, spot, type, time_ref, predicted, fitted, absolute from {psql_table_prop_new} '
                   f'where gaia_id = %s', (gaia_id,))
    row = cursor.fetchone()
    if row is None:
        logger.warning(f'The source with {gaia_id=} not found in {psql_table_prop_new}')
        return {}
    return dict(row)


@timeit
def request_photometric_params_description() -> dict:
    conn = psycopg2.connect(
        host=getenv("DB_HOST"),
        dbname=getenv("DB_NAME"),
        user=getenv("DB_USER"),
        password=getenv("DB_PASS")
    )
    cursor_di = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor_di.execute(f'select * from {psql_table_veb_parameters}')
    rows = cursor_di.fetchall()
    conn.commit()
    di = dict([(r['name'], (r['description'], r['unit'])) for r in rows])
    return di


@timeit
def _request_main_data(gaia_id: int, cursor: psycopg2.extras.RealDictCursor) -> dict:
    # cursor.execute(f'select * from {psql_table_main} where gaia_id = {gaia_id}')
    cursor.execute(f'select * from {psql_table_main} where gaia_id = %s', (gaia_id,))
    # column_names = [descr.name for descr in cursor.description]
    row = cursor.fetchone()
    if row is None:
        raise DBException(f'The source with {gaia_id=} not found in {psql_table_main}')
    return dict(row)


def _request_lightcurve_with_metadata(gaia_id: int, band: str) -> CurveDash:
    conn = psycopg2.connect(
        host=getenv("DB_HOST"),
        dbname=getenv("DB_NAME"),
        user=getenv("DB_USER"),
        password=getenv("DB_PASS")
    )
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # -----------------------------  Extract the variable's freq from the gaia prop table -----------------
    metadata = _request_fold_params(gaia_id, cursor)

    # metadata['band'] = band
    # metadata['gaia_id'] = gaia_id

    cross_ident = _request_cross_ident(gaia_id, cursor)
    # metadata['cross_ident'] = cross_ident

    #  ------------------------------ Request photometric data --------------------------------------------
    # We need period and epoch to fold the lightcurve
    epoch = metadata.get('epoch_gaia', None)
    period = metadata.get('period', None)
    # lc = _request_lightcurve(gaia_id, band, cursor, epoch, period)
    df = _request_lightcurve(gaia_id, band, cursor)

    conn.commit()
    lcd = CurveDash(gaia_id=gaia_id,
                    jd=df['jd'], flux=df['flux'], flux_err=df['flux_err'],
                    band=band,
                    timescale='tcb',
                    flux_unit=str(electron / u.s),
                    epoch=epoch,
                    period=period, period_unit='d',
                    cross_ident=cross_ident)

    return lcd


@timeit
def _request_fold_params(gaia_id: int, cursor: psycopg2.extras.RealDictCursor) -> dict:
    # cursor.execute(f'select freq, time_ref  from {psql_table_prop_gaia} where gaia_id = {gaia_id}')
    cursor.execute(f'select freq, time_ref  from {psql_table_prop_gaia} where gaia_id = %s', (gaia_id,))
    row_gaia = cursor.fetchone()
    if row_gaia is None:
        raise DBException(f'The source with {gaia_id=} not found in {psql_table_prop_gaia}')
    try:
        epoch_gaia = float(row_gaia['time_ref']) + jd0_gaia
    except Exception as e:
        logger.warning(repr(e))
        epoch_gaia = None

    try:
        freq = row_gaia['freq']
        period = 1 / freq
        period_unit = str(day)
    except Exception as e:
        logger.warning(repr(e))
        period = None
        period_unit = None

    # cursor.execute(f'select time_ref  from {psql_table_prop_new} where gaia_id = {gaia_id}')
    cursor.execute(f'select time_ref  from {psql_table_prop_new} where gaia_id = %s', (gaia_id,))
    row_new = cursor.fetchone()
    epoch_new = None
    if row_new is not None:
        try:
            epoch_new = float(row_new['time_ref']) + jd0_gaia
        except Exception as e:
            logger.warning(repr(e))

    return {'epoch_gaia': epoch_gaia, 'epoch_new': epoch_new, 'epoch': epoch_gaia,
            'period': period, 'period_unit': period_unit}


@timeit
def _request_lightcurve(gaia_id: int, band: str, cursor: psycopg2.extras.RealDictCursor) -> DataFrame:
                        # epoch_jd: float | None, period_day: float | None) -> DataFrame:
    # cursor.execute(f'select jdobs,flux,flux_err  from {psql_table_photo} where gaia_id = {gaia_id} '
    #                f'and band ilike \'{band}\'')
    cursor.execute(f'select jdobs,flux,flux_err  from {psql_table_photo} where gaia_id = %s '
                   f'and band ilike %s', (gaia_id, band))
    rows = cursor.fetchall()  # list of dictionaries
    if len(rows) < 1:
        raise DBException(f'The lightcurve in {band}-band of source with {gaia_id=} not found in {psql_table_photo}')
    try:
        # todo: Check this! lll
        df = pd.DataFrame(rows)
        df['jdobs'] += jd0_gaia
        df.rename(columns={'jdobs': 'jd'}, inplace=True)
        return df
        # lc = cook_lightcurve(df, timescale='tcb',
        #                              flux_unit=str(electron / u.s),
        #                              flux_err_unit=str(electron / u.s),
        #                              epoch_jd=epoch_jd, period_day=period_day)
    except Exception as e:
        error_str = f'An exception connected with lightcurve of {gaia_id} occurred: {repr(e)}'
        logger.warning(error_str)
        raise DBException(error_str)
    # return lc


def _debug_get_main_identifier(gaia_id: int) -> str:
    vsx, simbad = _debug_get_synonym(gaia_id)
    res = vsx if vsx is not None else simbad if simbad is not None else f'Gaia DR3 {gaia_id}'
    return res


def _debug_load_lightcurve_with_metadata(gaia_id, band) -> CurveDash:
    band = band.upper()
    filename_lc = f'{path_to_test_data}{gaia_id}_{band}_gaia.dat'
    period = None
    # period_unit = None
    try:
        with open(filename_lc, 'r') as f:
            head = f.readline()
        if len(head) > 0 and head[0] == '#':
            try:
                period = float(head.rstrip().split('=')[-1])
                # period_unit = str(day)
            except Exception as e:
                logger.warning(repr(e))
        # lc_arr = np.loadtxt(filename_lc)[:5, :]
        lc_arr = np.loadtxt(filename_lc)
        # df = pd.DataFrame(columns=['jdobs', 'flux', 'flux_err'], data=lc_arr)
        # df['jdobs'] += jd0_gaia
        # df.rename(columns={'jdobs': 'jd'}, inplace=True)

        dict_prop_gaia = _debug_load_gaia_params(gaia_id)
        try:
            epoch_gaia = float(dict_prop_gaia['time_ref']) + jd0_gaia
        except Exception as e:
            logger.warning(repr(e))
            epoch_gaia = None
        epoch_new = epoch_gaia - 0.1

        cross_ident = _debug_load_cross_ident(gaia_id)
        lcd = CurveDash(gaia_id=gaia_id,
                        jd=lc_arr[:, 0] + jd0_gaia, flux=lc_arr[:, 1], flux_err=lc_arr[:, 2],
                        band=band,
                        timescale='tcb',
                        flux_unit=str(electron / u.s),
                        epoch=epoch_gaia,
                        period=period, period_unit='d',
                        cross_ident=cross_ident)
        # lc = cook_lightcurve(df, timescale='tcb',
        #                              flux_unit=str(electron / u.s),
        #                              flux_err_unit=str(electron / u.s),
        #                              epoch_jd=epoch_gaia, period_day=period)

    except FileNotFoundError:
        raise DBException(f'Seems like we don\'t have debug data for {gaia_id=} {band=}')

    return lcd
    # return dict(lc=lc,
    #             metadata=dict(gaia_id=gaia_id, period=period, period_unit=period_unit,
    #                           epoch_gaia=epoch_gaia, epoch_new=epoch_new, band=band,
    #                           cross_ident=cross_ident))


def _load_main_data_remote(gaia_id: int) -> dict:
    import pyvo
    TAP_URL = "https://gaia.ari.uni-heidelberg.de/tap/"
    service = pyvo.dal.TAPService(TAP_URL)
    # query_main = """
    #     SELECT *
    #     FROM gaiadr3.gaia_source
    #     WHERE source_id = %d
    # """
    query_main = """
        SELECT source_id AS gaia_id, radians(ra) AS ra_rad, radians(dec) AS dec_rad, 
        parallax, parallax_error AS parallax_err, pm,
        pmra AS pm_ra, pmra_error AS pm_ra_err, 
        pmdec AS pm_de, pmdec_error AS pm_de_err,
        phot_g_mean_mag AS g_mag, -1 AS g_mag_err,
        phot_bp_mean_mag AS bp_mag, -1 AS bp_mag_err,
        phot_rp_mean_mag AS rp_mag, -1 AS rp_mag_err,
        radial_velocity AS rv, radial_velocity_error AS rv_err,
        teff_gspphot AS teff, teff_gspphot_lower AS teff_low, teff_gspphot_upper AS teff_up,
        logg_gspphot AS logg, logg_gspphot_lower AS logg_low, logg_gspphot_upper AS logg_up,
        mh_gspphot AS fe2h, mh_gspphot_lower AS fe2h_low, mh_gspphot_upper AS fe2h_up,
        vbroad, vbroad_error AS vbroad_err 
        FROM gaiadr3.gaia_source
        WHERE source_id = %d
    """
    job_main = service.run_async(query_main % gaia_id)
    result = job_main.to_table()
    if len(result) == 0:
        raise DBException(f'The source with source_id={gaia_id} not found in the remote '
                          f'gaia_source table via {TAP_URL}')

    result_dict = dict(result[0])
    result_dict['coordequ'] = f'({result_dict["ra_rad"]},{result_dict["dec_rad"]})'
    for k, v in result_dict.items():
        if isinstance(v, np.ma.core.MaskedConstant):
            result_dict[k] = ""
    result_dict.pop('ra_rad', None)
    result_dict.pop('dec_rad', None)
    # res_debug = _debug_load_main_data(gaia_id)
    # print(res_debug)
    return result_dict

    # cursor.execute(f'select * from {psql_table_main} where gaia_id = {gaia_id}')
    # cursor.execute(f'select * from {psql_table_main} where gaia_id = %s', (gaia_id,))
    # column_names = [descr.name for descr in cursor.description]
    # row = cursor.fetchone()
    # if row is None:
    #     raise DBException(f'The source with {gaia_id=} not found in {psql_table_main}')
    # return dict(row)


def _load_gaia_params_remote(gaia_id: int) -> dict:
    import pyvo
    TAP_URL = "https://gaia.ari.uni-heidelberg.de/tap/"
    service = pyvo.dal.TAPService(TAP_URL)
    # query_main = """
    #     SELECT *
    #     FROM gaiadr3.gaia_source
    #     WHERE source_id = %d
    # """
    # select * from gaiadr3.vari_eclipsing_binary where source_id = 5284186916701857536
    query_main = """
        SELECT source_id AS gaia_id, reference_time AS time_ref, frequency AS freq,frequency_error AS freq_err,
        geom_model_reference_level AS mag_mod, geom_model_reference_level_error AS mag_mod_err,
        geom_model_gaussian1_phase AS phase1, geom_model_gaussian1_phase_error AS phase1_err,
        geom_model_gaussian1_sigma AS sig_phase1, geom_model_gaussian1_sigma_error AS sig_phase1_err,
        geom_model_gaussian1_depth AS depth1,geom_model_gaussian1_depth_error AS depth1_err,
        geom_model_gaussian2_phase AS phase2, geom_model_gaussian2_phase_error AS phase2_err,
        geom_model_gaussian2_sigma AS sig_phase2, geom_model_gaussian2_sigma_error AS sig_phase2_err,
        geom_model_gaussian2_depth AS depth2,geom_model_gaussian2_depth_error AS depth2_err,
        geom_model_cosine_half_period_amplitude AS amp_chp, geom_model_cosine_half_period_amplitude_error AS amp_chp_err,
        geom_model_cosine_half_period_phase AS phase_chp, geom_model_cosine_half_period_phase_error AS phase_chp_err,
        derived_primary_ecl_phase AS phase_e1, derived_primary_ecl_phase_error AS phase_e1_err,
        derived_primary_ecl_duration AS dur_e1, derived_primary_ecl_duration_error AS dur_e1_err,
        derived_primary_ecl_depth AS depth_e1, derived_primary_ecl_depth_error AS depth_e1_err,
        derived_secondary_ecl_phase AS phase_e2, derived_secondary_ecl_phase_error AS phase_e2_err,
        derived_secondary_ecl_duration AS dur_e2, derived_secondary_ecl_duration_error AS dur_e2_err,
        derived_secondary_ecl_depth AS depth_e2, derived_secondary_ecl_depth_error AS depth_e2_err,
        model_type
        FROM gaiadr3.vari_eclipsing_binary WHERE source_id = %d
    """

    job_gaia_param = service.run_async(query_main % gaia_id)
    result = job_gaia_param.to_table()
    if len(result) == 0:
        raise DBException(f'The source with source_id={gaia_id} not found in the remote '
                          f'vari_eclipsing_binary via {TAP_URL}')

    result_dict = dict(result[0])
    for k, v in result_dict.items():
        if isinstance(v, np.ma.core.MaskedConstant):
            result_dict[k] = ""
    # res_debug = _debug_load_gaia_params(gaia_id)
    # print(res_debug)

    return result_dict

    # cursor.execute(f'select * from {psql_table_main} where gaia_id = {gaia_id}')
    # cursor.execute(f'select * from {psql_table_main} where gaia_id = %s', (gaia_id,))
    # column_names = [descr.name for descr in cursor.description]
    # row = cursor.fetchone()
    # if row is None:
    #     raise DBException(f'The source with {gaia_id=} not found in {psql_table_main}')
    # return dict(row)


def _debug_load_main_data(gaia_id=5284186916701857536) -> dict:  # todo This is a debug method
    import csv
    # import itertools
    filename_csv = f'{path_to_test_data}/main_gaia_data_{gaia_id}.csv'
    try:
        with open(filename_csv) as f:
            csv_reader = csv.reader(f)
            row_header = next(csv_reader)
            row = next(csv_reader)
            df = pd.DataFrame([row], columns=row_header)
    except FileNotFoundError:
        raise DBException(f'Seems like we have not debug data for {gaia_id=}')
    return df.to_dict(orient='records')[0]


def _debug_load_test_cone(gaia_id=5284186916701857536):  # todo This is a debug method
    import csv
    filename_csv = f'{path_to_test_data}/circle_02_{gaia_id}.csv'
    rows = []
    with open(filename_csv) as f:
        csv_reader = csv.reader(f)
        _ = next(csv_reader)  # header

        for row in csv_reader:
            di = {}
            di['gaia_id'], coordequ, di['dist'], di['g_mag'], di['vsx'], di['simbad'] = row
            di['ra'], di['dec'] = eval(coordequ)
            # row[2] = float(row[2])
            # row[3] = float(row[3])
            rows.append(di)
    return rows


def _debug_get_synonym(gaia_id):
    import csv
    filename_csv = f'{path_to_test_data}/synonyms.csv'
    dict_synonyms = {}
    with open(filename_csv) as f:
        csv_reader = csv.reader(f)
        _ = next(csv_reader)  # header
        for row in csv_reader:
            dict_synonyms[row[0]] = row[1:3]
    res = [None if v == '' else v for v in dict_synonyms[gaia_id]]
    return res


def _debug_load_cross_ident(gaia_id):
    logger.debug('Does not matter %s in debug mode', gaia_id)
    return {'gaia_id': gaia_id, 'vsx': None, 'simbad': f'Gaia DR3 {gaia_id}'}


def _debug_load_gaia_params(gaia_id=5284186916701857536) -> dict:  # todo This is a debug method
    import csv
    filename_csv = f'{path_to_test_data}/veb_prop_gaia_{gaia_id}.csv'
    with open(filename_csv) as f:
        csv_reader = csv.reader(f)
        row_header = next(csv_reader)
        row = next(csv_reader)
    dict_prop_gaia = {}
    for key, value in zip(row_header, row):
        dict_prop_gaia[key] = value
    return dict_prop_gaia


def _debug_load_lamost(gaia_id) -> dict:  # todo This is a debug method
    # gaia_id = 48158579233356928
    # gaia_id = 1000119251255360896
    gaia_id_dummy = 1000332964531901824
    logger.info(f'Debug mode: substitute {gaia_id=} for the dummy {gaia_id_dummy=}')
    gaia_id = gaia_id_dummy
    _psql_table_name = 'lamost'

    conn = psycopg2.connect(
        host=getenv("DB_HOST_DEBUG"),
        dbname=getenv("DB_NAME_DEBUG"),
        user=getenv("DB_USER_DEBUG"),
        password=getenv("DB_PASS_DEBUG")
    )

    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # cursor.execute(f'select * from {_psql_table_name} where gaia_id = {gaia_id}')
    cursor.execute(f'select * from {_psql_table_name} where gaia_id = %s', (gaia_id,))
    row_dict = cursor.fetchone()
    conn.commit()
    return row_dict


def _debug_split_json_prop_new(json_filename_full: str) -> (int, float, bool, str, str, dict, dict, dict):
    import json
    with open(json_filename_full, 'r') as f:
        jdict = json.load(f)
    jdict_predicted = {}
    jdict_fitted = {}
    jdict_abs = {}
    for key in jdict.keys():
        if key in ['star_id', 'ra_icrs', 'de_icrs', 'gmag', 'plx', 'e_plx', 'period',
                   'time_ref', 'time_ref_orig', 'spot', 'image', 'type']:
            continue
        if key.startswith('predicted_'):
            key_p = key.replace('predicted_', '')
            jdict_predicted[key_p] = jdict[key]
        elif key not in ['M1', 'M2', 'R1', 'R2', 'L1', 'L2', 'a']:
            jdict_fitted[key] = jdict[key]
        else:
            jdict_abs[key] = jdict[key]

    return (jdict['star_id'], jdict['time_ref'], jdict['spot'], jdict['type'], jdict['image'],
            jdict_predicted, jdict_fitted, jdict_abs)


def _debug_load_photometric_params(gaia_id) -> dict:
    logger.debug('%s does not matter here', gaia_id=gaia_id)
    gaia_id = 1000890283783933312
    json_filename_full = f'{path_to_test_data}{gaia_id}_p.json'
    gaia_id, time_ref, spot, eb_type, path_to_image, jdict_predicted, jdict_fitted, jdict_abs = (
        _debug_split_json_prop_new(json_filename_full))
    logger.debug('%s', gaia_id)
    dict_prop_new = {
        'gaia_id': gaia_id,
        'spot': spot,
        'type': eb_type,
        'time_ref': time_ref + jd0_gaia,
        'predicted': jdict_predicted,
        'fitted': jdict_fitted,
        'absolute': jdict_abs
    }
    return dict_prop_new


def _debug_photometric_params_image(gaia_id):
    logger.debug('%s does not matter here', gaia_id=gaia_id)
    gaia_id = 12345
    import base64
    _psql_table_name = 'veb_prop_new'
    conn = psycopg2.connect(
        host=getenv("DB_HOST_DEBUG"),
        dbname=getenv("DB_NAME_DEBUG"),
        user=getenv("DB_USER_DEBUG"),
        password=getenv("DB_PASS_DEBUG")
    )
    cursor = conn.cursor()
    # cursor.execute(f'select gaia_id,graph from {_psql_table_name} where gaia_id = {gaia_id}')
    cursor.execute(f'select gaia_id,graph from {_psql_table_name} where gaia_id = %s', (gaia_id,))
    row = cursor.fetchone()
    try:
        image_bin = row[1]
    except Exception as e:
        logger.warning(repr(e))
        raise RuntimeError(f'The properties of {gaia_id=} not found in {_psql_table_name} table (may be)')
    finally:
        conn.commit()
    return 'data:image/png;base64,' + base64.b64encode(image_bin).decode('utf-8')


# ------------------- END of debug part ------------------------

def _load_source_data(gaia_id):
    conn = psycopg2.connect(
        host=getenv("DB_HOST"),
        dbname=getenv("DB_NAME"),
        user=getenv("DB_USER"),
        password=getenv("DB_PASS")
    )
    cursor_di = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    jdict_main = _request_main_data(gaia_id, cursor_di)
    jdict_prop_gaia = _request_veb_prop_gaia(gaia_id, cursor_di)
    jdict_prop_new = _request_veb_prop_new(gaia_id, cursor_di)
    jdict_cross_ident = _request_cross_ident(gaia_id, cursor_di)
    jdict_lamost = _request_lamost(gaia_id, cursor_di)
    conn.commit()
    return jdict_main, jdict_prop_gaia, jdict_prop_new, jdict_cross_ident, jdict_lamost


def load_source_params(gaia_id: int) -> dict:
    """
    Loads data for a given Gaia ID from the various tables of the local PostgresSQL database
    Processes and converts the loaded data into dictionary format
    """
    try:
        gaia_id_int = int(gaia_id)
    except (ValueError, TypeError):
        error_str = f'Gaia ID must be an integer, got {type(gaia_id)} instead'
        raise DBException(error_str)
    if getenv('DEBUG_LOCAL'):
        # jdict_main = _debug_load_main_data(gaia_id_int)
        jdict_main = _load_main_data_remote(gaia_id_int)
        # jdict_gaia_params = _debug_load_gaia_params(gaia_id)
        jdict_gaia_params = _load_gaia_params_remote(gaia_id)
        jdict_photometric_params = _debug_load_photometric_params(gaia_id)
        jdict_cross_ident = _debug_load_cross_ident(gaia_id)
        # jdict_lamost = _debug_load_lamost(gaia_id)    # I've dropped brilliantly this table on my laptop
        jdict_lamost = {}
    else:
        (jdict_main, jdict_gaia_params, jdict_photometric_params,
         jdict_cross_ident, jdict_lamost) = _load_source_data(gaia_id_int)
        # jdict_lamost = {}  # todo !
    # Convert or add appropriate units:
    # https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_photometry/ssec_dm_epoch_photometry.html
    return dict(jdict_main=jdict_main, jdict_gaia_params=jdict_gaia_params,
                jdict_photometric_params=jdict_photometric_params,
                jdict_cross_ident=jdict_cross_ident, jdict_lamost=jdict_lamost)


def load_gaia_lightcurve(gaia_id: int, band: str) -> CurveDash:
    try:
        gaia_id_int = int(gaia_id)
    except (ValueError, TypeError):
        error_str = f'Gaia ID must be an integer, got {type(gaia_id)} instead'
        raise DBException(error_str)

    if getenv('DEBUG_LOCAL'):
        return _debug_load_lightcurve_with_metadata(gaia_id_int, band)
    else:
        return _request_lightcurve_with_metadata(gaia_id, band)


if __name__ == '__main__':
    from skvo_veb.logging_config import configure_logging

    configure_logging()
    #    res = request_coord_cone('91.4 -66.5', 0.2)
    request_photometric_params_description()
    request_coord_cone('20 54 05.689 +37 01 17.38', 0.2, 'Gaia')
    gaia_name_test = 5284186916701857536
    band_test_gaia = 'G'
    # band_test_gaia = 'BP'
    res_ = load_source_params(gaia_name_test)
    logger.info('%s', res_)
    di_p_g = _debug_load_gaia_params()
    logger.info('%s', di_p_g)


# todo: move into some common file
def decipher_source_id(source_id):
    if isinstance(source_id, int) and source_id > 0:  # Is it an integer identifier?
        gaia_id = source_id
        return gaia_id
    if not isinstance(source_id, str):  # Is it a string?
        raise PipeException(f'Unappropriated type of source identification {source_id}')  # Bad for you...
    # So, it is a string
    if is_like_gaia_id(source_id):  # A string with an integer identifier?
        gaia_id = int(source_id)
        return gaia_id
    # m.b. something like ''Gaia DR3 123345':
    if (gaia_id := ask_simbad.extract_gaia_id(source_id)) is not None:  # short call
        return gaia_id

    # M.b. this name is present in tho local crossident:
    if not getenv('DEBUG_LOCAL'):
        if (gaia_id := extract_gaia_id(source_id)) is not None:
            return gaia_id

    # Suppose it is a simbad-resolvable name:
    if (gaia_id := ask_simbad.get_gaia_id_by_simbad_name(source_id)) is not None:  # long remote call
        logger.info('Finally Simbad found it %s by %s', gaia_id, source_id)
        return gaia_id

    # M.b. at least Vizier will be able to find it in the Gaia VEB table? This happens...
    if (gaia_id := ask_simbad.get_gaia_id_from_gaia_veb_table(source_id)) is None:  # very long remote call
        raise DBException(f'Simbad does not provide a Gaia DR3 identifier for {source_id}')  # Bad for you...
    return gaia_id
