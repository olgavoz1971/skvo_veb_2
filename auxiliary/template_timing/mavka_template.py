"""Step 1a: build a template μ(τ) with MAVKA (AP / WSAP / WSL) on interval stacks."""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from fit_mask import resolve_fit_mask, warn_fit_mask_support
from fold_stack import phase_centred
from lc_io import load_lightcurve_frame
from manifest_config import FitDefaults, MavkaTemplateConfig
from mavka_models import ApproxFitResult, fit_interval, model_curve
from plot_style import FIGSIZE_INTERVAL, FONT_SIZE, apply_interval_plot_style
from template_build import photometry_fragment_to_flux, save_template_artifacts

logger = logging.getLogger(__name__)

_TEMPLATE_METHODS = ("AP", "WSAP", "WSL")


def _points_in_intervals(
    jd: np.ndarray,
    intervals: list[tuple[float, float]],
) -> np.ndarray:
    """Boolean mask: each JD lies in at least one closed interval.

    Args:
        jd (numpy.ndarray): Observation times (absolute JD).
        intervals (list[tuple[float, float]]): ``(t_start, t_end)`` windows.

    Returns:
        numpy.ndarray: Boolean mask aligned with ``jd``.
    """
    mask = np.zeros(jd.shape, dtype=bool)
    for t0, t1 in intervals:
        lo, hi = (t0, t1) if t0 <= t1 else (t1, t0)
        mask |= (jd >= lo) & (jd <= hi)
    return mask


def fold_interval_stack(
    df: pd.DataFrame,
    *,
    t_min: float,
    t_max: float,
    intervals: list[tuple[float, float]],
    fold_epoch: float,
    fold_period: float,
) -> pd.DataFrame:
    """Fold LC points that fall in any timing interval (single phase copy).

    Unlike the GP extended fold, MAVKA models one extremum, so each point is
    kept once at centred phase ``τ = φ P``.

    Args:
        df (pandas.DataFrame): Full light curve with ``jd`` / ``phot`` / ``phot_err``.
        t_min (float): Template window start (absolute JD).
        t_max (float): Template window end (absolute JD).
        intervals (list[tuple[float, float]]): Absolute JD interval pairs.
        fold_epoch (float): Fold epoch (absolute JD).
        fold_period (float): Fold period (days).

    Returns:
        pandas.DataFrame: Columns ``tau``, ``phot``, ``phot_err``.

    Raises:
        ValueError: If the window or interval mask yields no points.
    """
    if fold_period <= 0:
        raise ValueError("fold_period must be positive")
    piece = df.loc[(df["jd"] >= t_min) & (df["jd"] <= t_max)].copy()
    if piece.empty:
        raise ValueError(f"no LC points in template window [{t_min}, {t_max}]")
    jd = piece["jd"].to_numpy(dtype=float)
    in_int = _points_in_intervals(jd, intervals)
    if not np.any(in_int):
        raise ValueError(
            "no LC points fall inside any timing interval within the template window"
        )
    sel = piece.loc[in_int]
    times = sel["jd"].to_numpy(dtype=float)
    phi = phase_centred(times, fold_epoch, fold_period)
    tau = phi * fold_period
    phot = sel["phot"].to_numpy(dtype=float)
    if "phot_err" in sel.columns:
        err = sel["phot_err"].to_numpy(dtype=float)
    else:
        err = np.full_like(phot, np.nan)
    logger.info(
        "MAVKA stack: %s / %s points in intervals (window [%s, %s])",
        int(np.count_nonzero(in_int)),
        len(piece),
        t_min,
        t_max,
    )
    return pd.DataFrame({"tau": tau, "phot": phot, "phot_err": err})


def _eligible_for_best(result: ApproxFitResult) -> bool:
    """Return True if a fit may win ``method: best`` (ok and no warnings)."""
    return bool(result.ok) and not result.warning


