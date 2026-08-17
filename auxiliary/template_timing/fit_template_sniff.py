"""Step 2: fit GP template per rough interval (CC and NLS); report t_max."""

from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import matplotlib.pyplot as plt
import numpy as np

from skvo_veb.utils.gp.intervals import load_intervals

from lc_flux import load_lc_window, photometry_to_normalised_flux
from plot_style import FIGSIZE_INTERVAL, FONT_SIZE, apply_interval_plot_style
from fit_mask import resolve_fit_mask
from template_fit import (
    IntervalFitContext,
    ShiftFitResult,
    TemplateCurve,
    fit_cross_correlation,
    fit_nonlinear_least_squares,
    fit_nls_iterative_outlier_clean,
    fit_nls_scale_iterative_outlier_clean,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
LC_PATH = ROOT / "data" / "R_detrended.dat"
TEMPLATE_NPZ = ROOT / "data" / "template.npz"
TEMPLATE_META = ROOT / "data" / "template_meta.json"
INTERVALS_PATH = ROOT / "data" / "intervals.dat"
OUT_DIR = ROOT / "data" / "fits"
OUT_TEMPLATE_PREVIEW = ROOT / "data" / "template_preview.png"
OUT_SUMMARY = ROOT / "data" / "fit_summary.csv"

T_REF = 59866.41
# P0 = 0.06066
P0 = 0.0591
# T_OBS_MIN = 59866.0
# T_OBS_MAX = 59866.7
T_OBS_MIN = 59857.0
T_OBS_MAX = 59857.7
JD_OFFSET_ZERO = 2400000.0
WORKING_DOMAIN = "mag"

# Step 2 fit window around the peak: whole_period, or frac_period with a phase half-width.
FIT_MASK_MODE = "whole_period"
FIT_MASK_HALF_WIDTH_PHASE = 0.25

# Search half-width for phase shift (days), plus margin from interval span in tau.
DELTA_TAU_MARGIN = 0.003
DELTA_TAU_MAX = 0.02

OUTLIER_MAD_K = 3.0
OUTLIER_MAX_ITER = 8
OUTLIER_MIN_INLIERS = 8


def _apply_plot_style() -> None:
    apply_interval_plot_style()


def load_template_bundle() -> tuple[TemplateCurve, dict]:
    """Load template grid and metadata written by ``build_template``."""
    meta = json.loads(TEMPLATE_META.read_text(encoding="utf-8"))
    data = np.load(TEMPLATE_NPZ)
    curve = TemplateCurve(
        data["tau"],
        data["mu"],
        float(data["tau_peak"]),
        tau_data_min=float(meta["tau_data_min"]),
        tau_data_max=float(meta["tau_data_max"]),
    )
    return curve, meta


def _fit_mask(meta: dict, tau_peak: float):
    """Resolve the fit window from module constants and the template fold period."""
    return resolve_fit_mask(
        mode=FIT_MASK_MODE,
        half_width_phase=FIT_MASK_HALF_WIDTH_PHASE,
        period=float(meta.get("fold_period", meta["p0"])),
        tau_peak=tau_peak,
    )


def plot_template_preview(
    curve: TemplateCurve,
    meta: dict,
    *,
    save_path: Path,
) -> None:
    """Show saved template with tau mask used in fits."""
    mask = _fit_mask(meta, curve.tau_peak)
    tau_mask_min, tau_mask_max = mask.tau_min, mask.tau_max
    data = np.load(TEMPLATE_NPZ)
    tau = data["tau"]
    mu = data["mu"]
    fig, ax = plt.subplots(figsize=(20, 12))
    ax.plot(tau, mu, color="tab:blue", lw=2, label="template mu(tau)")
    ax.axvline(curve.tau_peak, color="magenta", ls="--", label=f"tau_peak={curve.tau_peak:.5f}")
    ax.axvspan(tau_mask_min, tau_mask_max, color="C1", alpha=0.15, label="tau mask for fits")
    ax.set_xlabel("tau (days)")
    ax.set_ylabel("normalised flux")
    ax.set_title("Template (Step 1) and fit mask")
    ax.legend()
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150)
    logger.info("Wrote %s", save_path)
    plt.show()


def _delta_t_bounds(t_start: float, t_end: float) -> tuple[float, float]:
    span = max(t_end - t_start, 1e-9)
    half = min(DELTA_TAU_MAX, 0.5 * span + DELTA_TAU_MARGIN)
    return -half, half


