"""Diagnostic figures for the template-epoch spike."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

_TIMING = Path(__file__).resolve().parents[1]
if str(_TIMING) not in sys.path:
    sys.path.insert(0, str(_TIMING))

from plot_style import FIGSIZE_TEMPLATE, apply_plot_style

from epoch_core import EpochSpikeResult
from epoch_io import days_to_seconds

logger = logging.getLogger(__name__)


def _save_or_show(fig, path: Path, *, dpi: int, show: bool) -> None:
    """Save a figure and optionally display it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi)
    logger.info("Wrote %s", path)
    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_template_marks(
    result: EpochSpikeResult,
    path: Path,
    *,
    dpi: int,
    show: bool,
) -> None:
    """GP mean with GP-argmin, KvW, and core-bisector marks.

    Args:
        result (EpochSpikeResult): Estimator output.
        path (Path): PNG path.
        dpi (int): Figure resolution.
        show (bool): Call ``plt.show()`` when true.
    """
    apply_plot_style()
    tmpl = result.template
    mask = (tmpl.tau >= result.copy_lo) & (tmpl.tau <= result.copy_hi)
    fig, ax = plt.subplots(figsize=FIGSIZE_TEMPLATE)
    ax.fill_between(
        tmpl.tau[mask],
        tmpl.mu[mask] - tmpl.sigma[mask],
        tmpl.mu[mask] + tmpl.sigma[mask],
        color="tab:blue",
        alpha=0.25,
        label="GP +/-1 sigma",
    )
    ax.plot(tmpl.tau[mask], tmpl.mu[mask], color="tab:blue", lw=2, label="GP mean")
    ax.axhline(result.continuum, color="0.5", ls=":", lw=1.2, label="continuum")
    ax.axhline(result.bottom, color="0.5", ls="-.", lw=1.2, label="bottom")
    ax.axvspan(
        result.kvw.tau - result.kvw_half_width_days,
        result.kvw.tau + result.kvw_half_width_days,
        color="tab:orange",
        alpha=0.12,
        label="KvW core",
    )
    ax.axvline(
        result.tau_gp_argmin,
        color="magenta",
        ls="--",
        lw=1.6,
        label=f"GP argmin {result.tau_gp_argmin:.5f} d",
    )
    ax.axvline(
        result.kvw.tau,
        color="tab:green",
        ls="-",
        lw=1.6,
        label=f"KvW {result.kvw.tau:.5f} d",
    )
    ax.axvline(
        result.bisector.tau_core,
        color="tab:red",
        ls="--",
        lw=1.4,
        label=f"bisector core {result.bisector.tau_core:.5f} d",
    )
    ax.set_xlabel("tau (days from phase 0)")
    ax.set_ylabel("normalised flux")
    ax.set_title("Template epoch marks")
    ax.legend()
    fig.tight_layout()
    _save_or_show(fig, path, dpi=dpi, show=show)


def plot_bisector_ladder(
    result: EpochSpikeResult,
    path: Path,
    *,
    dpi: int,
    show: bool,
) -> None:
    """Bisector time versus eclipse depth.

    Args:
        result (EpochSpikeResult): Estimator output.
        path (Path): PNG path.
        dpi (int): Figure resolution.
        show (bool): Call ``plt.show()`` when true.
    """
    apply_plot_style()
    depths = np.asarray([row.depth for row in result.bisector.levels], dtype=float)
    tau_bis = np.asarray([row.tau_bis for row in result.bisector.levels], dtype=float)
    sigma = np.asarray(
        [row.sigma_tau_bis for row in result.bisector.levels], dtype=float
    )
    fig, ax = plt.subplots(figsize=FIGSIZE_TEMPLATE)
    ax.errorbar(
        tau_bis,
        depths,
        xerr=sigma,
        fmt="o",
        color="tab:blue",
        capsize=3,
        label="bisector levels",
    )
    ax.axvline(result.tau_gp_argmin, color="magenta", ls="--", label="GP argmin")
    ax.axvline(result.kvw.tau, color="tab:green", ls="-", label="KvW")
    ax.axvline(
        result.bisector.tau_core, color="tab:red", ls="--", label="weighted core mean"
    )
    ax.axvline(
        result.bisector.tau_extrap_floor,
        color="tab:purple",
        ls=":",
        label="linear extrap. to floor",
    )
    ax.set_xlabel("bisector tau (days)")
    ax.set_ylabel("eclipse depth (0 = continuum, 1 = bottom)")
    ax.set_title(
        f"Bisector ladder; core slope "
        f"{days_to_seconds(result.bisector.slope_days_per_depth):.2f} s per unit depth"
    )
    ax.invert_yaxis()
    ax.legend()
    fig.tight_layout()
    _save_or_show(fig, path, dpi=dpi, show=show)


def plot_kvw_cost(
    result: EpochSpikeResult,
    path: Path,
    *,
    dpi: int,
    show: bool,
) -> None:
    """Kwee-van Woerden cost versus trial centre.

    Args:
        result (EpochSpikeResult): Estimator output.
        path (Path): PNG path.
        dpi (int): Figure resolution.
        show (bool): Call ``plt.show()`` when true.
    """
    apply_plot_style()
    kvw = result.kvw
    fig, ax = plt.subplots(figsize=FIGSIZE_TEMPLATE)
    ax.plot(kvw.scan_tau, kvw.scan_cost, color="tab:blue", lw=2, label="KvW cost")
    ax.axvline(result.tau_gp_argmin, color="magenta", ls="--", label="GP argmin")
    ax.axvline(kvw.tau, color="tab:green", ls="-", label="KvW minimiser")
    ax.axvline(kvw.tau_parabola, color="tab:orange", ls=":", label="parabola vertex")
    ax.set_xlabel("trial centre tau (days)")
    ax.set_ylabel("KvW cost")
    ax.set_title(
        f"KvW cost; offset {result.delta_kvw_minus_argmin_s:.2f} s from GP argmin"
    )
    ax.legend()
    fig.tight_layout()
    _save_or_show(fig, path, dpi=dpi, show=show)


def plot_branch_overlay(
    result: EpochSpikeResult,
    path: Path,
    *,
    dpi: int,
    show: bool,
) -> None:
    """Ingress vs egress GP mean about GP-argmin and about KvW.

    Args:
        result (EpochSpikeResult): Estimator output.
        path (Path): PNG path.
        dpi (int): Figure resolution.
        show (bool): Call ``plt.show()`` when true.
    """
    apply_plot_style()
    tmpl = result.template
    lags = result.kvw.lags
    fig, axes = plt.subplots(1, 2, figsize=FIGSIZE_TEMPLATE, sharey=True)
    centres = (
        (result.tau_gp_argmin, "GP argmin", axes[0]),
        (result.kvw.tau, "KvW", axes[1]),
    )
    for tau0, title, ax in centres:
        left = tmpl.mu_spline(tau0 - lags)
        right = tmpl.mu_spline(tau0 + lags)
        ax.plot(lags, left, color="tab:blue", lw=2, label="ingress (tau0 - lag)")
        ax.plot(lags, right, color="tab:orange", lw=2, label="egress (tau0 + lag)")
        ax.set_xlabel("lag (days)")
        ax.set_title(f"{title}: tau0={tau0:.5f} d")
        ax.legend()
    axes[0].set_ylabel("normalised flux")
    fig.suptitle("Symmetric-branch overlay")
    fig.tight_layout()
    _save_or_show(fig, path, dpi=dpi, show=show)
