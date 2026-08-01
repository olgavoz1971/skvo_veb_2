"""Gaussian Process peak timing pipeline (sklearn)."""

import logging

logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd
from scipy.stats import median_abs_deviation
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, RBF

from skvo_veb.utils.gp.config import (
    INTERVAL_DIVISOR,
    LENGTH_SCALE_FACTOR,
    SAMPLING_SCALE_FACTOR,
)
def residual_noise_estimate(x, y, baseline, ampl_guess, extrema_mode):
    """
    Estimate photometric noise from residuals after subtracting a simple peak model.

    My brave assumption:
    I pretend that the light-curve segment is dominated by a single smooth feature
    and approximate it with a very simple symmetric triangular shape.

    What I actually do:
    1. I draw two straight lines: up to the peak and down from the peak.
    2. I subtract this “masterpiece” from the data.
    3. I declare whatever is left (residuals) to be observational noise.

    I want to remove large-scale variability first, so that the remaining scatter
    mostly reflects measurement errors rather than real signal.

    The real light curve is more complex (at lest asymmetric).
    Anyway I provide user with tuning factor, so, they can fix things
    """

    # robust estimate of total scatter in flux
    mad_raw = median_abs_deviation(y, scale='normal')

    # --- define simple symmetric triangular model of maximum ---
    y_vals = y
    x_left, x_right = x.min(), x.max()
    x_center = 0.5 * (x_left + x_right)

    # If mode='max', y_peak is baseline + ampl_guess (higher)
    # If mode='min', y_peak is baseline - ampl_guess (lower)
    if extrema_mode == 'max':
        y_peak = baseline + ampl_guess
    else:
        y_peak = baseline - ampl_guess

    # y_base = baseline
    # y_peak = baseline + ampl_guess

    y_model = np.zeros_like(y_vals)

    # The slopes naturally follow y_peak:
    # Left branch
    left_mask = x <= x_center
    y_model[left_mask] = baseline + (y_peak - baseline) * (
            (x[left_mask] - x_left) / (x_center - x_left)
    )

    # Right branch
    right_mask = x > x_center
    y_model[right_mask] = y_peak - (y_peak - baseline) * (
            (x[right_mask] - x_center) / (x_right - x_center)
    )

    # --- residuals ---
    residuals = y_vals - y_model

    # left branch (rising)
    # left_mask = x <= x_center
    # y_model[left_mask] = y_base + (y_peak - y_base) * (
    #         (x[left_mask] - x_left) / (x_center - x_left)
    # )

    # right branch (falling)
    # right_mask = x > x_center
    # y_model[right_mask] = y_peak - (y_peak - y_base) * (
    #         (x[right_mask] - x_center) / (x_right - x_center)
    # )

    # --- residuals ---
    # residuals = y_vals - y_model

    # robust noise estimate from residuals
    mad = median_abs_deviation(residuals, scale='normal')

    logger.info(f'{mad=:.3f} {np.std(residuals) * 0.5=:.3f} {mad_raw=:.3f}')
    mad = mad if mad > 0 else np.std(residuals) * 0.5
    noise_sigma = min(mad_raw, mad)  # type: ignore

    return noise_sigma


def guess_length_scale(df):
    total_duration = df['jd'].max() - df['jd'].min()

    # The typical gap between points
    dt = np.diff(np.sort(df['jd']))
    sampling_scale = np.median(dt) if len(dt) > 0 else 0.01

    # A good starting point is a part (half?) the window (one "slope" of the feature)
    length_scale_init = total_duration / INTERVAL_DIVISOR

    # Min: Don't let the GP wiggle faster than our data resolution (Nyquist-ish)
    length_scale_min = sampling_scale * SAMPLING_SCALE_FACTOR

    # Max: Don't let it get so stiff it can't fit the feature in the window
    length_scale_max = length_scale_init * LENGTH_SCALE_FACTOR

    # Safety check: ensure min < init < max
    length_scale_min = min(length_scale_min, length_scale_init * 0.5)

    return {
        'length_scale_min': length_scale_min,
        'length_scale_init': length_scale_init,
        'length_scale_max': length_scale_max
    }


# MAIN GP PIPELINE


