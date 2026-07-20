"""Virtual Observatory (VO) Lightcurve Parsing and Formatting Module.

This module provides tools, classes, and helper functions to ingest, parse, and format
astronomical lightcurve data files complying with VO standards (e.g., VOTable) or
heuristic text/ASCII formats. It implements data models for coordinate systems (CooSys),
time systems (TimeSys), and photometric calibrations (PhotDM, PhotCal, PhotometryFilter)
and facilitates unit-safe conversions between astronomical magnitudes and fluxes.
"""

import io
import re
import numpy as np
import astropy.units as u
from astropy.table import Table
from astropy.table import MaskedColumn
from astropy.io.votable import is_votable
from astropy.io import ascii

from gavo.votable import votparse

import logging

logger = logging.getLogger(__name__)


class PhotometryFilter:
    """Represents a photometric filter with its identifier and physical spectral location.

    This class corresponds to IVOA photDM:PhotometryFilter data model component, which
    is used to describe a bandpass/filter in astronomical observations.
    """

    def __init__(self, filter_id=None, spectral_location=None, spectral_location_unit: str = None):
        """Initialises a PhotometryFilter instance.

        Args:
            filter_id (str, optional): The unique identifier for the filter. Defaults to None.
            spectral_location (float or astropy.units.Quantity, optional): The physical
                spectral location (e.g., central wavelength) of the filter. Defaults to None.
            spectral_location_unit (str, optional): The physical unit of the spectral
                location (e.g., 'nm', 'AA', 'um') if spectral_location is not already
                an astropy.units.Quantity. Defaults to None.
        """
        self._filter_id = filter_id  # photDM:PhotometryFilter.identifier

        # Build the physical quantity
        if spectral_location is None:
            self.spectral_location = None
        else:
            if isinstance(spectral_location, u.Quantity):
                self.spectral_location = spectral_location
            else:
                # Pair the value with the unit (defaulting to dimensionless if None)
                unit = u.dimensionless_unscaled
                if spectral_location_unit is not None:
                    try:
                        unit = u.Unit(spectral_location_unit)
                    except Exception as e:
                        logger.warning(f'Inappropriate spectral_location_unit {spectral_location_unit}: {type(e)}')

                self.spectral_location = spectral_location * unit
        # todo: blah-blah-blah

    @property
    def filter_id(self):
        """Gets or sets the filter identifier.

        Returns:
            str: The filter identifier.
        """
        return self._filter_id

    @filter_id.setter
    def filter_id(self, value):
        if not isinstance(value, str):
            raise ValueError("Filter ID must be a string.")
        self._filter_id = value.strip()

    def __repr__(self):
        return (f"<PhotometryFilter: filter_id={self.filter_id} "
                f"spectralLocation={self.spectral_location}>")


class PhotCal:
    """Represents the photometric calibration metadata.

    This class handles zero-point values for magnitude and flux, and defines the magnitude
    system (e.g., Vega). It facilitates unit-safe conversions between magnitudes and fluxes.
    """

    def __init__(self, zp_flux=1.0, zp_flux_unit=None, zp_mag=0.0, zp_mag_unit=None, mag_sys="Vega"):
        """Initialises a PhotCal instance with zero points.

        Args:
            zp_flux (float or astropy.units.Quantity, optional): Zero-point flux value.
                Defaults to 1.0.
            zp_flux_unit (str or astropy.units.Unit, optional): Unit for the zero-point flux.
                Defaults to None (which results in dimensionless).
            zp_mag (float or astropy.units.Quantity, optional): Zero-point magnitude value.
                Defaults to 0.0.
            zp_mag_unit (str or astropy.units.Unit, optional): Unit for the zero-point magnitude.
                Defaults to None (which defaults to magnitude 'mag').
            mag_sys (str, optional): The magnitude system used (e.g., 'Vega', 'AB').
                Defaults to "Vega".
        """
        # zp_flux, unit-aware. # photDM:PhotCal.zeroPoint.flux.value
        if isinstance(zp_flux, u.Quantity):
            self._zp_flux = zp_flux
        else:
            unit = u.dimensionless_unscaled
            if zp_flux_unit:
                try:
                    unit = u.Unit(zp_flux_unit)
                except Exception as e:
                    logger.warning(f"Invalid zp_flux_unit '{zp_flux_unit}': {type(e)}")
            self._zp_flux = zp_flux * unit

        # zp_mag  photDM:PhotCal.zeroPoint.referenceMagnitude.value
        # Here. I hope, I can guess the default ;-)
        if isinstance(zp_mag, u.Quantity):
            self._zp_mag = zp_mag
        else:
            m_unit = u.mag
            if zp_mag_unit:
                try:
                    m_unit = u.Unit(zp_mag_unit)
                except Exception as e:
                    logger.warning(f"Invalid zp_mag_unit '{zp_mag_unit}': {type(e)}")
            self._zp_mag = zp_mag * m_unit

        self._mag_sys = mag_sys  # photDM:PhotCal.magnitudeSystem.type

        # todo: add stuff like ZeroPoint.type ({0=Pogson, 1=Asinh, 2=Linear} ), units etc .......

    @property
    def zp_flux(self):
        """Gets or sets the zero-point flux.

        Returns:
            astropy.units.Quantity: The zero-point flux with its unit.
        """
        return self._zp_flux

    @zp_flux.setter
    def zp_flux(self, value):
        if not isinstance(value, (int, float, np.number)):
            raise ValueError("Zero point flux must be a number.")
        self._zp_flux = float(value)

    @property
    def zp_mag(self):
        """Gets or sets the zero-point magnitude.

        Returns:
            astropy.units.Quantity: The zero-point magnitude with its unit.
        """
        return self._zp_mag

    @zp_mag.setter
    def zp_mag(self, value):
        if not isinstance(value, (int, float, np.number)):
            raise ValueError("Zero point magnitude must be a number.")
        self._zp_mag = float(value)

    @property
    def mag_sys(self):
        """Gets or sets the magnitude system name.

        Returns:
            str: The magnitude system type.
        """
        return self._mag_sys

    @mag_sys.setter
    def mag_sys(self, value):
        # Example validation: ensure it's a string and capitalized
        if not isinstance(value, str):
            raise ValueError("Magnitude system must be a string.")
        self._mag_sys = value.strip()

    def mag_to_flux(self, mag):
        """Converts an astronomical magnitude to flux (instrumental or calibratied flux density).

        The computation is performed using unit-safe astropy quantities.

        Args:
            mag (astropy.units.Quantity): The magnitude to be converted.

        Returns:
            astropy.units.Quantity: The computed flux

        Raises:
            astropy.units.UnitsError: If the input magnitude's unit is incompatible with
                the calibrated zero-point magnitude unit.
        """
        if mag.unit is None or not mag.unit.is_equivalent(self._zp_mag.unit):
            raise u.UnitsError(
                f"magnitude column unit[{mag.unit}] and zero_point unit[{self._zp_mag.unit}] must match"
            )
        mag_zp = mag.to(self._zp_mag.unit)
        delta_mag = (mag_zp - self._zp_mag).to_value(self._zp_mag.unit)
        return self._zp_flux * 10 ** (-0.4 * delta_mag)

    def flux_to_mag(self, flux):
        """Converts flux to an astronomical magnitude.

        The computation is performed using unit-safe astropy quantities.

        Args:
            flux (astropy.units.Quantity): The flux density to be converted.

        Returns:
            astropy.units.Quantity: The computed astronomical magnitude.

        Raises:
            astropy.units.UnitsError: If the input flux's unit is incompatible with
                the calibrated zero-point flux unit.
        """
        if flux.unit is None or not flux.unit.is_equivalent(self._zp_flux.unit):
            raise u.UnitsError(
                f"flux column unit[{flux.unit}] and zero_point unit[{self._zp_flux.unit}] must match"
            )
        flux_zp = flux.to(self._zp_flux.unit)
        ratio = (flux_zp / self._zp_flux).to_value(u.dimensionless_unscaled)
        return self._zp_mag - 2.5 * np.log10(ratio) * self._zp_mag.unit

    def mag_err_to_flux_err(self, mag, mag_err):
        """Propagates magnitude uncertainties to flux using ``mag_to_flux``.

        For the Pogson relation implemented in ``mag_to_flux``, the flux uncertainty is
        ``|dF/dm| * sigma_m`` with ``|dF/dm| = 0.4 ln(10) F``.

        Args:
            mag (astropy.units.Quantity): Magnitude values.
            mag_err (astropy.units.Quantity): Magnitude uncertainties (equivalent to mag).

        Returns:
            astropy.units.Quantity: Flux uncertainties in the zero-point flux unit.

        Raises:
            astropy.units.UnitsError: If magnitude or uncertainty units are incompatible.
        """
        flux = self.mag_to_flux(mag)
        pogson_slope = 0.4 * np.log(10.0)
        if mag_err.unit is None or not mag_err.unit.is_equivalent(self._zp_mag.unit):
            raise u.UnitsError(
                f"magnitude error unit[{mag_err.unit}] and zero_point unit[{self._zp_mag.unit}] must match"
            )
        mag_err_zp = mag_err.to(self._zp_mag.unit)
        sigma_m = mag_err_zp.to_value(self._zp_mag.unit)
        return np.abs(flux * pogson_slope * sigma_m)

    def flux_err_to_mag_err(self, flux, flux_err):
        """Propagates flux uncertainties to magnitude using the ``flux_to_mag`` derivative.

        For the Pogson relation implemented in ``flux_to_mag``, the magnitude uncertainty is
        ``|dm/dF| * sigma_F`` with ``|dm/dF| = 2.5 / (F ln 10)``.

        Args:
            flux (astropy.units.Quantity): Flux values.
            flux_err (astropy.units.Quantity): Flux uncertainties (same unit as ``flux``).

        Returns:
            astropy.units.Quantity: Magnitude uncertainties.

        Raises:
            astropy.units.UnitsError: If flux or uncertainty units are incompatible.
        """
        if flux.unit is None or not flux.unit.is_equivalent(self._zp_flux.unit):
            raise u.UnitsError(
                f"flux column unit[{flux.unit}] and zero_point unit[{self._zp_flux.unit}] must match"
            )
        flux_zp = flux.to(self._zp_flux.unit)
        if flux_err.unit is None or not flux_err.unit.is_equivalent(self._zp_flux.unit):
            raise u.UnitsError(
                f"flux error unit[{flux_err.unit}] and zero_point unit[{self._zp_flux.unit}] must match"
            )
        err_zp = flux_err.to(self._zp_flux.unit)
        ln10 = np.log(10.0)
        ratio = (err_zp / flux_zp).to_value(u.dimensionless_unscaled)
        return (2.5 / ln10) * np.abs(ratio) * self._zp_mag.unit

    def __repr__(self):
        return (f"<PhotCal zeroPoint.referenceMagnitude={self.zp_mag}: "
                f"zeroPoint.flux={self.zp_flux} "
                f"magnitudeSystem={self.mag_sys}>")


