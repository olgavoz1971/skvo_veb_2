import numpy as np
from astropy.coordinates import SkyCoord
# noinspection PyUnresolvedReferences
from astropy.units import deg, rad, hourangle, day, electron


def deg_to_asec(deg, precision: int | None = None):
    return round(np.degrees(deg) * 3600, precision)


def coordequ_to_skycoord(coordequ_str: str) -> SkyCoord:
    """
    :param coordequ_str: like '(1.15, -1.2)' in radians or '(100d, -33.5d)' in degrees
    :return:
    """
    # try:
    units = rad
    if coordequ_str.find('d') > 0:
        units = deg
        coordequ_str = coordequ_str.replace('d', '')
    coord = SkyCoord(coordequ_str.replace('(', '').replace(')', '').replace(',', ' '),
                     unit=(units, units))
    return coord


def skycoord_to_hms_dms(coord: SkyCoord, precision: int | None = None) -> str:
    ra_str_hms = coord.ra.to_string(unit=hourangle, sep=':', pad=True, precision=precision)
    dec_str_dms = coord.dec.to_string(unit=deg, sep=':', alwayssign=True, pad=True, precision=precision)
    return f'{ra_str_hms} {dec_str_dms}'


def skycoord_to_dms_dms(coord: SkyCoord, precision: int | None = None) -> str:
    ra_str_dms = coord.ra.to_string(unit=deg, sep=':', pad=True, precision=precision)
    dec_str_dms = coord.dec.to_string(unit=deg, sep=':', alwayssign=True, pad=True, precision=precision)
    return f'{ra_str_dms} {dec_str_dms}'


# def coordequ_to_hms_dms_both_str(coordequ_str: str, precision: int | None = None) -> (str, str):
#     """
#     :param precision:
#     :param coordequ_str: like '(1.15, -1.2)' in radians or '(100d, -33.5d)' in degrees
#     :return:
#     """
#     coord = coordequ_to_skycoord(coordequ_str)
#     ra_str_hms = coord.ra.to_string(unit=u.hourangle, sep=':', pad=True, precision=precision)
#     ra_str_dms = coord.ra.to_string(unit=u.deg, sep=':', pad=True, precision=precision)
#     dec_str = coord.dec.to_string(unit=u.deg, sep=':', alwayssign=True, pad=True, precision=precision)
#     return f'{ra_str_hms} {dec_str}', f'{ra_str_dms} {dec_str}'


# def coordequ_to_hms_dms_str(coordequ_str: str, precision: int | None = None) -> str:
#     """
#
#     :param precision:
#     :param coordequ_str: like '(1.15, -1.2)' in radians or '(100d, -33.5d)' in degrees
#     :return:
#     """
#     coord = coordequ_to_skycoord(coordequ_str)
#     ra_str = coord.ra.to_string(unit=u.hourangle, sep=':', pad=True, precision=precision)
#     dec_str = coord.dec.to_string(unit=u.deg, sep=':', alwayssign=True, pad=True, precision=precision)
#     return f'{ra_str} {dec_str}'


# def coordequ_to_radec_float(coordequ_str: str, precision: int | None = None):
#     """
#
#     :param precision:
#     :param coordequ_str: like '(1.15, -1.2)' in radians or '(100d, -33.5d)' in degrees
#     :return: tuple (rad_deg: float, dec_deg: float)
#     """
#     # try:
#     units = u.rad
#     if coordequ_str.find('d') > 0:
#         units = u.deg
#         coordequ_str = coordequ_str.replace('d', '')
#     coord = SkyCoord(coordequ_str.replace('(', '').replace(')', '').replace(',', ' '),
#                      unit=(units, units))
#
#     return coord.ra.deg, coord.dec.deg


def is_it_coord(coord_str: str) -> bool:
    try:
        parse_coord_to_skycoord(coord_str)
        return True
    except ValueError:
        return False


def parse_coord_to_skycoord(coord_str: str) -> SkyCoord:
    coord_str = ' '.join(coord_str.split())
    try:
        coord = SkyCoord(coord_str, frame='icrs')
    # except u.UnitsError as e:
    except ValueError as e:
        if (coord_str.find(':') < 0) and (len(coord_str.split(' ')) == 2):
            coord = SkyCoord(coord_str, unit=(deg, deg), frame='icrs')
        else:
            coord = SkyCoord(coord_str, unit=(hourangle, deg), frame='icrs')
    return coord


# def parse_coord_to_deg_deg(coord_str: str):
#     coord = parse_coord_to_skycoord(coord_str)
#     return coord.ra.deg, coord.dec.deg


if __name__ == '__main__':
    # res = coordequ_to_hms_dms_str()
    for coord_str_ in ['20 54 05.689 +37 01 17.38',
                       '20h54m06s +37d01m17s',
                       '313d31m30s +37d1m17s',
                       '313.525      37.021388888888886',
                       ]:
        print(parse_coord_to_skycoord(coord_str_))
