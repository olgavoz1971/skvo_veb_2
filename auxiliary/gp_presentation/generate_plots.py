"""Gaussian Process regression illustration generator for variable star lightcurves.

Generates a synthetic RR Lyrae / Cepheid-like lightcurve with a characteristic
hump on the descending arm, adds observational noise and a data gap, fits a
Gaussian Process (GP) regressor, and creates high-resolution, publication-quality
illustrations for presentations.
"""

import os
import logging
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import UnivariateSpline
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, RBF

# Import configuration parameters
import config

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def true_lightcurve(x):
    """Generate the true, noise-free RR Lyrae / Cepheid-like lightcurve.
    
    Uses a Fourier series to create an asymmetric pulsation shape (steep rise,
    slow decline) and adds a Gaussian bump to represent a physical 'hump'
    on the descending arm.
    
    Args:
        x (np.ndarray): Phase values in [0, 1].
        
    Returns:
        np.ndarray: True lightcurve flux values.
    """
    # 1. Base pulsation from Fourier series
    y_base = np.zeros_like(x)
    for k, (amp, phase) in enumerate(config.FOURIER_COEFFS, 1):
        y_base += amp * np.sin(2 * np.pi * k * x + phase)
        
    # 2. Add the physical hump on the descending arm
    y_hump = config.HUMP_AMPLITUDE * np.exp(
        -0.5 * ((x - config.HUMP_PHASE) / config.HUMP_WIDTH) ** 2
    )
    
    # Combine and shift to have a mean around 1.0 (standard for normalised flux)
    return 1.0 + y_base + y_hump

def generate_data():
    """Generate synthetic observational data with noise and a gap.
    
    Returns:
        tuple: (x_true, y_true, x_obs, y_obs, y_err)
    """
    np.random.seed(config.RANDOM_SEED)
    
    # Dense grid for plotting the true underlying physics
    x_true = np.linspace(0.0, 1.0, 1000)
    y_true = true_lightcurve(x_true)
    
    # Irregularly sampled observation times (realistic for astronomy)
    x_raw = np.random.uniform(0.0, 1.0, config.NUM_POINTS)
    x_raw.sort()
    
    # Compute true flux at observation times and add Gaussian noise
    y_raw_true = true_lightcurve(x_raw)
    noise = np.random.normal(0.0, config.NOISE_SIGMA, config.NUM_POINTS)
    y_raw = y_raw_true + noise
    
    # Apply the data gap (e.g., daytime, satellite orbit gap, or instrument shutdown)
    gap_mask = (x_raw < config.GAP_START) | (x_raw > config.GAP_END)
    x_obs = x_raw[gap_mask]
    y_obs = y_raw[gap_mask]
    y_err = np.full_like(x_obs, config.NOISE_SIGMA)
    
    logger.info(
        f"Generated {config.NUM_POINTS} raw points. "
        f"After applying gap [{config.GAP_START:.2f}, {config.GAP_END:.2f}], "
        f"{len(x_obs)} observations remain."
    )
    return x_true, y_true, x_obs, y_obs, y_err

def fit_gaussian_process(x_obs, y_obs, y_err):
    """Fit a Gaussian Process regressor to the observed data.
    
    Args:
        x_obs (np.ndarray): Observed times/phases.
        y_obs (np.ndarray): Observed fluxes.
        y_err (np.ndarray): Observational errors.
        
    Returns:
        tuple: (gp, x_grid, y_mean, y_std, y_samples)
    """
    # Define the kernel: ConstantKernel (amplitude) * Matern or RBF
    if config.GP_KERNEL_TYPE == "matern":
        smooth_kernel = Matern(
            length_scale=config.GP_LENGTH_SCALE_INIT,
            length_scale_bounds=(config.GP_LENGTH_SCALE_MIN, config.GP_LENGTH_SCALE_MAX),
            nu=config.GP_MATERN_NU
        )
    else:
        smooth_kernel = RBF(
            length_scale=config.GP_LENGTH_SCALE_INIT,
            length_scale_bounds=(config.GP_LENGTH_SCALE_MIN, config.GP_LENGTH_SCALE_MAX)
        )
        
    kernel = ConstantKernel(
        constant_value=config.GP_AMP_INIT,
        constant_value_bounds=(config.GP_AMP_MIN, config.GP_AMP_MAX)
    ) * smooth_kernel
    
    # Instantiate the GP Regressor
    # alpha represents the variance of the observational noise
    gp = GaussianProcessRegressor(
        kernel=kernel,
        alpha=y_err ** 2,
        normalize_y=False,
        n_restarts_optimizer=config.GP_N_RESTARTS,
        random_state=config.RANDOM_SEED
    )
    
    # Fit to the observed data
    gp.fit(x_obs.reshape(-1, 1), y_obs)
    logger.info(f"Fitted GP Kernel: {gp.kernel_}")
    
    # Predict on a dense grid
    x_grid = np.linspace(0.0, 1.0, 500).reshape(-1, 1)
    y_mean, y_std = gp.predict(x_grid, return_std=True)
    
    # Draw random function samples from the posterior GP distribution
    y_samples = gp.sample_y(x_grid, n_samples=config.N_POSTERIOR_SAMPLES, random_state=config.RANDOM_SEED)
    
    return gp, x_grid.ravel(), y_mean, y_std, y_samples

