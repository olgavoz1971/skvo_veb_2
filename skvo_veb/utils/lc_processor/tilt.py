"""Local tilt: seed plot 2 from plot 1, then apply a user line to a stretch."""

from __future__ import annotations

import logging

import numpy as np

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_interaction import line_y_at_jd, plot_x_to_jd
from skvo_veb.utils.lc_processor.apply import (
    DETREND_ORIGIN_COPY,
    DETREND_ORIGIN_SMOOTH,
    cropped_series,
    pack_detrend_payload,
)
from skvo_veb.utils.lc_processor.smooth import detrend_observed, detrended_standard_error
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)


def residual_axis_title(
    origin: str | None,
    *,
    invert_y: bool,
    phot_unit: str | None = None,
) -> str:
    """Returns the plot-2 y-axis title for a residual origin.

    Args:
        origin (str | None): ``smooth``, ``copy``, or missing (treat as smooth).
        invert_y (bool): ``True`` for magnitude.
        phot_unit (str, optional): Active photometry unit label for copy mode.

    Returns:
        str: Axis title.
    """
    if origin == DETREND_ORIGIN_COPY:
        unit = (phot_unit or "").strip()
        if invert_y:
            return f"magnitude,{unit}" if unit else "magnitude"
        return f"flux,{unit}" if unit else "flux"
    return "Δmag (obs − trend)" if invert_y else "flux / trend"


def copy_working_as_residual(
    lcd: CurveDash,
    *,
    domain: str,
    t_min,
    t_max,
) -> dict:
    """Copies the cropped working series onto plot 2.

    Args:
        lcd (CurveDash): Cached working curve.
        domain (str): Working photometric domain.
        t_min: Crop start (display MJD).
        t_max: Crop end (display MJD).

    Returns:
        dict: Residual payload (``origin='copy'``).

    Raises:
        ValueError: If the cropped series is empty.
    """
    times, values, err, _perm, _labels = cropped_series(lcd, t_min, t_max)
    if not np.any(np.isfinite(values)):
        raise ValueError("Copy from plot 1 found no finite photometry points.")
    mode = lcd.active_domain or domain
    logger.info("Copied %s cropped point(s) from plot 1 onto plot 2", int(times.size))
    return pack_detrend_payload(
        times=times,
        residual=values,
        residual_err=err,
        domain=mode,
        method="copy",
        origin=DETREND_ORIGIN_COPY,
    )


def apply_local_tilt(
    payload: dict | None,
    *,
    anchor_a: tuple,
    anchor_b: tuple,
    time_axis_mode: str,
    display_epoch: float,
    jd_bounds: tuple[float, float] | None = None,
) -> dict:
    """Rewrites plot-2 samples inside the working time window.

    Same rule as GP Remove trend: the line is the model; ``jd_bounds``
    (Use visible range) is the locality. With no window, the whole
    seeded series is rewritten. Magnitude subtracts the line; flux
    divides by it.

    Args:
        payload (dict | None): Current residual blob.
        anchor_a (tuple): First handle ``(plot_x, y)``.
        anchor_b (tuple): Second handle ``(plot_x, y)``.
        time_axis_mode (str): ``mjd`` or ``date``.
        display_epoch (float): MJD display epoch.
        jd_bounds (tuple | None): Working window ``(jd_min, jd_max)``.

    Returns:
        dict: Updated residual payload.

    Raises:
        ValueError: If plot 2 is empty, the handles share a time, the
            window contains no points, or a flux line is not positive.
    """
    if not payload or not payload.get("residual"):
        raise ValueError(
            "Seed plot 2 first: Apply detrend or Copy from plot 1."
        )
    jd = np.asarray(payload["jd"], dtype=float)
    residual = np.asarray(payload["residual"], dtype=float)
    raw_err = payload.get("residual_err")
    err = None if raw_err is None else np.asarray(raw_err, dtype=float)
    domain = payload.get("domain")
    if domain not in ("mag", "flux"):
        raise ValueError(f"Unknown residual domain: {domain!r}")

    jd_a = plot_x_to_jd(anchor_a[0], time_axis_mode, display_epoch)
    jd_b = plot_x_to_jd(anchor_b[0], time_axis_mode, display_epoch)
    y_a = float(anchor_a[1])
    y_b = float(anchor_b[1])
    if jd_bounds is not None:
        lo, hi = sorted((float(jd_bounds[0]), float(jd_bounds[1])))
    else:
        finite_jd = jd[np.isfinite(jd)]
        if finite_jd.size == 0:
            raise ValueError("Local tilt window contains no plot-2 points.")
        lo, hi = float(np.min(finite_jd)), float(np.max(finite_jd))
    mask = np.isfinite(jd) & np.isfinite(residual) & (jd >= lo) & (jd <= hi)
    if not np.any(mask):
        raise ValueError("Local tilt window contains no plot-2 points.")

    try:
        line = line_y_at_jd(jd[mask], jd_a, y_a, jd_b, y_b)
    except PipeException as exc:
        raise ValueError(str(exc)) from exc

    updated_y = residual.copy()
    updated_y[mask] = detrend_observed(residual[mask], line, domain)
    updated_err = None
    if err is not None:
        updated_err = err.copy()
        updated_err[mask] = detrended_standard_error(
            residual[mask], line, err[mask], domain
        )

    n_hit = int(np.count_nonzero(mask))
    tilts = list(payload.get("tilts") or [])
    tilts.append(
        {
            "jd_a": float(jd_a),
            "jd_b": float(jd_b),
            "y_a": y_a,
            "y_b": y_b,
            "jd_lo": lo,
            "jd_hi": hi,
            "n_updated": n_hit,
        }
    )
    logger.info(
        "Local tilt applied to %s of %s plot-2 point(s) (origin=%s)",
        n_hit,
        int(jd.size),
        payload.get("origin"),
    )
    return pack_detrend_payload(
        times=jd,
        residual=updated_y,
        residual_err=updated_err,
        domain=domain,
        method=payload.get("method") or "copy",
        fill=payload.get("fill"),
        origin=payload.get("origin") or DETREND_ORIGIN_SMOOTH,
        tilts=tilts,
    )
