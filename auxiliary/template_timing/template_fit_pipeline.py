"""Step 2: fit template per interval for one manifest piece (library entry point)."""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from skvo_veb.utils.gp.intervals import load_intervals

from fold_stack import ensemble_calendar_from_delta_tau, observation_tau
from fit_mask import FitMask, resolve_fit_mask, warn_fit_mask_support
from manifest_config import FitDefaults, TimeWindow, interval_overlaps_fit_window, resolve_anchor_jd
from lc_flux import load_lc_fragment, mag_to_normalised_flux
from plot_style import (
    FIGSIZE_INTERVAL,
    FIGSIZE_SEGMENT_ANCHOR,
    FONT_SIZE,
    apply_interval_plot_style,
)
from template_build import load_template_sigma_grid
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


@dataclass
class FitSummaryEntry:
    """One ``fit_summary.csv`` data line with optional verbatim preservation."""

    raw_line: str
    row: dict
    commented: bool
    modified: bool = False


@dataclass
class FitSummaryTable:
    """Parsed ``fit_summary.csv`` with header and row order preserved."""

    header_line: str
    fieldnames: list[str]
    entries: list[FitSummaryEntry]
    newline: str = "\n"


def load_fit_summary_table(summary_path: Path) -> FitSummaryTable:
    """Load a wide summary table, retaining original line text and order.

    Commented (``#``) rows are kept as :class:`FitSummaryEntry` objects with
    ``commented=True`` and ``row["rejected"]="true"``.

    Args:
        summary_path (Path): Path to ``fit_summary.csv``.

    Returns:
        FitSummaryTable: Parsed table with verbatim lines for round-trip writes.
    """
    if not summary_path.is_file():
        raise FileNotFoundError(f"fit summary not found: {summary_path}")
    with summary_path.open(encoding="utf-8", newline="") as handle:
        lines = handle.readlines()
    if not lines:
        raise ValueError(f"empty fit summary: {summary_path}")
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    header_line = lines[0]
    fieldnames = next(csv.reader([header_line.lstrip("#").strip()]))
    entries: list[FitSummaryEntry] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        stripped = line.lstrip()
        commented = stripped.startswith("#")
        parse_line = stripped[1:] if commented else line.rstrip("\r\n")
        values = next(csv.reader([parse_line]))
        row = dict(zip(fieldnames, values, strict=False))
        if commented:
            row["rejected"] = "true"
        entries.append(
            FitSummaryEntry(raw_line=line, row=row, commented=commented, modified=False)
        )
    return FitSummaryTable(
        header_line=header_line,
        fieldnames=fieldnames,
        entries=entries,
        newline=newline,
    )


def load_fit_summary_rows(summary_path: Path, *, include_rejected: bool = False) -> list[dict]:
    """Load summary rows, optionally including commented rejections.

    Args:
        summary_path (Path): Path to ``fit_summary.csv``.
        include_rejected (bool): When false, skip ``#`` lines (accepted rows only).

    Returns:
        list[dict]: Parsed summary rows.
    """
    table = load_fit_summary_table(summary_path)
    if include_rejected:
        return [entry.row for entry in table.entries]
    return [entry.row for entry in table.entries if not entry.commented]