def _model_flux_on_jd_grid(
    t_line: np.ndarray,
    curve: TemplateCurve,
    fit: ShiftFitResult,
) -> tuple[np.ndarray, np.ndarray]:
    dt = t_line - fit.t_max
    mu = curve.eval_from_peak(dt)
    ok = np.isfinite(mu)
    return t_line[ok], (fit.scale * mu[ok] + fit.delta_y)


def _plot_fit_panel(
    ax,
    t: np.ndarray,
    y: np.ndarray,
    curve: TemplateCurve,
    fit: ShiftFitResult,
    t_start: float,
    t_end: float,
    title: str,
) -> None:
    inlier = fit.inlier_mask
    if inlier is not None and len(inlier) == len(t):
        ax.scatter(t[inlier], y[inlier], s=40, c="k", alpha=0.75, label="inliers")
        if np.any(~inlier):
            ax.scatter(
                t[~inlier],
                y[~inlier],
                s=60,
                facecolors="none",
                edgecolors="red",
                linewidths=1.5,
                label="rejected outliers",
            )
    else:
        ax.scatter(t, y, s=40, c="k", alpha=0.75, label="data")
    t_line = np.linspace(t_start, t_end, 300)
    t_ok, y_model = _model_flux_on_jd_grid(t_line, curve, fit)
    ax.plot(t_ok, y_model, color="tab:blue", lw=2, label="template + shift")
    ax.axvline(fit.t_max, color="magenta", ls="--", label=f"t_max={fit.t_max:.6f}")
    ax.set_xlim(t_start, t_end)
    ax.set_xlabel("time (LC units)")
    ax.set_ylabel("normalised flux")
    ax.set_title(
        f"{title}\nRMS={fit.rms:.4f}, n={fit.n_used}, "
        f"delta_t={fit.delta_t * 86400:.1f}s, s={fit.scale:.3f}"
    )
    ax.legend()


def plot_interval_fits(
    index: int,
    t_start: float,
    t_end: float,
    t: np.ndarray,
    y: np.ndarray,
    curve: TemplateCurve,
    cc: ShiftFitResult,
    nls: ShiftFitResult,
    nls_clean: ShiftFitResult,
    nls_scale_clean: ShiftFitResult,
    *,
    save_path: Path,
) -> None:
    """CC, NLS, cleaned NLS, and scaled+cleaned NLS for one cycle."""
    fig, (ax_cc, ax_nls, ax_clean, ax_scale) = plt.subplots(
        1, 4, figsize=FIGSIZE_INTERVAL, sharey=True
    )
    _plot_fit_panel(
        ax_cc, t, y, curve, cc, t_start, t_end, "Cross-correlation"
    )
    _plot_fit_panel(
        ax_nls, t, y, curve, nls, t_start, t_end, "Nonlinear least squares"
    )
    _plot_fit_panel(
        ax_clean,
        t,
        y,
        curve,
        nls_clean,
        t_start,
        t_end,
        "NLS + iterative outlier clean",
    )
    _plot_fit_panel(
        ax_scale,
        t,
        y,
        curve,
        nls_scale_clean,
        t_start,
        t_end,
        "NLS + scale + outlier clean",
    )
    fig.suptitle(f"Interval {index}: [{t_start:.5f}, {t_end:.5f}]", fontsize=FONT_SIZE)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    logger.info("Wrote %s", save_path)
    plt.show()