def gp_peak_pipeline(
        frag: pd.DataFrame,
        params,
        n_grid=2000,
        n_samples_uncert=300,
        random_state=None,      # if set to specific number (seed) will reproduce "random" stuff
        plot_final=False,
        plot_demo=False
) -> dict:
    """
    Fit GP to a fragment and estimate peak position (JD) with uncertainty.

    Parameters
    ----------
    frag : pd.DataFrame, piece og the lightcurve we are working with
        Must contain 'jd' and 'flux'. May contain 'flux_err'
    params : dict
        GP regression parameters:
        - 'guess_sigma' If guess_sigma=True OR no valid errors → use MAD
        - 'noise_scale_divisor' Empirical factor, allow user tune sigma estimated by algorthm
        - 'length_scale_init' Initial guess about GP lenght scale
        - 'length_scale_min', 'length_scale_max'    Bounds
        - 'white_noise_level_init' Initial guess about White Kernel noise level
        - 'white_noise_level_min', 'white_noise_level_max' Bounds
        - 'extrema_mode', 'min' or 'max'

    n_grid : int
        Number of points in the fine evaluation grid (for mean/derivative).
    n_samples_uncert : int
        Number of posterior samples used to estimate JD uncertainty.
    random_state : int
        Seed for reproducible posterior sampling.
    plot_final  : plot results as matplotlib graph (debug)
    plot_demo   : GP plot for demonstration (outreach)

    Returns
    -------
    result : dict
        {
            'jd_peak': float,               # estimated peak JD (from GP mean)
            'jd_peak_std': float,           # uncertainty (std) from posterior samples
            'gp': GaussianProcessRegressor, # fitted GP object
            'n_samples_uncert'              # number of samples to estimate moment uncertainty
            'mean_peak'                     # mean peak
            'peaks_jd'                      # raw peak JDs from posterior samples
            'jd_grid'                       # evaluation grid
            'mean_grid'                     # GP mean on grid
            'std_grid'
            'noise_sigma_norm'              # normalised sigma of the input data
            'extrema_mode'                  # max or min
        }
    """

    x = frag['jd'].values.copy()
    y = frag['flux'].values.copy()
    y_err = frag['flux_err'].values.copy()
    jd_left = frag['jd'].min()
    jd_right = frag['jd'].max()

    # --- 2. Determine Search Mode ---
    # Get mode from params: 'min' or 'max' (default to 'min' as per your UI)
    extrema_mode = params.get('extrema_mode', 'min')

    # --- 3. baseline and amplitude (Mode Aware) ---
    if extrema_mode == 'max':
        # For a peak: baseline is at the bottom, amplitude is positive (up)
        baseline = float(np.percentile(y, 5))
        ampl_guess = np.percentile(y, 95) - baseline
    else:
        # For a minimum: baseline is at the top, amplitude is "negative" (down)
        # OR keep amplitude positive but flip the model logic.
        # Let's keep ampl_guess positive and just flip the triangle while (and if)
        # guess_sigma in residual_noise_estimate()
        baseline = float(np.percentile(y, 95))
        ampl_guess = baseline - np.percentile(y, 5)

    if ampl_guess <= 0:
        ampl_guess = np.std(y) if np.std(y) > 0 else 1.0

    # baseline = float(np.percentile(y, 5))
    # ampl_guess = np.percentile(y, 95) - baseline
    logger.info(f'{baseline=:.3f} {ampl_guess=:.3f}')

    # if ampl_guess <= 0:
    #     ampl_guess = np.std(y) if np.std(y) > 0 else 1.0

    # --- 4. normalisation ---
    y_norm = (y - baseline) / ampl_guess

    # --- 3. estimate noise ---
    # If guess_sigma=True OR no valid errors → use MAD
    if params['guess_sigma'] or np.all(np.isnan(y_err)):
        noise_sigma = residual_noise_estimate(x, y, baseline, ampl_guess, extrema_mode)
        noise_sigma /= params['noise_scale_divisor']  # empirical factor, allow user tune it
        logger.info(f'guessed {noise_sigma=:.3f}')
        # propagate noise into normalized units
        noise_sigma_norm = noise_sigma / ampl_guess
    else:
        logger.info(f'noise_sigma mean {np.mean(y_err):.3f}')
        y_err /= params['noise_scale_divisor']      # allow user to tweak (to manipulate!) the uncertainties
        noise_sigma_norm = y_err / ampl_guess

    # --- 5. kernel ---
    amplitude = params['amplitude_init']
    amplitude_bounds = (params['amplitude_min'], params['amplitude_max'])

    length_scale = params['length_scale_init']
    # logger.info(f'length_scale_guess={length_scale:.3f}')
    ls_bounds = (params['length_scale_min'], params['length_scale_max'])
    y_norm_var = np.var(y_norm)
    # logger.info(f'{y_norm_var=:.3f}')

    # Vertical scale kernel (Amplitude)

    # constant_value_bounds = (1e-4, 20.0)
    # constant_value_bounds=(y_norm_var * 0.01, y_norm_var * 100.0)

    ckern = ConstantKernel(
        # constant_value=1.0,
        constant_value=amplitude,
        constant_value_bounds=amplitude_bounds
    )

    # Horizontal scale kernel (Smoothness)
    # Check a new parameter 'kernel_type' (default to Matern for backward compatibility)
    kernel_type = params.get('kernel_type', 'matern')

    if kernel_type == 'rbf':
        # RBF is infinitely differentiable - very smooth
        smooth_kern = RBF(length_scale=length_scale, length_scale_bounds=ls_bounds)
    else:
        # Matern 2.5 is twice differentiable - "physically" smooth but more flexible
        smooth_kern = Matern(length_scale=length_scale, length_scale_bounds=ls_bounds, nu=2.5)

    kernel = ckern * smooth_kern

    # ConstantKernel = amplitude (vertical scale) of the GP signal
    # constant_value=1.0 because we work with normalised fluxes
    # kernel = (
    #         ConstantKernel(constant_value=1.0,
    #                        constant_value_bounds=(y_norm_var * 0.01, y_norm_var * 100.0)) *
    #         Matern(length_scale=length_scale,
    #                length_scale_bounds=(params['length_scale_min'], params['length_scale_max']),
    #                nu=2.5) +
    #         WhiteKernel(noise_level=params['white_noise_level_init'],
    #                     noise_level_bounds=(params['white_noise_level_min'], params['white_noise_level_max']))
    # )

    logger.info(f'Start Gaussian Process with {kernel_type.upper()} kernel')

    gp = GaussianProcessRegressor(
        kernel=kernel,
        alpha=noise_sigma_norm ** 2,
        normalize_y=False,
        n_restarts_optimizer=3  # to find better _global_ optimum and do not get stuck in local one
    )

    logger.info('...')

    # --- 6. fit ---
    gp.fit(x.reshape(-1, 1), y_norm)  # sklearn expects a table of features, even if there is only one column (time).

    # logger.info(gp.kernel_)
    # Extract kernel parameters
    k = gp.kernel_
    amplitude_final = k.k1.constant_value
    length_scale_final = k.k2.length_scale
    # length_scale_final = k.k1.k2.length_scale
    # noise_level_final = k.k2.noise_level
    # amplitude_final = k.k1.k1.constant_value

    logger.info(f'Fit ready: {length_scale_final=:.3f} {amplitude_final=:.3f}')

    # --- 7. predict ---
    # ------- 7.1 grid ---
    # ------- 7.1 grid ---
    # padding around an interval:
    pad = max((jd_right - jd_left) * 0.02, length_scale_final * 0.2)
    grid_min = max(jd_left - pad, x.min())
    grid_max = min(jd_right + pad, x.max())
    jd_grid = np.linspace(grid_min, grid_max, n_grid).reshape(-1, 1)

    # ------- 7.2 predict ---
    mean_grid, std_grid = gp.predict(jd_grid, return_std=True)

    # --- 9. Estimate Extremum on Mean Grid ---
    if extrema_mode == 'max':
        idx_extr = np.argmax(mean_grid.ravel())
    else:
        idx_extr = np.argmin(mean_grid.ravel())

    jd_extr = jd_grid.ravel()[idx_extr]
    mean_extr = mean_grid.ravel()[idx_extr]
    logger.info(f'From GP predict: {jd_extr=:.10f} {mean_extr=:.10f}')

    # --- 10. Uncertainty via Posterior Sampling ---
    # Draw samples: (n_points, n_samples)
    # Check if random_state is None, if so, give it a truly random integer.
    # From Dash Plotly random_state=None still reproduces results
    if random_state is None:
        # local NumPy generator to avoid global conflicts
        random_state = int(np.random.default_rng().integers(0, 2**31 - 1))

    samples = gp.sample_y(jd_grid, n_samples=n_samples_uncert, random_state=random_state)

    if extrema_mode == 'max':
        # Find indices of maxima for each sampled curve
        extr_indices = np.argmax(samples, axis=0)
    else:
        # Find indices of minima for each sampled curve
        extr_indices = np.argmin(samples, axis=0)

    extr_jds = jd_grid.ravel()[extr_indices]

    # Calculate uncertainty (standard deviation of the time of extremum)
    jd_extr_std = float(np.std(extr_jds))
    jd_extr_mean = float(np.mean(extr_jds))
    logger.info(f'From samples: {jd_extr_std=:.7f} {jd_extr_mean=:.7f}')

    if plot_final or plot_demo:
        from skvo_veb.utils.gp import debug_plots

        if plot_final:
            debug_plots.plot_GP_results(
                x, y_norm, noise_sigma_norm,
                jd_extr, mean_extr, extr_jds, None, jd_extr_std,
                jd_grid, mean_grid, std_grid, n_samples_uncert,
            )
        if plot_demo:
            debug_plots.plot_GP_sampling_demo(
                x, y_norm, noise_sigma_norm, jd_grid,
                mean_grid, std_grid, samples, extr_jds, extrema_mode,
            )

    return {
        "noise_sigma_norm": noise_sigma_norm,
        "jd_grid": jd_grid,
        "mean_grid": mean_grid,
        "std_grid": std_grid,
        "peaks_jd": extr_jds,
        "jd_peak": jd_extr,
        "jd_peak_std": jd_extr_std,
        "mean_peak": mean_extr,
        "n_samples_uncert": n_samples_uncert,
        "gp": gp,
        "extrema_mode": extrema_mode,
    }
