"""Both-walls virtual minima and ASCII ToM files (JD, error).

Numbering follows the standing T0 rule:
``E = round(2*(JD - T0)/P)/2``. T0 is the VOTable epoch, not fitted M0.
Integer E is the eclipse nearest phase 0 of that T0 fold, which need not be
the deeper minimum in the data.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from astropy.time import Time

from eb_tuning import clip_timings, wall_band
from mikulasek_eb import fit_ephemeris, virtual_minima

logger = logging.getLogger(__name__)

# Half-orbit window: quadrature to quadrature; engine caps virtual_minima here.
HALF_ORBIT_WINDOW = 0.25

# Local windows tried for primary/secondary-only files (phase half-width).
LOCAL_WINDOWS = (0.15, 0.10, 0.06)

# Per-event polynomial degree in fit_minimum / virtual_minima.
TIMING_BASELINE_ORDER = 1

# Drop events whose formal sigma exceeds this times the median sigma.
MAX_SIGMA_FACTOR = 5.0

# Column separator in the two-column ASCII files.
COL_SEP = "   "

# Integer E if |E - round(E)| is below this (primary on the T0 fold).
INTEGER_E_ABS_TOL = 1e-6


def mjd_to_jd(t_mjd: np.ndarray | float) -> np.ndarray:
    """Convert MJD to absolute Julian Date (J0 = 0).

    Args:
        t_mjd (ndarray or float): Modified Julian Date.

    Returns:
        ndarray: Julian Date, same shape as the input after ``asarray``.
    """
    t = np.asarray(t_mjd, dtype=float)
    out = np.asarray(Time(np.atleast_1d(t), format="mjd").jd, dtype=float)
    return out.reshape(t.shape)


def eclipse_number_from_t0(t_jd: np.ndarray, t0_jd: float, period: float) -> np.ndarray:
    """Eclipse number from T0: integer primary-on-T0-fold, n+0.5 secondary.

    Args:
        t_jd (ndarray): Times of minima as absolute JD (days).
        t0_jd (float): VOTable epoch as absolute JD.
        period (float): Orbital period (days).

    Returns:
        ndarray: ``E = round(2 (JD - T0) / P) / 2``.
    """
    return np.round(2.0 * (np.asarray(t_jd, dtype=float) - t0_jd) / period) / 2.0


def assign_e_from_t0(vm: dict, t0_jd: float, period: float) -> dict:
    """Replace fitted eclipse numbers by E counted from the VOTable epoch.

    Args:
        vm (dict): Timing arrays; ``T`` must be absolute JD.
        t0_jd (float): Folding T0 as absolute JD.
        period (float): Orbital period (days).

    Returns:
        dict: Copy with ``E`` from T0.
    """
    out = {k: np.asarray(v) for k, v in vm.items()}
    out["E"] = eclipse_number_from_t0(out["T"], t0_jd, period)
    return out


def is_primary_on_t0_fold(e_num: np.ndarray) -> np.ndarray:
    """True for integer E (eclipse nearest phase 0 of the T0 fold).

    Args:
        e_num (ndarray): Eclipse numbers E.

    Returns:
        ndarray: Boolean mask.
    """
    e_num = np.asarray(e_num, dtype=float)
    return np.abs(e_num - np.round(e_num)) < INTEGER_E_ABS_TOL


def empty_timings() -> dict:
    """Return an empty virtual-minima dict.

    Returns:
        dict: Zero-length arrays.
    """
    return {k: np.array([]) for k in ("E", "T", "sigma", "delta", "n", "rchi2")}


def has_timings(vm: dict | None) -> bool:
    """True if ``vm`` contains at least one time of minimum.

    Args:
        vm (dict | None): Timing arrays, or None.

    Returns:
        bool: Whether any events are present.
    """
    return vm is not None and len(np.asarray(vm.get("T", []))) > 0


def select_eclipses(vm: dict, which: str) -> dict:
    """Keep T0-fold primary, secondary, or all events.

    Args:
        vm (dict): Timing arrays with E from T0.
        which (str): ``all``, ``primary``, or ``secondary``.

    Returns:
        dict: Filtered copy (may be empty).

    Raises:
        ValueError: If ``which`` is unknown.
    """
    n = len(np.asarray(vm.get("E", [])))
    if n == 0:
        return empty_timings()
    if which == "all":
        keep = np.ones(n, dtype=bool)
    elif which == "primary":
        keep = is_primary_on_t0_fold(vm["E"])
    elif which == "secondary":
        keep = ~is_primary_on_t0_fold(vm["E"])
    else:
        raise ValueError(f"Unknown eclipse selection {which!r}.")
    return {k: np.asarray(v)[keep] for k, v in vm.items()}


def clean_timings(vm: dict, deg: int = 1) -> dict:
    """Drop huge-sigma events and clip 4-sigma outliers about a linear ephemeris.

    Args:
        vm (dict): Timing arrays.
        deg (int): Ephemeris degree for clipping.

    Returns:
        dict: Cleaned timing arrays (empty if nothing survives).
    """
    if not has_timings(vm):
        return empty_timings()
    good = vm["sigma"] < MAX_SIGMA_FACTOR * np.median(vm["sigma"])
    vm = {k: np.asarray(v)[good] for k, v in vm.items()}
    if len(vm["T"]) == 0:
        logger.warning("No events remain after the median-sigma cut.")
        return empty_timings()
    keep = clip_timings(vm, deg=deg)
    vm = {k: np.asarray(v)[keep] for k, v in vm.items()}
    if len(vm["T"]) == 0:
        logger.warning("No events remain after 4-sigma ephemeris clipping.")
        return empty_timings()
    return vm


def time_both_walls(
    t_mjd,
    mag,
    sig,
    model,
    r,
    window: float,
    which: str,
    t0_jd: float,
    period: float,
    *,
    require_contact_walls: bool = True,
    clip_outliers: bool = True,
) -> dict:
    """Time eclipses; convert T to JD and number E from T0.

    ``require_contact_walls=True`` applies the 90%-10% ingress/egress point
    count (``wall_band``). ``False`` keeps every event that has observations
    on both sides of the predicted mid-eclipse (``min_each_side`` in
    ``virtual_minima``).

    Args:
        t_mjd (ndarray): Optimiser times (MJD).
        mag (ndarray): Magnitudes.
        sig (ndarray): Catalogue magnitude uncertainties.
        model: Frozen ``EBModel``.
        r: Global fit (template and ephemeris in MJD).
        window (float): Phase half-width (capped at 0.25 by ``virtual_minima``).
        which (str): ``all``, ``primary``, or ``secondary`` on the T0 fold.
        t0_jd (float): VOTable epoch as absolute JD.
        period (float): Period used to number E (VOTable PARAM, days).
        require_contact_walls (bool): If True, require sampled 90%-10% walls.
        clip_outliers (bool): If True, 5x-median sigma and 4-sigma O-C clip.

    Returns:
        dict: Timings with ``T`` as absolute JD and E from T0.
    """
    wb = wall_band(model, r.p) if require_contact_walls else None
    vm = virtual_minima(
        t_mjd,
        mag,
        sig,
        model,
        r.p,
        r.ephem,
        window=window,
        order=TIMING_BASELINE_ORDER,
        free=(),
        wall_band=wb,
    )
    if not has_timings(vm):
        logger.warning("No events at window=%.2f (%s).", window, which)
        return empty_timings()
    vm = {k: np.asarray(v) for k, v in vm.items()}
    vm["T"] = mjd_to_jd(vm["T"])
    vm = assign_e_from_t0(vm, t0_jd, period)
    vm = select_eclipses(vm, which)
    out = clean_timings(vm) if clip_outliers else vm
    if not has_timings(out):
        logger.warning("No %s events left at window=%.2f.", which, window)
    return out


def choose_local_window(
    t_mjd,
    mag,
    sig,
    model,
    r,
    which: str,
    t0_jd: float,
    period: float,
) -> tuple[float | None, dict]:
    """Pick the local window with the smallest O-C rms (both-walls only).

    Args:
        t_mjd (ndarray): Optimiser times (MJD).
        mag (ndarray): Magnitudes.
        sig (ndarray): Uncertainties.
        model: Frozen template.
        r: Global fit.
        which (str): ``primary`` or ``secondary`` on the T0 fold.
        t0_jd (float): VOTable epoch as absolute JD.
        period (float): Period (days).

    Returns:
        tuple[float | None, dict]: Chosen window and timings, or (None, empty).
    """
    rows = []
    by_w = {}
    logger.info("local window scan (%s, both-walls only)", which)
    for w in LOCAL_WINDOWS:
        v = time_both_walls(t_mjd, mag, sig, model, r, w, which, t0_jd, period)
        if not has_timings(v):
            logger.info("  window=%.2f  N=0 (skip)", w)
            continue
        _, res, _ = fit_ephemeris(v["T"], v["sigma"], v["E"], deg=1)
        med_s = 86400.0 * np.median(v["sigma"])
        oc_rms = 86400.0 * res.std()
        logger.info(
            "  window=%.2f  N=%s  med.sigma=%.1f s  O-C rms=%.1f s",
            w,
            len(v["T"]),
            med_s,
            oc_rms,
        )
        rows.append((w, oc_rms))
        by_w[w] = v
    if not rows:
        logger.warning("No local window with both-walls %s events.", which)
        return None, empty_timings()
    win = min(rows, key=lambda row: row[1])[0]
    logger.info("Chosen local window for %s: %.2f (smallest O-C rms)", which, win)
    return win, by_w[win]


def write_timing_ascii(
    path: Path,
    vm: dict,
    *,
    lightcurve: Path,
    period: float,
    t0_jd: float,
    method: str,
    window: float,
    events: str,
    extra_comments: list[str],
    timescale: str | None = None,
    coverage_line: str = (
        "coverage: observations on both sides of mid-eclipse; "
        "90-10 percent contact wall_band not required"
    ),
) -> None:
    """Write times of minima as two-column ASCII (JD, error in days).

    Args:
        path (Path): Output file.
        vm (dict): Cleaned timings (T, sigma in absolute JD days).
        lightcurve (Path): Source VOTable.
        period (float): Period used for O-C numbering (days).
        t0_jd (float): T0 as absolute JD.
        method (str): Timing method label.
        window (float): Phase window used.
        events (str): Which eclipses are in the file.
        extra_comments (list[str]): Extra metadata lines (without the hash).
        timescale (str, optional): TIMESYS timescale for the header.
        coverage_line (str): Header line describing the coverage cut.
    """
    if not has_timings(vm):
        logger.warning("skip %s: no timings to write", path)
        return
    jd = np.asarray(vm["T"], dtype=float)
    err = np.asarray(vm["sigma"], dtype=float)
    order = np.argsort(jd)
    ts_label = timescale if timescale else "undeclared"
    lines = [
        f"# lightcurve: {lightcurve}",
        f"# period_days: {period}",
        f"# t0_jd: {t0_jd:.10f}",
        "# folding: E = round(2*(JD-T0)/P)/2 from the VOTable epoch T0",
        "# T0 is the numbering origin, not required to be Min I in this light curve",
        "# integer E: eclipse nearest phase 0 of that T0 fold; n+0.5: nearest 0.5",
        f"# method: {method}",
        f"# window_phase: {window}",
        f"# events: {events}",
        f"# {coverage_line}",
        f"# timing_baseline_order: {TIMING_BASELINE_ORDER}",
        f"# time_system: Julian Date, J0=0 (TIMESYS timescale={ts_label})",
        "# columns: jd   error_of_time_of_minimum",
        "# units: day   day",
        "# quoted errors are formal fit sigma, not empirical O-C scatter",
    ]
    for c in extra_comments:
        lines.append(f"# {c}")
    for i in order:
        lines.append(f"{jd[i]:.10f}{COL_SEP}{err[i]:.10f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("wrote %s N=%s", path, len(order))