class PhotDM:
    """Photometry Data Model (photDM) hub combining filter and calibration information.

    Acts as a container linking a specific `PhotometryFilter` and its `PhotCal` calibration.
    """

    def __init__(self, photcal: PhotCal = None, photometry_filter: PhotometryFilter = None):
        """Initialises a PhotDM instance.

        Args:
            photcal (PhotCal, optional): The photometric calibration zero points.
                Defaults to None.
            photometry_filter (PhotometryFilter, optional): The photometric filter
                associated with this data model. Defaults to None.
        """
        self.photcal = photcal
        self.filter = photometry_filter
        # todo: blah-blah-blah

    @property
    def filter_id(self):
        """Gets or sets the filter identifier shortcut.

        Returns:
            str: The identifier of the filter, or "Unknown" if no filter is set.
        """
        return self.filter.filter_id if self.filter else "Unknown"

    @filter_id.setter
    def filter_id(self, value):
        self.filter.filter_id = value

    @property
    def mag0(self):
        """Gets or sets the zero-point magnitude shortcut.

        Returns:
            astropy.units.Quantity or float: The zero-point magnitude of the calibration,
                or 0.0 if no calibration is set.
        """
        return self.photcal.zp_mag if self.photcal else 0.0

    @mag0.setter
    def mag0(self, value):
        self.photcal.zp_mag = value

    def __repr__(self):
        # f_id = self.filter_id
        # sys = self.photcal.mag_sys if self.photcal else "None"
        # return f"<PhotDM Filter={f_id} Sys={sys}>"
        return f"<PhotDM Filter={self.filter} photcal={self.photcal}>"


class CooSys:
    """Represents a coordinate system reference frame for spatial coordinates.

    Used to model VOTable ``<COOSYS>`` metadata (reference frame and epoch).
    """

    def __init__(self, *, epoch=None, system='ICRS', coosys_id='system'):
        """Initialises a CooSys instance.

        Args:
            epoch (float, int, or str, optional): Reference epoch of the coordinates
                (e.g. proper-motion epoch for Gaia). ``None`` when the source VOTable
                omits ``COOSYS/@epoch``.
            system (str, optional): Reference coordinate system/frame. Defaults to ``ICRS``.
            coosys_id (str, optional): VOTable ``COOSYS/@ID`` value. Defaults to ``system``.
        """
        self.epoch = epoch
        self.system = system
        self.coosys_id = coosys_id

    def __repr__(self):
        return f"<CooSys id={self.coosys_id} epoch={self.epoch}: system={self.system}>"


class TimeSys:
    """Represents a time system standard for astronomical timing metadata.

    Captures reference position, origin (such as JD0/MJD0 offset), and timescale.
    """

    def __init__(self, refposition='HELIOCENTER', timeorigin=0.0, timescale='UTC'):
        """Initialises a TimeSys instance.

        Args:
            refposition (str, optional): Time reference position (e.g., 'HELIOCENTER',
                'BARYCENTER'). Defaults to 'HELIOCENTER'.
            timeorigin (float, optional): The origin offset of the time scale, i.e.,
                the JD0 or MJD0 value. Defaults to 0.0.
            timescale (str, optional): The timing scale used (e.g., 'UTC', 'TDB', 'TCB').
                Defaults to 'UTC'.
        """
        self.refposition = refposition  # HELIOCENTER OR BARYCENTER ...
        self.timeorigin = timeorigin  # JD0, f.e. 2400000.5
        self.timescale = timescale  # UTC, TCB, TBD etc

    @property
    def jd0(self):
        """Gets the reference time origin (JD0 offset).

        Returns:
            float: The reference time origin value.
        """
        return self.timeorigin

    def __repr__(self):
        return f"<TimeSys: timescale={self.timescale} refposition={self.refposition} timeorigin={self.timeorigin}>"


def _apply_gavo_votable_metadata(volc_instance, gavo_tree) -> None:
    """Populates TIMESYS, COOSYS, and PhotDM metadata from a GAVO VOTable tree.

    Args:
        volc_instance (VOLightCurve): Target instance to mutate in place.
        gavo_tree: GAVO stanxml root returned by ``votparse.readRaw``.
    """
    from skvo_veb.volightcurve.time_reference import extract_timesys_metadata_from_gavo

    ts_meta = extract_timesys_metadata_from_gavo(gavo_tree)
    volc_instance.timesys_by_id = ts_meta.registry
    volc_instance.field_timesys_ref = ts_meta.field_refs
    volc_instance.param_timesys_ref = ts_meta.param_refs
    volc_instance.timesys = ts_meta.default_timesys
    volc_instance.coosys = extract_coosys(gavo_tree)
    volc_instance.photdms = extract_photdm(gavo_tree)


