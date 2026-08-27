"""Step 1: fold a detrended mag LC segment and fit a GP template (no extremum pipeline)."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern

from skvo_veb.utils.gp.noise_policy import resolve_interval_noise_sigma_norm

from fold_stack import fold_for_template
from lc_io import load_lightcurve_frame
from plot_style import FIGSIZE_TEMPLATE as FIGSIZE, FONT_SIZE, apply_plot_style
from fit_mask import resolve_fit_mask
from template_build import photometry_fragment_to_flux
from template_peak import select_template_peak

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
# LC_PATH = ROOT / "data" / "R_detrended.dat"
LC_PATH = ROOT / "data" / "R_detrended_59857_lc.dat"
OUT_NPZ = ROOT / "data" / "template.npz"
OUT_META = ROOT / "data" / "template_meta.json"
OUT_PLOT = ROOT / "data" / "template_gp.png"

T_REF = 59866.41
# P0 = 0.06066
P0 = 0.0591
PERIOD_SLOPE = 0.0
# T_OBS_MIN = 59866.0
# T_OBS_MAX = 59866.7

T_OBS_MIN = 59857.0
T_OBS_MAX = 59857.7

KERNEL_TYPE = "matern"
LENGTH_SCALE_INIT = 0.02
LENGTH_SCALE_MIN = 0.01
LENGTH_SCALE_MAX = 0.026
AMPLITUDE_INIT = 0.3
AMPLITUDE_MIN = 0.1
AMPLITUDE_MAX = 0.7
GUESS_SIGMA = False
NOISE_SCALE = 1.0
EXTREMA_MODE = "max"

N_GRID = 2000
N_RESTARTS = 3

EXTENDED_FOLD = True
PEAK_EDGE_MARGIN_FRAC_PERIOD = 0.05
PEAK_MIN_SEPARATION_FRAC_PERIOD = 0.15
PEAK_MIN_PROMINENCE_FRAC = 0.25
PEAK_DUPLICATE_PHASE_TOL = 0.05
PEAK_SELECT = "dominant"
PEAK_TAU_HINT = None
FIT_MASK_MODE = "whole_period"
FIT_MASK_HALF_WIDTH_PHASE = 0.25
JD_OFFSET_ZERO = 2400000.0
WORKING_DOMAIN = "mag"


def _apply_plot_style() -> None:
    apply_plot_style()


def fit_gp_template(frag: pd.DataFrame) -> dict:
    """Fit GP on ``tau`` / normalised flux; same kernel/noise composition as the GP page."""
    x = frag["tau"].to_numpy(dtype=float)
    y = frag["flux"].to_numpy(dtype=float)
    y_err = frag["flux_err"].to_numpy(dtype=float)

    if EXTREMA_MODE == "max":
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
        EXTREMA_MODE,
        guess_sigma=GUESS_SIGMA,
        noise_scale=NOISE_SCALE,
    )

    ckern = ConstantKernel(
        constant_value=AMPLITUDE_INIT,
        constant_value_bounds=(AMPLITUDE_MIN, AMPLITUDE_MAX),
    )
    if KERNEL_TYPE == "rbf":
        from sklearn.gaussian_process.kernels import RBF

        smooth_kern = RBF(
            length_scale=LENGTH_SCALE_INIT,
            length_scale_bounds=(LENGTH_SCALE_MIN, LENGTH_SCALE_MAX),
        )
    else:
        smooth_kern = Matern(
            length_scale=LENGTH_SCALE_INIT,
            length_scale_bounds=(LENGTH_SCALE_MIN, LENGTH_SCALE_MAX),
            nu=2.5,
        )
    kernel = ckern * smooth_kern

    gp = GaussianProcessRegressor(
        kernel=kernel,
        alpha=noise_sigma_norm ** 2
        if np.isscalar(noise_sigma_norm)
        else noise_sigma_norm ** 2,
        normalize_y=False,
        n_restarts_optimizer=N_RESTARTS,
    )
    gp.fit(x.reshape(-1, 1), y_norm)

    k = gp.kernel_
    length_scale_final = float(k.k2.length_scale)
    amplitude_final = float(k.k1.constant_value)

    tau_lo = float(x.min())
    tau_hi = float(x.max())
    pad = max((tau_hi - tau_lo) * 0.02, length_scale_final * 0.2)
    tau_grid = np.linspace(tau_lo - pad, tau_hi + pad, N_GRID).reshape(-1, 1)
    mean_grid, std_grid = gp.predict(tau_grid, return_std=True)

    selection = select_template_peak(
        tau_grid.ravel(),
        mean_grid.ravel(),
        P0,
        tau_data_min=tau_lo,
        tau_data_max=tau_hi,
        extrema_mode=EXTREMA_MODE,
        edge_margin_frac_period=PEAK_EDGE_MARGIN_FRAC_PERIOD,
        min_separation_frac_period=PEAK_MIN_SEPARATION_FRAC_PERIOD,
        min_prominence_frac=PEAK_MIN_PROMINENCE_FRAC,
        duplicate_phase_tol=PEAK_DUPLICATE_PHASE_TOL,
        select=PEAK_SELECT,
        tau_hint=PEAK_TAU_HINT,
    )
    tau_peak = selection.tau_peak
    mask = resolve_fit_mask(
        mode=FIT_MASK_MODE,
        half_width_phase=FIT_MASK_HALF_WIDTH_PHASE,
        period=P0,
        tau_peak=tau_peak,
    )
    tau_mask_min, tau_mask_max = mask.tau_min, mask.tau_max

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
        "tau_peak": tau_peak,
        "tau_mask_min": tau_mask_min,
        "tau_mask_max": tau_mask_max,
        "tau_data_min": tau_lo,
        "tau_data_max": tau_hi,
        "fit_mask": mask,
        "peak_selection": selection,
        "length_scale_final": length_scale_final,
        "amplitude_final": amplitude_final,
    }


def plot_template_fit(result: dict, *, save_path: Path | None) -> None:
    """Matplotlib: folded data and GP mean plus 1 sigma (template only, no peak inference)."""
    x = result["x"]
    y_norm = result["y_norm"]
    noise = result["noise_sigma_norm"]
    tau_grid = result["tau_grid"]
    mean_grid = result["mean_grid"]
    std_grid = result["std_grid"]
    tau_peak = result["tau_peak"]
    tau_mask_min = result["tau_mask_min"]
    tau_mask_max = result["tau_mask_max"]

    yerr = noise if np.isscalar(noise) else noise
    fig, ax = plt.subplots(figsize=FIGSIZE)
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
    ax.axvline(tau_peak, color="magenta", ls="--", lw=1.5, label=f"tau_peak={tau_peak:.5f} d")
    ax.axvspan(
        tau_mask_min,
        tau_mask_max,
        color="C1",
        alpha=0.15,
        label="fit tau mask (Step 2)",
    )
    ax.set_xlabel("tau (days from phase 0)")
    ax.set_ylabel("normalised flux")
    ax.set_title("GP template on extended phase fold")
    ax.legend()
    fig.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote plot %s", save_path)
    plt.show()


def save_template(result: dict) -> None:
    """Persist template grid and metadata for Step 2."""
    OUT_NPZ.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        OUT_NPZ,
        tau=result["tau_grid"],
        mu=result["mean_grid"],
        sigma=result["std_grid"],
        tau_peak=result["tau_peak"],
    )
    meta = {
        "t_ref": T_REF,
        "p0": P0,
        "period_slope": PERIOD_SLOPE,
        "t_obs_min": T_OBS_MIN,
        "t_obs_max": T_OBS_MAX,
        "extended_fold": EXTENDED_FOLD,
        "tau_units": "days (phi_ext * P0, phase 0 at tau=0)",
        "peak_selection": result["peak_selection"].as_dict(),
        "extrema_mode": EXTREMA_MODE,
        "tau_peak": result["tau_peak"],
        "tau_data_min": result["tau_data_min"],
        "tau_data_max": result["tau_data_max"],
        "fit_mask_at_build": result["fit_mask"].as_dict(),
        "gp_kernel": KERNEL_TYPE,
        "length_scale_final": result["length_scale_final"],
        "amplitude_final": result["amplitude_final"],
        "baseline_flux": result["baseline"],
        "ampl_guess_flux": result["ampl_guess"],
        "source_lc": str(LC_PATH.name),
    }
    OUT_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("Wrote %s and %s", OUT_NPZ, OUT_META)


def main() -> None:
    _apply_plot_style()
    logging.basicConfig(level=logging.INFO)
    df_raw, lc_meta = load_lightcurve_frame(LC_PATH, working_domain=WORKING_DOMAIN)
    logger.info(
        "Loaded %s rows from %s (domain=%s)",
        len(df_raw),
        LC_PATH.name,
        lc_meta.get("active_domain"),
    )

    folded = fold_for_template(
        df_raw,
        t_min=JD_OFFSET_ZERO + T_OBS_MIN,
        t_max=JD_OFFSET_ZERO + T_OBS_MAX,
        t_ref=JD_OFFSET_ZERO + T_REF,
        period=P0,
    )
    logger.info("Folded stack: %s points after extended fold", len(folded))

    frag = photometry_fragment_to_flux(
        folded, lc_meta, context="build_template scratch"
    )
    result = fit_gp_template(frag)
    save_template(result)
    plot_template_fit(result, save_path=OUT_PLOT)


if __name__ == "__main__":
    main()
