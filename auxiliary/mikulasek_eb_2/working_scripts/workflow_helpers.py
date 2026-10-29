"""Shared helpers for Mikulasek spike workflows (fit diagnostics and plots)."""

from __future__ import annotations

import logging

import matplotlib.pyplot as plt
import numpy as np
from astropy.time import Time

from eb_tuning import binned_residuals
from mikulasek_eb import EBModel, FitResult, _Nuisance, phase

logger = logging.getLogger(__name__)

# Phase half-width for out-of-eclipse residual clip (cycles).
OUT_OF_ECLIPSE_PHASE_HALF = 0.12

# Primary zoom panel: |phase| < this (cycles).
PRIMARY_PHASE_ZOOM_HALF = 0.12

# Plot styling: single-component vs adopted template.
LINE_SINGLE_COLOUR = "#5b6b7a"
LINE_SINGLE_WIDTH = 1.5
LINE_ADOPTED_COLOUR = "#ff2e2e"
# Fold/zoom overlay can stay a bit thicker than the time-series line.
LINE_ADOPTED_WIDTH = 2.0
# Time-series fit: thin enough not to hide 10-min / 2-min points.
LINE_TIME_SERIES_WIDTH = 0.8

# Full folded panel (not the primary zoom): two cycles so Min II at ±0.5 is interior.
FOLD_PHASE_MIN = -1.0
FOLD_PHASE_MAX = 1.0
FOLD_PHASE_GRID_N = 4000


def absolute_jd_to_mjd(t_jd: np.ndarray | float) -> np.ndarray:
    """Convert absolute Julian Date to Modified Julian Date for LM fitting.

    Args:
        t_jd (ndarray or float): Absolute JD (J0 = 0).

    Returns:
        ndarray: MJD (same shape as input).
    """
    return np.asarray(Time(t_jd, format="jd").mjd, dtype=float)


def complete_template(p: dict, model: EBModel) -> dict:
    """Fill every key the model can use so staged fits never drop a term.

    Args:
        p (dict): Partial template dict.
        model (EBModel): Model that defines harmonics and O'Connell.

    Returns:
        dict: Copy with C, optional D2/G2/C2, H_k and S1 present.
    """
    q = dict(p)
    q.setdefault("C1", 0.0)
    q.setdefault("D2", q["D1"])
    q.setdefault("G2", q["G1"])
    q.setdefault("C2", q.get("C1", 0.0))
    for k in model.harmonics:
        q.setdefault(f"H{k}", 0.0)
    if model.ocon:
        q.setdefault("S1", 0.0)
    return q


def two_component_degenerate(p: dict, k: int, depth: float) -> bool:
    """True if A and Ab have opposite sign and each exceeds the eclipse depth.

    Args:
        p (dict): Template including optional ``A{k}b``.
        k (int): Eclipse index (1 or 2).
        depth (float): Single-component depth of that eclipse (mag).

    Returns:
        bool: Degenerate pair.
    """
    a, ab = p[f"A{k}"], p[f"A{k}b"]
    return (a * ab < 0.0) and (abs(a) > abs(depth)) and (abs(ab) > abs(depth))


def out_of_eclipse_phase_mask(theta: np.ndarray, half: float = OUT_OF_ECLIPSE_PHASE_HALF) -> np.ndarray:
    """Boolean mask of points away from both eclipse centres.

    Args:
        theta (ndarray): Fitted phase (cycles).
        half (float): Half-width around phase 0 and 0.5 (cycles).

    Returns:
        ndarray: True out of eclipse.
    """
    ph = theta - np.round(theta)
    d2 = ph - 0.5
    d2 = d2 - np.round(d2)
    return (np.abs(ph) > half) & (np.abs(d2) > half)


