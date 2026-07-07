"""Virtual Observatory (VO) Lightcurve Processing Package.

This package provides a comprehensive data model and parser for lightcurves, supporting
standard VOTable files as well as heuristic ASCII text formats. It maps columns to
astronomical concepts like coordinate systems, time systems, and photometric calibrations.
"""

from .lightcurve import *

__all__ = [
    "VOLightCurve",
    "write_vo_lightcurve",
    "find_columns_by_ucd",
    "get_time_colnames",
    "get_mag_colnames",
    "get_flux_colnames",
    "get_error_colnames",
    "print_col_ucd",
    "is_mag_column",
    "is_flux_column",
    "is_magnitude_phot_column",
    "assign_photometry_column_semantics",
]
