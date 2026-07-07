import logging

logger = logging.getLogger(__name__)

import re
import time

from astropy.coordinates import SkyCoord

positive_float_pattern = r"^(?:\d+\.?\d*|\.\d+)$"
float_pattern = r"^-?(?:\d+\.?\d*|\.\d+)$"
positive_integer_pattern = r"^[1-9]\d*$"


def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*, ]', '_', name)


def log_gamma(data, gamma=0.9, log=True):
    """
    Gamma correction to enhance dark regions
    :param log: disable if False
    :param data:
    :param gamma: Adjust gamma to control the contrast in dark regions
    :return:
    """
    if not log:
        return data
    from numpy import log1p, power
    log_data = log1p(data)
    return power(log_data, gamma)


def safe_none(value):
    return '' if value is None else value


def safe_float(value, fill_value=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fill_value


def timeit(f):
    def timed(*args, **kw):
        ts = time.time()
        result = f(*args, **kw)
        te = time.time()
        logger.debug(f'func:{f.__name__} args:{args, kw} took: {(te - ts):2.4f} sec')
        return result

    return timed


class DBException(Exception):
    # print(f'My exception {Exception} occurred')
    pass


class PipeException(Exception):
    # print(f'My exception {Exception} occurred')
    pass


class DataStructureException(Exception):
    # print(f'My exception {Exception} occurred')
    pass


def is_like_gaia_id(value: str | None):
    if value is None:
        return False
    return bool(re.fullmatch(r'\d+', value))


def tcb2tdb(jd_tcb):
    """
    Conversion between Barycentric Coordinate Time (TCB) and Barycentric Dynamical Time (TBD)

    Gaia photometric series use TCB, Kepler and TESS - TDB scale.
    The transformation between TCB and TDB time scales is given by Berthier et al. (2021)
    and Klioner et al. (2010) following IAU resolution 2006 B31
    TDB = TCB − L_B(JD_TCB − 2 443 144.500 3725) × 86400 s − 6.55 × 10−5 s,
    where the time is expressed in seconds, and L_B = 1.550 519 768 × 10−8.
    During the period covered by the Gaia DR3, the difference TDB − TCB is ∼ −19 s
    https://arxiv.org/pdf/2206.05561.pdf

    Astropy can also do this conversion:
    https://docs.astropy.org/en/stable/time/#convert-time-scale

    :param jd_tcb: TCB in jd,
    :return: TBD-TCB in seconds
    """
    L_B = 1.550519768E-08
    dt = -L_B * (jd_tcb - 2443144.5003725) * 86400 - 6.55 * 1.0E-05
    return dt


from astropy import units as u


# def helio_to_bary(coord: SkyCoord, hjd, obs_name='La Silla Observatory'):
def helio_to_bary(coords: list, hjd, unit=(u.hour, u.deg), obs_name='La Silla Observatory'):
    """
    ASAS-SN light curves use HJD (I hope, I'm right. http://asas-sn.ifa.hawaii.edu/skypatrol)
    This code of  StuartLittlefair converts Heliocentric julian into Baricentric
    https://gist.github.com/StuartLittlefair
    I suppose, we can enter any EarthLocation, for example, 'La Silla Observatory'
    An example: tdb = helio_to_bary([(23, -10)], 2455197.5, 'La Silla Observatory')

    :param coords:
    :param hjd: Heliocentric Julian Date
    :param obs_name:
    :return: TDB time
    """
    from astropy.coordinates import EarthLocation
    from astropy.time import Time

    helio = Time(hjd, scale='utc', format='jd')
    obs = EarthLocation.of_site(obs_name)
    coord = SkyCoord(coords, unit=unit)
    ltt = helio.light_travel_time(coord, 'heliocentric', location=obs)
    guess = helio - ltt
    # if we assume guess is correct - how far is heliocentric time away from true value?
    delta = (guess + guess.light_travel_time(coord, 'heliocentric', obs)).jd - helio.jd
    # apply this correction
    guess -= delta * u.d

    ltt = guess.light_travel_time(coord, 'barycentric', obs)
    return guess.tdb + ltt


# ra = 24; dec = -10; hjd = 2455197.5
# b = helio_to_bary([(ra, dec)], hjd)


def bary_to_helio(coords, bjd, obs_name):
    from astropy.coordinates import SkyCoord, EarthLocation
    from astropy import units as u
    from astropy.time import Time

    bary = Time(bjd, scale='tdb', format='jd')
    obs = EarthLocation.of_site(obs_name)
    star = SkyCoord(coords, unit=(u.hour, u.deg))
    ltt = bary.light_travel_time(star, 'barycentric', location=obs)
    guess = bary - ltt
    delta = (guess + guess.light_travel_time(star, 'barycentric', obs)).jd - bary.jd
    guess -= delta * u.d

    ltt = guess.light_travel_time(star, 'heliocentric', obs)
    return guess.utc + ltt


def explain_exception(e):
    # return f'{type(e).__name__}: {e}'
    return repr(e)


def main_name(cross_ident: dict):
    return cross_ident['vsx'] if cross_ident['vsx'] is not None else cross_ident['simbad'] \
        if cross_ident['simbad'] is not None else f'Gaia DR3 {cross_ident["gaia_id"]}'
