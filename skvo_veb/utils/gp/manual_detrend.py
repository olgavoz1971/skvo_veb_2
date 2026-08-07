"""Manual linear trend removal on GP prep light curves (transport JSON)."""

from __future__ import annotations

import json
import logging

import astropy.units as u
import numpy as np

from skvo_veb.utils.lc_bridge import _jd0_from_packet_meta, photcal_from_metadata
from skvo_veb.utils.lc_config import DOMAIN_FLUX, DOMAIN_MAG, DEFAULT_EPOCH_JD
from skvo_veb.utils.lc_interaction import plot_x_to_jd
from skvo_veb.utils.gp.flux import resolve_gp_photcal
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)


def line_y_at_jd(
    jd: np.ndarray,
    jd_a: float,
    y_a: float,
    jd_b: float,
    y_b: float,
) -> np.ndarray:
    """Evaluates the straight line through two anchor points in Julian Date space.

    Args:
        jd (numpy.ndarray): Absolute Julian dates.
        jd_a (float): First anchor JD.
        y_a (float): First anchor y (mag or flux).
        jd_b (float): Second anchor JD.
        y_b (float): Second anchor y.

    Returns:
        numpy.ndarray: Line values at ``jd``.

    Raises:
        PipeException: If anchor JDs are identical.
    """
    if jd_a == jd_b:
        raise PipeException(
            "Trend line anchors share the same time; pick two distinct points on the plot."
        )
    slope = (y_b - y_a) / (jd_b - jd_a)
    return y_a + slope * (np.asarray(jd, dtype=float) - jd_a)


def _resolve_photcal(meta: dict):
    """Returns ``PhotCal`` from transport meta, with GP fallback when incomplete."""
    try:
        return photcal_from_metadata(meta.get("photcal"))
    except ValueError:
        return resolve_gp_photcal(meta)