def extract_photdm(tree):
    """GAVO tree walker for IVOA PhotDM ``photcal`` GROUP metadata.

    Traverses a GAVO-parsed VOTable tree and resolves photometric calibration
    groups linked to photometry columns. Handles inline ``PARAM`` entries and
    ``PARAMref`` indirection (the pattern used by modern VO publishers such as
    DaCHS/UPJS TAP services).

    Args:
        tree: The GAVO VOTable tree node/element to parse.

    Returns:
        dict: A mapping of target column references (strings) to PhotDM instances.
    """
    id_map = {}

    def map_ids(node, text, attrs, childIter):
        node_id = getattr(node, "id", None) or getattr(node, "ID", None)
        if node_id: id_map[node_id] = node
        for child in childIter:
            if hasattr(child, 'apply'): child.apply(map_ids)

    tree.apply(map_ids)

    dm_map = {}

    UT_FLUX = "photDM:PhotCal.zeroPoint.flux.value"
    UT_MAG = "photDM:PhotCal.zeroPoint.referenceMagnitude.value"
    UT_MAG_SYS = "photDM:PhotCal.magnitudeSystem.type"
    UT_FILTER = "photDM:PhotometryFilter.identifier"
    UT_FILTER_SPEC = "photDM:PhotometryFilter.spectralLocation.value"

    # todo: extend this list

    def process_group(node, text, attrs, childIter):
        if node.name_ == 'GROUP' and getattr(node, "name", None) == "photcal":
            # arguments of PhotCal.__init__
            cal_params = {'zp_flux': 1.0, 'zp_mag': 0.0, 'zp_mag_unit': 'mag', 'zp_flux_unit': None}
            # these are arguments of the PhotomeryPilter.__init__
            filter_params = {'filter_id': '', 'spectral_location': 0.0, 'spectral_location_unit': None}
            # filter_id = ''
            # filter_spec = None
            # filter_spec_unit = None
            target_col = None
            for child in childIter:
                # Logic for PARAM and PARAMref
                target_param = None
                # Note: we should always look for the utype on the child (the reference) first!
                # The referenced parameter may have another utype
                role_utype = (getattr(child, "utype", None) or "").lower()

                if child.name_ == 'PARAM':
                    target_param = child
                elif child.name_ == 'PARAMref':
                    target_param = id_map.get(getattr(child, "ref", None))
                elif child.name_ == 'FIELDref':
                    target_col = getattr(child, "ref", None)

                if target_param is not None:
                    # If the reference (child) didn't have utype,
                    # use the parameter's own utype (so, I do not like this case)
                    ut = role_utype or (getattr(target_param, "utype", None) or "").lower()

                    if ut == UT_FLUX.lower():
                        cal_params['zp_flux'] = float(target_param.value)
                        cal_params['zp_flux_unit'] = getattr(target_param, "unit", None)
                    elif ut == UT_MAG.lower():
                        cal_params['zp_mag'] = float(target_param.value)
                        cal_params['zp_mag_unit'] = target_param.unit
                    elif ut == UT_MAG_SYS.lower():
                        cal_params['mag_sys'] = target_param.value
                    elif ut == UT_FILTER.lower():
                        filter_params['filter_id'] = target_param.value
                    elif ut == UT_FILTER_SPEC.lower():
                        filter_params['spectral_location'] = float(target_param.value)
                        filter_params['spectral_location_unit'] = getattr(target_param, "unit", None)

            if target_col:
                phot_filter = PhotometryFilter(**filter_params)
                # filter_id=filter_id, spectral_location=filter_spec, spectral_location_unit=filter_spec_unit)
                photcal = PhotCal(**cal_params)
                # calibrations[target_col] = PhotCal(**params)
                # Assign the DM hub to the column name
                dm_map[target_col] = PhotDM(photcal=photcal, photometry_filter=phot_filter)

        # Recursive walk
        for child in childIter:
            if hasattr(child, 'apply'): child.apply(process_group)

    tree.apply(process_group)
    return dm_map


def _gavo_votable_tree_from_source(file_path):
    """Parses a VOTable byte stream into a GAVO stanxml tree.

    Args:
        file_path (str or file-like): Path or stream containing VOTable bytes.

    Returns:
        GAVO stanxml tree root for metadata walkers.
    """
    if hasattr(file_path, "seek"):
        file_path.seek(0)
        return votparse.readRaw(file_path)
    with open(file_path, "rb") as handle:
        return votparse.readRaw(handle)


def extract_timesys(tree):
    """GAVO tree walker for the default ``TIMESYS`` metadata block.

    Args:
        tree: The GAVO VOTable tree node/element to parse.

    Returns:
        TimeSys: The first ``TIMESYS`` element in document order, or an empty default.
    """
    from skvo_veb.volightcurve.time_reference import extract_timesys_metadata_from_gavo

    return extract_timesys_metadata_from_gavo(tree).default_timesys


def extract_coosys(tree):
    """GAVO tree walker for IVOA ``COOSYS`` metadata.

    Preserves absent ``@epoch`` attributes as ``None`` rather than inventing a
    default proper-motion epoch.

    Args:
        tree: The GAVO VOTable tree node/element to parse.

    Returns:
        CooSys or None: Populated coordinate-system metadata when present.
    """
    data = {"coosys_id": "system", "epoch": None, "system": None}

    def find_cs(node, text, attrs, childIter):
        if node.name_ == "COOSYS":
            data["coosys_id"] = attrs.get("ID", "system")
            data["system"] = attrs.get("system")
            epoch = attrs.get("epoch")
            if epoch is not None:
                try:
                    data["epoch"] = float(epoch)
                except (TypeError, ValueError):
                    data["epoch"] = epoch
        for child in childIter:
            if hasattr(child, "apply"):
                child.apply(find_cs)

    tree.apply(find_cs)
    if not data["system"]:
        return None
    return CooSys(
        coosys_id=data["coosys_id"],
        system=data["system"],
        epoch=data["epoch"],
    )


def find_columns_by_ucd(table, ucd_fragment):
    """Retrieves all column names from an Astropy table that contain the specified UCD fragment.

    Args:
        table (astropy.table.Table): The table to search.
        ucd_fragment (str): The Unified Content Descriptor (UCD) substring/fragment to look for.

    Returns:
        list of str: A list of column names containing the given UCD fragment in their metadata.
    """
    matches = []
    for colname in table.colnames:
        col_ucd = table[colname].info.meta.get('ucd', '') if table[colname].info.meta else ''
        if ucd_fragment in col_ucd:
            matches.append(colname)
    return matches


def get_time_colnames(table):
    """Retrieves names of columns containing time epoch data from the table.

    Args:
        table (astropy.table.Table): The table to search.

    Returns:
        list of str: Column names matching time epoch UCDs (e.g., 'time.epoch').
    """
    return find_columns_by_ucd(table, 'time.epoch')


def get_mag_colnames(table):
    """Retrieves names of columns containing primary magnitudes from the table, excluding error columns.

    Args:
        table (astropy.table.Table): The table to search.

    Returns:
        list of str: Column names matching magnitude UCDs (e.g., 'phot.mag') that do not represent errors.
    """
    # Returns primary magnitudes, excludes errors
    all_mags = find_columns_by_ucd(table, 'phot.mag')
    return [c for c in all_mags if 'stat.error' not in table[c].info.meta.get('ucd', '')]


def get_flux_colnames(table):
    """Retrieves names of columns containing primary fluxes from the table, excluding error columns.

    Args:
        table (astropy.table.Table): The table to search.

    Returns:
        list of str: Column names matching flux UCDs (e.g., 'phot.flux') that do not represent errors.
    """
    all_flux = find_columns_by_ucd(table, 'phot.flux')
    return [c for c in all_flux if 'stat.error' not in table[c].info.meta.get('ucd', '')]


def is_mag_column(table: Table, colname: str | None):
    """Checks whether the specified column in the table is a magnitude column.

    Args:
        table (astropy.table.Table): The table containing the column.
        colname (str, optional): The column name to check.

    Returns:
        bool: True if the column is a magnitude column, False otherwise or if colname is None.
    """
    if colname is None: return False
    return 'phot.mag' in table[colname].info.meta.get('ucd', '')


def is_flux_column(table: Table, colname: str | None):
    """Checks whether the specified column in the table is a flux column.

    Args:
        table (astropy.table.Table): The table containing the column.
        colname (str, optional): The column name to check.

    Returns:
        bool: True if the column is a flux column, False otherwise or if colname is None.
    """
    if colname is None: return False
    return 'phot.flux' in table[colname].info.meta.get('ucd', '')