def primary_ripple_mmag(res: np.ndarray, th: np.ndarray) -> float:
    """Peak absolute binned residual around the primary (mmag).

    Args:
        res (ndarray): Residuals (mag).
        th (ndarray): Phase (cycles).

    Returns:
        float: Max |binned mean| in mmag; NaN if empty.
    """
    b = binned_residuals(res, th)
    vals = np.asarray(b["primary"], dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan")
    return float(np.max(np.abs(vals)))


def report_fit(tag: str, r: FitResult, noise: float) -> None:
    """Log one staged-fit attempt: chi-squared, rms vs noise floor, parameters.

    Args:
        tag (str): Attempt label.
        r (FitResult): Global-fit result.
        noise (float): Robust white-noise floor (mag).
    """
    log = logging.getLogger(__name__)
    log.info(
        "[%s] success=%s chi2=%.1f rchi2=%.2f rms=%.5f mag rms/noise=%.2f",
        tag,
        r.success,
        r.chi2,
        r.rchi2,
        r.rms,
        r.rms / noise,
    )
    vals = {**r.p, **r.ephem}
    for n in r.names:
        log.info("  %s = %.6f +- %.6f", n, vals[n], r.err[n])


def predicted_magnitude(t, mag, sig, model, p, ephem, seg, order):
    """Return the global-fit prediction, including per-segment polynomial baselines.

    Args:
        t (ndarray): Time in days (MJD for fits in this project).
        mag (ndarray): Observed magnitudes.
        sig (ndarray): Magnitude uncertainties.
        model (EBModel): Phenomenological eclipse model.
        p (dict): Fitted template parameters.
        ephem (dict): Fitted ephemeris (M0, P0, optional Pdot).
        seg (ndarray): Segment indices used in ``fit_global``.
        order (int): Polynomial degree used in ``fit_global``.

    Returns:
        tuple[ndarray, ndarray, ndarray]: Full prediction ``yhat``, template
        ``F`` (no baselines), and fitted phase ``theta``.
    """
    w = 1.0 / sig
    theta = phase(t, ephem["M0"], ephem["P0"], ephem.get("Pdot", 0.0))
    f_template = model(theta, p)
    nui = _Nuisance(t, w, seg, order)
    yhat = mag - nui.project(w * (mag - f_template)) / w
    return yhat, f_template, theta


def replicate_folded_points(
    phi: np.ndarray,
    *cols: np.ndarray,
    ph_min: float = FOLD_PHASE_MIN,
    ph_max: float = FOLD_PHASE_MAX,
) -> tuple[np.ndarray, ...]:
    """Repeat one orbital cycle of folded points until they fill ``[ph_min, ph_max]``.

    ``phi`` is expected in ``[-0.5, 0.5]``. Integer cycle shifts are appended
    so a secondary minimum that sits on the edge of one cycle appears in the
    interior of a two-cycle window.

    Args:
        phi (ndarray): Folded phase in one cycle.
        *cols (ndarray): Parallel arrays (magnitude, sigma, residuals, ...).
        ph_min (float): Left edge of the display window (cycles).
        ph_max (float): Right edge of the display window (cycles).

    Returns:
        tuple[ndarray, ...]: ``(phi_out, *cols_out)`` restricted to the window.
    """
    k_lo = int(np.floor(ph_min - 0.5))
    k_hi = int(np.ceil(ph_max + 0.5))
    phi_parts = []
    col_parts = [[] for _ in cols]
    for k in range(k_lo, k_hi + 1):
        shifted = phi + k
        keep = (shifted >= ph_min) & (shifted <= ph_max)
        if not np.any(keep):
            continue
        phi_parts.append(shifted[keep])
        for i, col in enumerate(cols):
            col_parts[i].append(col[keep])
    phi_out = np.concatenate(phi_parts)
    extras = tuple(np.concatenate(p) for p in col_parts)
    return (phi_out, *extras)


def plot_global_fit(
    t_jd: np.ndarray,
    mag: np.ndarray,
    sig: np.ndarray,
    yhat: np.ndarray,
    f_template: np.ndarray,
    theta: np.ndarray,
    model: EBModel,
    p_single: dict,
    p_adopted: dict,
    seg: np.ndarray | None,
    title: str,
    timescale: str | None = None,
    save_path: str | None = None,
) -> None:
    """Plot time series, fold, primary zoom, and residuals (matplotlib).

    Overlays single-component and adopted templates when they differ.

    Args:
        t_jd (ndarray): Absolute Julian Date for the time axis.
        mag (ndarray): Observed magnitudes.
        sig (ndarray): Magnitude uncertainties.
        yhat (ndarray): Full prediction from the adopted fit.
        f_template (ndarray): Adopted template without baselines.
        theta (ndarray): Fitted phase (cycles).
        model (EBModel): Fitted model.
        p_single (dict): Single-component template parameters.
        p_adopted (dict): Adopted template parameters.
        seg (ndarray | None): Baseline segment indices.
        title (str): Figure title.
        timescale (str, optional): TIMESYS timescale for the axis label.
        save_path (str, optional): If set, also save the figure to this path.
    """
    phi = theta - np.round(theta)
    phi_grid = np.linspace(FOLD_PHASE_MIN, FOLD_PHASE_MAX, FOLD_PHASE_GRID_N)
    zoom = np.linspace(-PRIMARY_PHASE_ZOOM_HALF, PRIMARY_PHASE_ZOOM_HALF, 2000)
    mag_corr = mag - (yhat - f_template)
    same = p_single is p_adopted or p_single == p_adopted

    fig, axes = plt.subplots(4, 1, figsize=(16, 20), sharex=False)
    ax = axes[0]
    ax.errorbar(
        t_jd,
        mag,
        yerr=sig,
        fmt="o",
        ms=2,
        alpha=0.35,
        elinewidth=0.4,
        capsize=0,
        color="C0",
        zorder=1,
        label="data",
    )
    if seg is None:
        ax.plot(
            t_jd,
            yhat,
            color=LINE_ADOPTED_COLOUR,
            lw=LINE_TIME_SERIES_WIDTH,
            zorder=5,
            label="fit",
        )
    else:
        for i, s in enumerate(np.unique(seg)):
            m = seg == s
            ax.plot(
                t_jd[m],
                yhat[m],
                color=LINE_ADOPTED_COLOUR,
                lw=LINE_TIME_SERIES_WIDTH,
                zorder=5,
                label="fit" if i == 0 else None,
            )
    axis = "Julian Date (d)" if timescale is None else f"Julian Date ({timescale}, d)"
    ax.set_xlabel(axis)
    ax.set_ylabel("Magnitude")
    ax.set_title(title)
    ax.invert_yaxis()
    ax.legend()

    ax = axes[1]
    phi_fold, mag_fold, sig_fold = replicate_folded_points(phi, mag_corr, sig)
    ord_ = np.argsort(phi_fold)
    ax.errorbar(
        phi_fold[ord_],
        mag_fold[ord_],
        yerr=sig_fold[ord_],
        fmt="o",
        ms=2,
        alpha=0.35,
        elinewidth=0.4,
        capsize=0,
        color="C0",
        zorder=1,
        label="baseline-corrected",
    )
    if not same:
        ax.plot(
            phi_grid,
            model(phi_grid, p_single),
            color=LINE_SINGLE_COLOUR,
            lw=LINE_SINGLE_WIDTH,
            zorder=4,
            label="earlier template",
        )
    ax.plot(
        phi_grid,
        model(phi_grid, p_adopted),
        color=LINE_ADOPTED_COLOUR,
        lw=LINE_ADOPTED_WIDTH,
        zorder=5,
        label="adopted fit",
    )
    ax.set_xlabel("Phase")
    ax.set_xlim(FOLD_PHASE_MIN, FOLD_PHASE_MAX)
    ax.set_ylabel("Magnitude (template scale)")
    ax.invert_yaxis()
    ax.legend()

    ax = axes[2]
    in_p = np.abs(phi) < PRIMARY_PHASE_ZOOM_HALF
    ax.errorbar(
        phi[in_p],
        mag_corr[in_p],
        yerr=sig[in_p],
        fmt="o",
        ms=3,
        alpha=0.5,
        elinewidth=0.4,
        capsize=0,
        color="C0",
        zorder=1,
        label="primary",
    )
    ax.plot(
        zoom,
        model(zoom, p_single),
        color=LINE_SINGLE_COLOUR,
        lw=LINE_SINGLE_WIDTH,
        zorder=4,
        label="single-component",
    )
    if not same:
        ax.plot(
            zoom,
            model(zoom, p_adopted),
            color=LINE_ADOPTED_COLOUR,
            lw=LINE_ADOPTED_WIDTH,
            zorder=5,
            label="adopted",
        )
    ax.set_xlabel("Phase (primary)")
    ax.set_ylabel("Magnitude (template scale)")
    ax.invert_yaxis()
    ax.legend()

    ax = axes[3]
    res = mag - yhat
    phi_res, res_fold = replicate_folded_points(phi, res)
    ax.scatter(phi_res, 1e3 * res_fold, s=4, alpha=0.35, zorder=1, label="residual")
    ax.axhline(0.0, color=LINE_ADOPTED_COLOUR, lw=1.2, zorder=5)
    ax.set_xlabel("Phase")
    ax.set_xlim(FOLD_PHASE_MIN, FOLD_PHASE_MAX)
    ax.set_ylabel("Residual (mmag)")
    ax.legend()
    note = (
        "Two-component primary: extension, not Mikulasek (2015)."
        if not same
        else "Single-component template."
    )
    fig.suptitle(note, y=0.995)
    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120, bbox_inches="tight")
    import matplotlib

    if matplotlib.get_backend().lower() != "agg":
        plt.show()
    else:
        plt.close(fig)