def select_mavka_fit(
    results: dict[str, ApproxFitResult],
    *,
    method: str,
) -> ApproxFitResult:
    """Choose the MAVKA fit for the template.

    Args:
        results (dict[str, ApproxFitResult]): Fits keyed by method id.
        method (str): ``best`` or a fixed ``AP`` / ``WSAP`` / ``WSL``.

    Returns:
        ApproxFitResult: Winning fit.

    Raises:
        ValueError: If no eligible fit exists.
    """
    method_u = method.strip().upper()
    if method_u == "BEST":
        candidates: list[tuple[float, ApproxFitResult]] = []
        for result in results.values():
            if not _eligible_for_best(result):
                continue
            if not np.isfinite(result.sigma_t_ext):
                continue
            candidates.append((max(float(result.sigma_t_ext), 1e-20), result))
        if not candidates:
            detail = {
                m: (r.ok, r.warning or r.fail_reason)
                for m, r in results.items()
            }
            raise ValueError(
                "MAVKA method=best: no fit without quality warnings; "
                f"outcomes={detail}"
            )
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    if method_u not in results:
        raise ValueError(f"unknown MAVKA method {method!r}")
    result = results[method_u]
    if not result.ok:
        raise ValueError(
            f"MAVKA method={method_u} failed: {result.fail_reason}"
        )
    if result.warning:
        raise ValueError(
            f"MAVKA method={method_u} has quality warning (refused for template): "
            f"{result.warning}"
        )
    return result


def fit_mavka_stack(
    tau: np.ndarray,
    y_norm: np.ndarray,
    *,
    method: str,
) -> tuple[ApproxFitResult, dict[str, ApproxFitResult]]:
    """Fit AP/WSAP/WSL on the normalised folded stack and select one.

    Args:
        tau (numpy.ndarray): Fold abscissa (days).
        y_norm (numpy.ndarray): Normalised flux (trough = minimum).
        method (str): ``best`` or fixed method id.

    Returns:
        tuple: ``(winner, all_results)``.
    """
    all_results: dict[str, ApproxFitResult] = {}
    for mid in _TEMPLATE_METHODS:
        all_results[mid] = fit_interval(mid, tau, y_norm)
        logger.info(
            "MAVKA %s: ok=%s σ=%.3g d warning=%r fail=%r",
            mid,
            all_results[mid].ok,
            all_results[mid].sigma_t_ext,
            all_results[mid].warning,
            all_results[mid].fail_reason,
        )
    winner = select_mavka_fit(all_results, method=method)
    logger.info(
        "MAVKA template method=%s (requested %s) TOM(τ)=%.8f",
        winner.method,
        method,
        winner.t_ext,
    )
    return winner, all_results


