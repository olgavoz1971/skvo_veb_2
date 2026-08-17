"""Step 1: build GP template for one manifest piece (library entry point)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

import astropy.units as u
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern

from skvo_veb.utils.gp.noise_policy import resolve_interval_noise_sigma_norm

from fit_mask import FitMask, resolve_fit_mask, warn_fit_mask_support
from fold_stack import (
    fold_for_template,
    fold_for_template_quadratic,
    resolve_tau_period,
)
from lc_io import load_lightcurve_frame, require_photcal
from manifest_config import FitDefaults, FoldEphemerisConfig, GPTemplateDefaults
from template_peak import select_template_peak

from plot_style import FIGSIZE_TEMPLATE, apply_plot_style

logger = logging.getLogger(__name__)


def photometry_fragment_to_flux(
    folded: pd.DataFrame,
    meta: dict,
    *,
    context: str = "Step 1 GP template",
) -> pd.DataFrame:
    """Convert folded photometry to GP ``flux`` / ``flux_err`` (instrumental flux)."""
    from skvo_veb.utils.lc_config import DOMAIN_FLUX, DOMAIN_MAG

    domain = meta.get("active_domain")
    phot = folded["phot"].to_numpy(dtype=float)
    err_phot = folded["phot_err"].to_numpy(dtype=float)

    if domain == DOMAIN_FLUX:
        flux = phot
        if np.any(np.isfinite(err_phot)):
            flux_err = np.where(np.isfinite(err_phot), err_phot, np.nan)
        else:
            flux_err = np.full_like(flux, np.nan)
    elif domain == DOMAIN_MAG:
        pc = require_photcal(meta, context=context)
        mag = phot * u.mag
        flux = np.asarray(pc.mag_to_flux(mag).value, dtype=float)
        if np.any(np.isfinite(err_phot)):
            err_q = np.where(np.isfinite(err_phot), err_phot, 0.0) * u.mag
            flux_err = np.asarray(
                pc.mag_err_to_flux_err(mag, err_q).value,
                dtype=float,
            )
            flux_err = np.where(np.isfinite(err_phot), flux_err, np.nan)
        else:
            flux_err = np.full_like(flux, np.nan)
    else:
        raise ValueError(
            f"{context}: unsupported active_domain {domain!r}; expected mag or flux"
        )

    out = folded.copy()
    out["flux"] = flux
    out["flux_err"] = flux_err
    return out


def fit_gp_template(frag: pd.DataFrame, cfg: GPTemplateDefaults, *, fold_period: float) -> dict:
    """Fit GP on ``tau`` / normalised flux."""
    x = frag["tau"].to_numpy(dtype=float)
    y = frag["flux"].to_numpy(dtype=float)
    y_err = frag["flux_err"].to_numpy(dtype=float)

    if cfg.extrema_mode == "max":
        baseline = float(np.percentile(y, 5))
        ampl_guess = float(np.percentile(y, 95) - baseline)
    else:
        baseline = float(np.percentile(y, 95))
        ampl_guess = float(baseline - np.percentile(y, 5))
    if ampl_guess <= 0:
        ampl_guess = float(np.std(y)) if np.std(y) > 0 else 1.0

    y_norm = (y - baseline) / ampl_guess
    noise_sigma_norm = resolve_interval_noise_sigma_norm(
        y_err,
        x,
        y,
        baseline,
        ampl_guess,
        cfg.extrema_mode,
        guess_sigma=cfg.guess_sigma,
        noise_scale_divisor=cfg.noise_scale_divisor,
    )

    ckern = ConstantKernel(
        constant_value=cfg.amplitude_init,
        constant_value_bounds=(cfg.amplitude_min, cfg.amplitude_max),
    )
    if cfg.kernel_type == "rbf":
        from sklearn.gaussian_process.kernels import RBF

        smooth_kern = RBF(
            length_scale=cfg.length_scale_init,
            length_scale_bounds=(cfg.length_scale_min, cfg.length_scale_max),
        )
    else:
        smooth_kern = Matern(
            length_scale=cfg.length_scale_init,
            length_scale_bounds=(cfg.length_scale_min, cfg.length_scale_max),
            nu=2.5,
        )
    kernel = ckern * smooth_kern

    gp = GaussianProcessRegressor(
        kernel=kernel,
        alpha=noise_sigma_norm ** 2
        if np.isscalar(noise_sigma_norm)
        else noise_sigma_norm ** 2,
        normalize_y=False,
        n_restarts_optimizer=cfg.n_restarts,
    )
    gp.fit(x.reshape(-1, 1), y_norm)

    k = gp.kernel_
    length_scale_final = float(k.k2.length_scale)
    amplitude_final = float(k.k1.constant_value)

    tau_lo = float(x.min())
    tau_hi = float(x.max())
    pad = max((tau_hi - tau_lo) * 0.02, length_scale_final * 0.2)
    tau_grid = np.linspace(tau_lo - pad, tau_hi + pad, cfg.n_grid).reshape(-1, 1)
    mean_grid, std_grid = gp.predict(tau_grid, return_std=True)

    selection = select_template_peak(
        tau_grid.ravel(),
        mean_grid.ravel(),
        fold_period,
        tau_data_min=tau_lo,
        tau_data_max=tau_hi,
        extrema_mode=cfg.extrema_mode,
        edge_margin_frac_period=cfg.peak_edge_margin_frac_period,
        min_separation_frac_period=cfg.peak_min_separation_frac_period,
        min_prominence_frac=cfg.peak_min_prominence_frac,
        duplicate_phase_tol=cfg.peak_duplicate_phase_tol,
        select=cfg.peak_select,
        tau_hint=cfg.peak_tau_hint,
    )
    return {
        "gp": gp,
        "x": x,
        "y_norm": y_norm,
        "baseline": baseline,
        "ampl_guess": ampl_guess,
        "noise_sigma_norm": noise_sigma_norm,
        "tau_grid": tau_grid.ravel(),
        "mean_grid": mean_grid.ravel(),
        "std_grid": std_grid.ravel(),
        "tau_peak": selection.tau_peak,
        "tau_data_min": tau_lo,
        "tau_data_max": tau_hi,
        "peak_selection": selection,
        "length_scale_final": length_scale_final,
        "amplitude_final": amplitude_final,
    }


def save_template_artifacts(
    result: dict,
    *,
    out_npz: Path,
    out_meta: Path,
    meta: dict,
) -> None:
    """Persist template grid and JSON metadata."""
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_npz,
        tau=result["tau_grid"],
        mu=result["mean_grid"],
        sigma=result["std_grid"],
        tau_peak=result["tau_peak"],
    )
    out_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("Wrote %s and %s", out_npz, out_meta)


def plot_template_fit(
    result: dict,
    cfg: GPTemplateDefaults,
    *,
    mask: FitMask,
    save_path: Path | None,
    show: bool,
) -> None:
    """Matplotlib: folded data, GP mean, peak candidates and the Step 2 fit window.

    Args:
        result (dict): Output of :func:`fit_gp_template`.
        cfg (GPTemplateDefaults): Step 1 settings for this piece.
        mask (FitMask): Fit window resolved from the manifest, drawn for reference.
        save_path (Path | None): Where to write the figure, if anywhere.
        show (bool): Call ``plt.show()`` when true.
    """
    apply_plot_style()
    x = result["x"]
    y_norm = result["y_norm"]
    noise = result["noise_sigma_norm"]
    tau_grid = result["tau_grid"]
    mean_grid = result["mean_grid"]
    std_grid = result["std_grid"]
    tau_peak = result["tau_peak"]

    yerr = noise if np.isscalar(noise) else noise
    fig, ax = plt.subplots(figsize=FIGSIZE_TEMPLATE)
    ax.errorbar(
        x,
        y_norm,
        yerr=yerr,
        fmt="o",
        markersize=4,
        ecolor="0.6",
        elinewidth=0.8,
        capsize=1,
        alpha=0.7,
        label="folded data (normalised flux)",
    )
    ax.plot(tau_grid, mean_grid, color="tab:blue", lw=2, label="GP mean (template)")
    ax.fill_between(
        tau_grid,
        mean_grid - std_grid,
        mean_grid + std_grid,
        color="tab:blue",
        alpha=0.25,
        label="GP +/-1 sigma",
    )
    selection = result["peak_selection"]
    ax.axvspan(
        tau_grid.min(),
        selection.search_min,
        color="0.5",
        alpha=0.12,
        label="excluded (pad and edge margin)",
    )
    ax.axvspan(selection.search_max, tau_grid.max(), color="0.5", alpha=0.12)
    for cand in selection.candidates:
        colour = "tab:green" if cand.accepted else "black"
        ax.plot(
            cand.tau,
            cand.mu,
            marker="v" if cand.accepted else "x",
            color=colour,
            markersize=9,
            markeredgecolor="white" if cand.accepted else colour,
            markeredgewidth=1.0,
            ls="none",
            zorder=6,
        )
        ax.annotate(
            f"{cand.prominence_frac:.2f}",
            (cand.tau, cand.mu),
            textcoords="offset points",
            xytext=(0, 11),
            ha="center",
            fontsize=8,
            color=colour,
            zorder=7,
            bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.75},
        )
    ax.axvline(tau_peak, color="magenta", ls="--", lw=1.5, label=f"tau_peak={tau_peak:.5f} d")
    ax.axvspan(
        mask.tau_min,
        mask.tau_max,
        color="C1",
        alpha=0.15,
        label=(
            f"Step 2 fit window: {mask.mode}, "
            f"+/-{mask.half_width_phase:.3f} phase = +/-{mask.half_width_days:.5f} d"
        ),
    )
    ax.set_xlabel("tau (days from phase 0)")
    ax.set_ylabel("normalised flux")
    ax.set_title(f"GP template on extended phase fold ({selection.reason.split(';')[0]})")
    ax.legend()
    fig.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote plot %s", save_path)
    if show:
        plt.show()
    else:
        plt.close(fig)


def load_template_sigma_grid(npz_path: Path) -> tuple[np.ndarray, np.ndarray] | None:
    """Return sorted ``(tau, sigma)`` arrays from ``template.npz``.

    Args:
        npz_path (Path): Path to ``template.npz``.

    Returns:
        tuple[numpy.ndarray, numpy.ndarray] | None: Fold grid and GP posterior
        sigma, or ``None`` when ``sigma`` was not stored.
    """
    data = np.load(npz_path)
    if "sigma" not in data:
        return None
    tau = np.asarray(data["tau"], dtype=float)
    sigma = np.asarray(data["sigma"], dtype=float)
    order = np.argsort(tau)
    return tau[order], sigma[order]


def plot_template_artifacts(
    npz_path: Path,
    meta_path: Path,
    *,
    mask: FitMask,
    save_path: Path | None,
    show: bool = False,
) -> None:
    """Plot saved template μ(τ) from ``template.npz`` (Step 1 skipped / loaded from disk).

    Folded data points are not available when reusing artefacts, so only the curve
    is drawn; the fit window comes from the current manifest, not from the artefact.

    Args:
        npz_path (Path): ``template.npz`` (``tau``, ``mu``, optional ``sigma``, ``tau_peak``).
        meta_path (Path): ``template_meta.json`` for peak diagnostics and provenance.
        mask (FitMask): Fit window resolved from the current manifest.
        save_path (Path | None): If set, write the figure here.
        show (bool): Call ``plt.show()`` when true.
    """
    apply_plot_style()
    data = np.load(npz_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    tau = np.asarray(data["tau"], dtype=float)
    mu = np.asarray(data["mu"], dtype=float)
    tau_peak = float(data["tau_peak"])

    fig, ax = plt.subplots(figsize=FIGSIZE_TEMPLATE)
    ax.plot(tau, mu, color="tab:blue", lw=2, label="template mu(tau)")
    sigma_grid = load_template_sigma_grid(npz_path)
    if sigma_grid is not None:
        tau_sig, sigma = sigma_grid
        ax.fill_between(
            tau_sig,
            mu - sigma,
            mu + sigma,
            color="tab:blue",
            alpha=0.25,
            label="GP +/-1 sigma (saved)",
        )
    selection = meta.get("peak_selection")
    if isinstance(selection, dict):
        ax.axvspan(
            tau.min(),
            selection["search_min"],
            color="0.5",
            alpha=0.12,
            label="excluded (pad and edge margin)",
        )
        ax.axvspan(selection["search_max"], tau.max(), color="0.5", alpha=0.12)
        for cand in selection["candidates"]:
            marker = "v" if cand["accepted"] else "x"
            colour = "tab:green" if cand["accepted"] else "0.4"
            ax.plot(cand["tau"], cand["mu"], marker=marker, color=colour, markersize=7, ls="none")
    ax.axvline(tau_peak, color="magenta", ls="--", lw=1.5, label=f"tau_peak={tau_peak:.5f} d")
    ax.axvspan(
        mask.tau_min,
        mask.tau_max,
        color="C1",
        alpha=0.15,
        label=(
            f"Step 2 fit window: {mask.mode}, "
            f"+/-{mask.half_width_phase:.3f} phase = +/-{mask.half_width_days:.5f} d"
        ),
    )
    loaded_from = meta.get("template_loaded_from") or meta.get("reuse_template_from")
    title = "Loaded GP template (artefacts on disk)"
    if loaded_from:
        title = f"{title} — {loaded_from}"
    ax.set_xlabel("tau (days from phase 0)")
    ax.set_ylabel("normalised flux")
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote plot %s", save_path)
    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_fold_stack(
    folded: pd.DataFrame,
    *,
    piece_id: str,
    fold_mode: str,
    tau_period: float,
    p0_ephemeris: float,
    working_domain: str,
    save_path: Path | None,
    show: bool,
) -> None:
    """Matplotlib: raw extended fold stack before the GP fit.

    Args:
        folded (pandas.DataFrame): Output of :func:`fold_for_template` or quadratic fold.
        piece_id (str): Manifest piece identifier for the title.
        fold_mode (str): ``constant`` or quadratic ephemeris kind.
        tau_period (float): ``P_τ`` used for the tau axis (days).
        p0_ephemeris (float): Reference period ``P₀`` from the manifest.
        working_domain (str): Manifest ``photometry_domain`` (``mag`` or ``flux``).
        save_path (Path | None): Where to write the figure, if anywhere.
        show (bool): Call ``plt.show()`` when true.
    """
    from skvo_veb.utils.lc_config import DOMAIN_MAG

    apply_plot_style()
    tau = folded["tau"].to_numpy(dtype=float)
    phot = folded["phot"].to_numpy(dtype=float)
    has_err = "phot_err" in folded.columns and np.any(
        np.isfinite(folded["phot_err"].to_numpy())
    )
    phot_err = folded["phot_err"].to_numpy(dtype=float) if has_err else None

    fig, ax = plt.subplots(figsize=FIGSIZE_TEMPLATE)
    if has_err and phot_err is not None:
        ax.errorbar(
            tau,
            phot,
            yerr=phot_err,
            fmt="o",
            markersize=3,
            ecolor="0.6",
            elinewidth=0.6,
            capsize=1,
            alpha=0.45,
            label="folded stack",
        )
    else:
        ax.plot(tau, phot, "o", markersize=3, alpha=0.45, color="C0", label="folded stack")

    ax.axvline(0.0, color="0.35", ls=":", lw=1.0)
    ax.axvline(tau_period, color="0.35", ls=":", lw=1.0, alpha=0.6)
    ax.set_xlabel("tau (days from phase 0)")
    if working_domain == DOMAIN_MAG:
        ax.invert_yaxis()
        y_label = "detrended mag"
    else:
        y_label = "flux"
    ax.set_ylabel(y_label)
    if fold_mode == "constant":
        subtitle = f"constant P = {tau_period:.8f} d"
    else:
        subtitle = (
            f"{fold_mode} fold, P0 = {p0_ephemeris:.8f} d, "
            f"P_tau = {tau_period:.8f} d"
        )
    ax.set_title(f"Step 1: folded stack before GP ({piece_id})\n{subtitle}")
    ax.legend(loc="best")
    fig.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote plot %s", save_path)
    if show:
        plt.show()
    else:
        plt.close(fig)


def build_piece_template(
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
    cfg: GPTemplateDefaults,
    fit_cfg: FitDefaults,
    fold_ephemeris: FoldEphemerisConfig | None = None,
    out_npz: Path,
    out_meta: Path,
    out_plot: Path | None = None,
    show_plot: bool = False,
) -> dict:
    """Run Step 1 for one piece; return GP result dict and write artefacts.

    Args:
        fold_epoch: Fold epoch (absolute JD) used for this build (piece ``local_epoch``
            or manifest ``default_epoch``).
        fold_period: Reference period ``P₀`` for constant fold or quadratic ephemeris.
        default_epoch: Manifest ``template_fold.default_epoch`` at build time (provenance).
        fold_ephemeris: Optional quadratic O-C fold; ``None`` → constant-``P`` fold.
        fit_cfg: Step 2 settings for this piece, used only to draw and record the fit
            window that Step 2 will resolve again from the manifest.
    """
    df_raw, lc_meta = load_lightcurve_frame(lc_path, working_domain=working_domain)

    if fold_ephemeris is None:
        tau_period = fold_period
        folded = fold_for_template(
            df_raw,
            t_min=t_obs_min,
            t_max=t_obs_max,
            t_ref=fold_epoch,
            period=fold_period,
        )
        fold_mode = "constant"
        e_start = None
        p_tau_source = "P0"
    else:
        tau_period, e_start = resolve_tau_period(
            period=fold_period,
            epoch=fold_epoch,
            oc_a=fold_ephemeris.oc_a,
            oc_b=fold_ephemeris.oc_b,
            oc_c=fold_ephemeris.oc_c,
            jd_segment_start=t_obs_min,
            tau_period_override=fold_ephemeris.tau_period,
        )
        folded = fold_for_template_quadratic(
            df_raw,
            t_min=t_obs_min,
            t_max=t_obs_max,
            epoch=fold_epoch,
            period=fold_period,
            oc_a=fold_ephemeris.oc_a,
            oc_b=fold_ephemeris.oc_b,
            oc_c=fold_ephemeris.oc_c,
            tau_period=tau_period,
        )
        fold_mode = fold_ephemeris.kind
        p_tau_source = (
            "manifest_override"
            if fold_ephemeris.tau_period is not None
            else "segment_start"
        )
        logger.info(
            "Piece %s: quadratic fold P0=%.8f, P_tau=%.8f (E_start=%.2f, %s)",
            piece_id,
            fold_period,
            tau_period,
            e_start,
            p_tau_source,
        )

    logger.info("Piece %s: folded stack %s points", piece_id, len(folded))

    stack_plot = None if out_plot is None else out_plot.with_name("template_stack.png")
    plot_fold_stack(
        folded,
        piece_id=piece_id,
        fold_mode=fold_mode,
        tau_period=tau_period,
        p0_ephemeris=fold_period,
        working_domain=working_domain,
        save_path=stack_plot,
        show=show_plot,
    )

    frag = photometry_fragment_to_flux(
        folded,
        lc_meta,
        context=f"Piece {piece_id} Step 1 GP",
    )
    result = fit_gp_template(frag, cfg, fold_period=tau_period)

    mask = resolve_fit_mask(
        mode=fit_cfg.fit_mask_mode,
        half_width_phase=fit_cfg.fit_mask_half_width_phase,
        period=tau_period,
        tau_peak=result["tau_peak"],
    )
    warn_fit_mask_support(
        mask,
        tau_data_min=result["tau_data_min"],
        tau_data_max=result["tau_data_max"],
        context=f"Piece {piece_id}",
    )

    meta = {
        "piece_id": piece_id,
        "fold_mode": fold_mode,
        "fold_epoch": fold_epoch,
        "t_ref": fold_epoch,
        "default_epoch": default_epoch,
        "P0_ephemeris": fold_period,
        "fold_period": tau_period,
        "P_tau": tau_period,
        "default_period": default_period,
        "p0": tau_period,
        "period_slope": period_slope,
        "t_obs_min": t_obs_min,
        "t_obs_max": t_obs_max,
        "extended_fold": cfg.extended_fold,
        "tau_units": "days (phi_ext * P_tau, phase 0 at tau=0)",
        "peak_selection": result["peak_selection"].as_dict(),
        "extrema_mode": cfg.extrema_mode,
        "tau_peak": result["tau_peak"],
        "tau_data_min": result["tau_data_min"],
        "tau_data_max": result["tau_data_max"],
        "fit_mask_at_build": {
            **mask.as_dict(),
            "note": "snapshot only; Step 2 re-resolves the window from the manifest",
        },
        "gp_kernel": cfg.kernel_type,
        "length_scale_final": result["length_scale_final"],
        "amplitude_final": result["amplitude_final"],
        "baseline_flux": result["baseline"],
        "ampl_guess_flux": result["ampl_guess"],
        "source_lc": str(lc_path.name),
        "gp_template_config": asdict(cfg),
    }
    if fold_ephemeris is not None:
        meta["fold_ephemeris"] = {
            "kind": fold_ephemeris.kind,
            "a": fold_ephemeris.oc_a,
            "b": fold_ephemeris.oc_b,
            "c": fold_ephemeris.oc_c,
            "tau_period_override": fold_ephemeris.tau_period,
            "P_tau_source": p_tau_source,
            "E_start": e_start,
            "jd_segment_start": t_obs_min,
        }
    save_template_artifacts(result, out_npz=out_npz, out_meta=out_meta, meta=meta)
    plot_template_fit(result, cfg, mask=mask, save_path=out_plot, show=show_plot)
    return result
