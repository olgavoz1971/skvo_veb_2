import logging

logger = logging.getLogger(__name__)

from dash.dcc import Markdown

from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.request_gaia import jd0_gaia

photometric_parameter_template = {
        # {long name: (fitted_key, predicted_key, (unit, precision))}
        # The order does matter
        'Inclination': (('i', 'i'), ('deg', 0)),
        'Mass ratio': (('q', 'q'), (None, 2)),
        'Potential': ((None, 'pot'), (None, 2)),
        'Potential of 1st component': (('pot1', None), (None, 3)),
        'Potential of 2st component': (('pot2', None), (None, 3)),
        'Temperature ratio': (('t1/t2', 't1/t2'), (None, 2)),
        'Temperature of the 1st component': (('t1', None), (None, 0)),
        'Temperature of the 2st component': (('t2', None), (None, 0)),
        'Bolometric luminosity of the 1st component': ((None, 'BL1'), ('solar luminosity', 2)),
        'Bolometric luminosity of the 2st component': ((None, 'BL2'), ('solar luminosity', 2)),
        'Equivalent radius of the 1st component': ((None, 'R1_eq'), ('solar radius', 3)),
        'Equivalent radius of the 2st component': ((None, 'R2_eq'), ('solar radius', 3)),
        'Phase shift': ((None, 'phase_shift'), (None, 1)),
        'Sum of squares of fit': (('sq', 'sq'), (None, 5)),
    }
main_parameters_dict = {
        'gaia_id': ('Source identifier', None),
        'parallax': ('Parallax', 'mas', 4),
        'pm': ('Total proper motion', 'mas/yr', 4),
        'pm_ra': ('Proper motion in right ascension direction, pmRA*cosDE', 'mas/yr', 4),
        'pm_de': ('Proper motion in declination direction', 'mas/yr', 4),
        'g_mag': ('G magnitude', 'mag', 3),
        'bp_mag': ('Bp magnitude', 'mag', 3),
        'rp_mag': ('Rp magnitude', 'mag', 3),
        'teff': ('Teff from BP/RP spectra', 'K', 0),
        'teff_low': ('Lower confidence level (16%) of Teff', 'K', 0),
        'teff_up': ('Upper confidence level (84%) of Teff', 'K', 0),
        'logg': ('Logg from BP/RP spectra', None, 3),
        'logg_up': ('Upper confidence level (84%) of logg', None, 3),
        'logg_low': ('Lower confidence level (16%) of logg', None, 3),
        'fe2h': ('[Fe/H] from BP/RP spectra', None, 3),
        'fe2h_up': ('Upper confidence level (84%) of [Fe/H]', None, 3),
        'fe2h_low': ('Lower confidence level (16%) of [Fe/H]', None, 3),
        'rv': ('Radial velocity', 'km/s', 3),
        'vbroad': ('Spectral line broadening parameter', 'km/s', 3),
        'coordequ': None,  # i.e., ignore this parameter
    }
gaia_photometric_parameter_name_dict = {
        # Gaia parameters: Description, units, precision (digits after the decimal point)
        'gaia_id': ('Source identifier', None),
        'time_ref': ('Estimated reference time', f'jd-{jd0_gaia}', 4),
        'freq': ('Frequency', None, 5),
        'mag_mod': ('Model magnitude reference level', 'mag', 3),
        'phase1': ('Phase of the Gaussian 1 component', None, 3),
        'sig_phase1': ('Standard deviation of Gaussian 1 component', 'phase', 3),
        'depth1': ('Magnitude depth of Gaussian 1 component', 'mag', 3),
        'phase2': ('Phase of the Gaussian 2 component', None, 3),
        'sig_phase2': ('Standard deviation of Gaussian 2 component', 'phase', 3),
        'depth2': ('Magnitude depth of Gaussian 2 component', 'mag', 3),
        'amp_chp': ('Amplitude of the cosine component with half the period of the model', 'mag', 3),
        'phase_chp': ('Reference phase of the cosine component with half the period of the model', None, 3),
        'phase_e1': ('Primary eclipse: phase at geometrically deepest point', None, 3),
        'dur_e1': ('Primary eclipse: duration', 'phase fraction', 4),
        'depth_e1': ('Primary eclipse: depth', 'mag', 3),
        'phase_e2': ('Secondary eclipse: phase at geometrically deepest point', None, 3),
        'dur_e2': ('Secondary eclipse: duration', 'phase fraction', 4),
        'depth_e2': ('Secondary eclipse: depth', 'mag', 3),
        'model_type': ('Type of geometrical model of the light curve', None),
    }
lamost_parameter_name_dict = {
        # LAMOST parameters
        'Teff(low)': ('Teff from Low-resolution spectrum', 'K', 0),
        'Teff_lasp(med)': ('Teff from Medium-resolution spectrum, LAMOST pipeline', 'K', 0),
        'Teff_cnn(med)': ('Teff from Medium-resolution spectrum, CNN method', 'K', 0),
        'Fe/H(low)': ('[Fe/H] from Low-resolution spectrum', None, 3),
        'Fe/H_lasp(med)': ('[Fe/H] from Medium-resolution spectrum, LAMOST pipeline', None, 3),
        'Fe/H_cnn(med)': ('[Fe/H] from Medium-resolution spectrum, CNN method', None, 3),
        'logg(low)': ('Logg from Low-resolution spectrum', None, 2),
        'logg_lasp(med)': ('Logg from Medium-resolution spectrum, LAMOST pipeline', None, 2),
        'logg_cnn(med)': ('Logg from Medium-resolution spectrum, CNN method', None, 2),
    }