def _normalise_flux_for_min(y: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Normalise flux so the eclipse is a trough around zero amplitude scale.

    Args:
        y (numpy.ndarray): Instrumental flux.

    Returns:
        tuple: ``(y_norm, baseline, ampl_guess)``.
    """
    baseline = float(np.percentile(y, 95))
    ampl_guess = float(baseline - np.percentile(y, 5))
    if ampl_guess <= 0:
        ampl_guess = float(np.std(y)) if float(np.std(y)) > 0 else 1.0
    y_norm = (y - baseline) / ampl_guess
    return y_norm, baseline, ampl_guess


def plot_mavka_template(
    *,
    tau_data: np.ndarray,
    y_norm: np.ndarray,
    results: dict[str, ApproxFitResult],
    winner: ApproxFitResult,
    save_path: Path | None,
    show: bool,
) -> None:
    """Three-panel diagnostic: AP / WSAP / WSL on the interval stack.

    Does **not** draw the Step 2 ``fit_mask`` band: that mask comes from the
    manifest and is unrelated to the narrower MAVKA approximation support.

    Args:
        tau_data (numpy.ndarray): Folded data τ.
        y_norm (numpy.ndarray): Normalised flux at data.
        results (dict[str, ApproxFitResult]): Fits for ``AP``, ``WSAP``, ``WSL``.
        winner (ApproxFitResult): Selected template method.
        save_path (Path | None): PNG path.
        show (bool): Interactive show.
    """
    apply_interval_plot_style()
    methods = list(_TEMPLATE_METHODS)
    fig, axes = plt.subplots(1, len(methods), figsize=FIGSIZE_INTERVAL, sharey=True)
    t_lo = float(np.min(tau_data))
    t_hi = float(np.max(tau_data))
    t_line = np.linspace(t_lo, t_hi, 500)

    for ax, method in zip(axes, methods):
        result = results[method]
        ax.scatter(
            tau_data,
            y_norm,
            s=28,
            c="k",
            alpha=0.35,
            zorder=3,
            edgecolors="none",
            label="stack",
        )
        title = method
        if result.method == winner.method:
            title += " ★"
        if result.ok and result.params.size:
            y_line = model_curve(method, result.params, t_line)
            c4 = float(result.c4) if np.isfinite(result.c4) else float("nan")
            c5 = float(result.c5) if np.isfinite(result.c5) else float("nan")
            if np.isfinite(c4) and np.isfinite(c5):
                left = t_line < c4
                core = (t_line >= c4) & (t_line <= c5)
                right = t_line > c5
                if np.any(left):
                    ax.plot(
                        t_line[left],
                        y_line[left],
                        color="#6a3d9a",
                        lw=3.5,
                        alpha=0.95,
                        label="left",
                    )
                if np.any(core):
                    ax.plot(
                        t_line[core],
                        y_line[core],
                        color="#33a02c",
                        lw=4.0,
                        alpha=0.95,
                        label="core",
                    )
                if np.any(right):
                    ax.plot(
                        t_line[right],
                        y_line[right],
                        color="#ff7f00",
                        lw=3.5,
                        alpha=0.95,
                        label="right",
                    )
                ax.axvline(c4, color="maroon", lw=2.0, alpha=0.75)
                ax.axvline(c5, color="maroon", lw=2.0, alpha=0.75)
            else:
                ax.plot(
                    t_line,
                    y_line,
                    color="tab:blue",
                    lw=3.5,
                    alpha=0.95,
                    label=method,
                )
            ax.axvline(
                result.t_ext,
                color="magenta",
                ls="--",
                lw=2.5,
                alpha=0.9,
                label="TOM",
            )
            sigma_s = (
                result.sigma_t_ext * 86400.0
                if np.isfinite(result.sigma_t_ext)
                else float("nan")
            )
            title += f"\nTOM={result.t_ext:.6f} d"
            if np.isfinite(sigma_s):
                title += f"  σ={sigma_s:.1f} s"
            if result.warning:
                title += f"\n{result.warning[:70]}"
        else:
            title += f"\nFAILED: {result.fail_reason}"
        ax.set_title(title)
        ax.set_xlabel("tau (days from phase 0)")
        ax.legend(loc="best")

    axes[0].set_ylabel("normalised flux")
    fig.suptitle(
        f"MAVKA template fits (selected {winner.method}; "
        f"tau_peak={winner.t_ext:.5f} d)",
        fontsize=FONT_SIZE,
    )
    fig.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote %s", save_path)
    if show:
        plt.show(block=True)
    plt.close(fig)


def build_piece_template_mavka(
    lc_path: Path,
    *,
    piece_id: str,
    t_obs_min: float,
    t_obs_max: float,
    fold_epoch: float,
    fold_period: float,
    default_epoch: float,
    default_period: float,
    period_slope: float,
    working_domain: str,
    intervals: list[tuple[float, float]],
    intervals_path: Path,
    mavka_cfg: MavkaTemplateConfig,
    fit_cfg: FitDefaults,
    out_npz: Path,
    out_meta: Path,
    out_plot: Path | None = None,
    show_plot: bool = False,
) -> dict:
    """Build a MAVKA template for one piece and write ``template.npz`` / meta.

    ``tau_peak`` is the MAVKA TOM on the fold axis. Fits with quality warnings
    are refused (fixed method) or excluded from ``best``.

    Args:
        lc_path (Path): Detrended LC.
        piece_id (str): Piece id.
        t_obs_min (float): Template window start JD.
        t_obs_max (float): Template window end JD.
        fold_epoch (float): Fold epoch JD.
        fold_period (float): Fold period (days).
        default_epoch (float): Manifest default epoch (provenance).
        default_period (float): Manifest default period (provenance).
        period_slope (float): Manifest period slope (provenance).
        working_domain (str): ``flux`` or ``mag``.
        intervals (list[tuple[float, float]]): Absolute JD intervals.
        intervals_path (Path): Source intervals file (provenance).
        mavka_cfg (MavkaTemplateConfig): MAVKA settings.
        fit_cfg (FitDefaults): Step 2 mask settings (snapshot only).
        out_npz (Path): Output ``template.npz``.
        out_meta (Path): Output ``template_meta.json``.
        out_plot (Path | None): Diagnostic PNG.
        show_plot (bool): Interactive plot.

    Returns:
        dict: Build result (grids, winner summary).

    Raises:
        ValueError: On empty stacks, failed selection, or unsupported settings.
    """
    if mavka_cfg.extrema_mode != "min":
        raise ValueError(
            "MAVKA templates currently require extrema_mode: min "
            f"(got {mavka_cfg.extrema_mode!r})"
        )
    if not intervals:
        raise ValueError(f"piece {piece_id}: MAVKA template requires timing intervals")

    df_raw, lc_meta = load_lightcurve_frame(lc_path, working_domain=working_domain)
    folded = fold_interval_stack(
        df_raw,
        t_min=t_obs_min,
        t_max=t_obs_max,
        intervals=intervals,
        fold_epoch=fold_epoch,
        fold_period=fold_period,
    )
    frag = photometry_fragment_to_flux(
        folded,
        lc_meta,
        context=f"Piece {piece_id} Step 1 MAVKA",
    )
    y = frag["flux"].to_numpy(dtype=float)
    tau = frag["tau"].to_numpy(dtype=float)
    y_norm, baseline, ampl_guess = _normalise_flux_for_min(y)

    winner, all_results = fit_mavka_stack(tau, y_norm, method=mavka_cfg.method)
    tau_peak = float(winner.t_ext)
    tau_data_min = float(np.min(tau))
    tau_data_max = float(np.max(tau))
    if not (tau_data_min <= tau_peak <= tau_data_max):
        raise ValueError(
            f"piece {piece_id}: MAVKA TOM τ={tau_peak} lies outside data support "
            f"[{tau_data_min}, {tau_data_max}]"
        )

    n_grid = max(int(mavka_cfg.n_grid), 64)
    tau_grid = np.linspace(tau_data_min, tau_data_max, n_grid)
    mu_grid = model_curve(winner.method, winner.params, tau_grid)
    # Formal σ deferred; store residual RMS as a flat placeholder for loaders/plots.
    rms = float(winner.rms) if np.isfinite(winner.rms) else 0.0
    std_grid = np.full_like(mu_grid, max(rms, 1e-12))

    mask = resolve_fit_mask(
        mode=fit_cfg.fit_mask_mode,
        half_width_phase=fit_cfg.fit_mask_half_width_phase,
        period=fold_period,
        tau_peak=tau_peak,
    )
    warn_fit_mask_support(
        mask,
        tau_data_min=tau_data_min,
        tau_data_max=tau_data_max,
        context=f"Piece {piece_id} MAVKA",
    )

    result = {
        "tau_grid": tau_grid,
        "mean_grid": mu_grid,
        "std_grid": std_grid,
        "tau_peak": tau_peak,
        "tau_data_min": tau_data_min,
        "tau_data_max": tau_data_max,
        "baseline": baseline,
        "ampl_guess": ampl_guess,
        "x": tau,
        "y_norm": y_norm,
    }
    trial_summary = {
        mid: {
            "ok": r.ok,
            "t_ext": r.t_ext if r.ok else None,
            "sigma_t_ext_d": r.sigma_t_ext if np.isfinite(r.sigma_t_ext) else None,
            "rms": r.rms if np.isfinite(r.rms) else None,
            "warning": r.warning,
            "fail_reason": r.fail_reason,
            "eligible_for_best": _eligible_for_best(r),
        }
        for mid, r in all_results.items()
    }
    meta = {
        "piece_id": piece_id,
        "template_engine": "mavka",
        "fold_mode": "constant",
        "fold_epoch": fold_epoch,
        "t_ref": fold_epoch,
        "default_epoch": default_epoch,
        "P0_ephemeris": fold_period,
        "fold_period": fold_period,
        "P_tau": fold_period,
        "default_period": default_period,
        "p0": fold_period,
        "period_slope": period_slope,
        "t_obs_min": t_obs_min,
        "t_obs_max": t_obs_max,
        "extended_fold": False,
        "tau_units": "days (phi * P, phase 0 at tau=0; single copy, interval stack)",
        "extrema_mode": mavka_cfg.extrema_mode,
        "tau_peak": tau_peak,
        "tau_peak_source": "mavka_tom",
        "tau_data_min": tau_data_min,
        "tau_data_max": tau_data_max,
        "fit_mask_at_build": {
            **mask.as_dict(),
            "note": (
                "manifest Step 2 window snapshot only; not drawn on "
                "template_mavka.png (MAVKA support is the interval stack)"
            ),
        },
        "baseline_flux": baseline,
        "ampl_guess_flux": ampl_guess,
        "source_lc": str(lc_path.name),
        "intervals_path": str(intervals_path),
        "mavka": {
            "requested_method": mavka_cfg.method,
            "selected_method": winner.method,
            "c4": winner.c4,
            "c5": winner.c5,
            "params": winner.params.tolist(),
            "rms": winner.rms,
            "sigma_t_ext_d": winner.sigma_t_ext,
            "n_points": winner.n_points,
            "trials": trial_summary,
            "sigma_grid_note": (
                "placeholder = fit residual RMS; formal template σ deferred"
            ),
            "config": asdict(mavka_cfg),
        },
    }
    save_template_artifacts(result, out_npz=out_npz, out_meta=out_meta, meta=meta)
    plot_mavka_template(
        tau_data=tau,
        y_norm=y_norm,
        results=all_results,
        winner=winner,
        save_path=out_plot,
        show=show_plot,
    )
    return result
