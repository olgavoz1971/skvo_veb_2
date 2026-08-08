"""Step 2: fit template per interval for one manifest piece (library entry point)."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from skvo_veb.utils.gp.intervals import load_intervals

from fold_stack import observation_tau
from lc_flux import load_lc_fragment, mag_to_normalised_flux
from manifest_config import FitDefaults
from template_fit import (
    EphemerisContext,
    ShiftFitResult,
    TemplateCurve,
    fit_cross_correlation,
    fit_nonlinear_least_squares,
    fit_nls_iterative_outlier_clean,
    fit_nls_scale_iterative_outlier_clean,
)

from plot_style import FIGSIZE_INTERVAL, FONT_SIZE, apply_interval_plot_style

logger = logging.getLogger(__name__)

METHOD_FIELD_MAP = {
    "cc": ("t_max_cc", "rms_cc", "delta_tau_cc"),
    "nls": ("t_max_nls", "rms_nls", "delta_tau_nls"),
    "nls_clean": ("t_max_nls_clean", "rms_nls_clean", "delta_tau_nls_clean"),
    "nls_scale_clean": (
        "t_max_nls_scale_clean",
        "rms_nls_scale_clean",
        "delta_tau_nls_scale_clean",
    ),
}


def load_template_bundle(npz_path: Path, meta_path: Path) -> tuple[TemplateCurve, dict]:
    """Load template grid and metadata."""
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    data = np.load(npz_path)
    curve = TemplateCurve(data["tau"], data["mu"], float(data["tau_peak"]))
    return curve, meta


def fold_period_from_meta(meta: dict) -> float:
    """Period used for ``tau`` folding and ``t_max`` (Step 1 ``p0`` in meta)."""
    return float(meta["p0"])


def tau_mask_from_meta(meta: dict, fit_defaults: FitDefaults) -> tuple[float, float]:
    if "tau_mask_min" in meta and "tau_mask_max" in meta:
        return float(meta["tau_mask_min"]), float(meta["tau_mask_max"])
    return fit_defaults.tau_mask_min_fallback, fit_defaults.tau_mask_max_fallback


def delta_tau_bounds(t_start: float, t_end: float, fit: FitDefaults) -> tuple[float, float]:
    span = max(t_end - t_start, 1e-9)
    half = min(fit.delta_tau_max, 0.5 * span + fit.delta_tau_margin)
    return -half, half


def _model_flux_on_jd_grid(
    t_line: np.ndarray,
    curve: TemplateCurve,
    fit: ShiftFitResult,
    t_ref: float,
    fold_period: float,
) -> tuple[np.ndarray, np.ndarray]:
    tau_obs = observation_tau(t_line, t_ref, fold_period, tau_peak=curve.tau_peak)
    tau_q = tau_obs - fit.delta_tau
    mu = curve.eval(tau_q)
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
    t_ref: float,
    fold_period: float,
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
    t_ok, y_model = _model_flux_on_jd_grid(t_line, curve, fit, t_ref, fold_period)
    ax.plot(t_ok, y_model, color="tab:blue", lw=2, label="template + shift")
    ax.axvline(fit.t_max, color="magenta", ls="--", label=f"t_max={fit.t_max:.6f}")
    ax.set_xlim(t_start, t_end)
    ax.set_xlabel("truncated JD")
    ax.set_ylabel("normalised flux")
    ax.set_title(
        f"{title}\nRMS={fit.rms:.4f}, n={fit.n_used}, "
        f"delta_tau={fit.delta_tau * 86400:.1f}s, s={fit.scale:.3f}"
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
    save_path: Path | None,
    t_ref: float,
    fold_period: float,
    show: bool,
) -> None:
    """Four-panel comparison for one interval."""
    apply_interval_plot_style()
    fig, (ax_cc, ax_nls, ax_clean, ax_scale) = plt.subplots(
        1, 4, figsize=FIGSIZE_INTERVAL, sharey=True
    )
    _plot_fit_panel(
        ax_cc, t, y, curve, cc, t_start, t_end, "Cross-correlation", t_ref, fold_period
    )
    _plot_fit_panel(
        ax_nls, t, y, curve, nls, t_start, t_end, "Nonlinear least squares", t_ref, fold_period
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
        t_ref,
        fold_period,
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
        t_ref,
        fold_period,
    )
    fig.suptitle(f"Interval {index}: [{t_start:.5f}, {t_end:.5f}]", fontsize=FONT_SIZE)
    fig.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote %s", save_path)
    if show:
        plt.show()
    else:
        plt.close(fig)


def fit_all_methods(
    curve: TemplateCurve,
    tau_obs: np.ndarray,
    y: np.ndarray,
    ephem: EphemerisContext,
    *,
    tau_mask_min: float,
    tau_mask_max: float,
    dtau_lo: float,
    dtau_hi: float,
    fit_cfg: FitDefaults,
) -> tuple[ShiftFitResult, ShiftFitResult, ShiftFitResult, ShiftFitResult]:
    """Run CC, NLS, cleaned NLS, and scaled cleaned NLS."""
    cc = fit_cross_correlation(
        curve,
        tau_obs,
        y,
        ephem,
        tau_mask_min=tau_mask_min,
        tau_mask_max=tau_mask_max,
        delta_tau_min=dtau_lo,
        delta_tau_max=dtau_hi,
    )
    nls = fit_nonlinear_least_squares(
        curve,
        tau_obs,
        y,
        ephem,
        tau_mask_min=tau_mask_min,
        tau_mask_max=tau_mask_max,
        delta_tau_min=dtau_lo,
        delta_tau_max=dtau_hi,
        delta_tau_init=cc.delta_tau,
    )
    nls_clean = fit_nls_iterative_outlier_clean(
        curve,
        tau_obs,
        y,
        ephem,
        tau_mask_min=tau_mask_min,
        tau_mask_max=tau_mask_max,
        delta_tau_min=dtau_lo,
        delta_tau_max=dtau_hi,
        delta_tau_init=nls.delta_tau,
        mad_k=fit_cfg.outlier_mad_k,
        max_iter=fit_cfg.outlier_max_iter,
        min_inliers=fit_cfg.outlier_min_inliers,
    )
    nls_scale_clean = fit_nls_scale_iterative_outlier_clean(
        curve,
        tau_obs,
        y,
        ephem,
        tau_mask_min=tau_mask_min,
        tau_mask_max=tau_mask_max,
        delta_tau_min=dtau_lo,
        delta_tau_max=dtau_hi,
        delta_tau_init=nls_clean.delta_tau,
        scale_init=1.0,
        mad_k=fit_cfg.outlier_mad_k,
        max_iter=fit_cfg.outlier_max_iter,
        min_inliers=fit_cfg.outlier_min_inliers,
        scale_min=fit_cfg.scale_min,
        scale_max=fit_cfg.scale_max,
    )
    return cc, nls, nls_clean, nls_scale_clean


def official_fit_result(
    method: str,
    cc: ShiftFitResult,
    nls: ShiftFitResult,
    nls_clean: ShiftFitResult,
    nls_scale_clean: ShiftFitResult,
) -> ShiftFitResult:
    """Select the manifest timing method."""
    mapping = {
        "cc": cc,
        "nls": nls,
        "nls_clean": nls_clean,
        "nls_scale_clean": nls_scale_clean,
    }
    return mapping[method]


def fit_piece_intervals(
    lc_path: Path,
    *,
    piece_id: str,
    fit_t_min: float,
    fit_t_max: float,
    intervals_path: Path,
    template_npz: Path,
    template_meta_path: Path,
    mag0: float | None,
    fit_cfg: FitDefaults,
    timing_method: str,
    out_summary: Path,
    fits_dir: Path | None,
    show_plots: bool,
) -> list[dict]:
    """Run Step 2 for all intervals in a piece; write ``fit_summary.csv``."""
    curve, meta = load_template_bundle(template_npz, template_meta_path)
    t_ref = float(meta["t_ref"])
    fold_period = fold_period_from_meta(meta)
    tau_mask_min, tau_mask_max = tau_mask_from_meta(meta, fit_cfg)

    piece, header = load_lc_fragment(lc_path, fit_t_min, fit_t_max)
    effective_mag0 = mag0 if mag0 is not None else header.get("mag0")
    norm = mag_to_normalised_flux(
        piece,
        effective_mag0,
        float(meta["baseline_flux"]),
        float(meta["ampl_guess_flux"]),
    )
    t_all = norm["jd"].to_numpy(dtype=float)
    y_all = norm["y_norm"].to_numpy(dtype=float)

    with intervals_path.open(encoding="utf-8") as handle:
        intervals = load_intervals(handle)
    if not intervals:
        raise ValueError(f"no intervals in {intervals_path}")

    rows: list[dict] = []
    for idx, (t_start, t_end) in enumerate(intervals):
        if t_start > t_end:
            t_start, t_end = t_end, t_start
        mask = (t_all >= t_start) & (t_all <= t_end)
        t = t_all[mask]
        y = y_all[mask]
        if len(t) < 5:
            logger.error("Piece %s interval %s: only %s points; skip", piece_id, idx, len(t))
            continue

        t_centre = 0.5 * (t_start + t_end)
        tau_obs = observation_tau(t, t_ref, fold_period, tau_peak=curve.tau_peak)
        ephem = EphemerisContext(
            t_ref=t_ref,
            period=fold_period,
            tau_peak=curve.tau_peak,
            t_anchor=t_centre,
        )

        dtau_lo, dtau_hi = delta_tau_bounds(t_start, t_end, fit_cfg)
        cc, nls, nls_clean, nls_scale_clean = fit_all_methods(
            curve,
            tau_obs,
            y,
            ephem,
            tau_mask_min=tau_mask_min,
            tau_mask_max=tau_mask_max,
            dtau_lo=dtau_lo,
            dtau_hi=dtau_hi,
            fit_cfg=fit_cfg,
        )

        if fits_dir is not None:
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
                save_path=fits_dir / f"interval_{idx:02d}.png",
                t_ref=t_ref,
                fold_period=fold_period,
                show=show_plots,
            )

        official = official_fit_result(timing_method, cc, nls, nls_clean, nls_scale_clean)
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
                "piece_id": piece_id,
                "interval": idx,
                "t_start": t_start,
                "t_end": t_end,
                "t_anchor": t_centre,
                "n_points": len(t),
                "timing_method": timing_method,
                "t_max": official.t_max,
                "rms_official": official.rms,
                "delta_tau_official": official.delta_tau,
                "scale_official": official.scale,
                "n_outliers_rejected": n_rejected,
                "n_outliers_rejected_scale": n_rejected_scale,
                "delta_tau_cc": cc.delta_tau,
                "delta_y_cc": cc.delta_y,
                "t_max_cc": cc.t_max,
                "rms_cc": cc.rms,
                "delta_tau_nls": nls.delta_tau,
                "delta_y_nls": nls.delta_y,
                "t_max_nls": nls.t_max,
                "rms_nls": nls.rms,
                "delta_tau_nls_clean": nls_clean.delta_tau,
                "delta_y_nls_clean": nls_clean.delta_y,
                "t_max_nls_clean": nls_clean.t_max,
                "rms_nls_clean": nls_clean.rms,
                "scale_nls_scale_clean": nls_scale_clean.scale,
                "delta_tau_nls_scale_clean": nls_scale_clean.delta_tau,
                "delta_y_nls_scale_clean": nls_scale_clean.delta_y,
                "t_max_nls_scale_clean": nls_scale_clean.t_max,
                "rms_nls_scale_clean": nls_scale_clean.rms,
                "tau_peak": curve.tau_peak,
            }
        )

    if rows:
        out_summary.parent.mkdir(parents=True, exist_ok=True)
        with out_summary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Piece %s: wrote %s (%s intervals)", piece_id, out_summary, len(rows))
    return rows
