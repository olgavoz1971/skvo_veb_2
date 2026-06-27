import logging
from os import getenv
logging.basicConfig(filename=getenv('APP_LOG'), level=logging.INFO)

import warnings
from astropy.coordinates import SkyCoord
from astroquery.simbad import Simbad
from astroquery.vizier import Vizier

from skvo_veb.utils.my_tools import PipeException

Simbad.TIMEOUT = 120
Vizier.TIMEOUT = 120


def _get_simbad_table(name) -> tuple[str, SkyCoord] | None:
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=UserWarning)
        try:
            # so = Simbad.query_object(name)
            simbad_table = Simbad.query_objectids(name)
        except Exception as e:
            logging.info(f' !!!!!!!!!!!! Simbad connection error {repr(e)}')
            raise PipeException(e)
        return simbad_table


def extract_gaia_id(name) -> int | None:
    gaia_str = 'GAIADR3'
    if name.replace(' ', '').upper().find(gaia_str) == 0:
        gaia_id = name.replace(' ', '').upper()[len(gaia_str):]
        return int(gaia_id)
    return None


def _gaia_id_from_simbad_table(t) -> int | None:
    if t is None:
        return None
    # gaia_str = 'GAIADR3'
    for id_ in t['ID']:
        # if id_.replace(' ', '').upper().find(gaia_str) == 0:
        #     gaia_id = id_.replace(' ', '').upper()[len(gaia_str):]
        gaia_id = extract_gaia_id(id_)
        if gaia_id is not None:
            return gaia_id
    return None


def get_gaia_id_from_gaia_veb_table(name: str) -> int | None:
    table_list = Vizier.query_object(name, catalog='I/358/veb')
    if len(table_list) < 1:
        return None
        # raise DBException(f'Object named {name} was not found in Gaia VEB catalogue')
    if len(table_list[0]) < 1:
        return None
        # raise DBException(f'Object named {name} was not found in Gaia VEB catalogue')
    elif len(table_list[0]) > 1:
        raise PipeException(f'Gaia VEB catalogue has more then 1 object named {name}')
    gaia_id = table_list[0][0]['Source']
    return int(gaia_id)


def get_gaia_id_by_simbad_name(name):
    simbad_table = _get_simbad_table(name)
    return _gaia_id_from_simbad_table(simbad_table)


if __name__ == '__main__':
    name_ = 'OGLE LMC570.29.000434'
    ret1 = get_gaia_id_by_simbad_name(name_)
    print(f'simbad: {ret1}')
    ret2 = get_gaia_id_from_gaia_veb_table(name_)
    print(f'VEB: {ret2}')
