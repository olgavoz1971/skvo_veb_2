"""Lightcurve Data Storage, Serialisation, and Processing Utility.

This module provides the `CurveDash` class, which handles astronomical lightcurve data.
It facilitates ingestion, storage, serialisation, and restoration of lightcurves along with
their associated physical units, zero-point calibrations, and metadata.
"""

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
    """Initialises an Astropy Unit from a string representation.

    If the provided unit string is empty or invalid, returns a dimensionless unit.

    Args:
        unit_str (str): The string representing the physical unit.

    Returns:
        astropy.units.Unit: The initialised Astropy Unit object.
    """
    if not unit_str:
        return u.Unit()
    try:
        return u.Unit(unit_str)
    except ValueError:
        return u.Unit()


class CurveDash:
    """Deals with astronomical lightcurve data and related metadata.

    This class stores, saves, serialises, and restores lightcurves with physical units
    and related metadata. The lightcurve itself is represented internally as a pandas DataFrame.
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
        """Initialises an instance of the CurveDash class.

        Allows the creation of a lightcurve directly from lists of time (jd) and
        flux values. The initialised object contains a lightcurve attribute
        defined as a pandas DataFrame and a metadata dictionary.

        Args:
            jd (array-like, optional): A column of Julian dates representing time points
                of the lightcurve. Defaults to None.
            flux (array-like, optional): A column of flux values corresponding to the
                Julian dates in `jd`. Defaults to None.
            flux_err (array-like, optional): An array of statistical uncertainties for the
                flux values. Defaults to None.
            label (array-like, optional): An array of uint8 values to mark groups of points
                (for example, TESS sectors). Defaults to None.
            flux_correction (str, optional): Type of flux correction applied. Defaults to None.
            zero_point (float, optional): Zero point for magnitude calculation. Defaults to 0.0.
            name (str, optional): Target object name. Defaults to ''.
            lookup_name (str, optional): Alternative name used to lookup the target. Defaults to None.
            gaia_id (int or str, optional): Gaia DR3 identifier. Defaults to None.
            title (str, optional): Custom title for plotting or display. Defaults to ''.
            band (str, optional): Photometric band. Defaults to ''.
            time_unit (str, optional): Unit of time data. Defaults to ''.
            flux_unit (str, optional): Unit of flux data. Defaults to ''.
            timescale (str, optional): Time scale, e.g., an Astropy time scale or 'hjd' for
                Heliocentric Julian date. Defaults to None.
            period (float, optional): Rotation or pulsation period. Defaults to None.
            period_unit (str, optional): Unit of the period (e.g., 'd'). Defaults to 'd'.
            epoch (float, optional): Epoch reference time. Defaults to jd0.
            cross_ident (any, optional): Cross identifiers. Defaults to None.
            folded_view (int, optional): View flag indicating if the folded view is active.
                Defaults to 0.
            mag_view (int, optional): View flag indicating if the magnitude view is active.
                Defaults to 0.

        Raises:
            PipeException: If the lengths of the flux and flux_err arrays differ,
                or if the lengths of the label and flux arrays differ.
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
        """Initialises an instance of the class from a serialised JSON string.

        This is useful for restoring a CurveDash object from dcc.Store data.

        Args:
            serialized (str): A JSON string representation of the lightcurve data.

        Returns:
            CurveDash: The deserialised CurveDash instance (can be empty if input is empty).

        Raises:
            PipeException: If the serialised data is inconsistent or parsing fails.
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
        """Reads an astronomical table from a binary file-like object using heuristics.

        Attempts to determine the format based on the extension and tries multiple
        formats as fallbacks if the primary one fails.

        Args:
            file_obj (io.BytesIO): The file stream to read from.
            extension (str): The file extension used to resolve the expected format.

        Returns:
            astropy.table.Table: The parsed table.

        Raises:
            DataStructureException: If unable to determine or parse the table data format.
        """
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
        """Initialises a CurveDash instance by reading from an open file-like stream.

        Supported formats include VOTable, FITS, and various ASCII text formats.
        The function handles column name resolution for time ('jd' or 'time') and 
        photometry ('flux' or 'mag' with an assumed zero point fallback).

        Args:
            file_obj (io.BytesIO): The file stream containing the lightcurve data.
            extension (str): The file extension indicating the format.

        Returns:
            CurveDash: The initialised CurveDash instance populated with file data.

        Raises:
            DataStructureException: If the file is missing required time or photometry
                columns, or has incorrect data structures.
        """
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
        """Serialises the lightcurve data and metadata to a JSON string.

        Warning! This serialization approach is used by lightcurve_gaia.py and lightcurve_asassn etc.
        in JavaScript clientside callbacks, so I don't recommend changing it unless absolutely necessary.

        Returns:
            str: A JSON string representation of the lightcurve and its metadata.
        """
        if self.lightcurve is None or self.metadata is None:
            return '{}'
        lc = self.lightcurve.to_dict(orient='split', index=False)
        metadata = self.metadata
        return json.dumps({'lightcurve': lc, 'metadata': metadata})

    @property
    def title(self):
        """Gets or sets the custom title of the lightcurve.

        Returns:
            str or None: The title value if metadata is initialised, otherwise None.
        """
        return self.metadata.get('title') if self.metadata else None

    @title.setter
    def title(self, value: str):
        if self.metadata is not None:
            self.metadata['title'] = value

    @property
    def name(self):
        """Gets the target object name.

        Returns:
            str or None: The target object name, or None if metadata is not set.
        """
        return self.metadata.get('name') if self.metadata else None

    @property
    def lookup_name(self):
        """Gets the alternative name used to lookup the target.

        Returns:
            str or None: The alternative lookup name, or None if metadata is not set.
        """
        return self.metadata.get('lookup_name') if self.metadata else None

    @property
    def folded_view(self):
        """Gets or sets the folded view flag.

        Returns:
            int or None: The folded view flag, or None if metadata is not set.
        """
        return self.metadata.get('folded_view') if self.metadata else None

    @folded_view.setter
    def folded_view(self, value):
        if self.metadata is not None:
            self.metadata['folded_view'] = value

    @property
    def flux_correction(self):
        """Gets the type of flux correction applied.

        Returns:
            str: The flux correction string, defaulting to an empty string if not set.
        """
        if self.metadata is not None:
            if self.metadata.get('flux_correction') is not None:
                return self.metadata.get('flux_correction')
        return ''

    def recalc_phase(self):
        """Recalculates the phase of all data points.

        Uses the current period and epoch stored in the metadata. Recalculated phases
        are stored in-place in the lightcurve DataFrame.
        """
        if self.epoch is None:
            self.epoch = jd0
        if self.period is not None and self.epoch is not None:
            df = self.lightcurve
            # Using loc to avoid SettingWithCopyWarning and ensure inplace DataFrame update
            df.loc[:, 'phase'] = self.calc_phase(df['jd'], self.epoch, self.period, self.period_unit)
            self.lightcurve = df

    def shift_epoch(self, phi_to_zero: float) -> float:
        """Calculates a new epoch that shifts the specified phase to zero.

        The period of this CurveDash instance is used to fold the curve. Usually, the 
        phase of the primary minimum is shifted to 0.

        Args:
            phi_to_zero (float): The phase that needs to be shifted to 0 (typically the primary minimum phase).

        Returns:
            float: The newly computed epoch (Julian Date).
        """
        if self.epoch is None:
            self.epoch = jd0
        new_epoch = self.epoch + self.period * phi_to_zero
        return new_epoch

    @staticmethod
    def calc_phase(time_arr, epoch_jd: float | None, period: float | None, period_unit: str):
        """Calculates phase values for a given array of observation times.

        Args:
            time_arr (array-like): An array or Series of observation times.
            epoch_jd (float, optional): The reference epoch Julian Date.
            period (float, optional): The period value.
            period_unit (str): The unit of the period (e.g., 'd').

        Returns:
            array-like: The computed phase values, bounded between 0 and 1.
        """
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
        """Retrieves a list of all supported table formats.

        Returns:
            list of str: Supported table format names.
        """
        return list(CurveDash.format_dict.keys())

    @staticmethod
    def get_file_extension(table_format: str) -> str:
        """Determines the file extension corresponding to the given table format.

        Args:
            table_format (str): The table format name.

        Returns:
            str: Corresponding file extension, defaulting to 'dat' if not found.
        """
        return CurveDash.format_dict.get(table_format, 'dat')

    @staticmethod
    def get_table_format(file_extension: str) -> str:
        """Determines the table format corresponding to the given file extension.

        Args:
            file_extension (str): The file extension name.

        Returns:
            str or None: Corresponding table format, or None if not found.
        """
        return CurveDash.extension_dict.get(file_extension, None)

    @staticmethod
    def get_extension_list():
        """Retrieves a list of all unique file extensions for the supported table formats.

        Returns:
            list of str: File extension strings.
        """
        return [CurveDash.get_file_extension(f) for f in CurveDash.get_format_list()]

    @property
    def flux(self):
        """Gets the flux values series from the lightcurve.

        It's important to leave 'is not None' here, because flux is pandas.Series, we can't ask 'if pandas.Series'.

        Returns:
            pandas.Series or None: The flux values Series, or None if lightcurve is not set.
        """
        # It's important to leave 'is not None' here, because flux is pandas.Series, we can't ask 'if pandas.Series'
        return self.lightcurve.get('flux') if self.lightcurve is not None else None

    @property
    def flux_err(self):
        """Gets the flux statistical errors series from the lightcurve.

        Returns:
            pandas.Series or None: The flux errors Series, or None if lightcurve is not set.
        """
        return self.lightcurve.get('flux_err') if self.lightcurve is not None else None

    @property
    def mag(self):
        """Converts flux values to astronomical magnitudes.

        Uses the standard formula: mag = -2.5 * log10(flux) + zero_point.
        Returns NaN for invalid (non-positive) flux values.

        Returns:
            pandas.Series or None: The calculated magnitudes Series, or None if lightcurve is not set.
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
        """Converts flux errors to magnitude errors.

        Uses the first-order approximation: mag_err = 1.0857 * flux_err / flux.
        Returns NaN where flux is non-positive or either value is missing.

        Returns:
            pandas.Series or None: The calculated magnitude errors Series, or None if lightcurve is not set.
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
        """Gets the Julian Dates series from the lightcurve.

        Returns:
            pandas.Series or None: The Julian Dates Series, or None if lightcurve is not set.
        """
        return self.lightcurve.get('jd') if self.lightcurve is not None else None

    @property
    def phase(self):
        """Gets the phase values series from the lightcurve.

        Returns:
            pandas.Series or None: The phase Series, or None if lightcurve is not set.
        """
        return self.lightcurve.get('phase') if self.lightcurve is not None else None

    @property
    def label(self):
        """Gets the label column as a string Series.

        Returns:
            pandas.Series or None: The labels as string Series, or None if lightcurve is not set.
        """
        if self.lightcurve is not None and 'label' in self.lightcurve:
            return self.lightcurve['label'].astype(str)
        return None

    @property
    def perm_index(self):
        """Gets the permanent unique index series of each observation point.

        The permanent index is protected from cleaning and all kinds of point reordering.
        It is stored in the customdata of the Plotly figure.

        Returns:
            pandas.Series or None: The permanent index series, or None if lightcurve is not set.
        """
        return self.lightcurve.get('perm_index') if self.lightcurve is not None else None

    @property
    def flux_unit(self):
        """Gets the flux unit string.

        Returns:
            str: The flux unit string.
        """
        return self.metadata.get('flux_unit') if self.metadata else ''

    @property
    def flux_unit_ap(self):
        """Gets the convertible Astropy Unit object of the flux.

        Returns:
            astropy.units.Unit or None: The Astropy Unit if convertible, otherwise None.
        """
        # return astropy.unit if it is convertable
        return astropy_init(self.metadata.get('flux_unit')) if self.metadata else None

    @property
    def time_unit(self):
        """Gets the time unit string.

        Returns:
            str or None: The time unit string.
        """
        return self.metadata.get('time_unit') if self.metadata else None

    @property
    def time_unit_ap(self):
        """Gets the convertible Astropy Unit object of the time.

        Returns:
            astropy.units.Unit or None: The Astropy Unit if convertible, otherwise None.
        """
        # return astropy.unit if it is convertable
        return astropy_init(self.metadata.get('time_unit')) if self.metadata else None

    @property
    def timescale(self):
        """Gets the time scale string.

        Returns:
            str or None: The time scale (e.g., 'UTC', 'TDB', 'hjd'), or None if not set.
        """
        return self.metadata.get('timescale') if self.metadata else None

    @property
    def period(self):
        """Gets or sets the period value.

        Returns:
            float or None: The period value, or None if not set.
        """
        return self.metadata.get('period') if self.metadata is not None else None

    @period.setter
    def period(self, value):
        if self.metadata is not None:
            self.metadata['period'] = value
            # self.recalc_phase()

    @property
    def zero_point(self):
        """Gets or sets the zero point for magnitude calculations.

        Returns:
            float or None: The zero point value, or None if not set.
        """
        return self.metadata.get('zero_point') if self.metadata is not None else None

    @zero_point.setter
    def zero_point(self, value):
        if self.metadata is not None:
            self.metadata['zero_point'] = value

    @property
    def period_unit(self):
        """Gets or sets the unit of the period.

        Returns:
            str or None: The unit of the period (e.g., 'd'), or None if not set.
        """
        return self.metadata.get('period_unit') if self.metadata else None

    @period_unit.setter
    def period_unit(self, value):
        if self.metadata is not None:
            self.metadata['period_unit'] = value
            # self.recalc_phase()

    @property
    def period_unit_ap(self):
        """Gets the convertible Astropy Unit object of the period.

        Returns:
            astropy.units.Unit or None: The Astropy Unit if convertible, otherwise None.
        """
        return astropy_init(self.metadata.get('period_unit')) if self.metadata else None

    @property
    def epoch(self):
        """Gets or sets the epoch reference time.

        Returns:
            float or None: The epoch reference time, or None if not set.
        """
        return self.metadata.get('epoch') if self.metadata else None

    @epoch.setter
    def epoch(self, value):
        logging.debug(f'Epoch setter, new epoch={value}')
        if self.metadata is not None:
            self.metadata['epoch'] = value
            # self.recalc_phase()

    @property
    def gaia_id(self):
        """Gets the Gaia identifier.

        Returns:
            str or None: The Gaia identifier as a string, or None if not set.
        """
        return self.metadata.get('gaia_id') if self.metadata else None

    @property
    def band(self):
        """Gets the photometric band name.

        Returns:
            str or None: The band name (e.g., 'G', 'BP', 'RP'), or None if not set.
        """
        return self.metadata.get('band') if self.metadata else None

    def find_phase_of_min_simple(self):
        """Finds the phase of the folded lightcurve minimum using a robust, direct minimum search.

        First, robust version.

        Returns:
            float: Phase of the folded lightcurve minimum.
        """
        self.recalc_phase()
        phase_of_min = self.lightcurve['phase'][np.argmin(self.lightcurve['flux'])]
        return phase_of_min

    def find_phase_of_min_gauss(self):
        """Finds the phase of the folded lightcurve minimum by fitting a Gaussian to the primary minimum.

        Fits a Gaussian model to the surroundings of the initial minimum guess.
        Handles phase wrapping/shifting to keep the minimum within [0.2, 0.8] for a continuous fit.
        Thanks to Maxim Gabdeev.

        Returns:
            float or None: Phase of the folded lightcurve minimum, or None if fitting fails.
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
        """Removes a piece of the lightcurve between the specified left and right borders along the time axis.

        Args:
            left_border (float): The start time (Julian Date) of the segment to remove.
            right_border (float): The end time (Julian Date) of the segment to remove.
        """
        df = self.lightcurve
        self.lightcurve = df[(df['jd'] < left_border) | (df['jd'] > right_border)]

    def keep(self, left_border, right_border):
        """Keeps only the segment of the lightcurve between the specified left and right borders, removing the rest.

        Args:
            left_border (float): The start time (Julian Date) of the segment to keep.
            right_border (float): The end time (Julian Date) of the segment to keep.
        """
        df = self.lightcurve
        self.lightcurve = df[(df['jd'] >= left_border) & (df['jd'] <= right_border)]

    def download(self, table_format='ascii.ecsv') -> bytes:
        """Serialises and exports the lightcurve to a byte string of the specified format.

        Supported formats include 'ascii.ecsv', 'votable', 'fits', and other ASCII table formats.
        Uses io.StringIO or io.BytesIO to write the Astropy table to memory.
        If you know a better way, please tell me.

        Args:
            table_format (str, optional): The target file format for export. Defaults to 'ascii.ecsv'.

        Returns:
            bytes: The serialised table as a UTF-8 encoded byte string.

        Raises:
            PipeException: If the lightcurve is empty or the requested table_format is unsupported.
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
        """Appends another CurveDash instance's lightcurve observations to this instance.

        Args:
            other (CurveDash): The other lightcurve container to append.

        Raises:
            TypeError: If the input object is not an instance of CurveDash.
        """
        # todo: append title
        if not isinstance(other, CurveDash):
            raise TypeError("The input object must be an instance of CurveDash.")
        if (self.lightcurve is None) or self.lightcurve.empty:
            self.lightcurve = other.lightcurve.copy()
        elif not other.lightcurve.empty:
            self.lightcurve = pd.concat([self.lightcurve, other.lightcurve], ignore_index=True)
