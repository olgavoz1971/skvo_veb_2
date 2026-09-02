"""Matplotlib helpers for the running-parabola spike."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from astropy.modeling import models
from astropy.modeling.fitting import LinearLSQFitter

_plot_style_path = Path(__file__).resolve().with_name("plot_style.py")
_plot_style_spec = importlib.util.spec_from_file_location(
    "running_parabola_spike.plot_style",
    _plot_style_path,
)
if _plot_style_spec is None or _plot_style_spec.loader is None:
    raise ImportError(f"Cannot load plot_style from {_plot_style_path}")
_plot_style = importlib.util.module_from_spec(_plot_style_spec)
_plot_style_spec.loader.exec_module(_plot_style)

FIGSIZE_INTERVAL = _plot_style.FIGSIZE_INTERVAL
FIGSIZE_OVERVIEW = _plot_style.FIGSIZE_OVERVIEW
FONT_SIZE = _plot_style.FONT_SIZE
apply_interval_plot_style = _plot_style.apply_interval_plot_style
apply_plot_style = _plot_style.apply_plot_style
from running_parabola import RunningParabolaConfig, SmoothedPoint
from parabola_tom import ParabolaTomConfig, ParabolaTomResult, effective_fit_half_width
from smooth_extrema import SmoothExtremaResult

logger = logging.getLogger(__name__)


def plot_overview(
    jd: np.ndarray,
    phot: np.ndarray,
    points: list[SmoothedPoint],
    *,
    working_domain: str,
    cfg: RunningParabolaConfig,
    extrema: SmoothExtremaResult | None = None,
    tom: ParabolaTomResult | None = None,
    extremum_kind: str = "min",
    save_path: Path | None = None,
    show: bool = False,
) -> None:
    """Overlay raw data and the smoothed running-parabola curve.

    Args:
        jd (numpy.ndarray): Raw observation times.
        phot (numpy.ndarray): Raw photometry.
        points (list[SmoothedPoint]): Smoothed series.
        working_domain (str): ``mag`` or ``flux``.
        cfg (RunningParabolaConfig): Run settings for the title.
        extrema (SmoothExtremaResult | None): Optional detected extrema to mark.
        tom (ParabolaTomResult | None): Optional parabola-refined extrema to mark.
        extremum_kind (str): ``min`` or ``max`` label for plot legend/title.
        save_path (Path | None): Optional PNG path.
        show (bool): Call ``plt.show()``.

    Returns:
        None.
    """
    apply_plot_style()
    fig, ax = plt.subplots(figsize=FIGSIZE_OVERVIEW)
    kind = str(extremum_kind).strip().lower()
    ext_label = f"{kind}imum" if kind in ("min", "max") else extremum_kind
    ax.scatter(jd, phot, s=50, c="0.55", alpha=0.35, label="raw", zorder=1)
    xs = np.array([p.jd for p in points], dtype=float)
    ys = np.array([p.smooth for p in points], dtype=float)
    ax.plot(xs, ys, color="tab:red", lw=1.4, label="running parabola", zorder=2)
    if tom is not None and tom.n_ok > 0:
        tom_jd = np.array([h.tom_jd for h in tom.hits], dtype=float)
        tom_y = np.array([h.y_ext for h in tom.hits], dtype=float)
        ax.scatter(
            tom_jd,
            tom_y,
            s=280,
            c="red",
            edgecolors="darkred",
            linewidths=1.2,
            label=f"parabola ToM ({ext_label})",
            zorder=10,
        )
    elif extrema is not None and extrema.n_extrema > 0:
        ax.scatter(
            extrema.jd,
            extrema.smooth,
            s=280,
            c="red",
            edgecolors="darkred",
            linewidths=1.2,
            label=f"rough {ext_label}",
            zorder=10,
        )
    y_label = "mag" if working_domain == "mag" else "flux"
    if working_domain == "mag":
        ax.invert_yaxis()
    ax.set_xlabel("JD")
    ax.set_ylabel(y_label)
    title = (
        f"Running parabola smooth ({ext_label}, W={cfg.window_width_d} d, "
        f"step={cfg.step_d} d, weights={cfg.use_weights})"
    )
    if tom is not None and tom.n_ok >= 2:
        tom_jd = np.array([h.tom_jd for h in tom.hits], dtype=float)
        rough_p = float(np.median(np.diff(np.sort(tom_jd))))
        title += f"\nrough P ~ {rough_p:.4f} d ({tom.n_ok} parabola ToM)"
    elif extrema is not None and extrema.median_interval_d is not None:
        title += (
            f"\nrough P ~ {extrema.median_interval_d:.4f} d "
            f"({extrema.n_extrema} rough {ext_label})"
        )
    elif extrema is not None and extrema.n_extrema > 0:
        title += f"\n{extrema.n_extrema} rough {ext_label} (need >=2 for rough P)"
    ax.set_title(title)
    ax.legend(loc="best")
    fig.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote %s", save_path)
    if show:
        plt.show()
    plt.close(fig)


def plot_demo_windows(
    jd: np.ndarray,
    phot: np.ndarray,
    phot_err: np.ndarray,
    centre_indices: list[int],
    points: list[SmoothedPoint],
    *,
    working_domain: str,
    cfg: RunningParabolaConfig,
    save_path: Path | None = None,
    show: bool = False,
) -> None:
    """Show parabola fits and centre marks for selected smoothed-point indices.

    Args:
        jd (numpy.ndarray): Full raw series (same crop as smoothing).
        phot (numpy.ndarray): Raw photometry.
        phot_err (numpy.ndarray): Uncertainties.
        centre_indices (list[int]): Indices into ``points`` to illustrate.
        points (list[SmoothedPoint]): Full smoothed output.
        working_domain (str): ``mag`` or ``flux``.
        cfg (RunningParabolaConfig): Window and weight settings.
        save_path (Path | None): Optional PNG path.
        show (bool): Call ``plt.show()``.

    Returns:
        None.
    """
    if not centre_indices:
        return

    apply_interval_plot_style()
    n = len(centre_indices)
    panel_h = FIGSIZE_INTERVAL[1]
    fig, axes = plt.subplots(n, 1, figsize=(FIGSIZE_INTERVAL[0], panel_h * n), squeeze=False)
    half = 0.5 * cfg.window_width_d
    y_label = "mag" if working_domain == "mag" else "flux"

    for ax, idx in zip(axes.ravel(), centre_indices):
        if idx < 0 or idx >= len(points):
            logger.warning("demo window index %s out of range; skip", idx)
            continue
        pt = points[idx]
        t_c = pt.jd
        mask = (jd >= t_c - half) & (jd <= t_c + half)
        t_win = np.asarray(jd[mask], dtype=float)
        y_win = np.asarray(phot[mask], dtype=float)
        e_win = np.asarray(phot_err[mask], dtype=float)

        ax.scatter(t_win, y_win, s=101, c="k", alpha=0.65, label="in window", zorder=3)
        if t_win.size >= 3:
            dt = t_win - t_c
            poly = models.Polynomial1D(degree=2)
            fitter = LinearLSQFitter()
            weights = None
            if cfg.use_weights:
                finite = np.isfinite(e_win) & (e_win > 0.0)
                if np.count_nonzero(finite) >= 3:
                    inv_var = np.zeros_like(y_win)
                    inv_var[finite] = 1.0 / (e_win[finite] ** 2)
                    weights = inv_var
            fitted = fitter(poly, dt, y_win, weights=weights)
            t_line = np.linspace(float(np.min(t_win)), float(np.max(t_win)), 200)
            dt_line = t_line - t_c
            ax.plot(
                t_line,
                fitted(dt_line),
                color="tab:green",
                lw=2,
                label="parabola",
            )
        ax.axvline(t_c, color="tab:red", ls="--", lw=1.2, alpha=0.8)
        ax.scatter(
            [t_c],
            [pt.smooth],
            s=80,
            facecolors="none",
            edgecolors="tab:red",
            linewidths=2,
            zorder=5,
            label="centre",
        )
        ax.set_xlabel("JD")
        ax.set_ylabel(y_label)
        if working_domain == "mag":
            ax.invert_yaxis()
        ax.set_title(
            f"window #{idx}  centre={t_c:.6f}  c={pt.curvature:.3e}  rms={pt.rms:.3e}"
        )
        ax.legend(loc="best")
    fig.suptitle("Running parabola window fits", fontsize=FONT_SIZE)

    fig.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote %s", save_path)
    if show:
        plt.show()
    plt.close(fig)


def plot_tom_demo_windows(
    jd: np.ndarray,
    phot: np.ndarray,
    phot_err: np.ndarray,
    hit_indices: list[int],
    tom: ParabolaTomResult,
    *,
    working_domain: str,
    tom_cfg: ParabolaTomConfig,
    save_path: Path | None = None,
    show: bool = False,
) -> None:
    """Show parabola ToM fits for selected refined-minimum indices.

    Args:
        jd (numpy.ndarray): Raw observation times.
        phot (numpy.ndarray): Raw photometry.
        phot_err (numpy.ndarray): Per-point uncertainties.
        hit_indices (list[int]): Indices into ``tom.hits`` to illustrate.
        tom (ParabolaTomResult): Parabola ToM refinement output.
        working_domain (str): ``mag`` or ``flux``.
        tom_cfg (ParabolaTomConfig): Fit window and weight settings.
        save_path (Path | None): Optional PNG path.
        show (bool): Call ``plt.show()``.

    Returns:
        None.
    """
    if not hit_indices:
        return

    apply_interval_plot_style()
    n = len(hit_indices)
    panel_h = FIGSIZE_INTERVAL[1]
    fig, axes = plt.subplots(n, 1, figsize=(FIGSIZE_INTERVAL[0], panel_h * n), squeeze=False)
    y_label = "mag" if working_domain == "mag" else "flux"
    rough_jd = np.array([h.rough_jd for h in tom.hits], dtype=float)

    for ax, idx in zip(axes.ravel(), hit_indices):
        if idx < 0 or idx >= len(tom.hits):
            logger.warning("demo ToM index %s out of range; skip", idx)
            continue
        hit = tom.hits[idx]
        t_anchor = hit.rough_jd
        half_w = effective_fit_half_width(
            t_anchor,
            rough_jd,
            fit_half_width_d=tom_cfg.fit_half_width_d,
        )
        mask = (jd >= t_anchor - half_w) & (jd <= t_anchor + half_w)
        t_win = np.asarray(jd[mask], dtype=float)
        y_win = np.asarray(phot[mask], dtype=float)
        e_win = np.asarray(phot_err[mask], dtype=float)

        ax.scatter(t_win, y_win, s=101, c="k", alpha=0.65, label="in window", zorder=3)
        if t_win.size >= 3:
            dt = t_win - t_anchor
            poly = models.Polynomial1D(degree=2)
            fitter = LinearLSQFitter()
            weights = None
            if tom_cfg.use_weights:
                finite = np.isfinite(e_win) & (e_win > 0.0)
                if np.count_nonzero(finite) >= 3:
                    inv_var = np.zeros_like(y_win)
                    inv_var[finite] = 1.0 / (e_win[finite] ** 2)
                    weights = inv_var
            fitted = fitter(poly, dt, y_win, weights=weights)
            t_line = np.linspace(float(np.min(t_win)), float(np.max(t_win)), 200)
            dt_line = t_line - t_anchor
            ax.plot(
                t_line,
                fitted(dt_line),
                color="tab:green",
                lw=2,
                label="parabola",
            )
        ax.axvline(t_anchor, color="0.45", ls=":", lw=1.2, alpha=0.9, label="rough anchor")
        ax.axvline(hit.tom_jd, color="tab:red", ls="--", lw=1.2, alpha=0.8)
        ax.scatter(
            [hit.tom_jd],
            [hit.y_ext],
            s=280,
            c="red",
            edgecolors="darkred",
            linewidths=1.2,
            zorder=5,
            label="ToM",
        )
        ax.set_xlabel("JD")
        ax.set_ylabel(y_label)
        if working_domain == "mag":
            ax.invert_yaxis()
        sigma_s = hit.sigma_t_d * 86400.0
        ax.set_title(
            f"ToM #{idx}  tom={hit.tom_jd:.6f}  σ={sigma_s:.1f}s  "
            f"c={hit.curvature:.3e}  rms={hit.rms:.3e}  n={hit.n_points}"
        )
        ax.legend(loc="best")
    fig.suptitle(
        f"Parabola ToM fits ({tom.extremum_kind}, fit_half_width={tom_cfg.fit_half_width_d} d)",
        fontsize=FONT_SIZE,
    )

    fig.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote %s", save_path)
    if show:
        plt.show()
    plt.close(fig)
