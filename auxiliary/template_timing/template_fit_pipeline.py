"""Step 2: fit template per interval for one manifest piece (library entry point)."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from skvo_veb.utils.gp.intervals import load_intervals

from fit_mask import FitMask, resolve_fit_mask, warn_fit_mask_support
from manifest_config import FitDefaults, interval_overlaps_fit_window
from lc_flux import load_lc_fragment, mag_to_normalised_flux
from plot_style import FIGSIZE_INTERVAL, FONT_SIZE, apply_interval_plot_style
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

TEMPLATE_SUPPORT_KEYS = ("tau_data_min", "tau_data_max")


def template_data_range(meta: dict, *, context: str) -> tuple[float, float]:
    """Read the folded-photometry ``tau`` range from template metadata.

    Args:
        meta (dict): Parsed ``template_meta.json``.
        context (str): Label for error messages, typically the piece id.

    Returns:
        tuple[float, float]: ``(tau_data_min, tau_data_max)``.

    Raises:
        ValueError: If the metadata predates recorded photometric support.
    """
    missing = [key for key in TEMPLATE_SUPPORT_KEYS if key not in meta]
    if missing:
        raise ValueError(
            f"{context}: template_meta.json lacks {', '.join(missing)}; it was written "
            f"before the fit window became explicit. Rebuild the template (drop "
            f"existing_template_dir for this piece) so the photometric support of the "
            f"fold is known."
        )
    return float(meta["tau_data_min"]), float(meta["tau_data_max"])


def load_template_bundle(
    npz_path: Path,
    meta_path: Path,
    *,
    context: str = "template",
) -> tuple[TemplateCurve, dict]:
    """Load template grid and metadata, restricted to its photometric support."""
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    data = np.load(npz_path)
    tau_data_min, tau_data_max = template_data_range(meta, context=context)
    curve = TemplateCurve(
        data["tau"],
        data["mu"],
        float(data["tau_peak"]),
        tau_data_min=tau_data_min,
        tau_data_max=tau_data_max,
    )
    return curve, meta


def fit_mask_for_template(
    meta: dict,
    fit_defaults: FitDefaults,
    *,
    tau_peak: float,
    context: str,
) -> FitMask:
    """Resolve the Step 2 window from the manifest and the template fold period.

    The window is manifest policy, not a template property, so it is re-resolved on
    every run; only the fold period is taken from the template, since that is the
    axis the shape lives on.

    Args:
        meta (dict): Parsed ``template_meta.json``.
        fit_defaults (FitDefaults): Fit settings for this piece.
        tau_peak (float): Template peak in days.
        context (str): Label for logs and warnings, typically the piece id.

    Returns:
        FitMask: Resolved window in peak-centred and fold coordinates.

    Raises:
        ValueError: If the template metadata has no fold period.
    """
    if "fold_period" not in meta:
        raise ValueError(f"{context}: template_meta.json lacks fold_period")
    mask = resolve_fit_mask(
        mode=fit_defaults.fit_mask_mode,
        half_width_phase=fit_defaults.fit_mask_half_width_phase,
        period=float(meta["fold_period"]),
        tau_peak=tau_peak,
    )
    tau_data_min, tau_data_max = template_data_range(meta, context=context)
    logger.info("%s: fit mask %s", context, mask.describe())
    warn_fit_mask_support(
        mask,
        tau_data_min=tau_data_min,
        tau_data_max=tau_data_max,
        context=context,
    )
    return mask


def delta_t_search_bounds(t_start: float, t_end: float, fit: FitDefaults) -> tuple[float, float]:
    """Allowed peak shift from interval centre (days, same unit as LC)."""
    span = max(t_end - t_start, 1e-9)
    half = min(fit.delta_tau_max, 0.5 * span + fit.delta_tau_margin)
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
    save_path: Path | None,
    show: bool,
) -> None:
    """Four-panel comparison for one interval."""
    apply_interval_plot_style()
    fig, (ax_cc, ax_nls, ax_clean, ax_scale) = plt.subplots(
        1, 4, figsize=FIGSIZE_INTERVAL, sharey=True
    )
    _plot_fit_panel(ax_cc, t, y, curve, cc, t_start, t_end, "Cross-correlation")
    _plot_fit_panel(ax_nls, t, y, curve, nls, t_start, t_end, "Nonlinear least squares")
    _plot_fit_panel(
        ax_clean, t, y, curve, nls_clean, t_start, t_end, "NLS + iterative outlier clean"
    )
    _plot_fit_panel(
        ax_scale, t, y, curve, nls_scale_clean, t_start, t_end, "NLS + scale + outlier clean"
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
    t_jd: np.ndarray,
    y: np.ndarray,
    ctx: IntervalFitContext,
    *,
    dt_min: float,
    dt_max: float,
    delta_t_lo: float,
    delta_t_hi: float,
    fit_cfg: FitDefaults,
) -> tuple[ShiftFitResult, ShiftFitResult, ShiftFitResult, ShiftFitResult]:
    """Run CC, NLS, cleaned NLS, and scaled cleaned NLS."""
    cc = fit_cross_correlation(
        curve,
        t_jd,
        y,
        ctx,
        dt_min=dt_min,
        dt_max=dt_max,
        delta_t_min=delta_t_lo,
        delta_t_max=delta_t_hi,
    )
    nls = fit_nonlinear_least_squares(
        curve,
        t_jd,
        y,
        ctx,
        dt_min=dt_min,
        dt_max=dt_max,
        delta_t_min=delta_t_lo,
        delta_t_max=delta_t_hi,
        delta_t_init=cc.delta_t,
    )
    nls_clean = fit_nls_iterative_outlier_clean(
        curve,
        t_jd,
        y,
        ctx,
        dt_min=dt_min,
        dt_max=dt_max,
        delta_t_min=delta_t_lo,
        delta_t_max=delta_t_hi,
        delta_t_init=nls.delta_t,
        mad_k=fit_cfg.outlier_mad_k,
        max_iter=fit_cfg.outlier_max_iter,
        min_inliers=fit_cfg.outlier_min_inliers,
    )
    nls_scale_clean = fit_nls_scale_iterative_outlier_clean(
        curve,
        t_jd,
        y,
        ctx,
        dt_min=dt_min,
        dt_max=dt_max,
        delta_t_min=delta_t_lo,
        delta_t_max=delta_t_hi,
        delta_t_init=nls_clean.delta_t,
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


def fit_result_from_summary_row(row: dict, method: str) -> ShiftFitResult:
    """Rebuild :class:`ShiftFitResult` for one method from a ``fit_summary`` row."""
    if method == "nls_scale_clean":
        scale = float(row["scale_nls_scale_clean"])
    else:
        scale = 1.0
    return ShiftFitResult(
        delta_t=float(row[f"delta_t_{method}"]),
        delta_y=float(row[f"delta_y_{method}"]),
        t_max=float(row[f"t_max_{method}"]),
        rms=float(row[f"rms_{method}"]),
        n_used=int(row["n_points"]),
        method=method,
        scale=scale,
    )


def method_timing_record(row: dict, method: str) -> dict:
    """Narrow one wide summary row to a single-method timing export record."""
    if method == "nls_scale_clean":
        scale = float(row["scale_nls_scale_clean"])
    else:
        scale = 1.0
    return {
        "piece_id": row["piece_id"],
        "interval": row["interval"],
        "t_max": row[f"t_max_{method}"],
        "sigma_t_max": row.get(f"sigma_t_max_{method}", float("nan")),
        "timing_method": method,
        "rms": row[f"rms_{method}"],
        "delta_t": row[f"delta_t_{method}"],
        "scale": scale,
        "t_start": row["t_start"],
        "t_end": row["t_end"],
        "t_anchor": row["t_anchor"],
        "n_points": row["n_points"],
        "n_outliers_rejected_scale": row["n_outliers_rejected_scale"],
    }


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
    curve, meta = load_template_bundle(
        template_npz, template_meta_path, context=f"Piece {piece_id}"
    )
    mask = fit_mask_for_template(
        meta,
        fit_cfg,
        tau_peak=curve.tau_peak,
        context=f"Piece {piece_id}",
    )
    dt_min, dt_max = mask.dt_min, mask.dt_max

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
        if not interval_overlaps_fit_window(
            t_start, t_end, fit_t_min=fit_t_min, fit_t_max=fit_t_max
        ):
            logger.info(
                "Piece %s interval %s [%.5f, %.5f] outside fit_window; skip",
                piece_id,
                idx,
                t_start,
                t_end,
            )
            continue
        mask = (t_all >= t_start) & (t_all <= t_end)
        t = t_all[mask]
        y = y_all[mask]
        if len(t) < 5:
            logger.error("Piece %s interval %s: only %s points; skip", piece_id, idx, len(t))
            continue

        t_centre = 0.5 * (t_start + t_end)
        ctx = IntervalFitContext(t_anchor=t_centre)
        delta_t_lo, delta_t_hi = delta_t_search_bounds(t_start, t_end, fit_cfg)
        cc, nls, nls_clean, nls_scale_clean = fit_all_methods(
            curve,
            t,
            y,
            ctx,
            dt_min=dt_min,
            dt_max=dt_max,
            delta_t_lo=delta_t_lo,
            delta_t_hi=delta_t_hi,
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
                "delta_t_official": official.delta_t,
                "scale_official": official.scale,
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

    if rows:
        out_summary.parent.mkdir(parents=True, exist_ok=True)
        with out_summary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Piece %s: wrote %s (%s intervals)", piece_id, out_summary, len(rows))
    return rows