def main() -> None:
    _apply_plot_style()
    logging.basicConfig(level=logging.INFO)

    curve, meta = load_template_bundle()
    mask = _fit_mask(meta, curve.tau_peak)
    dt_min, dt_max = mask.dt_min, mask.dt_max

    plot_template_preview(curve, meta, save_path=OUT_TEMPLATE_PREVIEW)

    piece, lc_meta = load_lc_window(
        LC_PATH,
        JD_OFFSET_ZERO + T_OBS_MIN,
        JD_OFFSET_ZERO + T_OBS_MAX,
        working_domain=WORKING_DOMAIN,
    )
    norm = photometry_to_normalised_flux(
        piece,
        lc_meta,
        float(meta["baseline_flux"]),
        float(meta["ampl_guess_flux"]),
        context="fit_template_sniff",
    )
    t_all = norm["jd"].to_numpy(dtype=float)
    y_all = norm["y_norm"].to_numpy(dtype=float)

    with INTERVALS_PATH.open(encoding="utf-8") as handle:
        intervals = load_intervals(handle)
    if not intervals:
        raise ValueError(f"no intervals in {INTERVALS_PATH}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for idx, (t_start, t_end) in enumerate(intervals):
        if t_start > t_end:
            t_start, t_end = t_end, t_start
        if t_start < T_OBS_MIN or t_end > T_OBS_MAX:
            logger.warning(
                "Interval %s [%.5f, %.5f] extends outside LC cut [%.5f, %.5f]",
                idx,
                t_start,
                t_end,
                T_OBS_MIN,
                T_OBS_MAX,
            )
        mask = (t_all >= t_start) & (t_all <= t_end)
        t = t_all[mask]
        y = y_all[mask]
        if len(t) < 5:
            logger.error("Interval %s: only %s points; skip", idx, len(t))
            continue

        t_centre = 0.5 * (t_start + t_end)
        ctx = IntervalFitContext(t_anchor=t_centre)

        dt_lo, dt_hi = _delta_t_bounds(t_start, t_end)
        cc = fit_cross_correlation(
            curve,
            t,
            y,
            ctx,
            dt_min=dt_min,
            dt_max=dt_max,
            delta_t_min=dt_lo,
            delta_t_max=dt_hi,
        )
        nls = fit_nonlinear_least_squares(
            curve,
            t,
            y,
            ctx,
            dt_min=dt_min,
            dt_max=dt_max,
            delta_t_min=dt_lo,
            delta_t_max=dt_hi,
            delta_t_init=cc.delta_t,
        )
        nls_clean = fit_nls_iterative_outlier_clean(
            curve,
            t,
            y,
            ctx,
            dt_min=dt_min,
            dt_max=dt_max,
            delta_t_min=dt_lo,
            delta_t_max=dt_hi,
            delta_t_init=nls.delta_t,
            mad_k=OUTLIER_MAD_K,
            max_iter=OUTLIER_MAX_ITER,
            min_inliers=OUTLIER_MIN_INLIERS,
        )
        nls_scale_clean = fit_nls_scale_iterative_outlier_clean(
            curve,
            t,
            y,
            ctx,
            dt_min=dt_min,
            dt_max=dt_max,
            delta_t_min=dt_lo,
            delta_t_max=dt_hi,
            delta_t_init=nls_clean.delta_t,
            scale_init=1.0,
            mad_k=OUTLIER_MAD_K,
            max_iter=OUTLIER_MAX_ITER,
            min_inliers=OUTLIER_MIN_INLIERS,
            scale_min=0.05,
            scale_max=5.0,
        )

        plot_interval_fits(
            idx,
            t_start,
            t_end,
            t,
            y,
            curve,
            cc,
            nls,
            nls_clean,
            nls_scale_clean,
            save_path=OUT_DIR / f"interval_{idx:02d}.png",
        )

        n_rejected = (
            int(np.count_nonzero(~nls_clean.inlier_mask))
            if nls_clean.inlier_mask is not None
            else 0
        )
        n_rejected_scale = (
            int(np.count_nonzero(~nls_scale_clean.inlier_mask))
            if nls_scale_clean.inlier_mask is not None
            else 0
        )
        rows.append(
            {
                "interval": idx,
                "t_start": t_start,
                "t_end": t_end,
                "t_anchor": t_centre,
                "n_points": len(t),
                "n_outliers_rejected": n_rejected,
                "n_outliers_rejected_scale": n_rejected_scale,
                "delta_t_cc": cc.delta_t,
                "delta_y_cc": cc.delta_y,
                "t_max_cc": cc.t_max,
                "rms_cc": cc.rms,
                "delta_t_nls": nls.delta_t,
                "delta_y_nls": nls.delta_y,
                "t_max_nls": nls.t_max,
                "rms_nls": nls.rms,
                "delta_t_nls_clean": nls_clean.delta_t,
                "delta_y_nls_clean": nls_clean.delta_y,
                "t_max_nls_clean": nls_clean.t_max,
                "rms_nls_clean": nls_clean.rms,
                "scale_nls_scale_clean": nls_scale_clean.scale,
                "delta_t_nls_scale_clean": nls_scale_clean.delta_t,
                "delta_y_nls_scale_clean": nls_scale_clean.delta_y,
                "t_max_nls_scale_clean": nls_scale_clean.t_max,
                "rms_nls_scale_clean": nls_scale_clean.rms,
                "tau_peak": curve.tau_peak,
            }
        )
        logger.info(
            "Interval %s: t_max clean=%.8f scale_clean=%.8f s=%.3f (outliers=%s/%s)",
            idx,
            nls_clean.t_max,
            nls_scale_clean.t_max,
            nls_scale_clean.scale,
            n_rejected,
            n_rejected_scale,
        )

    if rows:
        with OUT_SUMMARY.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Wrote %s (%s intervals)", OUT_SUMMARY, len(rows))


if __name__ == "__main__":
    main()
