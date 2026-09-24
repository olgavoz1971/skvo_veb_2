"""GP-specific flux extraction for timing fits (normalised instrumental flux)."""

from __future__ import annotations

import json
import logging

import astropy.units as u
import numpy as np
import pandas as pd

from skvo_veb.utils.lc_bridge import photcal_from_metadata, unpack_json_for_plotly
from volightcurve.lightcurve import PhotCal
from volightcurve.photcal_check import PhotCalError

logger = logging.getLogger(__name__)

_GP_CALIBRATION_HINT = (
    "Set the photometric zero points for this light curve before converting "
    "or fitting. The upload warning lists any values that were only suggested."
)


def resolve_gp_photcal(meta: dict) -> PhotCal:
    """Build a ``PhotCal`` for mag-to-flux conversion.

    Uses the calibration already stored on the packet. It does not fill
    missing zero points. Upload is the place that may suggest defaults, and
    that path shows a warning.

    Args:
        meta (dict): Transport packet ``meta`` block.

    Returns:
        PhotCal: Calibration for monotonic mag-to-flux conversion before GP
        normalisation.

    Raises:
        PhotCalError: When the stored calibration cannot convert.
    """
    from skvo_veb.utils.photcal_coherence import inspect_photcal_dict

    flux_unit = meta.get("flux_unit")
    problems = inspect_photcal_dict(meta.get("photcal"), flux_unit=flux_unit)
    if problems:
        raise PhotCalError([*problems, _GP_CALIBRATION_HINT])
    return photcal_from_metadata(meta.get("photcal") or {})


def decode_gp_flux_arrays(json_str: str) -> dict:
    """Decode the whole transport packet once into GP instrumental flux arrays.

    Decoding is the expensive half of interval work: it parses the full transport
    JSON and converts every row. Callers that need many intervals from one light
    curve must decode once with this function and then call
    :func:`slice_gp_flux_arrays` per interval, rather than calling
    :func:`get_gp_flux_fragment` in a loop.

    For magnitude-native uploads the conversion uses ``PhotCal`` from transport
    metadata after shared photcal reconciliation
    (:func:`resolve_gp_photcal`).

    Args:
        json_str (str): Serialised lightcurve transport JSON.

    Returns:
        dict: ``jd``, ``flux`` and ``flux_err`` as ``numpy.ndarray`` of equal
            length, in the original row order.
    """
    meta = json.loads(json_str)["meta"]

    if meta.get("active_domain") == "flux":
        lc_flux = unpack_json_for_plotly(json_str, view_mode="flux")
        flux = np.asarray(lc_flux["y"], dtype=float)
        err = lc_flux["err"]
        return {
            "jd": np.asarray(lc_flux["x"], dtype=float),
            "flux": flux,
            "flux_err": (
                np.asarray(err, dtype=float)
                if err is not None
                else np.full_like(flux, np.nan)
            ),
        }

    lc_mag = unpack_json_for_plotly(json_str, view_mode="mag")
    pc = resolve_gp_photcal(meta)
    mag = lc_mag["y"]
    err_mag = lc_mag["err"]

    flux = np.asarray(pc.mag_to_flux(mag * u.mag).value, dtype=float)
    if err_mag is not None and np.any(np.isfinite(err_mag)):
        err_q = np.where(np.isfinite(err_mag), err_mag, 0.0) * u.mag
        mag_q = mag * u.mag
        flux_err = np.asarray(
            pc.mag_err_to_flux_err(mag_q, err_q).value, dtype=float
        )
        flux_err = np.where(np.isfinite(err_mag), flux_err, np.nan)
    else:
        flux_err = np.full_like(flux, np.nan)

    return {
        "jd": np.asarray(lc_mag["x"], dtype=float),
        "flux": flux,
        "flux_err": flux_err,
    }


def slice_gp_flux_arrays(
    arrays: dict,
    jd_min: float,
    jd_max: float,
) -> pd.DataFrame:
    """Slice decoded flux arrays to one closed JD interval.

    Args:
        arrays (dict): Output of :func:`decode_gp_flux_arrays`.
        jd_min (float): Interval lower bound (absolute JD, inclusive).
        jd_max (float): Interval upper bound (absolute JD, inclusive).

    Returns:
        pandas.DataFrame: Columns ``jd``, ``flux``, ``flux_err`` for rows inside
            the interval, with non-finite ``jd`` or ``flux`` dropped.
    """
    jd = arrays["jd"]
    mask = (jd >= jd_min) & (jd <= jd_max)
    frag = pd.DataFrame({
        "jd": jd[mask],
        "flux": arrays["flux"][mask],
        "flux_err": arrays["flux_err"][mask],
    })
    return frag.dropna(subset=["jd", "flux"])


def get_gp_flux_fragment(json_str: str, jd_min: float, jd_max: float) -> pd.DataFrame:
    """Return a JD-sliced fragment as instrumental flux for ``gp_peak_pipeline``.

    Convenience wrapper for single-interval use. Decoding dominates the cost, so
    loops over many intervals must use :func:`decode_gp_flux_arrays` once
    followed by :func:`slice_gp_flux_arrays`.

    Args:
        json_str (str): Serialised lightcurve transport JSON.
        jd_min (float): Interval lower bound (absolute JD).
        jd_max (float): Interval upper bound (absolute JD).

    Returns:
        pandas.DataFrame: Columns ``jd``, ``flux``, ``flux_err``.
    """
    return slice_gp_flux_arrays(decode_gp_flux_arrays(json_str), jd_min, jd_max)


def empty_interval_indices(intervals: list, lc_json_string: str) -> list[int]:
    """Returns indices of intervals that contain no lightcurve points.

    Uses the same JD slicing as ``get_gp_flux_fragment`` so emptiness matches GP
    data selection. Decodes the light curve once for the whole list.

    Args:
        intervals (list): ``[[jd_start, jd_end], ...]`` in absolute JD.
        lc_json_string (str): Serialised lightcurve transport JSON.

    Returns:
        list[int]: Indices with zero points in ``[jd_start, jd_end]``.
    """
    if not intervals or not lc_json_string:
        return []
    arrays = decode_gp_flux_arrays(lc_json_string)
    empty: list[int] = []
    for index, piece in enumerate(intervals):
        jd_min, jd_max = float(piece[0]), float(piece[1])
        if len(slice_gp_flux_arrays(arrays, jd_min, jd_max)) == 0:
            empty.append(index)
    return empty