def fit_spline(x_obs, y_obs):
    """Fit a Penalised B-spline (P-spline) to the observed data.
    
    This is a sophisticated, non-periodic spline approach from auxiliary/trend
    that uses a roughness penalty on the second differences of B-spline coefficients
    to prevent overfitting the noise.
    
    Args:
        x_obs (np.ndarray): Observed times/phases.
        y_obs (np.ndarray): Observed fluxes.
        
    Returns:
        tuple: (x_grid, y_spline)
    """
    from scipy.interpolate import BSpline
    
    # Sort observations
    order = np.argsort(x_obs)
    x_sorted = x_obs[order]
    y_sorted = y_obs[order]
    
    n_segments = 15
    spline_degree = 3
    penalty_lambda = config.SPLINE_PENALTY_LAMBDA
    
    t_min = float(x_sorted[0])
    t_max = float(x_sorted[-1])
    
    internal = np.linspace(t_min, t_max, n_segments + 2)[1:-1]
    knots = np.r_[
        [t_min] * (spline_degree + 1),
        internal,
        [t_max] * (spline_degree + 1),
    ]
    
    # Build design matrix
    design = BSpline.design_matrix(x_sorted, knots, spline_degree)
    x_mat = design.toarray() if hasattr(design, "toarray") else np.asarray(design)
    
    # Second difference penalty matrix
    n_coeffs = x_mat.shape[1]
    diff = np.diff(np.eye(n_coeffs), n=2, axis=0)
    
    # Solve penalised least squares
    normal = x_mat.T @ x_mat + penalty_lambda * (diff.T @ diff)
    rhs = x_mat.T @ y_sorted
    coef = np.linalg.solve(normal, rhs)
    
    # Evaluate on dense grid
    x_grid = np.linspace(0.0, 1.0, 500)
    spl = BSpline(knots, coef, spline_degree, extrapolate=True)
    y_spline = spl(x_grid)
    
    return x_grid, y_spline

def fit_trigonometric(x_obs, y_obs, n_harmonics=3):
    """Fit a trigonometric (Fourier series) model to the observed data.
    
    Uses linear least squares to fit a sum of sines and cosines.
    
    Args:
        x_obs (np.ndarray): Observed times/phases.
        y_obs (np.ndarray): Observed fluxes.
        n_harmonics (int): Number of Fourier harmonics to fit.
        
    Returns:
        tuple: (x_grid, y_trig)
    """
    # Design matrix for linear least squares
    A = [np.ones_like(x_obs)]
    for i in range(1, n_harmonics + 1):
        A.append(np.sin(2 * np.pi * i * x_obs))
        A.append(np.cos(2 * np.pi * i * x_obs))
    A = np.column_stack(A)
    
    # Solve linear least squares
    coeffs, _, _, _ = np.linalg.lstsq(A, y_obs, rcond=None)
    
    # Predict on grid
    x_grid = np.linspace(0.0, 1.0, 500)
    A_grid = [np.ones_like(x_grid)]
    for i in range(1, n_harmonics + 1):
        A_grid.append(np.sin(2 * np.pi * i * x_grid))
        A_grid.append(np.cos(2 * np.pi * i * x_grid) )
    A_grid = np.column_stack(A_grid)
    
    y_trig = A_grid @ coeffs
    return x_grid, y_trig