def _view_values_native_column(
    v: np.ndarray,
    e: np.ndarray | None,
    has_err: bool,
    native_domain: str,
    view_mode: str,
    pc,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Maps stored column values into the active Mag/Flux view domain."""
    y = np.asarray(v, dtype=float)
    err = np.asarray(e, dtype=float) if has_err and e is not None else None
    flux_unit = pc.zp_flux.unit

    if view_mode == native_domain:
        return y, err

    if view_mode == DOMAIN_FLUX and native_domain == DOMAIN_MAG:
        mag_q = y * u.mag
        y_out = np.asarray(pc.mag_to_flux(mag_q).value, dtype=float)
        if err is not None:
            err_q = err * u.mag
            err_out = np.asarray(
                pc.mag_err_to_flux_err(mag_q, err_q).value, dtype=float
            )
        else:
            err_out = None
        return y_out, err_out

    if view_mode == DOMAIN_MAG and native_domain == DOMAIN_FLUX:
        y_out = np.full_like(y, np.nan)
        mask = y > 0
        flux_q = y[mask] * flux_unit
        y_out[mask] = np.asarray(pc.flux_to_mag(flux_q).value, dtype=float)
        if err is not None:
            err_out = np.full_like(err, np.nan)
            err_q = err[mask] * flux_unit
            err_out[mask] = np.asarray(
                pc.flux_err_to_mag_err(flux_q, err_q).value, dtype=float
            )
        else:
            err_out = None
        return y_out, err_out

    raise PipeException(f"Unsupported domain pair: native={native_domain}, view={view_mode}")


def _native_from_view_values(
    y_view: np.ndarray,
    err_view: np.ndarray | None,
    native_domain: str,
    view_mode: str,
    pc,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Writes view-domain values back into the transport native column domain."""
    if view_mode == native_domain:
        return y_view, err_view

    flux_unit = pc.zp_flux.unit

    if view_mode == DOMAIN_MAG and native_domain == DOMAIN_FLUX:
        y_out = np.full_like(y_view, np.nan)
        mask = np.isfinite(y_view)
        mag_q = y_view[mask] * u.mag
        flux_q = pc.mag_to_flux(mag_q)
        y_out[mask] = np.asarray(flux_q.value, dtype=float)
        if err_view is not None:
            err_out = np.full_like(err_view, np.nan)
            err_q = err_view[mask] * u.mag
            err_out[mask] = np.asarray(
                pc.flux_err_to_mag_err(flux_q, err_q).value, dtype=float
            )
        else:
            err_out = None
        return y_out, err_out

    if view_mode == DOMAIN_FLUX and native_domain == DOMAIN_MAG:
        mag_q = pc.flux_to_mag(y_view * flux_unit)
        y_out = np.asarray(mag_q.value, dtype=float)
        if err_view is not None:
            err_q = err_view * flux_unit
            err_out = np.asarray(
                pc.flux_err_to_mag_err(y_view * flux_unit, err_q).value, dtype=float
            )
        else:
            err_out = None
        return y_out, err_out

    raise PipeException(f"Unsupported domain pair: native={native_domain}, view={view_mode}")


def apply_manual_linear_detrend(
    json_str: str,
    *,
    view_mode: str,
    anchor_a: tuple[float | str, float],
    anchor_b: tuple[float | str, float],
    time_axis_mode: str,
    display_epoch: float = DEFAULT_EPOCH_JD,
) -> str:
    """Removes a user line from the transport light curve in the current view domain.

    Magnitude view subtracts the line; flux view divides by it. Native
    ``active_domain`` and column layout are preserved (values round-trip through
    photcal when view differs from storage).

    Args:
        json_str (str): Serialised GP transport JSON.
        view_mode (str): ``mag`` or ``flux`` (Mag/Flux toggle at apply time).
        anchor_a (tuple): First anchor ``(plot_x, y)``.
        anchor_b (tuple): Second anchor ``(plot_x, y)``.
        time_axis_mode (str): Prep plot time axis (``mjd`` or ``date``).
        display_epoch (float): MJD display epoch offset.

    Returns:
        str: Updated transport JSON.

    Raises:
        PipeException: On invalid anchors, non-positive flux trend, or conversion errors.
    """
    packet = json.loads(json_str)
    meta = packet["meta"]
    native_domain = meta.get("active_domain") or DOMAIN_MAG
    has_err = packet["schema"]["error"] is not None
    jd0 = _jd0_from_packet_meta(meta) or 0.0
    pc = _resolve_photcal(meta)

    jd_a = plot_x_to_jd(anchor_a[0], time_axis_mode, display_epoch)
    jd_b = plot_x_to_jd(anchor_b[0], time_axis_mode, display_epoch)
    y_a = float(anchor_a[1])
    y_b = float(anchor_b[1])

    data = packet["data"]
    n_updated = 0
    for row in data:
        t_raw = float(row[0])
        v_raw = float(row[1])
        if np.isnan(t_raw) or np.isnan(v_raw):
            continue
        jd = t_raw + jd0
        ell = float(line_y_at_jd(np.array([jd]), jd_a, y_a, jd_b, y_b)[0])

        e_raw = row[2]
        err_val = float(e_raw) if has_err and e_raw is not None else None

        y_view, e_view = _view_values_native_column(
            np.array([v_raw]),
            np.array([err_val]) if err_val is not None else None,
            has_err and err_val is not None,
            native_domain,
            view_mode,
            pc,
        )
        y0 = float(y_view[0])
        e0 = float(e_view[0]) if e_view is not None and np.isfinite(e_view[0]) else None

        if view_mode == DOMAIN_MAG:
            y1 = y0 - ell
            e1 = e0
        elif view_mode == DOMAIN_FLUX:
            if ell <= 0:
                raise PipeException(
                    "Flux trend line is zero or negative at at least one observation; "
                    "adjust the line or switch to magnitude view."
                )
            y1 = y0 / ell
            e1 = (e0 / ell) if e0 is not None else None
        else:
            raise PipeException(f"Unknown view mode: {view_mode}")

        v_native, e_native = _native_from_view_values(
            np.array([y1]),
            np.array([e1]) if e1 is not None else None,
            native_domain,
            view_mode,
            pc,
        )
        row[1] = float(v_native[0])
        if has_err and view_mode == DOMAIN_FLUX:
            if e_native is not None and np.isfinite(e_native[0]):
                row[2] = float(e_native[0])
            elif e1 is None:
                row[2] = None
        n_updated += 1

    if n_updated == 0:
        raise PipeException("No valid light curve rows to detrend.")

    logger.info(
        "Manual linear detrend applied (%s view) on %d rows",
        view_mode,
        n_updated,
    )
    return json.dumps(packet)
