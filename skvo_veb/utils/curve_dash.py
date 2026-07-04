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
from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD,
    DOMAIN_FLUX,
    DOMAIN_MAG,
    FALLBACK_MAG_ZERO_POINT,
    FLUX_TO_MAG_ERR_FACTOR,
    MAG_TO_FLUX_ERR_FACTOR,
)

from astropy import units as u

jd0 = DEFAULT_EPOCH_JD
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
        'ecsv': 'ascii.ecsv',
        'html': 'html',
        'json': 'pandas.json',
        'fits': 'fits',
        'fit': 'fits',
        'vot': 'votable',
        'xml': 'votable',
    }

    def __init__(self, jd=None, flux=None, flux_err=None, mag=None, mag_err=None,
                 label=None, active_domain: str | None = None, photcal: dict | None = None,
                 flux_correction: str | None = None, zero_point=0.0,
                 name: str = '', lookup_name: str | None = None, gaia_id=None,
                 title: str = '',
                 band='',
                 time_unit: str = '', flux_unit: str = '', mag_unit: str = 'mag',
                 timescale: str | None = None,  # one pf astropy.time Scale or 'hjd' for Heliocentric julian
                 period: float | None = None, period_unit: str = 'd',
                 epoch: float | None = jd0,
                 cross_ident=None, folded_view=0, mag_view=0):
        """Initialises an instance of the CurveDash class.

        Allows the creation of a lightcurve directly from lists of time (jd) and
        photometry values. Data are stored in the native domain supplied at
        ingestion (magnitude or flux) without automatic conversion.

        Args:
            jd (array-like, optional): Julian dates for each observation.
            flux (array-like, optional): Flux values when ``active_domain`` is ``'flux'``.
            flux_err (array-like, optional): Flux uncertainties.
            mag (array-like, optional): Magnitude values when ``active_domain`` is ``'mag'``.
            mag_err (array-like, optional): Magnitude uncertainties.
            label (array-like, optional): Group labels (e.g. TESS sectors).
            active_domain (str, optional): ``'flux'`` or ``'mag'``. Inferred from
                which photometry columns are provided when omitted.
            photcal (dict, optional): Photometric calibration metadata
                (``zp_flux``, ``zp_mag``, ``mag_sys``, etc.) for on-demand conversion.
            flux_correction (str, optional): Type of flux correction applied.
            zero_point (float, optional): Legacy zero point for magnitude display.
            name (str, optional): Target object name.
            lookup_name (str, optional): Alternative lookup name.
            gaia_id (int or str, optional): Gaia DR3 identifier.
            title (str, optional): Display title.
            band (str, optional): Photometric band.
            time_unit (str, optional): Unit of time data.
            flux_unit (str, optional): Unit of flux data.
            mag_unit (str, optional): Unit of magnitude data. Defaults to ``'mag'``.
            timescale (str, optional): Astropy time scale or ``'hjd'``.
            period (float, optional): Variability period.
            period_unit (str, optional): Period unit. Defaults to ``'d'``.
            epoch (float, optional): Reference epoch. Defaults to ``DEFAULT_EPOCH_JD``.
            cross_ident (any, optional): Cross identifiers.
            folded_view (int, optional): Folded-view UI flag.
            mag_view (int, optional): Magnitude-view UI flag.

        Raises:
            PipeException: If array lengths are inconsistent or no photometry is supplied.
        """

        if epoch is None:
            epoch = jd0
        self.lightcurve: pandas.DataFrame | None = None
        self.metadata: dict | None = None

        if jd is None:
            return

        if mag is not None and flux is not None:
            raise PipeException('Supply either flux or mag photometry, not both.')

        if mag is not None:
            domain = DOMAIN_MAG
            phot_vals = mag
            phot_err_vals = mag_err
            phot_unit = mag_unit
        elif flux is not None:
            domain = DOMAIN_FLUX
            phot_vals = flux
            phot_err_vals = flux_err
            phot_unit = flux_unit
        else:
            raise PipeException('Either flux or mag photometry must be supplied.')

        if phot_err_vals is None:
            phot_err_vals = np.zeros_like(phot_vals, dtype=float)
        elif np.shape(phot_vals) != np.shape(phot_err_vals):
            raise PipeException('Photometry and uncertainty arrays must have equal length.')

        if label is None:
            label = np.zeros(np.shape(phot_vals), dtype=np.uint8)
        elif np.shape(label) != np.shape(phot_vals):
            raise PipeException('Label array length must match photometry length.')

        if domain == DOMAIN_FLUX:
            table_dict = {'jd': jd, 'flux': phot_vals, 'flux_err': phot_err_vals, 'label': label}
        else:
            table_dict = {'jd': jd, 'mag': phot_vals, 'mag_err': phot_err_vals, 'label': label}

        df = Table(table_dict).to_pandas()

        if domain == DOMAIN_FLUX:
            df.loc[df['flux'] <= 0, 'flux'] = np.nan
            df.loc[df['flux_err'] <= 0, 'flux_err'] = np.nan

        df.loc[:, 'selected'] = 0
        df.loc[:, 'perm_index'] = df.index
        df.loc[:, 'phase'] = 0.0
        self.lightcurve = df

        if lookup_name and lookup_name == name:
            lookup_name = ''

        resolved_domain = active_domain or domain
        self.metadata = {
            'name': name,
            'lookup_name': lookup_name,
            'gaia_id': str(gaia_id),
            'band': band,
            'cross_ident': cross_ident,
            'time_unit': time_unit,
            'timescale': timescale,
            'title': title,
            'flux_correction': flux_correction,
            'flux_unit': flux_unit if resolved_domain == DOMAIN_FLUX else '',
            'mag_unit': mag_unit if resolved_domain == DOMAIN_MAG else '',
            'active_domain': resolved_domain,
            'photcal': photcal or {},
            'period': period,
            'period_unit': period_unit,
            'epoch': epoch,
            'folded_view': folded_view,
            'mag_view': mag_view,
            'zero_point': zero_point,
        }
        self.recalc_phase()

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
            if self.metadata is not None and 'active_domain' not in self.metadata:
                if 'mag' in self.lightcurve.columns:
                    self.metadata['active_domain'] = DOMAIN_MAG
                else:
                    self.metadata['active_domain'] = DOMAIN_FLUX
            if self.metadata is not None and 'photcal' not in self.metadata:
                self.metadata['photcal'] = {}
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
        if 'flux' in t.colnames:
            flux = t['flux']
            flux_err = t['flux_err'] if 'flux_err' in t.colnames else 0
            flux_unit = str(getattr(t['flux'], 'unit', ''))
            phot_kwargs = dict(flux=flux, flux_err=flux_err, flux_unit=flux_unit, active_domain=DOMAIN_FLUX)
        elif 'mag' in t.colnames:
            mag = t['mag']
            mag_err = t['mag_err'] if 'mag_err' in t.colnames else 0
            mag_unit = str(getattr(t['mag'], 'unit', 'mag'))
            phot_kwargs = dict(mag=mag, mag_err=mag_err, mag_unit=mag_unit, active_domain=DOMAIN_MAG)
        else:
            raise DataStructureException("Table must contain 'flux' or 'mag' column")
        metadata = getattr(t, 'meta', None)
        if 'label' in t.colnames:
            label = t['label']
        else:
            label = None
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
        self = cls(jd=jd, label=label, time_unit='d', **phot_kwargs)
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
    def active_domain(self) -> str:
        """Gets the native photometric domain of the stored data.

        Returns:
            str: ``'flux'`` or ``'mag'``.
        """
        if self.metadata is None:
            return DOMAIN_FLUX
        return self.metadata.get('active_domain', DOMAIN_FLUX)

    @property
    def phot(self):
        """Gets photometry values in the currently active domain.

        Returns:
            pandas.Series or None: Magnitude or flux values depending on ``active_domain``.
        """
        if self.lightcurve is None:
            return None
        if self.active_domain == DOMAIN_MAG:
            return self.lightcurve.get('mag')
        return self.lightcurve.get('flux')

    @property
    def phot_err(self):
        """Gets photometry uncertainties in the currently active domain.

        Returns:
            pandas.Series or None: Magnitude or flux errors depending on ``active_domain``.
        """
        if self.lightcurve is None:
            return None
        if self.active_domain == DOMAIN_MAG:
            return self.lightcurve.get('mag_err')
        return self.lightcurve.get('flux_err')

    @property
    def phot_unit(self) -> str:
        """Gets the unit string for the active photometric domain.

        Returns:
            str: Flux or magnitude unit string.
        """
        if self.metadata is None:
            return ''
        if self.active_domain == DOMAIN_MAG:
            return self.metadata.get('mag_unit', 'mag')
        return self.metadata.get('flux_unit', '')

    @property
    def photcal(self) -> dict:
        """Gets stored photometric calibration metadata for domain conversion.

        Returns:
            dict: Zero-point and magnitude-system metadata.
        """
        if self.metadata is None:
            return {}
        return self.metadata.get('photcal', {})

    def _resolve_photcal(self):
        """Builds a ``PhotCal`` instance from stored metadata.

        Returns:
            skvo_veb.volightcurve.lightcurve.PhotCal: Calibration for mag/flux conversion.
        """
        from skvo_veb.volightcurve.lightcurve import PhotCal

        pc = self.photcal
        zp_flux = pc.get('zp_flux', 1.0)
        zp_mag = pc.get('zp_mag', FALLBACK_MAG_ZERO_POINT)
        return PhotCal(
            zp_flux=zp_flux,
            zp_flux_unit=pc.get('zp_flux_unit') or 'Jy',
            zp_mag=zp_mag,
            zp_mag_unit=pc.get('zp_mag_unit') or 'mag',
            mag_sys=pc.get('mag_sys', 'Vega'),
        )

    def convert_to_flux(self) -> None:
        """Converts stored magnitude data to flux in-place.

        Uses ``PhotCal`` from the volightcurve layer when calibration metadata is
        available. Updates ``active_domain`` to ``'flux'`` and replaces DataFrame
        columns accordingly.

        Raises:
            PipeException: If data are already in flux domain or magnitude columns are missing.
        """
        if self.lightcurve is None or self.metadata is None:
            raise PipeException('Cannot convert an empty lightcurve to flux.')
        if self.active_domain == DOMAIN_FLUX:
            return

        mag_col = self.lightcurve.get('mag')
        mag_err_col = self.lightcurve.get('mag_err')
        if mag_col is None:
            raise PipeException('No magnitude column available for conversion to flux.')

        photcal = self._resolve_photcal()
        mag_values = mag_col.values.astype(float)
        try:
            mag_quantity = mag_values * u.mag
            flux_quantity = photcal.mag_to_flux(mag_quantity)
            flux_vals = np.array(flux_quantity.value, dtype=float)
            flux_unit_str = str(flux_quantity.unit)
        except (u.UnitsError, u.UnitTypeError, TypeError, ValueError) as exc:
            logging.warning('PhotCal mag_to_flux failed (%s); using fallback formula.', exc)
            zp_m = photcal.zp_mag.value
            zp_f = photcal.zp_flux.value
            flux_vals = zp_f * 10 ** (-0.4 * (mag_values - zp_m))
            flux_unit_str = str(photcal.zp_flux.unit)

        if mag_err_col is not None:
            flux_err_vals = flux_vals * MAG_TO_FLUX_ERR_FACTOR * mag_err_col.values
        else:
            flux_err_vals = np.zeros_like(flux_vals)

        df = self.lightcurve.drop(columns=['mag', 'mag_err'], errors='ignore')
        df['flux'] = flux_vals
        df['flux_err'] = flux_err_vals
        df.loc[df['flux'] <= 0, 'flux'] = np.nan
        df.loc[df['flux_err'] <= 0, 'flux_err'] = np.nan
        self.lightcurve = df
        self.metadata['active_domain'] = DOMAIN_FLUX
        self.metadata['flux_unit'] = flux_unit_str
        self.metadata['mag_unit'] = ''

    def convert_to_mag(self) -> None:
        """Converts stored flux data to magnitude in-place.

        Uses ``PhotCal`` from the volightcurve layer when calibration metadata is
        available. Updates ``active_domain`` to ``'mag'`` and replaces DataFrame
        columns accordingly.

        Raises:
            PipeException: If data are already in magnitude domain or flux columns are missing.
        """
        if self.lightcurve is None or self.metadata is None:
            raise PipeException('Cannot convert an empty lightcurve to magnitude.')
        if self.active_domain == DOMAIN_MAG:
            return

        flux_col = self.lightcurve.get('flux')
        flux_err_col = self.lightcurve.get('flux_err')
        if flux_col is None:
            raise PipeException('No flux column available for conversion to magnitude.')

        photcal = self._resolve_photcal()
        flux_vals = flux_col.values.astype(float)
        try:
            flux_unit = self.flux_unit_ap or u.dimensionless_unscaled
            flux_quantity = flux_vals * flux_unit
            mag_quantity = photcal.flux_to_mag(flux_quantity)
            mag_vals = np.array(mag_quantity.value, dtype=float)
        except (u.UnitsError, u.UnitTypeError, TypeError, ValueError) as exc:
            logging.warning('PhotCal flux_to_mag failed (%s); using fallback formula.', exc)
            zp_m = photcal.zp_mag.value
            zp_f = photcal.zp_flux.value
            valid = flux_vals > 0
            mag_vals = np.full_like(flux_vals, np.nan)
            mag_vals[valid] = zp_m - 2.5 * np.log10(flux_vals[valid] / zp_f)

        if flux_err_col is not None:
            flux_vals = flux_col.values.astype(float)
            err_vals = flux_err_col.values.astype(float)
            valid = flux_vals > 0
            mag_err_vals = np.full_like(flux_vals, np.nan)
            mag_err_vals[valid] = FLUX_TO_MAG_ERR_FACTOR * (err_vals[valid] / flux_vals[valid])
        else:
            mag_err_vals = np.zeros_like(mag_vals)

        df = self.lightcurve.drop(columns=['flux', 'flux_err'], errors='ignore')
        df['mag'] = mag_vals
        df['mag_err'] = mag_err_vals
        self.lightcurve = df
        self.metadata['active_domain'] = DOMAIN_MAG
        self.metadata['mag_unit'] = 'mag'
        self.metadata['flux_unit'] = ''

    @property
    def flux(self):
        """Gets the flux values series when ``active_domain`` is ``'flux'``.

        Returns:
            pandas.Series or None: Flux values, or None if stored in magnitude domain.
        """
        if self.lightcurve is None or self.active_domain != DOMAIN_FLUX:
            return None
        return self.lightcurve.get('flux')

    @property
    def flux_err(self):
        """Gets the flux error series when ``active_domain`` is ``'flux'``.

        Returns:
            pandas.Series or None: Flux errors, or None if stored in magnitude domain.
        """
        if self.lightcurve is None or self.active_domain != DOMAIN_FLUX:
            return None
        return self.lightcurve.get('flux_err')

    @property
    def mag(self):
        """Gets the magnitude values series when ``active_domain`` is ``'mag'``.

        Returns:
            pandas.Series or None: Magnitude values, or None if stored in flux domain.
        """
        if self.lightcurve is None or self.active_domain != DOMAIN_MAG:
            return None
        return self.lightcurve.get('mag')

    @property
    def mag_err(self):
        """Gets the magnitude error series when ``active_domain`` is ``'mag'``.

        Returns:
            pandas.Series or None: Magnitude errors, or None if stored in flux domain.
        """
        if self.lightcurve is None or self.active_domain != DOMAIN_MAG:
            return None
        return self.lightcurve.get('mag_err')

    def _phot_for_minimum_search(self):
        """Returns photometry values oriented so that minima correspond to eclipses.

        Returns:
            pandas.Series: Values where lower means deeper eclipse regardless of domain.
        """
        phot = self.phot
        if phot is None:
            raise PipeException('No photometry available for minimum search.')
        if self.active_domain == DOMAIN_MAG:
            return -phot
        return phot

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
        y = self._phot_for_minimum_search()
        phase_of_min = self.lightcurve['phase'][np.argmin(y)]
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
        x = self.lightcurve['phase']
        y = self._phot_for_minimum_search()
        y = y.max() - y
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
        if table_format == 'votable':
            raise PipeException(
                'Standards-compliant VOTable export must use lc_bridge.export_curvedash().'
            )
        tab = Table.from_pandas(self.lightcurve)
        if self.active_domain == DOMAIN_FLUX and 'flux' in tab.colnames:
            tab['flux'].unit = self.flux_unit_ap
            tab['flux_err'].unit = self.flux_unit_ap
        elif self.active_domain == DOMAIN_MAG and 'mag' in tab.colnames:
            tab['mag'].unit = u.mag
            tab['mag_err'].unit = u.mag
        timescale = self.timescale if self.timescale != 'hjd' else None

        phot_cols = (
            ['jd', 'phase', 'mag', 'mag_err', 'label']
            if self.active_domain == DOMAIN_MAG
            else ['jd', 'phase', 'flux', 'flux_err', 'label']
        )
        if (table_format == 'pandas.json' or table_format == 'fits'
                or table_format in self._format_dict_dat):
            selected_columns = phot_cols
        else:
            tab['time'] = Time(tab['jd'], format='jd', scale=timescale)
            selected_columns = ['time', 'phase'] + phot_cols[2:]

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
        if self.active_domain != other.active_domain:
            raise PipeException(
                f'Cannot append lightcurves with different domains '
                f'({self.active_domain} vs {other.active_domain}).'
            )
        if (self.lightcurve is None) or self.lightcurve.empty:
            self.lightcurve = other.lightcurve.copy()
        elif not other.lightcurve.empty:
            self.lightcurve = pd.concat([self.lightcurve, other.lightcurve], ignore_index=True)