def get_error_colnames(table, base_ucd=None):
    """Retrieves names of columns containing statistical errors from the table.

    If a base UCD is specified, narrows down to error columns associated with that base UCD.

    Args:
        table (astropy.table.Table): The table to search.
        base_ucd (str, optional): The base UCD (e.g., 'phot.mag', 'phot.flux') to filter errors by.
            Defaults to None.

    Returns:
        list of str: Column names matching the statistical error UCD and optional base UCD.
    """
    errors = find_columns_by_ucd(table, 'stat.error')
    if base_ucd:
        return [c for c in errors if base_ucd in table[c].info.meta.get('ucd', '')]
    return errors


def is_magnitude_phot_column(table: Table, colname: str = "phot") -> bool:
    """Detects whether a ``phot`` column holds magnitudes rather than flux.

    Uses column unit and UCD metadata following VO photometry conventions.

    Args:
        table (astropy.table.Table): Source table.
        colname (str): Photometry column name.

    Returns:
        bool: True when the column represents magnitudes.
    """
    if colname not in table.colnames:
        return False
    col = table[colname]
    if col.unit is not None:
        try:
            if col.unit.is_equivalent(u.mag):
                col.unit.to(u.mag)
                return True
        except (u.UnitsError, u.UnitTypeError, TypeError, ValueError):
            pass
    ucd = (col.info.meta or {}).get("ucd", "")
    if "phot.mag" in ucd:
        return True
    if "phot.flux" in ucd:
        return False
    return False


def assign_photometry_column_semantics(
    table: Table,
    phot_col: str = "phot",
    error_col: str | None = "flux_error",
    *,
    force_magnitude: bool | None = None,
) -> Table:
    """Assigns VO UCD metadata to generic ``phot`` and error columns.

    Args:
        table (astropy.table.Table): Export or upload table to annotate.
        phot_col (str): Primary photometry column name.
        error_col (str, optional): Uncertainty column name.
        force_magnitude (bool, optional): Override automatic domain detection.

    Returns:
        astropy.table.Table: The same table with UCD metadata updated in place.
    """
    if phot_col not in table.colnames:
        return table
    is_mag = force_magnitude if force_magnitude is not None else is_magnitude_phot_column(table, phot_col)
    phot_ucd = "phot.mag" if is_mag else "phot.flux;em.opt"
    err_ucd = "stat.error;phot.mag" if is_mag else "stat.error;phot.flux;em.opt"
    if table[phot_col].info.meta is None:
        table[phot_col].info.meta = {}
    table[phot_col].info.meta["ucd"] = phot_ucd
    if error_col and error_col in table.colnames:
        if table[error_col].info.meta is None:
            table[error_col].info.meta = {}
        table[error_col].info.meta["ucd"] = err_ucd
    return table


def resolve_votable_phot_field_labels(table: Table, phot_col: str = "phot", error_col: str = "flux_error") -> dict:
    """Returns VOTable field UCDs and descriptions for a ``phot`` column.

    Args:
        table (astropy.table.Table): Export table containing ``phot``.
        phot_col (str): Photometry column name.
        error_col (str): Uncertainty column name.

    Returns:
        dict: Keys ``phot_ucd``, ``error_ucd``, ``phot_description``, ``error_description``.
    """
    is_mag = is_magnitude_phot_column(table, phot_col)
    if is_mag:
        return {
            "phot_ucd": "phot.mag",
            "error_ucd": "stat.error;phot.mag",
            "phot_description": "Photometry (magnitude)",
            "error_description": "Statistical uncertainty of magnitude",
        }
    return {
        "phot_ucd": "phot.flux;em.opt",
        "error_ucd": "stat.error;phot.flux;em.opt",
        "phot_description": "Photometry (flux)",
        "error_description": "Statistical uncertainty of flux",
    }


def _promote_to_vo_standards(table):
    """Heuristically assigns Unified Content Descriptors (UCDs) and physical units to table columns.

    This function scans column names for common patterns (e.g., 'mag', 'flux', 'time')
    and assigns appropriate Astropy units and UCD metadata values without renaming columns.

    Args:
        table (astropy.table.Table): The table to process.

    Returns:
        astropy.table.Table: The table with updated column units and UCD metadata.
    """
    for colname in table.colnames:
        col = table[colname]
        name_low = colname.lower()
        if not col.unit:
            if 'mag' in name_low:
                col.unit = u.mag
            elif 'flux' in name_low:
                # col.unit = u.Jy  # default assumption
                col.unit = 'electron s-1'  # default assumption
            elif any(k in name_low for k in ['time', 'jd', 'mjd']):
                col.unit = u.d

        if not col.info.meta or not col.info.meta.get('ucd'):
            if col.info.meta is None:
                col.info.meta = {}
            if name_low == 'phot':
                ucd = 'phot.mag' if is_magnitude_phot_column(table, colname) else 'phot.flux;em.opt'
            elif 'mag' in name_low:
                ucd = 'phot.mag'
            elif 'flux' in name_low:
                ucd = 'phot.flux'
            elif any(k in name_low for k in ['time', 'jd', 'mjd']):
                ucd = 'time.epoch'
            else:
                continue

            if any(k in name_low for k in ['err', 'uncert', 'sigma']) and name_low != 'phot':
                ucd = f"stat.error;{ucd}"
            col.info.meta['ucd'] = ucd
    return table


def _pickup_jd0_from_table(table):
    """Parses metadata comments to locate the time origin value (JD0).

    Searches the table comments for patterns like "JD0 = value".

    Args:
        table (astropy.table.Table): The table to scan.

    Returns:
        float: The parsed JD0 value if found, or 0.0 otherwise.
    """
    jd0_pattern = re.compile(r"JD0\s*=\s*([+-]?\d*\.?\d+)")
    for line in table.meta.get('comments', []):
        match = jd0_pattern.search(line.upper())
        if match: return float(match.group(1))
    return 0.0


def _pickup_mag0_from_table(table):
    """Parses metadata comments to locate the reference magnitude zero point (MAG0).

    Searches the table comments for patterns like "MAG0 = value".

    Args:
        table (astropy.table.Table): The table to scan.

    Returns:
        float: The parsed MAG0 value if found, or 0.0 otherwise.
    """
    jd0_pattern = re.compile(r"MAG0\s*=\s*([+-]?\d*\.?\d+)")
    for line in table.meta.get('comments', []):
        match = jd0_pattern.search(line.upper())
        if match: return float(match.group(1))
    return 0.0


def _pickup_filter_from_table(table):
    """Scans the table comments for filter/band identification.

    Matches comments containing patterns like: FILTER=Gaia_G.v2 or BAND = r.

    Args:
        table (astropy.table.Table): The table to scan.

    Returns:
        str: The extracted filter name or identifier if found, otherwise "Unknown".
    """
    # Matches alphanumeric, dots, underscores, and dashes after the '='
    filter_pattern = re.compile(r"(?:FILTER|BAND)\s*=\s*([\w\.\-]+)")

    for line in table.meta.get('comments', []):
        match = filter_pattern.search(line.upper())
        if match:
            # We return the original case from the line, not the upper() version
            # so 'Gaia_G' doesn't become 'GAIA_G'
            actual_line = line.split('=')[-1].strip()
            return actual_line.split()[0]  # Take first word to avoid trailing comments

    return "Unknown"


