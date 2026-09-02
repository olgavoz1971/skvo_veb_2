"""Step 1 O-C cycle assignment and residuals."""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from skvo_veb.utils.oc.tom_io import records_to_arrays

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86400.0


def cycle_shifts_from_store(
    shift_rows: list[dict] | None,
    *,
    display_epoch: float,
) -> list[tuple[float, int]]:
    """Converts UI cycle-shift rows (display MJD) to ``(at_jd, delta_E)``.

    Args:
        shift_rows (list[dict] | None): Stored rows with ``at_mjd`` and ``delta_e``.
        display_epoch (float): Same offset as the Epoch field (``jd0``).

    Returns:
        list[tuple[float, int]]: Shifts in absolute JD, sorted by time.
    """
    if not shift_rows:
        return []
    out: list[tuple[float, int]] = []
    for row in shift_rows:
        at_mjd = float(row["at_mjd"])
        at_jd = at_mjd + float(display_epoch)
        out.append((at_jd, int(row["delta_e"])))
    out.sort(key=lambda item: item[0])
    return out


def compute_step1_oc(
    records: list[dict],
    *,
    t0_jd: float,
    p0: float,
    cycle_shifts: list[tuple[float, int]] | None = None,
    source: str,
) -> dict[str, Any]:
    """Assigns cycles and O-C residuals (days) for ToM records.

    ``E = round((jd_ext - T0) / P0)``, then integer ``delta_E`` is added for
    every point with ``jd_ext >= at_jd``. Residual:
    ``O-C = jd_ext - (T0 + E * P0)``.

    Args:
        records (list[dict]): ``jd_ext`` / ``sigma_jd`` rows.
        t0_jd (float): Trial epoch as absolute JD.
        p0 (float): Trial period in days.
        cycle_shifts (list[tuple[float, int]] | None): ``(at_jd, delta_E)`` pairs.
        source (str): ``gp``, ``mavka``, or ``upload``.

    Returns:
        dict: JSON-safe arrays and ephemeris metadata for plot and export.

    Raises:
        ValueError: If ``p0`` is not positive or ``records`` is empty.
    """
    if p0 <= 0.0 or not math.isfinite(p0):
        raise ValueError("Period P0 must be a positive finite number of days.")
    if not math.isfinite(t0_jd):
        raise ValueError("Epoch T0 must be a finite Julian Date.")
    if not records:
        raise ValueError("No ToMs to plot.")

    jd_list, sigma_list = records_to_arrays(records)
    jd_ext = np.asarray(jd_list, dtype=float)
    sigma_jd = np.asarray(sigma_list, dtype=float)
    e_naive = np.round((jd_ext - t0_jd) / p0)
    delta = np.zeros_like(e_naive)
    shifts = list(cycle_shifts or [])
    for at_jd, delta_e in sorted(shifts, key=lambda item: item[0]):
        delta += np.where(jd_ext >= at_jd, delta_e, 0)
    cycle_e = e_naive + delta
    oc_days = jd_ext - (t0_jd + cycle_e * p0)
    jd_calc = t0_jd + cycle_e * p0
    rms = float(np.sqrt(np.mean(oc_days**2)))
    payload = {
        "source": source,
        "t0_jd": float(t0_jd),
        "p0": float(p0),
        "cycle_shifts": [
            {"at_jd": float(at_jd), "delta_e": int(delta_e)}
            for at_jd, delta_e in shifts
        ],
        "E": [float(value) for value in cycle_e],
        "OC": [float(value) for value in oc_days],
        "jd_ext": [float(value) for value in jd_ext],
        "jd_calc": [float(value) for value in jd_calc],
        "sigma_jd": [float(value) for value in sigma_jd],
        "n": int(len(cycle_e)),
        "rms_d": rms,
        "rms_s": rms * SECONDS_PER_DAY,
    }
    logger.info(
        "O-C %s: N=%s RMS=%.6f d (%.1f s) shifts=%s",
        source,
        payload["n"],
        rms,
        payload["rms_s"],
        len(shifts),
    )
    return payload


def absolute_jd_to_display_mjd(jd_abs: float, display_epoch: float) -> float:
    """Converts an absolute Julian Date to the page display MJD offset.

    Args:
        jd_abs (float): Absolute Julian Date.
        display_epoch (float): Offset subtracted on the page (``jd0``).

    Returns:
        float: ``jd_abs - display_epoch``.
    """
    return float(jd_abs) - float(display_epoch)


def at_mjd_from_oc_click(
    click_data: dict | None,
    payload: dict | None = None,
    *,
    display_epoch: float | None = None,
) -> float:
    """Reads observed display MJD from an O-C graph ``clickData`` payload.

    Prefers ``customdata[1]`` (observed MJD on the figure). If that is missing,
    reconstructs ``jd_ext`` from the clicked ``E``, ``O-C``, and the last plot
    payload: ``T0 + E × P0 + (O-C)``.

    Args:
        click_data (dict | None): Dash ``dcc.Graph.clickData``.
        payload (dict | None): Last ``compute_step1_oc`` store, used as fallback.
        display_epoch (float | None): Page MJD offset (``jd0``) for the fallback.

    Returns:
        float: Observed MJD of the clicked point.

    Raises:
        ValueError: If the click has no point or no observed MJD.
    """
    if not click_data or not click_data.get("points"):
        raise ValueError("No O-C point selected.")
    point = click_data["points"][0]
    custom = point.get("customdata")
    if isinstance(custom, (list, tuple)) and len(custom) >= 2:
        value = float(custom[1])
        if math.isfinite(value):
            return value
    if payload is None or display_epoch is None:
        raise ValueError("Clicked point is missing observed MJD.")
    if "x" not in point or "y" not in point:
        raise ValueError("Clicked point is missing observed MJD.")
    cycle_e = float(point["x"])
    oc_days = float(point["y"])
    t0_jd = float(payload["t0_jd"])
    p0 = float(payload["p0"])
    jd_ext = t0_jd + cycle_e * p0 + oc_days
    value = absolute_jd_to_display_mjd(jd_ext, display_epoch)
    if not math.isfinite(value):
        raise ValueError("Observed MJD is not finite.")
    return value