def plot_gp_regression(x_true, y_true, x_obs, y_obs, y_err, x_grid, y_mean, y_std, y_samples):
    """Generate and save the textbook-style Gaussian Process regression plot."""
    plt.figure(figsize=(10, 6.5), dpi=300)
    
    # Calculate dynamic y-axis limits with padding
    y_all = np.concatenate([y_true, y_obs, y_mean - 2 * y_std, y_mean + 2 * y_std])
    y_min = y_all.min()
    y_max = y_all.max()
    y_range = y_max - y_min
    ylim_bottom = y_min - 0.08 * y_range
    ylim_top = y_max + 0.15 * y_range  # Extra padding at the top for labels/text
    
    # 1. Plot the true underlying physical lightcurve (bright and noticeable)
    # plt.plot(
    #     x_true, y_true,
    #     color="#E74C3C", linestyle="-", linewidth=2.0,
    #     label="True Physical Lightcurve"
    # )
    
    # 2. Plot the GP uncertainty bands (1-sigma and 2-sigma)
    plt.fill_between(
        x_grid, y_mean - 2 * y_std, y_mean + 2 * y_std,
        color="#1F77B4", alpha=0.12, label="GP Posterior Uncertainty (±2$\sigma$)"
    )
    plt.fill_between(
        x_grid, y_mean - y_std, y_mean + y_std,
        color="#1F77B4", alpha=0.25, label="GP Posterior Uncertainty (±1$\sigma$)"
    )
    
    # 3. Plot individual posterior function samples (the "textbook look")
    n_plot = max(1, int(config.N_POSTERIOR_SAMPLES * (config.PLOT_SAMPLES_PERCENT / 100.0)))
    logger.info(f"Plotting {n_plot} out of {config.N_POSTERIOR_SAMPLES} posterior samples ({config.PLOT_SAMPLES_PERCENT}%).")
    for i in range(n_plot):
        plt.plot(
            x_grid, y_samples[:, i],
            linestyle="-", linewidth=0.8, alpha=0.5,
            label="Posterior Function Sample" if i == 0 else ""
        )
        
    # 4. Plot the GP mean prediction
    plt.plot(
        x_grid, y_mean,
        color="#1F77B4", linestyle="-", linewidth=2.5,
        label="GP Mean Prediction"
    )
    
    # 5. Plot the noisy observed data points with errorbars (semi-transparent)
    plt.errorbar(
        x_obs, y_obs, yerr=y_err,
        fmt="o", color="#2C3E50", markersize=5, elinewidth=1.2, capsize=2,
        alpha=0.4, label="Observed Data (with Noise)"
    )
    
    # Styling and Labels (UK English spelling)
    # plt.title("Gaussian Process Regression: Modelling a Variable Star with a Data Gap", fontsize=14, pad=15, fontweight="bold")
    plt.xlabel("Phase", fontsize=12, labelpad=10)
    plt.ylabel("Normalised Flux", fontsize=12, labelpad=10)
    
    # Set axis limits with some padding
    plt.xlim(-0.02, 1.02)
    plt.ylim(ylim_bottom, ylim_top)
    
    # Clean up spines (borders)
    ax = plt.gca()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#BDC3C7")
    ax.spines["bottom"].set_color("#BDC3C7")
    
    # Add a subtle grid
    plt.grid(True, linestyle=":", alpha=0.5, color="#BDC3C7")
    
    # Legend placement outside or inside nicely
    plt.legend(loc="lower left", frameon=True, facecolor="white", edgecolor="none", shadow=False, fontsize=9.5)
    
    plt.tight_layout()
    output_path = "auxiliary/gp_presentation/gp_regression_only.png"
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved GP regression plot to {output_path}")

def plot_spline_comparison(x_true, y_true, x_obs, y_obs, y_err, x_grid_spline, y_spline):
    """Generate and save the spline interpolation plot for comparison."""
    plt.figure(figsize=(10, 6.5), dpi=300)
    
    # Calculate dynamic y-axis limits with padding
    y_all = np.concatenate([y_true, y_obs, y_spline])
    y_min = y_all.min()
    y_max = y_all.max()
    y_range = y_max - y_min
    ylim_bottom = y_min - 0.08 * y_range
    ylim_top = y_max + 0.15 * y_range  # Extra padding at the top for labels/text
    
    # 1. Plot the true underlying physical lightcurve (bright and noticeable)
    # plt.plot(
    #     x_true, y_true,
    #     color="#E74C3C", linestyle="-", linewidth=2.0,
    #     label="True Physical Lightcurve"
    # )
    
    # 2. Plot the Spline fit
    plt.plot(
        x_grid_spline, y_spline,
        color="#E67E22", linestyle="-", linewidth=2.5,
        label="Smoothing Spline Fit (P-spline)"
    )
    
    # 3. Plot the noisy observed data points (semi-transparent)
    plt.errorbar(
        x_obs, y_obs, yerr=y_err,
        fmt="o", color="#2C3E50", markersize=5, elinewidth=1.2, capsize=2,
        alpha=0.4, label="Observed Data (with Noise)"
    )
    
    # Styling and Labels (UK English spelling)
    # plt.title("Classical Spline Interpolation: Smooth Non-Periodic Fit", fontsize=14, pad=15, fontweight="bold")
    plt.xlabel("Phase", fontsize=12, labelpad=10)
    plt.ylabel("Normalised Flux", fontsize=12, labelpad=10)
    
    # Set axis limits
    plt.xlim(-0.02, 1.02)
    plt.ylim(ylim_bottom, ylim_top)
    
    # Clean up spines
    ax = plt.gca()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#BDC3C7")
    ax.spines["bottom"].set_color("#BDC3C7")
    
    # Add subtle grid
    plt.grid(True, linestyle=":", alpha=0.5, color="#BDC3C7")
    
    # Legend
    plt.legend(loc="lower left", frameon=True, facecolor="white", edgecolor="none", shadow=False, fontsize=9.5)
    
    plt.tight_layout()
    output_path = "auxiliary/gp_presentation/spline_fit_only.png"
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved Spline fit plot to {output_path}")