def write_fit_summary_table(path: Path, table: FitSummaryTable) -> None:
    """Write ``fit_summary.csv``, preserving unmodified lines verbatim.

    Args:
        path (Path): Output CSV path.
        table (FitSummaryTable): Table loaded from :func:`load_fit_summary_table`
            or returned by :func:`review_piece_from_summary`.
    """
    from fit_review import parse_rejected_flag

    fieldnames = list(table.fieldnames)
    if "rejected" not in fieldnames:
        fieldnames = [*fieldnames, "rejected"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(table.header_line)
        for entry in table.entries:
            if not entry.modified:
                handle.write(entry.raw_line)
                continue
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
            writer.writerow(entry.row)
            line = buffer.getvalue()
            if table.newline == "\r\n" and line.endswith("\n"):
                line = line[:-1] + "\r\n"
            if parse_rejected_flag(entry.row.get("rejected")):
                handle.write(f"#{line}")
            else:
                handle.write(line)


def fit_summary_table_rows(table: FitSummaryTable) -> list[dict]:
    """Return all row dicts from a table in file order."""
    return [entry.row for entry in table.entries]


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


def _require_constant_period_template(
    meta: dict,
    *,
    piece_period: float,
    context: str,
) -> tuple[float, float]:
    """Validate a constant-P template and return ``(t_ref, period)``.

    Args:
        meta (dict): Parsed ``template_meta.json``.
        piece_period (float): Manifest fold period for this piece.
        context (str): Label for error messages.

    Returns:
        tuple[float, float]: Template fold epoch and fold period.

    Raises:
        ValueError: If the template is not a constant-period fold, or if the
            piece period disagrees with the template.
    """
    fold_mode = str(meta.get("fold_mode", "constant"))
    if fold_mode != "constant":
        raise ValueError(
            f"{context}: segment_anchor ensemble ToM requires a constant-period "
            f"template; this template has fold_mode={fold_mode!r}"
        )
    t_ref = _fold_epoch_from_meta(meta)
    period = float(meta["fold_period"])
    if not np.isclose(piece_period, period, rtol=1e-8, atol=1e-12):
        raise ValueError(
            f"{context}: piece period {piece_period:.10f} d disagrees with "
            f"template fold_period {period:.10f} d; ensemble ToM folds in the "
            f"template tau frame, so the periods must match"
        )
    return t_ref, period


def _with_fold_t_max(fit: ShiftFitResult, tau_peak: float) -> ShiftFitResult:
    """Copy a fit with ``t_max`` set to the fold-space peak ``tau_peak + delta_t``."""
    return replace(fit, t_max=float(tau_peak + fit.delta_t))


def _calendar_fit_from_fold(
    fit: ShiftFitResult,
    *,
    t_ref: float,
    period: float,
    tau_peak: float,
    t_pick: float,
) -> ShiftFitResult:
    """Copy a fold-space fit with ``t_max`` converted to calendar time."""
    _cycle, _t_anchor, t_max = ensemble_calendar_from_delta_tau(
        fit.delta_t,
        t_ref=t_ref,
        period=period,
        tau_peak=tau_peak,
        t_pick=t_pick,
    )
    return replace(fit, t_max=float(t_max))


def delta_tau_search_bounds(fit: FitDefaults) -> tuple[float, float]:
    """Allowed fold-space peak shift (days) for ensemble ToM."""
    half = fit.delta_tau_max
    if half <= 0:
        raise ValueError(f"delta_tau_max must be positive, got {half}")
    return -half, half


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


def _fold_epoch_from_meta(meta: dict) -> float:
    """Return Step 1 fold epoch stored in template metadata."""
    if "fold_epoch" in meta:
        return float(meta["fold_epoch"])
    if "t_ref" in meta:
        return float(meta["t_ref"])
    raise ValueError("template_meta.json lacks fold_epoch / t_ref")


def segment_tau_from_meta(jd: np.ndarray, meta: dict, *, tau_peak: float) -> np.ndarray:
    """Map calendar times to extended-fold ``tau`` using Step 1 ephemeris from meta."""
    t_ref = _fold_epoch_from_meta(meta)
    period = float(meta["fold_period"])
    return observation_tau(jd, t_ref, period, tau_peak=tau_peak)


def _plot_shifted_gp_sigma_band(
    ax,
    curve: TemplateCurve,
    fit: ShiftFitResult,
    x_line: np.ndarray,
    gp_tau: np.ndarray,
    gp_sigma: np.ndarray,
) -> None:
    """Draw GP +/-1 sigma around a shifted/scaled template (segment-anchor panels)."""
    dt = x_line - fit.t_max
    mu = curve.eval_from_peak(dt)
    ok = np.isfinite(mu)
    tau_ok = x_line[ok]
    y_mid = fit.scale * mu[ok] + fit.delta_y
    sig = np.interp(tau_ok, gp_tau, gp_sigma, left=np.nan, right=np.nan)
    in_support = (
        (tau_ok >= curve.tau_min)
        & (tau_ok <= curve.tau_max)
        & np.isfinite(sig)
    )
    if not np.any(in_support):
        return
    t = tau_ok[in_support]
    s = sig[in_support]
    y = y_mid[in_support]
    ax.fill_between(
        t,
        y - fit.scale * s,
        y + fit.scale * s,
        color="tab:blue",
        alpha=0.25,
        label="GP +/-1 sigma",
    )


def _plot_folded_segment_panel(
    ax,
    tau: np.ndarray,
    y: np.ndarray,
    curve: TemplateCurve,
    *,
    dt_min: float,
    dt_max: float,
    title: str,
) -> None:
    """Top panel: folded fit-window LC vs the unshifted Step 1 template."""
    ax.scatter(tau, y, s=12, c="k", alpha=0.35, label="folded segment")
    tau_line = np.linspace(curve.tau_min, curve.tau_max, 400)
    mu = curve.eval(tau_line)
    ok = np.isfinite(mu)
    ax.plot(tau_line[ok], mu[ok], color="tab:blue", lw=2, label="GP template (unshifted)")
    mask_lo = curve.tau_peak + dt_min
    mask_hi = curve.tau_peak + dt_max
    ax.axvspan(mask_lo, mask_hi, color="tab:orange", alpha=0.18, label="Step 2 fit mask")
    ax.axvline(curve.tau_peak, color="tab:green", ls="--", lw=1.2, label="template peak")
    ax.set_xlabel("tau (days, Step 1 fold)")
    ax.set_ylabel("normalised flux")
    ax.set_title(title)
    ax.legend(loc="best", fontsize=FONT_SIZE * 0.55)


def _plot_fit_panel(
    ax,
    t: np.ndarray,
    y: np.ndarray,
    curve: TemplateCurve,
    fit: ShiftFitResult,
    x_lo: float,
    x_hi: float,
    title: str,
    *,
    xlabel: str = "time (LC units)",
    peak_label: str = "t_max",
    scatter_s: float = 40,
    gp_sigma_grid: tuple[np.ndarray, np.ndarray] | None = None,
) -> None:
    """One method panel: data, shifted template, and fitted peak."""
    inlier = fit.inlier_mask
    if inlier is not None and len(inlier) == len(t):
        ax.scatter(t[inlier], y[inlier], s=scatter_s, c="k", alpha=0.75, label="inliers")
        if np.any(~inlier):
            ax.scatter(
                t[~inlier],
                y[~inlier],
                s=scatter_s * 1.5,
                facecolors="none",
                edgecolors="red",
                linewidths=1.5,
                label="rejected outliers",
            )
    else:
        ax.scatter(t, y, s=scatter_s, c="k", alpha=0.75, label="data")
    t_line = np.linspace(x_lo, x_hi, 300)
    t_ok, y_model = _model_flux_on_jd_grid(t_line, curve, fit)
    if gp_sigma_grid is not None:
        gp_tau, gp_sigma = gp_sigma_grid
        _plot_shifted_gp_sigma_band(ax, curve, fit, t_line, gp_tau, gp_sigma)
    ax.plot(t_ok, y_model, color="tab:blue", lw=2, label="template + shift")
    ax.axvline(fit.t_max, color="magenta", ls="--", label=f"{peak_label}={fit.t_max:.6f}")
    ax.set_xlim(x_lo, x_hi)
    ax.set_xlabel(xlabel)
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
    return_figure: bool = False,
    fit_zoom: tuple[float, float] | None = None,
) -> plt.Figure | None:
    """Four-panel comparison for one interval.

    Args:
        fit_zoom (tuple[float, float] | None): Optional ``(x_lo, x_hi)`` calendar-time
            limits for the fit panels. When omitted, the full ``[t_start, t_end]`` span
            is used (appropriate for short per-interval windows).
        return_figure (bool): When true, return the figure without closing it
            (used by interactive review mode).

    Returns:
        plt.Figure | None: The figure when ``return_figure`` is true, else None.
    """
    apply_interval_plot_style()
    x_lo, x_hi = fit_zoom if fit_zoom is not None else (t_start, t_end)
    fig, (ax_cc, ax_nls, ax_clean, ax_scale) = plt.subplots(
        1, 4, figsize=FIGSIZE_INTERVAL, sharey=True
    )
    _plot_fit_panel(ax_cc, t, y, curve, cc, x_lo, x_hi, "Cross-correlation")
    _plot_fit_panel(ax_nls, t, y, curve, nls, x_lo, x_hi, "Nonlinear least squares")
    _plot_fit_panel(
        ax_clean, t, y, curve, nls_clean, x_lo, x_hi, "NLS + iterative outlier clean"
    )
    _plot_fit_panel(
        ax_scale, t, y, curve, nls_scale_clean, x_lo, x_hi, "NLS + scale + outlier clean"
    )
    fig.suptitle(f"Interval {index}: [{t_start:.5f}, {t_end:.5f}]", fontsize=FONT_SIZE)
    fig.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote %s", save_path)
    if return_figure:
        return fig
    if show:
        plt.show()
    else:
        plt.close(fig)
    return None