def _reformat_dict(di: dict) -> dict:
    """
        interpret *_err keys as errors of *
    :param di:
    :return: improved dict {name: (val,err)}
    """
    #
    new_di = {}
    for key, value in di.items():
        if value is None or (isinstance(value, str) and value.strip() == ''):
            # Ignore empty parameters
            continue
        # if key.startswith('e_') and (key.replace('e_', '') in di.keys()):
        if key.endswith('_err') and (key.replace('_err', '') in di.keys()):
            if value is None:
                continue
            key_new = key.replace('_err', '')
            new_di[key_new] = (di[key_new], value)
        else:
            new_di[key] = value
    return new_di


def _format_field_name(description, unit):
    if unit is None:
        # return f'{desc_.capitalize()}'
        return f'{description}'
    # return f'{desc_.capitalize()}, ({unit_})'
    return f'{description}, ({unit})'


def _format_value(value, precision: int | None):
    try:
        if isinstance(value, tuple) and len(value) == 2:
            val, err = value
        else:
            val = value
            err = None
        err_str = ''
        val_str = str(val)
        if precision is not None:  # and isinstance(val_, (int, float)):
            try:
                val_str = f'{float(val):.{precision}f}'
                if err is not None:
                    # err = round(float(err), precision)
                    err = float(err)
                    err_str = f'\({err:.{precision}f}\)' if err else ''
            except Exception as e_:
                logger.warning(f'table_from_dict: format_value {value=}, {precision=} {e_}')
                pass
        text = f'{val_str}    {err_str}'
    except (TypeError, ValueError):
        # text = f'${value}$'
        text = f'{value}'
    return Markdown(text)
    # return dcc.Markdown(text, mathjax=True)


def table_from_dict(di: dict | None, params_catalog: str) -> list:
    """
    Convert a parameter dictionary into formatted table, i.e., a list of pairs of strings in the form "name","value"
    The dictionary keys are converted into a formatted name using a special dictionary
    "parameter_name_dict" loaded from the Database
    :param params_catalog: Gaia, Lamost, Photometric -- dictionary of parameters description: Long name, unit, precision
    :param di: dictionary in the form {parameter_name: (value,error)}
    :return:
    """
    row_list = []
    if di is None:
        di = {}
    di = _reformat_dict(di)

    def parse_options(opt: tuple):
        desc_, unit_, prec_ = None, None, None
        try:
            desc_, unit_, prec_ = opt
        except ValueError:
            try:
                desc_, unit_ = opt
            except ValueError:
                desc_ = opt
        except Exception as e:
            logger.warning(f'parse_options {opt}: {repr(e)}')
        return desc_, unit_, prec_

    if ('GAIA' and 'PHOTOMETRIC') in params_catalog.upper():
        parameter_name_dict = gaia_photometric_parameter_name_dict
    elif 'LAMOST' in params_catalog.upper():
        parameter_name_dict = lamost_parameter_name_dict
    elif ('GAIA' and 'MAIN') in params_catalog.upper():
        parameter_name_dict = main_parameters_dict
    else:
        raise PipeException(f'veb_parameters.table_from_dict: bad params_catalog {params_catalog}')

    # First, try to fill a catalog-specific dictionary grom the DB:
    for key, option in parameter_name_dict.items():
        if key not in di:
            continue
        val = di.pop(key)
        if option is None:  # This item has been marked as ignored
            continue
        desc, unit, prec = parse_options(option)
        row_list.append([_format_field_name(desc, unit), _format_value(val, prec)])
    # Then add the rest:
    for key, val in di.items():
        desc, unit, prec = key, None, None
        logger.warning(f'The description of parameter {key} is missing from the database')
        row_list.append([_format_field_name(desc, unit), _format_value(val, prec)])
    return row_list


def photometric_param_table(predicted_params: dict, fitted_params: dict) -> list:
    row_list = [['Name', 'Fitted', 'Predicted']]
    predicted_params = _reformat_dict(predicted_params)
    fitted_params = _reformat_dict(fitted_params)
    for desc, value in photometric_parameter_template.items():
        # {long name: (fitted_key, predicted_key, (unit, precision))}
        key_fitted, key_predicted = value[0]
        unit, prec = value[1]
        val_fitted = fitted_params.get(key_fitted, '') if key_fitted is not None else ''
        val_predicted = predicted_params.get(key_predicted, '') if key_predicted is not None else ''
        if val_fitted == '' and val_predicted == '':
            continue
        row_list.append([_format_field_name(desc, unit), _format_value(val_fitted, prec),
                         _format_value(val_predicted, prec)])
    return row_list
