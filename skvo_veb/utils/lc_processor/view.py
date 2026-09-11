"""Working-curve view helpers for the Lightcurve processor page.

Cropping is for plots (and later fits) only. The session-cached ``CurveDash``
is not mutated here.
"""

from __future__ import annotations

import logging

import numpy as np

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, TIME_AXIS_MJD, normalize_time_axis_mode
from skvo_veb.utils.lc_interaction import plot_x_to_jd

logger = logging.getLogger(__name__)


def display_mjd_to_absolute_jd(value) -> float | None:
    """Converts a crop widget MJD offset to absolute Julian Date.

    Args:
        value: Display MJD (``JD − DEFAULT_EPOCH_JD``), or empty.

    Returns:
        float | None: Absolute JD, or ``None`` when the bound is unset.
    """
    if value is None or value == "":
        return None
    return plot_x_to_jd(float(value), TIME_AXIS_MJD, DEFAULT_EPOCH_JD)


def raw_labels(lcd: CurveDash) -> np.ndarray:
    """Returns the label column without stringifying missing cells.

    Args:
        lcd (CurveDash): Working light curve.

    Returns:
        numpy.ndarray: Object array of raw label cells.
    """
    n = 0 if lcd.lightcurve is None else int(len(lcd.lightcurve))
    if lcd.lightcurve is None or "label" not in lcd.lightcurve.columns:
        return np.full(n, None, dtype=object)
    return lcd.lightcurve["label"].to_numpy(dtype=object)


def timescale_refposition(lcd: CurveDash) -> tuple[str | None, str | None]:
    """Reads TIMESYS labels from ``CurveDash`` metadata.

    Args:
        lcd (CurveDash): Working light curve.

    Returns:
        tuple: ``(timescale, refposition)``.
    """
    meta = lcd.metadata or {}
    envelope = meta.get("vo_envelope") or {}
    return lcd.timescale, envelope.get("refposition")


def plot_uirevision(
    lcd: CurveDash | None,
    filename: str | None,
    domain: str,
    time_axis_mode: str,
) -> str:
    """Returns Plotly ``uirevision`` so zoom is kept without a zoom store.

    Selection flags are not included. Delete changes the row count or JD span.

    Args:
        lcd (CurveDash | None): Working light curve, or ``None`` when empty.
        filename (str | None): Upload name.
        domain (str): ``mag`` or ``flux``.
        time_axis_mode (str): ``mjd`` or ``date``.

    Returns:
        str: Revision token for both plots.
    """
    axis = normalize_time_axis_mode(time_axis_mode)
    name = ""
    data = "n=0"
    if lcd is not None and lcd.lightcurve is not None and not lcd.lightcurve.empty:
        jd = lcd.lightcurve["jd"]
        data = f"n={len(lcd.lightcurve)}|{float(jd.min()):.8f}|{float(jd.max()):.8f}"
        meta = lcd.metadata or {}
        name = meta.get("lookup_name") or meta.get("name") or ""
    return f"{filename or 'lc'}|{name}|{domain}|x={axis}|{data}"


def selected_perm_indices(lcd: CurveDash) -> list[int]:
    """Returns permanent indices marked ``selected=1``.

    Args:
        lcd (CurveDash): Working light curve.

    Returns:
        list[int]: Selected ``perm_index`` values.
    """
    df = lcd.lightcurve
    if df is None or "selected" not in df.columns or "perm_index" not in df.columns:
        return []
    mask = df["selected"] == 1
    return [int(v) for v in df.loc[mask, "perm_index"].tolist()]


def crop_curvedash_copy(
    lcd: CurveDash,
    t_min_jd: float | None,
    t_max_jd: float | None,
) -> CurveDash:
    """Returns a copy of ``lcd`` restricted to inclusive absolute-JD bounds.

    ``perm_index`` is preserved so plot selection still maps onto the cached
    series. An empty or inverted crop fails fast.

    Args:
        lcd (CurveDash): Working light curve (not mutated).
        t_min_jd (float | None): Inclusive lower bound, or ``None``.
        t_max_jd (float | None): Inclusive upper bound, or ``None``.

    Returns:
        CurveDash: Copy, cropped when bounds are set.

    Raises:
        ValueError: If the curve is empty, the crop is inverted, or no points
            remain.
    """
    view = CurveDash.from_serialized(lcd.serialize())
    df = view.lightcurve
    if df is None or df.empty:
        raise ValueError("No light curve is loaded.")
    if t_min_jd is None and t_max_jd is None:
        return view
    if t_min_jd is not None and t_max_jd is not None and t_min_jd > t_max_jd:
        raise ValueError("t min must be ≤ t max.")
    jd = df["jd"].to_numpy(dtype=float)
    keep = np.ones(len(df), dtype=bool)
    if t_min_jd is not None:
        keep &= jd >= float(t_min_jd)
    if t_max_jd is not None:
        keep &= jd <= float(t_max_jd)
    if not np.any(keep):
        raise ValueError("No points remain in the requested time crop.")
    view.lightcurve = df.loc[keep].copy()
    logger.debug("Cropped view to %s of %s points", int(np.count_nonzero(keep)), len(df))
    return view
