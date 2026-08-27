"""Gaussian Process utilities for O-C extremum timing."""

from skvo_veb.utils.gp.config import (
    AMPLITUDE_INIT,
    AMPLITUDE_MAX,
    AMPLITUDE_MIN,
    DEFAULT_FLOAT_PARAMS,
    DEFAULT_REFERENCE_MAG,
    EXTREMA_MODE,
    GP_ZP_FLUX_DIMENSIONLESS,
    GUESS_SIGMA,
    KERNEL_TYPE,
    LEN_MIN,
    NOISE_SCALE,
)
from skvo_veb.utils.gp.figure import figure_from_gp_result
from skvo_veb.utils.gp.flux import (
    decode_gp_flux_arrays,
    empty_interval_indices,
    get_gp_flux_fragment,
    resolve_gp_photcal,
    slice_gp_flux_arrays,
)
from skvo_veb.utils.gp.ingest import pack_uploaded_lightcurve
from skvo_veb.utils.gp.intervals import format_intervals_download, load_intervals
from skvo_veb.utils.gp.pipeline import gp_peak_pipeline, guess_length_scale

__all__ = [
    "AMPLITUDE_INIT",
    "AMPLITUDE_MAX",
    "AMPLITUDE_MIN",
    "DEFAULT_FLOAT_PARAMS",
    "DEFAULT_REFERENCE_MAG",
    "EXTREMA_MODE",
    "GP_ZP_FLUX_DIMENSIONLESS",
    "GUESS_SIGMA",
    "KERNEL_TYPE",
    "LEN_MIN",
    "NOISE_SCALE",
    "empty_interval_indices",
    "figure_from_gp_result",
    "format_intervals_download",
    "decode_gp_flux_arrays",
    "get_gp_flux_fragment",
    "slice_gp_flux_arrays",
    "gp_peak_pipeline",
    "guess_length_scale",
    "load_intervals",
    "pack_uploaded_lightcurve",
    "resolve_gp_photcal",
]