def plot_trigonometric_comparison(x_true, y_true, x_obs, y_obs, y_err, x_grid_trig, y_trig):
    """Generate and save the trigonometric (Fourier) fit plot for comparison."""
    plt.figure(figsize=(10, 6.5), dpi=300)
    
    # Calculate dynamic y-axis limits with padding
    y_all = np.concatenate([y_true, y_obs, y_trig])
    y_min = y_all.min()
    y_max = y_all.max()
    y_range = y_max - y_min
    ylim_bottom = y_min - 0.08 * y_range
    ylim_top = y_max + 0.15 * y_range  # Extra padding at the top for labels/text
    
    # 1. Plot the true underlying physical lightcurve (bright and noticeable)
    # plt.plot(
    #     x_true, y_true,
    #     color="#E74C3C", linestyle="-", linewidth=2.0,
    #     label="True Physical Lightcurve"
    # )
    
    # 2. Plot the Trigonometric fit
    plt.plot(
        x_grid_trig, y_trig,
        color="#27AE60", linestyle="-", linewidth=2.5,
        label="Trigonometric Fit (Fourier Series)"
    )
    
    # 3. Plot the noisy observed data points (semi-transparent)
    plt.errorbar(
        x_obs, y_obs, yerr=y_err,
        fmt="o", color="#2C3E50", markersize=5, elinewidth=1.2, capsize=2,
        alpha=0.4, label="Observed Data (with Noise)"
    )
    
    # Styling and Labels (UK English spelling)
    # plt.title("Trigonometric Fitting: Global Periodic Model", fontsize=14, pad=15, fontweight="bold")
    plt.xlabel("Phase", fontsize=12, labelpad=10)
    plt.ylabel("Normalised Flux", fontsize=12, labelpad=10)
    
    # Set axis limits
    plt.xlim(-0.02, 1.02)
    plt.ylim(ylim_bottom, ylim_top)
    
    # Clean up spines
    ax = plt.gca()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#BDC3C7")
    ax.spines["bottom"].set_color("#BDC3C7")
    
    # Add subtle grid
    plt.grid(True, linestyle=":", alpha=0.5, color="#BDC3C7")
    
    # Legend
    plt.legend(loc="lower left", frameon=True, facecolor="white", edgecolor="none", shadow=False, fontsize=9.5)
    
    plt.tight_layout()
    output_path = "auxiliary/gp_presentation/trig_fit_only.png"
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved Trigonometric fit plot to {output_path}")

def main():
    # Ensure output directory exists
    os.makedirs("auxiliary/gp_presentation", exist_ok=True)
    
    # 1. Generate synthetic data
    x_true, y_true, x_obs, y_obs, y_err = generate_data()
    
    # 2. Fit Gaussian Process
    gp, x_grid, y_mean, y_std, y_samples = fit_gaussian_process(x_obs, y_obs, y_err)
    
    # 3. Fit Smoothing Spline (with periodic padding)
    x_grid_spline, y_spline = fit_spline(x_obs, y_obs)
    
    # 4. Fit Trigonometric (Fourier series) model
    x_grid_trig, y_trig = fit_trigonometric(x_obs, y_obs, n_harmonics=3)
    
    # 5. Generate plots
    plot_gp_regression(x_true, y_true, x_obs, y_obs, y_err, x_grid, y_mean, y_std, y_samples)
    plot_spline_comparison(x_true, y_true, x_obs, y_obs, y_err, x_grid_spline, y_spline)
    plot_trigonometric_comparison(x_true, y_true, x_obs, y_obs, y_err, x_grid_trig, y_trig)
    
    logger.info("All illustrations successfully generated!")

if __name__ == "__main__":
    main()
