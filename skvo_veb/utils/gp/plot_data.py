"""Plot-oriented JSON unpack for the GP page (domain view + GP photcal fallback)."""

from __future__ import annotations

import json

import astropy.units as u
import numpy as np

from skvo_veb.utils.lc_config import DOMAIN_FLUX, DOMAIN_MAG
from skvo_veb.utils.lc_bridge import unpack_json_for_plotly, _jd0_from_packet_meta
from skvo_veb.utils.gp.flux import resolve_gp_photcal


def unpack_json_for_gp_plot(json_str: str, view_mode: str = "mag") -> dict:
    """Unpack transport JSON for the GP prep plot, with GP calibration fallback.

    Uses ``unpack_json_for_plotly`` when bridge photcal is complete. When the user
    requests a domain conversion but upload metadata lacks zero points (typical for
    exported CSV flux), applies ``resolve_gp_photcal`` from GP config.

    Args:
        json_str (str): Serialised lightcurve from ``pack_volc_to_json``.
        view_mode (str): ``mag`` or ``flux`` for the y-axis.

    Returns:
        dict: Same shape as ``unpack_json_for_plotly``.
    """
    try:
        return unpack_json_for_plotly(json_str, view_mode=view_mode)
    except ValueError as exc:
        if "photcal" not in str(exc).lower():
            raise
        return _unpack_with_gp_photcal(json_str, view_mode=view_mode)


def _unpack_with_gp_photcal(json_str: str, view_mode: str) -> dict:
    """Decode transport JSON and convert domains using GP ``PhotCal`` defaults."""
    packet = json.loads(json_str)
    meta = packet["meta"]
    data = np.array(packet["data"], dtype=object)

    t_raw = data[:, 0].astype(float)
    v_raw = data[:, 1].astype(float)
    valid_mask = ~np.isnan(t_raw) & ~np.isnan(v_raw)
    t = t_raw[valid_mask]
    v = v_raw[valid_mask]

    has_err = packet["schema"]["error"] is not None
    e_raw = data[valid_mask, 2]
    e = e_raw.astype(float) if has_err else None
    f = data[valid_mask, 3]

    jd0 = _jd0_from_packet_meta(meta)
    if jd0:
        t += jd0

    current_domain = meta["active_domain"]
    y_data = v
    e_data = e

    if view_mode != current_domain:
        pc = resolve_gp_photcal(meta)
        flux_unit = pc.zp_flux.unit

        if view_mode == DOMAIN_FLUX and current_domain == DOMAIN_MAG:
            mag_q = v * u.mag
            flux_q = pc.mag_to_flux(mag_q)
            y_data = np.asarray(flux_q.value, dtype=float)
            if has_err and e is not None:
                err_q = e * u.mag
                e_data = np.asarray(
                    pc.mag_err_to_flux_err(mag_q, err_q).value, dtype=float
                )
        elif view_mode == DOMAIN_MAG and current_domain == DOMAIN_FLUX:
            mask = v > 0
            y_data = np.full_like(v, np.nan)
            flux_q = v[mask] * flux_unit
            y_data[mask] = np.asarray(pc.flux_to_mag(flux_q).value, dtype=float)
            if has_err and e is not None:
                e_data = np.full_like(e, np.nan)
                err_q = e[mask] * flux_unit
                e_data[mask] = np.asarray(
                    pc.flux_err_to_mag_err(flux_q, err_q).value, dtype=float
                )

    y_label = "Magnitude" if view_mode == DOMAIN_MAG else "Normalised flux"
    return {
        "x": t,
        "y": y_data,
        "err": e_data,
        "flag": f,
        "x_label": "Julian Date (JD)",
        "y_label": y_label,
        "is_mag": view_mode == DOMAIN_MAG,
        "timescale": meta.get("timescale"),
        "refposition": meta.get("refposition"),
    }


def folding_metadata_from_transport(json_str: str) -> tuple[float | None, float | None, str]:
    """Read period, epoch, and native photometric domain from transport meta.

    Args:
        json_str (str): Serialised lightcurve JSON.

    Returns:
        tuple: ``(period, epoch_jd, active_domain)`` with ``None`` for missing keys.
    """
    meta = json.loads(json_str).get("meta") or {}
    period = meta.get("period")
    epoch = meta.get("epoch")
    domain = meta.get("active_domain") or "mag"
    if period is not None:
        period = float(period)
    if epoch is not None:
        epoch = float(epoch)
    return period, epoch, domain
