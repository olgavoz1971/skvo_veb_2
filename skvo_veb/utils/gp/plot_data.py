"""Plot-oriented JSON unpack for the GP page (domain view + shared photcal)."""

from __future__ import annotations

import hashlib
import json

from skvo_veb.utils.lc_bridge import unpack_json_for_plotly
from skvo_veb.utils.gp.flux import _GP_CALIBRATION_HINT
from volightcurve.photcal_check import PhotCalError


def unpack_json_for_gp_plot(json_str: str, view_mode: str = "mag") -> dict:
    """Unpack transport JSON for the GP prep plot, with shared photcal policy.

    Uses ``unpack_json_for_plotly``. A failed conversion is reported as
    :class:`PhotCalError` and is not repaired here.

    Args:
        json_str (str): Serialised lightcurve from ``pack_volc_to_json``.
        view_mode (str): ``mag`` or ``flux`` for the y-axis.

    Returns:
        dict: Same shape as ``unpack_json_for_plotly``.
    """
    try:
        return unpack_json_for_plotly(json_str, view_mode=view_mode)
    except PhotCalError as exc:
        raise PhotCalError([*exc.problems, _GP_CALIBRATION_HINT]) from exc
    except ValueError as exc:
        if "photcal" not in str(exc).lower() and "zero-point" not in str(exc).lower():
            raise
        raise PhotCalError([str(exc), _GP_CALIBRATION_HINT]) from exc


def transport_revision_token(json_str: str) -> str:
    """Short stable identity for a transport packet, for Plotly ``uirevision``.

    ``uirevision`` only has to *change* when the light curve changes; it does not
    have to contain it. Interpolating the transport string adds its full size to
    every figure payload, which for a 20 000-row light curve is close to a
    megabyte per plot update. The digest is a change detector, not a checksum for
    integrity or security.

    Args:
        json_str (str): Serialised lightcurve transport JSON.

    Returns:
        str: Short hex digest, or an empty string when there is no light curve.
    """
    if not json_str:
        return ""
    return hashlib.sha1(json_str.encode("utf-8")).hexdigest()[:16]


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


def apply_folding_metadata_to_transport(
    json_str: str,
    period,
    epoch_display,
    *,
    display_epoch: float,
    active_domain: str | None = None,
) -> tuple[str, bool]:
    """Writes prep ephemeris / view domain into transport ``meta``.

    Empty period or epoch widgets leave the existing meta values. Domain is
    updated only when ``active_domain`` is a non-empty string.

    Args:
        json_str (str): Serialised lightcurve transport JSON.
        period: Sidebar period in days, or empty.
        epoch_display: Sidebar epoch as an offset from ``display_epoch``.
        display_epoch (float): Same MJD reference as the prep Epoch field.
        active_domain (str, optional): ``mag`` or ``flux`` for the view radio.

    Returns:
        tuple: ``(updated_json, changed)`` where ``changed`` is ``True`` when any
        meta field was written.
    """
    from skvo_veb.utils.lc_config import absolute_jd_from_display_epoch
    from skvo_veb.utils.my_tools import safe_float

    packet = json.loads(json_str)
    meta = packet.setdefault("meta", {})
    changed = False

    period_val = safe_float(period)
    if period_val is not None and period_val > 0:
        if meta.get("period") != period_val:
            meta["period"] = period_val
            changed = True

    epoch_abs = absolute_jd_from_display_epoch(epoch_display, display_epoch)
    if epoch_abs is not None:
        if meta.get("epoch") != epoch_abs:
            meta["epoch"] = epoch_abs
            changed = True

    if active_domain in ("mag", "flux") and meta.get("active_domain") != active_domain:
        meta["active_domain"] = active_domain
        changed = True

    if not changed:
        return json_str, False
    return json.dumps(packet), True