def _recover_lc_colnames(table):
    """Strictly renames columns for unlabelled 'colN' tables based on comments or positional fallback.

    Requires a comment line to have exactly the same number of whitespace-separated 
    words as the table has columns to be considered a valid header. Otherwise, applies 
    a rigid positional fallback: column 1 becomes 'obs_time', column 2 'mag', column 3 'mag_err'.

    Args:
        table (astropy.table.Table): The table whose columns are to be renamed.

    Returns:
        astropy.table.Table: The renamed table.
    """
    comments = table.meta.get('comments', [])
    num_cols = len(table.colnames)
    found_header = None

    # Look into the comments
    for line in comments:
        # Remove #, strip, and split into words
        parts = line.strip().lstrip('#').strip().split()

        # STRICT CHECK: Word count must equal Column count
        if len(parts) == num_cols:
            found_header = parts
            break

    # Apply names
    for i, colname in enumerate(table.colnames):
        if found_header:
            new_name = found_header[i]
        else:
            # RIGID POSITIONAL FALLBACK
            if i == 0:
                new_name = 'obs_time'
            elif i == 1:
                new_name = 'mag'
            elif i == 2:
                new_name = 'mag_err'
            else:
                new_name = f'col{i + 1}'

        if colname != new_name:
            table.rename_column(colname, new_name)
    return table


class VOLightCurve:
    """Represents a Virtual Observatory (VO) lightcurve container.

    Encapulates an Astropy Table containing timing and photometric observations,
    along with associated coordinate system, time system, and photometric calibration
    metadata mapped to specific columns. It supports files in both VOTable and ASCII
    heuristic formats.
    """

    def __init__(self, file_path):
        """Initialises a VOLightCurve instance and ingests the specified data file.

        Args:
            file_path (str or file-like object): Path to the input file or an active file-like stream.
        """
        self.file_path = file_path
        self.table = None
        self.timesys = TimeSys()
        self.timesys_by_id: dict[str, TimeSys] = {}
        self.field_timesys_ref: dict[str, str] = {}
        self.param_timesys_ref: dict[str, str | None] = {}
        self.coosys = None
        self.photdms = {}  # maps column_name -> PhotDM instance

        self._ingest(file_path)

    def _ingest(self, file_path):
        """Main ingestion flow that loads and processes the input file.

        Attempts to load the file as a standard VOTable first. Table data and TABLE
        PARAM values are copied with astropy; ``TIMESYS``, ``COOSYS``, and PhotDM
        metadata use GAVO tree walkers. If the file is not a valid VOTable, it
        attempts to read it as a standard tabular file, falling back to ASCII parsing
        and heuristic column recovery based on comments/position.

        Args:
            file_path (str or file-like object): Path to the input file or an active file-like stream.
        """
        try:
            if hasattr(file_path, 'seek'):
                file_path.seek(0)
            
            votable_detected = is_votable(file_path)
            
            if hasattr(file_path, 'seek'):
                file_path.seek(0)

            if votable_detected:
                # The best track:
                self.table = Table.read(file_path, format='votable')
                
                # Copy TABLE PARAM values with astropy; VO metadata via GAVO walkers.
                astropy_success = False
                try:
                    if hasattr(file_path, 'seek'):
                        file_path.seek(0)
                    import astropy.io.votable as vot

                    tree = vot.parse(file_path)
                    first_table = tree.get_first_table()
                    for param in first_table.params:
                        if param.name:
                            self.table.meta[param.name] = param.value

                    gavo_tree = _gavo_votable_tree_from_source(file_path)
                    _apply_gavo_votable_metadata(self, gavo_tree)
                    self.table = _promote_to_vo_standards(self.table)
                    astropy_success = True
                except Exception as e:
                    logger.warning(f"Failed to parse VOTable params and metadata: {e}")

                if astropy_success:
                    return

                # Fallback when TABLE PARAM copy failed but the file is still a VOTable
                try:
                    votable_tree = _gavo_votable_tree_from_source(file_path)

                    self.table = _promote_to_vo_standards(self.table)
                    _apply_gavo_votable_metadata(self, votable_tree)
                    return
                except Exception as e_gavo:
                    logger.warning(f"GAVO metadata parsing also failed: {e_gavo}")
                    raise

            # Try to fix things ...
            if hasattr(file_path, 'seek'):
                file_path.seek(0)
            self.table = Table.read(file_path)
            logger.info(f"We have read {file_path} using Table.read, though it is not the right VOTable")

        except Exception as e:
            logger.warning(f"Standard read failed, trying heuristic ASCII...")
            # print(f"Standard read failed ({e}), trying heuristic ASCII...")
            if hasattr(file_path, 'seek'):
                file_path.seek(0)
            self.table = ascii.read(file_path)
            self.table = _recover_lc_colnames(self.table)

        # Post-process: Tag columns with UCDs/Units
        self.table = _promote_to_vo_standards(self.table)
        # Try to extract metadata
        self.timesys.timeorigin = _pickup_jd0_from_table(self.table)
        heur_filter_id = _pickup_filter_from_table(self.table)
        heur_mag0 = _pickup_mag0_from_table(self.table)

        # put this filter into the photcal and attach photCal to any mag/flux columns
        for colname in self.get_flux_colnames() + self.get_mag_colnames():
            photdm = self.photdms.get(colname, None)

            # todo: sanitise this defaults/zeros/None logic
            if photdm is None:
                new_filter = PhotometryFilter(filter_id=heur_filter_id)
                if heur_mag0:
                    photcal = PhotCal(zp_mag=heur_mag0, zp_mag_unit='mag')
                else:
                    photcal = None
                self.photdms[colname] = PhotDM(photcal=photcal, photometry_filter=new_filter)
            else:
                # If it already existed but had no filter name, update it
                if photdm.filter_id is None:
                    photdm.filter_id = heur_filter_id
                if heur_mag0 is not None:
                    photdm.mag0 = heur_mag0

        # Ensure we have photcal objects for every mag/flux column (even if dummy)
        # self._fill_missing_calibrations()

        # # Update table metadata for storage
        # self.table.meta['jd0'] = self.timesys.jd0
        # self.table.meta['timesys'] = vars(self.timesys)

    def __repr__(self):
        return f"<VOLightCurve: {len(self.table)} rows, {len(self.photdms)} PhotCals, jd0={self.jd0}>"

    def __getitem__(self, key):
        """Allows row/column indexing directly on the underlying Astropy Table.

        Args:
            key (str or int or slice): Key to access columns or rows in the table.

        Returns:
            astropy.table.Column or astropy.table.Row or astropy.table.Table: The requested data.
        """
        return self.table[key]

    def __getattr__(self, name):
        """Allows direct attribute access delegate to the underlying Astropy Table.

        This enables accessing table properties such as 'colnames', 'meta', 'row_groups', etc.
        directly on the VOLightCurve instance.

        Args:
            name (str): The name of the attribute.

        Returns:
            Any: The attribute value from the underlying table.

        Raises:
            AttributeError: If 'table' is not yet initialized or the attribute is not found.
        """
        # Avoid infinite recursion if table isn't initialized yet
        if name == "table":
            raise AttributeError("Table not yet initialized")

        try:
            return getattr(self.table, name)
        except AttributeError:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def __len__(self):
        """Returns the number of rows in the underlying table.

        Returns:
            int: The row count of the table.
        """
        return len(self.table)

    @property
    def jd0(self):
        """Gets the reference time origin (JD0) from the time system metadata.

        Returns:
            float: The reference time origin value.
        """
        # Yes, I realise that I ought to have a set of timesys connected to time columns,
        # but I'm too lazy to implement this (yet)
        return self.timesys.jd0

    def add_flux_column_from_mag(self, mag_col_name, new_col_name=None):
        """Generates and adds a new flux column converted from the specified magnitude column.

        Retrieves the associated PhotCal calibration and performs a unit-safe conversion to 
        physical flux density. If no calibration is available, fills the new column with NaN values.

        Args:
            mag_col_name (str): The name of the source magnitude column in the table.
            new_col_name (str, optional): The name for the newly created flux column. 
                Defaults to None (which yields 'flux_from_<mag_col_name>').

        Returns:
            str: The name of the newly added flux column.
        """

        colname_out = new_col_name or f"flux_from_{mag_col_name}"
        photdm = self.photdms.get(mag_col_name, None)

        if photdm is None or photdm.photcal is None:
            logger.warning(f'No PhotCal for {mag_col_name}. Filling {new_col_name} with None/NaN')
            flux = np.full(len(self.table), np.nan)
            self.table[new_col_name] = MaskedColumn(data=flux, mask=np.isnan(flux))
        else:
            # Unit safety:
            try:
                flux = photdm.photcal.mag_to_flux(self.table[mag_col_name])
            except (u.UnitConversionError, u.UnitTypeError, u.UnitsError, TypeError, ValueError) as e:
                logger.error(f"Unit conversion failed for {mag_col_name} [{self.table[mag_col_name].unit}]: {e}")
                data = np.full(len(self.table), np.nan)
                flux = MaskedColumn(data=data, mask=np.ones(len(data), dtype=bool))

            # Check physical equivalence: Flux Density is power/area/freq (or wavelength)
            ucd = 'phot.flux'
            if hasattr(flux, 'unit') and flux.unit is not None:
                u_flux_nu = u.W / (u.m ** 2 * u.Hz)
                u_flux_lam = u.W / (u.m ** 2 * u.m)
                is_flux_density = False
                for ref_unit in (u_flux_nu, u_flux_lam):
                    if flux.unit.is_equivalent(ref_unit):
                        flux.unit.to(ref_unit)
                        is_flux_density = True
                        break
                if is_flux_density:
                    ucd = 'phot.flux.density'

            self.table[colname_out] = flux
            self.table[colname_out].info.meta = {'ucd': ucd}

            # Link the same DataModel
            self.photdms[colname_out] = photdm

        return colname_out

    def add_mag_column_from_flux(self, flux_col_name, new_col_name='mag_from_flux'):
        """Generates and adds a new magnitude column converted from the specified flux column.

        Retrieves the associated PhotCal calibration and performs a unit-safe conversion to 
        astronomical magnitudes. If no calibration is available, fills the new column with NaN values.

        Args:
            flux_col_name (str): The name of the source flux column in the table.
            new_col_name (str, optional): The name for the newly created magnitude column. 
                Defaults to 'mag_from_flux' (or 'mag_from_<flux_col_name>' if none provided).

        Returns:
            str: The name of the newly added magnitude column.
        """
        colname_out = new_col_name or f"mag_from_{flux_col_name}"
        photdm = self.photdms.get(flux_col_name, None)

        if photdm is None or photdm.photcal is None:
            logger.warning(f'No PhotCal for {flux_col_name}. Filling {new_col_name} with None/NaN')
            mag = np.full(len(self.table), np.nan)
            self.table[new_col_name] = MaskedColumn(data=mag, mask=np.isnan(mag))
        else:
            # Unit safety:
            try:
                mag = photdm.photcal.flux_to_mag(self.table[flux_col_name])
            except (u.UnitConversionError, u.UnitTypeError, u.UnitsError, TypeError, ValueError) as e:
                logger.error(
                    f"Unit conversion failed for {flux_col_name} [{self.table[flux_col_name].unit}]: {e}")
                data = np.full(len(self.table), np.nan)
                mag = MaskedColumn(data=data, mask=np.ones(len(data), dtype=bool))

            # Check physical equivalence: Flux Density is power/area/freq (or wavelength)
            ucd = 'phot.mag'
            self.table[colname_out] = mag
            self.table[colname_out].info.meta = {'ucd': ucd}

            # Link the same DataModel
            self.photdms[colname_out] = photdm

        return colname_out

    def get_time_colnames(self):
        """Retrieves list of table column names containing time data.

        Returns:
            list of str: Column names associated with time coordinate standards.
        """
        return get_time_colnames(self.table)

    def get_mag_colnames(self):
        """Retrieves list of table column names containing primary magnitudes.

        Returns:
            list of str: Column names containing magnitude data.
        """
        return get_mag_colnames(self.table)

    def get_flux_colnames(self):
        """Retrieves list of table column names containing primary fluxes.

        Returns:
            list of str: Column names containing flux data.
        """
        return get_flux_colnames(self.table)

    def get_mag_error_colnames(self):
        """Retrieves list of table column names containing magnitude statistical errors.

        Returns:
            list of str: Column names representing statistical errors on magnitudes.
        """
        return get_error_colnames(self.table, base_ucd='phot.mag')

    def get_flux_error_colnames(self):
        """Retrieves list of table column names containing flux statistical errors.

        Returns:
            list of str: Column names representing statistical errors on fluxes.
        """
        return get_error_colnames(self.table, base_ucd='phot.flux')

    def write_votable(
        self,
        output_stream_or_path,
        table_name: str,
        filter_identifier: str,
        refposition: str = "HELIOCENTER",
        timescale: str = "UTC", # could we reasonable presume this for old-fashioned handmade scripts?
        timeorigin: float = 0,
        votable_description: str | None = None,
        creator: str | None = None,
        zero_point_flux: float | None = None,
        # zero_point_flux_unit: str = "Jy", #    No assumption about calibrated things
        zero_point_flux_unit: str = "",
        zero_point_ref_mag: float | None = None,
        zero_point_ref_mag_unit: str = "mag",
        magnitude_system: str = "Vega",
        effective_wavelength: float | None = None,
        effective_wavelength_unit: str = "m",
        table_description: str | None = None,
        ra: float | None = None,
        dec: float | None = None,
        filter_name: str | None = None,
        period: float | None = None,
        epoch: float | None = None,
        binary: bool = True,
        coosys_id: str = "system",
        coosys_system: str | None = None,
        coosys_epoch: float | str | None = None,
        publication_id: str | None = None,
    ):
        """Writes this lightcurve to a compliant IVOA VOTable XML file.

        Refer to `write_vo_lightcurve` for detailed argument descriptions.
        """
        write_kwargs = dict(
            output_stream_or_path=output_stream_or_path,
            table_data=self.table,
            table_name=table_name,
            filter_identifier=filter_identifier,
            refposition=refposition,
            timescale=timescale,
            timeorigin=timeorigin,
            votable_description=votable_description,
            creator=creator,
            zero_point_flux=zero_point_flux,
            zero_point_flux_unit=zero_point_flux_unit,
            zero_point_ref_mag=zero_point_ref_mag,
            zero_point_ref_mag_unit=zero_point_ref_mag_unit,
            magnitude_system=magnitude_system,
            effective_wavelength=effective_wavelength,
            effective_wavelength_unit=effective_wavelength_unit,
            table_description=table_description,
            ra=ra,
            dec=dec,
            filter_name=filter_name,
            period=period,
            epoch=epoch,
            binary=binary,
        )
        if self.coosys is not None:
            write_kwargs.update(
                coosys_id=self.coosys.coosys_id,
                coosys_system=self.coosys.system,
                coosys_epoch=self.coosys.epoch,
            )
        elif coosys_system is not None:
            write_kwargs.update(
                coosys_id=coosys_id,
                coosys_system=coosys_system,
                coosys_epoch=coosys_epoch,
            )
        if publication_id is not None:
            write_kwargs["publication_id"] = publication_id
        return write_vo_lightcurve(**write_kwargs)



