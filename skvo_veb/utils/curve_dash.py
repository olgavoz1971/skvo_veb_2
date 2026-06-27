import logging
from os import getenv
logging.basicConfig(filename=getenv('APP_LOG'), level=logging.INFO)

import io

import numpy as np
import pandas
import pandas as pd
import json

from astropy.io.ascii import InconsistentTableError
from astropy.io.registry import IORegistryError
from astropy.table import Table
from astropy.time import Time

from skvo_veb.utils.my_tools import PipeException, DataStructureException

from astropy import units as u

jd0 = 2400000.5
fill_nans = 'median'


def astropy_init(unit_str: str):
    if not unit_str:
        return u.Unit()
    try:
        return u.Unit(unit_str)
    except ValueError:
        return u.Unit()


class CurveDash:
    """
    Class deals with lightcurve data. It stores, saves, serializes and restores lightcurves with units
    and related metadata. Lightcurve is stored as pandas.DataFrame
    """

    _format_dict_bytes = {
        'votable': 'vot',
        'fits': 'fits',
    }

    _format_dict_text = {
        'ascii.ecsv': 'ecsv',
        'csv': 'csv',
        'ascii': 'dat',
        'ascii.commented_header': 'dat',
        'ascii.fixed_width': 'dat',
        'html': 'html',
        'ascii.html': 'html',
        'pandas.csv': 'csv',
        'pandas.json': 'json'
    }

    _format_dict_dat = {
        'csv': 'csv',
        'ascii': 'dat',
        'ascii.commented_header': 'dat',
        'ascii.fixed_width': 'dat',
        'html': 'html',
        'ascii.html': 'html',
        'pandas.csv': 'csv',
        'pandas.json': 'json'
    }

    # Combine both dictionaries into a single class-level dictionary
    # format_dict = {**_format_dict_text, **_format_dict_bytes}
    format_dict = _format_dict_text | _format_dict_bytes

    _json_format_list = ['pandas.json']
    _fits_format_list = ['fits', 'fit']

    # extension_dict = {v: k for k, v in format_dict.items()}   # Ambiguous ;-(
    extension_dict = {
        'csv': 'csv',
        'dat': 'ascii.commented_header',  # just because I like this particular type of the "dat" format
        'html': 'html',
        'json': 'pandas.json',
        'fits': 'fits',
        'fit': 'fits'
    }

    def __init__(self, jd=None, flux=None, flux_err=None, label=None,
                 flux_correction: str | None = None, zero_point=0.0,
                 name: str = '', lookup_name: str | None = None, gaia_id=None,
                 title: str = '',
                 band='',
                 time_unit: str = '', flux_unit: str = '',
                 timescale: str | None = None,  # one pf astropy.time Scale or 'hjd' for Heliocentric julian
                 period: float | None = None, period_unit: str = 'd',
                 epoch: float | None = jd0,
                 cross_ident=None, folded_view=0, mag_view=0):
        """
        Initializes an instance of the class, allowing the creation of a lightcurve
        directly from lists of time (jd) and flux values. The initialized
        object will have a lightcurve attribute defined as a Pandas DataFrame

        :param jd: A column of Julian dates representing time points of the lightcurve.
            Only used if `js_lightcurve` is not provided.
        :param flux: A column of flux values corresponding to the Julian dates in `jd`.
            Only used if `js_lightcurve` is not provided.
        :param label: an array of uint8 values to mark groups of points (foe example TESS sectors)
        """

        if epoch is None:
            epoch = jd0
        self.lightcurve: pandas.DataFrame | None = None
        self.metadata: dict | None = None

        # Create structures from the scratch
        if (jd is not None) and (flux is not None):
            if flux_err is None:
                flux_err = np.zeros_like(flux, dtype=float)
            elif flux.shape != flux_err.shape:
                raise PipeException('The lengths of the flux and flux_err arrays differ. '
                                    'Please check the input light curve')
            # When I create a df from a masked array (like flux_err), pandas automatically converts
            # the masked values to NaN. And it is actually what I need
            if label is None:
                label = np.zeros(flux.shape, dtype=np.uint8)
            elif label.shape != flux.shape:
                raise PipeException('The lengths of the label and flux arrays differ. '
                                    'Please check the input light curve')

            # df = pd.DataFrame({'jd': jd, 'flux': flux, 'flux_err': flux_err, 'label': label})
            t = Table({'jd': jd, 'flux': flux, 'flux_err': flux_err, 'label': label})
            df = t.to_pandas()
            # df = pd.DataFrame({'jd': jd, 'flux': flux, 'flux_err': flux_err, 'label': label})

            # Clean bad fluxes for the following log and division operations
            # NaN is used to mark bad values because it is ignored by most statistical functions
            # and plotting libraries. For instance, NumPy functions like np.nanmean and np.nanstd
            # automatically skip NaNs in calculations, ensuring that only valid data is considered.
            # Matplotlib also ignores NaNs when plotting, so bad values don't distort graphs. This
            # approach keeps calculations and visualizations clean without the need for manual filtering

            # I do the cleanup right here, in the __init__, because I don't want to overload client side callbacks
            df.loc[df['flux'] <= 0, 'flux'] = np.nan
            df.loc[df['flux_err'] <= 0, 'flux_err'] = np.nan

            # Using loc to avoid SettingWithCopyWarning and ensure in -place DataFrame update
            df.loc[:, 'selected'] = 0
            # create permanent index. Keep it forever, protect against reindexing; important when cleaning data:
            df.loc[:, 'perm_index'] = df.index
            df.loc[:, 'phase'] = 0.0
            self.lightcurve = df
            # todo: clean flux<=0 here
            if lookup_name and lookup_name == name:
                lookup_name = ''
            # Note: Convert gaia_id to a string to avoid precision loss during JSON serialization.
            # JSON can lose precision when large integers are directly converted, especially in JavaScript,
            # so converting gaia_id to a string ensures its full value is preserved when transferred
            # and parsed on the client-side.
            self.metadata: dict = {'name': name, 'lookup_name': lookup_name, 'gaia_id': str(gaia_id), 'band': band,
                                   'cross_ident': cross_ident,
                                   'time_unit': time_unit, 'timescale': timescale,
                                   'title': title,
                                   'flux_correction': flux_correction,
                                   'flux_unit': flux_unit, 'period': period, 'period_unit': period_unit,
                                   'epoch': epoch,
                                   'folded_view': folded_view,
                                   'mag_view': mag_view,
                                   'zero_point': zero_point}
            self.recalc_phase()  # recalc phase after period and epoch setting

    @classmethod
    def from_serialized(cls, serialized: str):
        """
        Initializes an instance of the class, allowing the recreation of a lightcurve from a
        JSON string. This is useful for restoring an object from dcc.Store data
        :param serialized: A JSON string representation of the lightcurve data.
        :type serialized: str
        """
        try:
            self = cls()
            if not serialized:
                return self  # create an empty lcd
            di = json.loads(serialized)
            if not di:  # empty dictionary
                return self  # create an empty lcd
            lightcurve_dict = di.get('lightcurve')
            self.lightcurve = pd.DataFrame(data=lightcurve_dict['data'], columns=lightcurve_dict['columns'])
            self.metadata = di.get('metadata')
            return self
        except Exception as e:
            logging.warning(f'curve_dash.__init__: {e}')
            raise PipeException('CurveDash init: inconsistent serialized data')

    @staticmethod
    def _read_table(file_obj: io.BytesIO, extension: str) -> Table:
        format_by_extension = CurveDash.get_table_format(extension)
        if format_by_extension in CurveDash._json_format_list:
            formats_to_try = [format_by_extension, None, 'ascii.commented_header', 'ascii']  # Order does matter
        else:
            formats_to_try = [None, 'ascii.commented_header', 'ascii', format_by_extension]
        for fmt in formats_to_try:
            try:
                tab = Table.read(file_obj, format=fmt) if fmt else Table.read(file_obj)
                break
            except (IORegistryError, InconsistentTableError):
                continue
        else:  # Sorry (
            raise DataStructureException("Unable to determine data format from file extension")
        # Replace all 'Undefined' values in metadata with None
        if format_by_extension in CurveDash._fits_format_list:
            from astropy.io.fits.card import Undefined
            # Replace all 'Undefined' values in metadata with None
            meta = {k: (None if isinstance(v, Undefined) else v) for k, v in tab.meta.items()}
            tab.meta = meta
        return tab

    @classmethod
    def from_file(cls, file_obj: io.BytesIO, extension: str):
        # t = Table.read(file_obj, format=CurveDash.get_table_format(extension))
        t = CurveDash._read_table(file_obj, extension)
        if 'flux' not in t.colnames:
            if 'mag' in t.colnames:
                mag0 = 25   # todo try to extract this from the input file
                t['flux'] = 10**(-0.4*(t['mag']-mag0))
            else:
                raise DataStructureException("Table must contain 'flux' column")
        flux_unit = str(getattr(t['flux'], 'unit', ''))
        metadata = getattr(t, 'meta', None)
        if 'label' in t.colnames:
            label = t['label']
        else:
            label = None
        if 'flux_err' not in t.colnames:
            t['flux_err'] = 0
        if 'jd' in t.colnames:
            jd = t['jd']
        elif 'time' in t.colnames:
            try:
                jd = t['time'].jd
            except Exception as e:
                logging.warning(f'curve_dash:from file: {e}')
                raise DataStructureException("Inappropriate data type in the 'time' column")
        else:
            raise DataStructureException("Table must contain 'jd' or 'time' column")
        self = cls(jd=jd, flux=t['flux'], flux_err=t['flux_err'],
                   label=label, flux_unit=flux_unit, time_unit='d')
        if metadata:
            self.metadata = self.metadata | metadata
        return self

    def serialize(self):
        """
        Warning! This serialization approach is used by lightcurve_gaia.py and lightcurve_asassn etc.
        in JavaScript clientside callbacks, so I don't recommend changing it unless absolutely necessary
        """
        if self.lightcurve is None or self.metadata is None:
            return '{}'
        lc = self.lightcurve.to_dict(orient='split', index=False)
        metadata = self.metadata
        return json.dumps({'lightcurve': lc, 'metadata': metadata})

    @property
    def title(self):
        return self.metadata.get('title') if self.metadata else None

    @title.setter
    def title(self, value: str):
        if self.metadata is not None:
            self.metadata['title'] = value

    @property
    def name(self):
        return self.metadata.get('name') if self.metadata else None

    @property
    def lookup_name(self):
        return self.metadata.get('lookup_name') if self.metadata else None

    @property
    def folded_view(self):
        return self.metadata.get('folded_view') if self.metadata else None

    @folded_view.setter
    def folded_view(self, value):
        if self.metadata is not None:
            self.metadata['folded_view'] = value

    @property
    def flux_correction(self):
        if self.metadata is not None:
            if self.metadata.get('flux_correction') is not None:
                return self.metadata.get('flux_correction')
        return ''

    def recalc_phase(self):
        if self.epoch is None:
            self.epoch = jd0
        if self.period is not None and self.epoch is not None:
            df = self.lightcurve
            # Using loc to avoid SettingWithCopyWarning and ensure inplace DataFrame update
            df.loc[:, 'phase'] = self.calc_phase(df['jd'], self.epoch, self.period, self.period_unit)
            self.lightcurve = df

    def shift_epoch(self, phi_to_zero: float) -> float:
        """
        Calculate the new epoch which brings the phi_to_zero to zero
        self.period is used to fold the curve

        :param phi_to_zero: the phase (usually the phase of the primary minimum) that needs to be shifted to 0
        """
        if self.epoch is None:
            self.epoch = jd0
        new_epoch = self.epoch + self.period * phi_to_zero
        return new_epoch

    @staticmethod
    def calc_phase(time_arr, epoch_jd: float | None, period: float | None, period_unit: str):
        # noinspection PyUnresolvedReferences
        period_day = (period * astropy_init(period_unit)).to(u.day)
        epoch_jd = epoch_jd or 0
        period_day = period_day.value or 1
        # period_day = 1 if period_day is None else period_day
        # epoch_jd = 0 if epoch_jd is None else epoch_jd
        phase = ((time_arr - epoch_jd) / period_day) % 1
        return phase

    # def calc_phase(time_arr, epoch_jd: float | None, period: float | None, period_unit: str):
    #     # noinspection PyUnresolvedReferences
    #     period_day = (period * astropy_init(period_unit)).to(u.day)
    #     phase = ((time_arr - (0 if epoch_jd is None else epoch_jd)) / (1 if period_day is None else period_day)) % 1
    #     return phase

    @staticmethod
    def get_format_list() -> list[str]:
        """
        :return: a list of all supported table formats.
        """
        return list(CurveDash.format_dict.keys())

    @staticmethod
    def get_file_extension(table_format: str) -> str:
        """
        :return:  File extension corresponding to the table_format, or 'dat' if not found
        """
        return CurveDash.format_dict.get(table_format, 'dat')

    @staticmethod
    def get_table_format(file_extension: str) -> str:
        """
        :return:  Table format corresponding to the file_extension, or None if not found
        """
        return CurveDash.extension_dict.get(file_extension, None)

    @staticmethod
    def get_extension_list():
        return [CurveDash.get_file_extension(f) for f in CurveDash.get_format_list()]

    @property
    def flux(self):
        # It's important to leave 'is not None' here, because flux is pandas.Series, we can't ask 'if pandas.Series'
        return self.lightcurve.get('flux') if self.lightcurve is not None else None

    @property
    def flux_err(self):
        return self.lightcurve.get('flux_err') if self.lightcurve is not None else None

    @property
    def mag(self):
        """Convert fluxes to magnitudes using the standard formula.
        Returns NaN for invalid (non-positive) flux values.
        """
        if self.lightcurve is None:
            return None

        flux = self.lightcurve.get('flux')
        if flux is None:
            return None

        flux[flux <= 0] = np.nan
        return -2.5 * np.log10(flux) + self.zero_point

    @property
    def mag_err(self):
        """Convert flux errors to magnitude errors using the formula:
        mag_err = 1.0857 * flux_err / flux
        Returns NaN where flux is non-positive or either value is missing.
        """
        if self.lightcurve is None:
            return None

        flux = self.lightcurve.get('flux')
        flux_err = self.lightcurve.get('flux_err')
        if flux is None or flux_err is None:
            return None

        flux = np.array(flux, copy=True)
        flux_err = np.array(flux_err, copy=True)

        flux[flux <= 0] = np.nan  # mark bad flux values
        mag_err = 1.0857 * flux_err / flux

        return mag_err

    @property
    def jd(self):
        return self.lightcurve.get('jd') if self.lightcurve is not None else None

    @property
    def phase(self):
        return self.lightcurve.get('phase') if self.lightcurve is not None else None

    @property
    def label(self):
        if self.lightcurve is not None and 'label' in self.lightcurve:
            return self.lightcurve['label'].astype(str)
        return None

    @property
    def perm_index(self):
        """
        Unique identifier of each, protected from cleaning and all kinds of point reordering.
        It is stored in customdata of the plotly figure
        :return:
        """
        return self.lightcurve.get('perm_index') if self.lightcurve is not None else None

    @property
    def flux_unit(self):
        return self.metadata.get('flux_unit') if self.metadata else ''

    @property
    def flux_unit_ap(self):
        # return astropy.unit if it is convertable
        return astropy_init(self.metadata.get('flux_unit')) if self.metadata else None

    @property
    def time_unit(self):
        return self.metadata.get('time_unit') if self.metadata else None

    @property
    def time_unit_ap(self):
        # return astropy.unit if it is convertable
        return astropy_init(self.metadata.get('time_unit')) if self.metadata else None

    @property
    def timescale(self):
        return self.metadata.get('timescale') if self.metadata else None

    @property
    def period(self):
        return self.metadata.get('period') if self.metadata is not None else None

    @period.setter
    def period(self, value):
        if self.metadata is not None:
            self.metadata['period'] = value
            # self.recalc_phase()

    @property
    def zero_point(self):
        return self.metadata.get('zero_point') if self.metadata is not None else None

    @zero_point.setter
    def zero_point(self, value):
        if self.metadata is not None:
            self.metadata['zero_point'] = value

    @property
    def period_unit(self):
        return self.metadata.get('period_unit') if self.metadata else None

    @period_unit.setter
    def period_unit(self, value):
        if self.metadata is not None:
            self.metadata['period_unit'] = value
            # self.recalc_phase()

    @property
    def period_unit_ap(self):
        return astropy_init(self.metadata.get('period_unit')) if self.metadata else None

    @property
    def epoch(self):
        return self.metadata.get('epoch') if self.metadata else None

    @epoch.setter
    def epoch(self, value):
        logging.debug(f'Epoch setter, new epoch={value}')
        if self.metadata is not None:
            self.metadata['epoch'] = value
            # self.recalc_phase()

    @property
    def gaia_id(self):
        return self.metadata.get('gaia_id') if self.metadata else None

    @property
    def band(self):
        return self.metadata.get('band') if self.metadata else None

    def find_phase_of_min_simple(self):
        """
        First, robust version
        :return:phase of the folded light curve minimum
        """
        self.recalc_phase()
        phase_of_min = self.lightcurve['phase'][np.argmin(self.lightcurve['flux'])]
        return phase_of_min

    def find_phase_of_min_gauss(self):
        """
        Fine version. Fir Gaussian in the surroundings of minimum (initial guess);
        Thanks to Maxim Gabdeev
        :return:phase of the folded light curve minimum
        """
        from scipy.optimize import curve_fit

        def gaussian(x_, a, x0, sigma):
            return a * np.exp(-(x_ - x0) ** 2 / (2 * sigma ** 2))

        self.recalc_phase()
        # initial_guess = [max(y), x_[np.argmax(y)], 0.2 * period]

        # Turn upside down the lightcurve to fit a Gaussian into the primary minimum:
        x = self.lightcurve['phase']
        y = self.lightcurve['flux'].max() - self.lightcurve['flux']
        initial_guess = [max(y), x[np.argmax(y)], 0.2]

        # Shift the phase to keep the minimum within [0.2, 0.8] for a continuous Gaussian fit
        if initial_guess[1] < 0.2:
            logging.debug('find_phase_of_min_gauss: shift left part to the right')
            x = np.where(x < 0.5, x + 1, x)  # shift left part to the right
            initial_guess[1] += 1
        elif initial_guess[1] > 0.8:
            logging.debug('find_phase_of_min_gauss: shift right part to the left')
            x = np.where(x > 0.5, x - 1, x)  # shift right part to the left
            initial_guess[1] -= 1

        # Take points around the initial guess within phase 0.2
        # A also mak nans, because curve_fit is sensitive to them (it raises an Exception)
        mask = (x > initial_guess[1] - 0.2) & (x < initial_guess[1] + 0.2) & ~np.isnan(y)
        x_fit = x[mask]
        y_fit = y[mask]
        try:
            # Fit the Gaussian model to the data
            popt, pcov, _, _, _ = curve_fit(gaussian, x_fit, y_fit.to_numpy(), p0=initial_guess, full_output=True)
            # res = curve_fit(gaussian, x_fit, y_fit.to_numpy(),
            #                 p0=initial_guess)
            # The center of the eclipse is the mean of the Gaussian
            logging.debug(f'find_phase_of_min_gauss: {popt=}')
            # popt = res[0]
            phase_of_min = popt[1]  # todo: check this warning
            return phase_of_min
        except RuntimeError as e:
            logging.error(e)
            return None

    # todo: Rewrite the following methods in JavaScript
    def cut(self, left_border, right_border):
        """
        Remove a piece of lightcurve between  left_border and right_border along the time axis
        :param left_border: start_time
        :param right_border: end_time
        """
        df = self.lightcurve
        self.lightcurve = df[(df['jd'] < left_border) | (df['jd'] > right_border)]

    def keep(self, left_border, right_border):
        """
        Keep only a piece of lightcurve (remove the rest) between left_border and right_border along the time axis
        :param left_border: start_time
        :param right_border: end_time
        """
        df = self.lightcurve
        self.lightcurve = df[(df['jd'] >= left_border) & (df['jd'] <= right_border)]

    def download(self, table_format='ascii.ecsv') -> bytes:
        """
        Write astropy Table into some string. The io.StringIO or io.BytesIO mimics the output file for Table.write()
        The specific IO type depends on the desirable output format, i.e., on the writer type:
        astropy.io.ascii.write, astropy.io.fits.write, astropy.io.votable.write
        We use BytesIO for binary format (including xml-type votable, Yes!) and StringIO for the text formats.
        If you know the better way, please tell me
        """
        import io
        if self.lightcurve is None:
            raise PipeException(f'CurveDash.download: Empty lightcurve')
        if table_format in self._format_dict_text:
            my_weird_io = io.StringIO()
        elif table_format in self._format_dict_bytes:
            my_weird_io = io.BytesIO()
        else:
            raise PipeException(f'Unsupported format {table_format}\n Valid formats: {str(self.format_dict.keys())}')
        tab = Table.from_pandas(self.lightcurve)
        tab['flux'].unit = self.flux_unit_ap
        # u.Unit(self.metadata.get('flux_unit'))
        tab['flux_err'].unit = self.flux_unit_ap
        timescale = self.timescale if self.timescale != 'hjd' else None
        # if table_format not in self._format_dict_dat:
        #     tab['time'] = Time(tab['jd'], format='jd', scale=timescale)
        #     tab.remove_column('jd')

        if (table_format == 'votable' or table_format == 'pandas.json' or table_format == 'fits'
                or table_format in self._format_dict_dat):
            # tab['jd'] = tab['time'].jd
            selected_columns = ['jd', 'phase', 'flux', 'flux_err', 'label']
        else:
            tab['time'] = Time(tab['jd'], format='jd', scale=timescale)
            selected_columns = ['time', 'phase', 'flux', 'flux_err', 'label']

        tab = tab[[col for col in selected_columns if col in tab.colnames]]
        tab.meta = self.metadata
        tab.write(my_weird_io, format=table_format, overwrite=True)

        # self.lightcurve.write(my_weird_io, format=table_format, overwrite=True)
        my_weird_string = my_weird_io.getvalue()
        if isinstance(my_weird_string, str):
            my_weird_string = bytes(my_weird_string, 'utf-8')
        my_weird_io.close()  # todo Needed?

        return my_weird_string

    def append(self, other: "CurveDash") -> None:
        # todo: append title
        if not isinstance(other, CurveDash):
            raise TypeError("The input object must be an instance of CurveDash.")
        if (self.lightcurve is None) or self.lightcurve.empty:
            self.lightcurve = other.lightcurve.copy()
        elif not other.lightcurve.empty:
            self.lightcurve = pd.concat([self.lightcurve, other.lightcurve], ignore_index=True)