def plot_segment_anchor_fits(
    index: int,
    t_start: float,
    t_end: float,
    tau: np.ndarray,
    y: np.ndarray,
    curve: TemplateCurve,
    t_anchor: float,
    anchor_epoch: str,
    cc: ShiftFitResult,
    nls: ShiftFitResult,
    nls_clean: ShiftFitResult,
    nls_scale_clean: ShiftFitResult,
    *,
    dt_min: float,
    dt_max: float,
    save_path: Path | None,
    show: bool,
    return_figure: bool = False,
    template_npz: Path | None = None,
) -> plt.Figure | None:
    """Two-row figure: unshifted folded stack, then four fold-space ensemble fits.

    Step 2 for ``segment_anchor`` fits the template to **all** points stacked in
    tau. The bottom panels use that fold-space shift; calendar ``t_max`` is the
    same ``delta_t`` placed on the reporting cycle.

    Args:
        index (int): Segment index (always 0 for segment_anchor).
        t_start (float): Fit window start (LC units).
        t_end (float): Fit window end (LC units).
        tau: Fold coordinates of the fit-window LC (days).
        y: Normalised flux in the fit window.
        curve (TemplateCurve): Step 1 template.
        t_anchor (float): Calendar time of the unshifted template peak on the
            reporting cycle.
        anchor_epoch (str): Manifest anchor kind (for the title).
        cc, nls, nls_clean, nls_scale_clean: Fit results (``delta_t`` in tau).
        dt_min (float): Lower fit-mask edge in days from template peak.
        dt_max (float): Upper fit-mask edge in days from template peak.
        save_path (Path | None): Output PNG path.
        show (bool): Call ``plt.show()`` when true.
        return_figure (bool): Return figure for interactive review.
        template_npz (Path | None): ``template.npz`` for GP sigma on shifted fits.

    Returns:
        plt.Figure | None: Figure when ``return_figure`` is true.
    """
    apply_interval_plot_style()
    gp_sigma_grid = (
        load_template_sigma_grid(template_npz) if template_npz is not None else None
    )
    tau_peak = curve.tau_peak
    margin = 0.08 * max(dt_max - dt_min, 1e-9)
    x_lo = tau_peak + dt_min - margin
    x_hi = tau_peak + dt_max + margin
    cc_tau = _with_fold_t_max(cc, tau_peak)
    nls_tau = _with_fold_t_max(nls, tau_peak)
    clean_tau = _with_fold_t_max(nls_clean, tau_peak)
    scale_tau = _with_fold_t_max(nls_scale_clean, tau_peak)
    panel_kw = {
        "xlabel": "tau (days)",
        "peak_label": "tau_max",
        "scatter_s": 14,
        "gp_sigma_grid": gp_sigma_grid,
    }
    fig = plt.figure(figsize=FIGSIZE_SEGMENT_ANCHOR)
    gs = fig.add_gridspec(2, 4, height_ratios=[1.0, 1.15], hspace=0.38, wspace=0.25)
    ax_fold = fig.add_subplot(gs[0, :])
    _plot_folded_segment_panel(
        ax_fold,
        tau,
        y,
        curve,
        dt_min=dt_min,
        dt_max=dt_max,
        title=(
            "Folded segment vs unshifted template — all cycles stack in tau; "
            "orange band is the ensemble fit mask (GP sigma: see template_gp.png)"
        ),
    )
    ax_cc = fig.add_subplot(gs[1, 0])
    ax_nls = fig.add_subplot(gs[1, 1])
    ax_clean = fig.add_subplot(gs[1, 2])
    ax_scale = fig.add_subplot(gs[1, 3])
    _plot_fit_panel(ax_cc, tau, y, curve, cc_tau, x_lo, x_hi, "Cross-correlation", **panel_kw)
    _plot_fit_panel(
        ax_nls, tau, y, curve, nls_tau, x_lo, x_hi, "Nonlinear least squares", **panel_kw
    )
    _plot_fit_panel(
        ax_clean,
        tau,
        y,
        curve,
        clean_tau,
        x_lo,
        x_hi,
        "NLS + iterative outlier clean",
        **panel_kw,
    )
    _plot_fit_panel(
        ax_scale,
        tau,
        y,
        curve,
        scale_tau,
        x_lo,
        x_hi,
        "NLS + scale + outlier clean",
        **panel_kw,
    )
    fig.suptitle(
        f"Ensemble ToM {index}: fit [{t_start:.5f}, {t_end:.5f}], "
        f"anchor={anchor_epoch} (t_anchor={t_anchor:.5f})",
        fontsize=FONT_SIZE,
        y=0.98,
    )
    fig.text(
        0.5,
        0.52,
        f"Bottom row: four methods on the folded stack (n used is all cycles in the mask); "
        f"calendar t_max = t_anchor + delta_t",
        ha="center",
        va="center",
        fontsize=FONT_SIZE * 0.55,
        transform=fig.transFigure,
    )
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote %s", save_path)
    if return_figure:
        return fig
    if show:
        plt.show()
    else:
        plt.close(fig)
    return None


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