def _repair_votable_xml_char_param_ampersands(payload: bytes) -> bytes:
    """Corrects double-escaped ampersands in astropy VOTable XML char PARAM values.

    Astropy 6.x may serialise ``&`` in char PARAM ``value`` attributes as
    ``&amp;amp;`` instead of ``&amp;``. Archives and VO clients expect a single
    XML escape (e.g. bibcodes containing ``A&A``).

    Args:
        payload (bytes): Raw VOTable XML document bytes.

    Returns:
        bytes: XML with ``&amp;amp;`` normalised to ``&amp;``.
    """
    return payload.replace(b"&amp;amp;", b"&amp;")


def print_col_ucd(lc: VOLightCurve):
    """Prints the column names, units, and UCD metadata for a given lightcurve.

    Args:
        lc (VOLightCurve): The lightcurve object whose columns should be printed.
    """
    for colname in lc.colnames:
        logger.info(
            "Col: %-10s Unit: %s UCD: %s",
            colname,
            lc[colname].unit,
            lc[colname].info.meta.get('ucd', 'None'),
        )


def write_vo_lightcurve(
    output_stream_or_path,
    table_data,
    table_name: str,
    filter_identifier: str,
    refposition: str = "BARYCENTER",
    timescale: str = "TCB",
    timeorigin: float = 0,
    votable_description: str | None = None,
    creator: str | None = None,
    zero_point_flux: float | None = None,
    zero_point_flux_unit: str = "",
    zero_point_ref_mag: float | None = None,
    zero_point_ref_mag_unit: str = "mag",
    magnitude_system: str = "Vega",
    effective_wavelength: float | None = None,
    effective_wavelength_unit: str = "m",
    table_description: str | None = None,
    ra: float | None = None,
    dec: float | None = None,
    filter_name: str | None = None,
    period: float | None = None,
    epoch: float | None = None,
    binary: bool = True,
    coosys_id: str = "system",
    coosys_system: str | None = None,
    coosys_epoch: float | str | None = None,
    publication_id: str | None = None,
):
    """Writes a lightcurve to a compliant IVOA VOTable (v1.4) XML file/stream.

    This function structures the input table, assigns Standard Unified Content
    Descriptors (UCDs), links time columns to a `<TIMESYS>` element, groups
    photometry under a `<GROUP name="photcal">` tag with metadata Parameters,
    and encodes the output using BINARY base64 or TABLEDATA format.

    Args:
        output_stream_or_path (str or file-like object): Path or stream to write the output to.
        table_data (astropy.table.Table or pandas.DataFrame or VOLightCurve):
            The source lightcurve containing timing and photometry.
        table_name (str): Value for the `<TABLE name="...">` attribute (Obligatory).
        filter_identifier (str): Value for the `filterIdentifier` PARAM (Obligatory).
        refposition (str, optional): Time reference position (e.g. 'BARYCENTER', 'HELIOCENTER').
            Defaults to "BARYCENTER" (Obligatory).
        timescale (str, optional): Time scale. Defaults to "TCB" (Optional).
        timeorigin (float, optional): Time origin offset added to ``obs_time`` to obtain
            absolute Julian Date. Use ``0`` when ``obs_time`` holds full JD; use
            ``2400000.5`` (``JD_TO_MJD``) when ``obs_time`` holds Modified Julian Date.
            Defaults to ``0``.
        votable_description (str, optional): High-level global description. Defaults to None.
        creator (str, optional): Pipeline or entity creator name. Defaults to None.
        zero_point_flux (float, optional): Zero point flux value. Defaults to None.
        zero_point_flux_unit (str, optional): Unit of zeroPointFlux.
        zero_point_ref_mag (float, optional): Reference magnitude zero point. Defaults to None.
        zero_point_ref_mag_unit (str, optional): Unit of zeroPointReferenceMagnitude. Defaults to "mag".
        magnitude_system (str, optional): Type of magnitude system. Defaults to "Vega".
        effective_wavelength (float, optional): Effective wavelength value. Defaults to None.
        effective_wavelength_unit (str, optional): Unit of effectiveWavelength. Defaults to "m".
        table_description (str, optional): Table block description. Defaults to None.
        ra (float, optional): RA of target in degrees. Defaults to None.
        dec (float, optional): Dec of target in degrees. Defaults to None.
        filter_name (str, optional): Generic filter/band name to write as a Table Param. Defaults to None.
        period (float, optional): Variability period in days. Defaults to None.
        epoch (float, optional): Reference time epoch in days. Defaults to None.
        binary (bool, optional): If True, encodes table data in BINARY format.
            If False, encodes in TABLEDATA XML format. Defaults to True.
        coosys_id (str, optional): ``COOSYS/@ID`` when writing coordinate metadata.
        coosys_system (str, optional): ``COOSYS/@system`` (e.g. ``ICRS``). When omitted,
            no ``<COOSYS>`` element is written unless supplied via a ``VOLightCurve``.
        coosys_epoch (float or str, optional): ``COOSYS/@epoch`` (proper-motion epoch).
        publication_id (str, optional): Publication bibcode written as TABLE ``bibcode`` PARAM.
    """
    import astropy.io.votable as vot
    from astropy.io.votable.tree import Group, Param, Info, FieldRef, TimeSys, CooSys as VOTableCooSys
    import pandas as pd

    # Extract astropy Table
    if isinstance(table_data, Table):
        t = table_data.copy()
    elif hasattr(table_data, 'table') and isinstance(table_data.table, Table):
        t = table_data.table.copy()
    elif isinstance(table_data, pd.DataFrame):
        t = Table.from_pandas(table_data)
    else:
        raise TypeError(
            "table_data must be an astropy Table, VOLightCurve, or pandas DataFrame."
        )

    # Heuristic/Positional detection and mapping of columns to standardized names
    time_col = None
    for name in ['obs_time', 'time', 'jd', 'mjd']:
        if name in t.colnames:
            time_col = name
            break
    flux_col = None
    for name in ['phot', 'flux', 'mag']:
        if name in t.colnames:
            flux_col = name
            break
    err_col = None
    for name in ['flux_error', 'flux_err', 'mag_err', 'error', 'err']:
        if name in t.colnames:
            err_col = name
            break

    if time_col and time_col != 'obs_time':
        t.rename_column(time_col, 'obs_time')
    if flux_col and flux_col != 'phot':
        t.rename_column(flux_col, 'phot')
    if err_col and err_col != 'flux_error':
        t.rename_column(err_col, 'flux_error')

    for name in ('label', 'sector'):
        if name in t.colnames and name != 'label':
            t.rename_column(name, 'label')
            break

    # Positional fallback if names don't map
    if 'obs_time' not in t.colnames:
        if len(t.colnames) > 0:
            t.rename_column(t.colnames[0], 'obs_time')
        else:
            raise ValueError("Table data must contain a time column.")
    if 'phot' not in t.colnames:
        if len(t.colnames) > 1:
            t.rename_column(t.colnames[1], 'phot')
        else:
            raise ValueError("Table data must contain a photometry (flux/magnitude) column.")
    if 'flux_error' not in t.colnames and len(t.colnames) > 2:
        third_col = t.colnames[2]
        if third_col != 'label':
            t.rename_column(third_col, 'flux_error')

    # Construct the strictly defined output table containing standard columns
    t_out = Table()
    t_out['obs_time'] = t['obs_time']
    t_out['phot'] = t['phot']
    if 'flux_error' in t.colnames:
        t_out['flux_error'] = t['flux_error']
    if 'label' in t.colnames:
        t_out['label'] = t['label']

    # Convert to VOTableFile structure
    vot_file = vot.from_table(t_out)
    vot_file.version = '1.4'
    if votable_description:
        vot_file.description = votable_description

    res = vot_file.resources[0]
    tab = res.tables[0]
    tab.name = table_name
    if table_description:
        tab.description = table_description

    # Add creator info if provided
    if creator:
        info = Info(name='creator', value=creator)
        info.ucd = 'meta.bib.author'
        info.content = 'Pipeline or contributing resource creator'
        res.infos.append(info)

    # Add TimeSys metadata element
    ts = TimeSys(
        ID='ts',
        refposition=refposition,
        timescale=timescale,
        timeorigin=str(timeorigin),
        config={'version_1_4_or_later': True}
    )
    res.time_systems.append(ts)

    if coosys_system is not None:
        cs = VOTableCooSys(
            ID=coosys_id or "system",
            system=coosys_system,
            epoch=str(coosys_epoch) if coosys_epoch is not None else None,
        )
        res.coordinate_systems.append(cs)

    # Standardize Table Fields and cross-link with systems
    phot_labels = resolve_votable_phot_field_labels(t_out)
    for f in tab.fields:
        if f.name == 'obs_time':
            f.ID = 'obs_time'
            f.ucd = 'time.epoch'
            f.unit = 'd'
            f.ref = 'ts'
            f.description = 'Time'
        elif f.name == 'phot':
            f.ID = 'phot'
            f.ucd = phot_labels['phot_ucd']
            f.unit = str(t_out['phot'].unit or 's**-1')
            f.ref = 'phot_def'
            f.description = phot_labels['phot_description']
        elif f.name == 'flux_error':
            f.ID = 'flux_error'
            f.ucd = phot_labels['error_ucd']
            f.unit = str(t_out['flux_error'].unit or 's**-1')
            f.description = phot_labels['error_description']
        elif f.name == 'label':
            f.ID = 'label'
            f.ucd = 'meta.id;meta.dataset'
            f.description = 'Dataset or sector label for each observation'

    # Add GROUP ID="phot_def" name="photcal"
    g = Group(vot_file, ID='phot_def', name='photcal')

    # filterIdentifier (Obligatory PARAM)
    p_fid = Param(vot_file, name='filterIdentifier', value=filter_identifier, datatype='char', arraysize='*')
    p_fid.utype = 'photDM:PhotometryFilter.identifier'
    p_fid.ucd = 'meta.id;instr.filter'
    g.entries.append(p_fid)

    # zeroPointFlux (Optional PARAM)
    if zero_point_flux is not None:
        p_zpf = Param(vot_file, name='zeroPointFlux', value=float(zero_point_flux), datatype='double', unit=zero_point_flux_unit)
        p_zpf.utype = 'photDM:PhotCal.zeroPoint.flux.value'
        p_zpf.ucd = 'phot.flux;arith.zp'
        g.entries.append(p_zpf)

    # zeroPointReferenceMagnitude (Optional PARAM)
    if zero_point_ref_mag is not None:
        p_zpm = Param(vot_file, name='zeroPointReferenceMagnitude', value=float(zero_point_ref_mag), datatype='double', unit=zero_point_ref_mag_unit)
        p_zpm.utype = 'photDM:PhotCal.zeroPoint.referenceMagnitude.value'
        p_zpm.ucd = 'phot.mag;arith.zp'
        g.entries.append(p_zpm)

    # magnitudeSystem (PARAM with default "Vega")
    p_mgs = Param(vot_file, name='magnitudeSystem', value=magnitude_system, datatype='char', arraysize='*')
    p_mgs.utype = 'photDM:PhotCal.magnitudeSystem.type'
    p_mgs.ucd = 'meta.code'
    g.entries.append(p_mgs)

    # effectiveWavelength (Optional PARAM)
    if effective_wavelength is not None:
        p_wl = Param(vot_file, name='effectiveWavelength', value=float(effective_wavelength), datatype='double', unit=effective_wavelength_unit)
        p_wl.utype = 'photDM:PhotometryFilter.spectralLocation.value'
        p_wl.ucd = 'em.wl.effective'
        g.entries.append(p_wl)

    # FieldRef linking GROUP back to the phot column
    fref = FieldRef(vot_file, ref='phot', utype='adhoc:location', config={'version_1_2_or_later': True})
    g.entries.append(fref)

    res.groups.append(g)

    # Table-level optional metadata PARAMs
    if ra is not None:
        p_ra = Param(vot_file, name='ra', value=float(ra), datatype='double')
        p_ra.ucd = 'pos.eq.ra'
        p_ra.description = 'RA of source object'
        tab.params.append(p_ra)

    if dec is not None:
        p_dec = Param(vot_file, name='dec', value=float(dec), datatype='double')
        p_dec.ucd = 'pos.eq.dec'
        p_dec.description = 'Dec of source object'
        tab.params.append(p_dec)

    if filter_name is not None:
        p_filt = Param(vot_file, name='filter', value=str(filter_name), datatype='char', arraysize='*')
        p_filt.ucd = 'meta.id;instr.filter'
        p_filt.description = 'Photometric filter name'
        tab.params.append(p_filt)

    if period is not None:
        p_per = Param(vot_file, name='period', value=float(period), datatype='double', unit='d')
        p_per.ucd = 'src.var;time.period'
        p_per.description = 'Period of the variable star'
        tab.params.append(p_per)

    if epoch is not None:
        p_ep = Param(vot_file, name='epoch', value=float(epoch), datatype='double', unit='d')
        p_ep.ucd = 'time.epoch'
        p_ep.ref = 'ts'
        p_ep.description = 'Reference time'
        tab.params.append(p_ep)

    if publication_id:
        p_bib = Param(
            vot_file,
            name='bibcode',
            value=str(publication_id),
            datatype='char',
            arraysize='*',
        )
        p_bib.ucd = 'meta.bib.bibcode'
        p_bib.utype = 'ssa:Curation.Reference'
        p_bib.description = 'URL or bibcode of a publication describing this data.'
        tab.params.append(p_bib)

    meta_src = getattr(t, 'meta', None) or {}
    optional_char_params = (
        ('sectors', 'meta.id;meta.dataset', 'TESS sector identifiers present in this lightcurve'),
        ('flux_origins', 'meta.code', 'Photometry extraction method (e.g. pdcsap, sap)'),
        ('authors', 'meta.bib.author', 'Pipeline author(s)'),
        ('title', 'meta.note', 'Display title for the lightcurve figure'),
        ('name', 'meta.id', 'Target identifier'),
        ('stitched', 'meta.code', 'True when sectors were stitched and flux calibration is relative'),
        ('cutout_source', 'meta.id;instr', 'Cutout data source: FFI or TPF'),
        ('mask_mode', 'meta.code', 'Aperture mask mode: handmade, threshold, or pipeline'),
    )
    for param_name, param_ucd, param_desc in optional_char_params:
        param_val = meta_src.get(param_name)
        if param_val is None:
            continue
        if isinstance(param_val, (list, tuple)):
            param_val = ','.join(str(v) for v in param_val)
        param_val = str(param_val).strip()
        if not param_val:
            continue
        p_extra = Param(vot_file, name=param_name, value=param_val, datatype='char', arraysize='*')
        p_extra.ucd = param_ucd
        p_extra.description = param_desc
        tab.params.append(p_extra)

    # Write to target path or stream
    tabledata_format = 'binary' if binary else 'tabledata'
    needs_ampersand_repair = bool(publication_id and "&" in str(publication_id))
    if needs_ampersand_repair:
        buffer = io.BytesIO()
        vot_file.to_xml(buffer, tabledata_format=tabledata_format)
        payload = _repair_votable_xml_char_param_ampersands(buffer.getvalue())
        if hasattr(output_stream_or_path, "write"):
            output_stream_or_path.write(payload)
        else:
            with open(output_stream_or_path, "wb") as handle:
                handle.write(payload)
    else:
        vot_file.to_xml(output_stream_or_path, tabledata_format=tabledata_format)



