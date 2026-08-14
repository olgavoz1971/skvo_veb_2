"""Step 2: fit template per interval for one manifest piece (library entry point)."""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
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
    return_figure: bool = False,
) -> plt.Figure | None:
    """Four-panel comparison for one interval.

    Args:
        return_figure (bool): When true, return the figure without closing it
            (used by interactive review mode).

    Returns:
        plt.Figure | None: The figure when ``return_figure`` is true, else None.
    """
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
                "timing_method": selected_method,
                "selected_method": selected_method,
                "rejected": rejected,
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