def sync_official_columns(row: dict, method: str) -> None:
    """Copy one method's fit columns into the official summary fields."""
    fit = fit_result_from_summary_row(row, method)
    row["selected_method"] = method
    row["timing_method"] = method
    row["t_max"] = fit.t_max
    row["rms_official"] = fit.rms
    row["delta_t_official"] = fit.delta_t
    row["scale_official"] = fit.scale
    if f"sigma_t_max_{method}" in row:
        row["sigma_t_max"] = row[f"sigma_t_max_{method}"]


def _interval_arrays_for_row(
    t_all: np.ndarray,
    y_all: np.ndarray,
    t_start: float,
    t_end: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Slice LC arrays for one interval, swapping bounds if needed."""
    if t_start > t_end:
        t_start, t_end = t_end, t_start
    mask = (t_all >= t_start) & (t_all <= t_end)
    return t_all[mask], y_all[mask]


def _fit_summary_row(
    *,
    piece_id: str,
    interval: int,
    t_start: float,
    t_end: float,
    t_anchor: float,
    n_points: int,
    timing_method: str,
    selected_method: str,
    rejected: str,
    official: ShiftFitResult,
    cc: ShiftFitResult,
    nls: ShiftFitResult,
    nls_clean: ShiftFitResult,
    nls_scale_clean: ShiftFitResult,
    tau_peak: float,
    timing_mode: str = "per_interval",
    anchor_epoch: str | None = None,
    cycle_index: int | None = None,
) -> dict:
    """Build one wide ``fit_summary`` row from fit results."""
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
    row = {
        "piece_id": piece_id,
        "interval": interval,
        "t_start": t_start,
        "t_end": t_end,
        "t_anchor": t_anchor,
        "n_points": n_points,
        "timing_method": selected_method,
        "selected_method": selected_method,
        "rejected": rejected,
        "timing_mode": timing_mode,
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
        "tau_peak": tau_peak,
    }
    if anchor_epoch is not None:
        row["anchor_epoch"] = anchor_epoch
    if cycle_index is not None:
        row["cycle_index"] = cycle_index
    return row


def fit_piece_segment_anchor(
    lc_path: Path,
    *,
    piece_id: str,
    fit_t_min: float,
    fit_t_max: float,
    anchor_epoch: str,
    piece_period: float,
    template_npz: Path,
    template_meta_path: Path,
    mag0: float | None,
    fit_cfg: FitDefaults,
    timing_method: str,
    out_summary: Path,
    fits_dir: Path | None,
    show_plots: bool,
    review_fits: bool = False,
) -> list[dict]:
    """Fit the template to the folded segment (ensemble ToM); write ``fit_summary.csv``.

    All points in ``fit_window`` are folded with the template ephemeris and the
    four Step 2 methods run in tau. The fitted ``delta_t`` is then placed on the
    calendar cycle nearest ``anchor_epoch``.

    Args:
        lc_path (Path): Light-curve file for this piece.
        piece_id (str): Piece identifier.
        fit_t_min (float): Fit window lower bound.
        fit_t_max (float): Fit window upper bound.
        anchor_epoch (str): ``window_centre``, ``window_start``, or ``window_end``.
        piece_period (float): Manifest fold period; must match the template.
        template_npz (Path): Template bundle path.
        template_meta_path (Path): Template metadata JSON path.
        mag0 (float | None): Reference magnitude for flux normalisation.
        fit_cfg (FitDefaults): Step 2 fit settings.
        timing_method (str): Manifest default timing method.
        out_summary (Path): Output ``fit_summary.csv`` path.
        fits_dir (Path | None): Directory for the diagnostic PNG.
        show_plots (bool): Call ``plt.show()`` when true.
        review_fits (bool): Open interactive review after the fit.

    Returns:
        list[dict]: One summary row (interval index 0).

    Raises:
        ValueError: If the window is too short, the template is not constant-P,
            or the piece period disagrees with the template.
    """
    curve, meta = load_template_bundle(
        template_npz, template_meta_path, context=f"Piece {piece_id}"
    )
    t_ref, period = _require_constant_period_template(
        meta, piece_period=piece_period, context=f"Piece {piece_id}"
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

    t_start, t_end = fit_t_min, fit_t_max
    if t_start > t_end:
        t_start, t_end = t_end, t_start
    t = t_all
    y = y_all
    if len(t) < 5:
        raise ValueError(
            f"Piece {piece_id}: segment_anchor fit_window has only {len(t)} points; "
            f"need at least 5"
        )

    tau = observation_tau(t, t_ref, period, tau_peak=curve.tau_peak)
    t_pick = resolve_anchor_jd(TimeWindow(t_min=t_start, t_max=t_end), anchor_epoch)
    cycle_index, t_anchor, _t_max_unshifted = ensemble_calendar_from_delta_tau(
        0.0,
        t_ref=t_ref,
        period=period,
        tau_peak=curve.tau_peak,
        t_pick=t_pick,
    )
    ctx = IntervalFitContext(t_anchor=curve.tau_peak)
    delta_t_lo, delta_t_hi = delta_tau_search_bounds(fit_cfg)
    cc_fold, nls_fold, nls_clean_fold, nls_scale_clean_fold = fit_all_methods(
        curve,
        tau,
        y,
        ctx,
        dt_min=dt_min,
        dt_max=dt_max,
        delta_t_lo=delta_t_lo,
        delta_t_hi=delta_t_hi,
        fit_cfg=fit_cfg,
    )

    if fits_dir is not None or show_plots:
        plot_segment_anchor_fits(
            0,
            t_start,
            t_end,
            tau,
            y,
            curve,
            t_anchor,
            anchor_epoch,
            cc_fold,
            nls_fold,
            nls_clean_fold,
            nls_scale_clean_fold,
            dt_min=dt_min,
            dt_max=dt_max,
            save_path=fits_dir / "segment_anchor.png" if fits_dir else None,
            show=show_plots and not review_fits,
            template_npz=template_npz,
        )

    selected_method = timing_method
    rejected = "false"
    if review_fits:
        from fit_review import review_segment_anchor_fits

        decision = review_segment_anchor_fits(
            0,
            t_start,
            t_end,
            tau,
            y,
            curve,
            t_anchor,
            anchor_epoch,
            cc_fold,
            nls_fold,
            nls_clean_fold,
            nls_scale_clean_fold,
            dt_min=dt_min,
            dt_max=dt_max,
            default_method=timing_method,
            piece_id=piece_id,
            template_npz=template_npz,
        )
        if decision.rejected:
            selected_method = timing_method
            rejected = "true"
        else:
            selected_method = decision.selected_method or timing_method
            rejected = "false"

    cal_kw = {
        "t_ref": t_ref,
        "period": period,
        "tau_peak": curve.tau_peak,
        "t_pick": t_pick,
    }
    cc = _calendar_fit_from_fold(cc_fold, **cal_kw)
    nls = _calendar_fit_from_fold(nls_fold, **cal_kw)
    nls_clean = _calendar_fit_from_fold(nls_clean_fold, **cal_kw)
    nls_scale_clean = _calendar_fit_from_fold(nls_scale_clean_fold, **cal_kw)
    official = official_fit_result(selected_method, cc, nls, nls_clean, nls_scale_clean)
    rows = [
        _fit_summary_row(
            piece_id=piece_id,
            interval=0,
            t_start=t_start,
            t_end=t_end,
            t_anchor=t_anchor,
            n_points=len(t),
            timing_method=timing_method,
            selected_method=selected_method,
            rejected=rejected,
            official=official,
            cc=cc,
            nls=nls,
            nls_clean=nls_clean,
            nls_scale_clean=nls_scale_clean,
            tau_peak=curve.tau_peak,
            timing_mode="segment_anchor",
            anchor_epoch=anchor_epoch,
            cycle_index=cycle_index,
        )
    ]

    out_summary.parent.mkdir(parents=True, exist_ok=True)
    with out_summary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    logger.info(
        "Piece %s: ensemble ToM wrote %s (anchor_epoch=%s, cycle=%s, "
        "t_anchor=%.5f, t_max=%.5f, n_used=%s / %s)",
        piece_id,
        out_summary,
        anchor_epoch,
        cycle_index,
        t_anchor,
        official.t_max,
        official.n_used,
        len(t),
    )
    return rows


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
    review_fits: bool = False,
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

        if fits_dir is not None or show_plots:
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
                save_path=fits_dir / f"interval_{idx:02d}.png" if fits_dir else None,
                show=show_plots and not review_fits,
            )

        selected_method = timing_method
        rejected = "false"
        if review_fits:
            from fit_review import review_interval_fits

            decision = review_interval_fits(
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
                default_method=timing_method,
                piece_id=piece_id,
            )
            if decision.rejected:
                selected_method = timing_method
                rejected = "true"
            else:
                selected_method = decision.selected_method or timing_method
                rejected = "false"

        official = official_fit_result(selected_method, cc, nls, nls_clean, nls_scale_clean)
        rows.append(
            _fit_summary_row(
                piece_id=piece_id,
                interval=idx,
                t_start=t_start,
                t_end=t_end,
                t_anchor=t_centre,
                n_points=len(t),
                timing_method=timing_method,
                selected_method=selected_method,
                rejected=rejected,
                official=official,
                cc=cc,
                nls=nls,
                nls_clean=nls_clean,
                nls_scale_clean=nls_scale_clean,
                tau_peak=curve.tau_peak,
            )
        )

    if rows:
        out_summary.parent.mkdir(parents=True, exist_ok=True)
        with out_summary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Piece %s: wrote %s (%s intervals)", piece_id, out_summary, len(rows))
    return rows


def review_piece_from_summary(
    lc_path: Path,
    *,
    piece_id: str,
    fit_t_min: float,
    fit_t_max: float,
    template_npz: Path,
    template_meta_path: Path,
    mag0: float | None,
    default_method: str,
    fit_cfg: FitDefaults,
    summary_table: FitSummaryTable,
) -> FitSummaryTable:
    """Re-open interactive review for active summary rows without refitting.

    Commented (rejected) rows are left untouched and are not shown again.

    Args:
        lc_path (Path): Light-curve file for this piece.
        piece_id (str): Piece identifier.
        fit_t_min (float): Fit window lower bound.
        fit_t_max (float): Fit window upper bound.
        template_npz (Path): Template bundle path.
        template_meta_path (Path): Template metadata JSON path.
        mag0 (float | None): Reference magnitude for flux normalisation.
        default_method (str): Manifest default timing method.
        fit_cfg (FitDefaults): Step 2 fit settings for fit-mask resolution.
        summary_table (FitSummaryTable): Existing summary table for this piece.

    Returns:
        FitSummaryTable: Updated table; unmodified rows keep verbatim ``raw_line``.
    """
    from fit_review import (
        apply_review_decision,
        normalise_review_fields,
        parse_rejected_flag,
        review_interval_fits,
    )

    curve, meta = load_template_bundle(
        template_npz, template_meta_path, context=f"Piece {piece_id}"
    )
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

    for entry in summary_table.entries:
        if entry.commented:
            logger.debug(
                "Piece %s interval %s: commented rejection; skip review",
                piece_id,
                entry.row.get("interval"),
            )
            continue

        row = entry.row
        normalise_review_fields(row, default_method=default_method)
        before_method = str(row.get("selected_method") or default_method)
        before_rejected = parse_rejected_flag(row.get("rejected"))

        idx = int(row["interval"])
        t_start = float(row["t_start"])
        t_end = float(row["t_end"])
        t, y = _interval_arrays_for_row(t_all, y_all, t_start, t_end)
        if len(t) < 5:
            logger.error(
                "Piece %s interval %s: only %s points during review; keep row unchanged",
                piece_id,
                idx,
                len(t),
            )
            continue

        cc = fit_result_from_summary_row(row, "cc")
        nls = fit_result_from_summary_row(row, "nls")
        nls_clean = fit_result_from_summary_row(row, "nls_clean")
        nls_scale_clean = fit_result_from_summary_row(row, "nls_scale_clean")
        if str(row.get("timing_mode")) == "segment_anchor":
            from fit_review import review_segment_anchor_fits

            mask = fit_mask_for_template(
                meta,
                fit_cfg,
                tau_peak=curve.tau_peak,
                context=f"Piece {piece_id}",
            )
            anchor_epoch = str(row.get("anchor_epoch") or "window_centre")
            t_anchor = float(row["t_anchor"])
            tau = segment_tau_from_meta(t, meta, tau_peak=curve.tau_peak)
            decision = review_segment_anchor_fits(
                idx,
                t_start,
                t_end,
                tau,
                y,
                curve,
                t_anchor,
                anchor_epoch,
                cc,
                nls,
                nls_clean,
                nls_scale_clean,
                dt_min=mask.dt_min,
                dt_max=mask.dt_max,
                default_method=default_method,
                piece_id=piece_id,
                template_npz=template_npz,
            )
        else:
            decision = review_interval_fits(
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
                default_method=default_method,
                piece_id=piece_id,
            )
        apply_review_decision(row, decision, default_method=default_method)
        if not parse_rejected_flag(row["rejected"]):
            sync_official_columns(row, row["selected_method"])

        after_method = str(row.get("selected_method") or default_method)
        after_rejected = parse_rejected_flag(row.get("rejected"))
        if before_method != after_method or before_rejected != after_rejected:
            entry.modified = True

    return summary_table