def main():
    """Main execution block to test and demonstrate ingestion and conversion functionality."""
    for filename in [
        # 'data/lc_tess_HD182144_TIC_406949643_sector__40_author__SPOC_methods__pdcsap.vot',
        'data/lc_tess_HD182144_TIC_406949643_sector__40_author__SPOC_methods__pdcsap.ecsv'
        # 'data/OGLE-SMC-CEP-0325-I.vot',
        # 'data/6009363278148078848-G.vot',
        # 'data/AY_Lac-R.vot',
        # 'data/g2_jk.vot',
        # 'data/my_g3.vot',
        # 'data/ASas19pm.dat'
    ]:
        logger.info('Ingesting %s', filename)
        lc = VOLightCurve(file_path=filename)
        print_col_ucd(lc)
        logger.info('%s', lc.photdms)
        logger.info('%s', lc.timesys)
        logger.info('time columns: %s', get_time_colnames(lc))
        logger.info('flux columns: %s', get_flux_colnames(lc))
        logger.info('mag columns: %s', get_mag_colnames(lc))

        logger.info('%s', lc[0])
        logger.info('All flux columns. Convert into magnitudes')
        for colname in lc.get_flux_colnames():
            out_colname = f'magnitude_from_{colname}'
            logger.info('flux:%s --> mag:%s', colname, out_colname)
            lc.add_mag_column_from_flux(colname, out_colname)
            logger.info('%s', lc[out_colname, colname][0])
        logger.info('All magnitude columns. Convert into flux')
        for colname in lc.get_mag_colnames():
            out_colname = f'flux_from_{colname}'
            logger.info('mag:%s --> flux:%s', colname, out_colname)
            lc.add_flux_column_from_mag(colname, out_colname)
            logger.info('%s', lc[out_colname, colname][0])


if __name__ == "__main__":
    from skvo_veb.logging_config import configure_logging

    configure_logging()
    main()
