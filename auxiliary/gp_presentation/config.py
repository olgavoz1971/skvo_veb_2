"""Configuration parameters for the Gaussian Process presentation illustration.

All parameters can be tweaked here to adjust the synthetic lightcurve shape,
noise level, gap width/position, and Gaussian Process hyperparameters.
"""

# --- Reproducibility ---
RANDOM_SEED = 42

# --- Synthetic Lightcurve Generation ---
NUM_POINTS = 70            # Total number of data points before applying the gap
NOISE_SIGMA = 0.07         # Standard deviation of the observational Gaussian noise

# --- The Gap ---
# Data points within this phase interval [0, 1] will be completely removed
# GAP_START = 0.42
# GAP_END = 0.68

GAP_START = 0.3
# GAP_END = 0.3
GAP_END = 0.53
# --- RR Lyrae / Cepheid Shape Parameters ---
# The base lightcurve is modeled using a Fourier series to get an asymmetric shape
# (steep rise, slow decline). We use 6 harmonics to model a very steep, RR Lyrae-like rise.
FOURIER_COEFFS = [
    # (amplitude, phase_shift)
    (0.348, -0.314),  # 1st harmonic
    (0.165, -0.628),  # 2nd harmonic
    (0.101, -0.942),  # 3rd harmonic
    (0.067, -1.257),  # 4th harmonic
    (0.045, -1.571),  # 5th harmonic
    (0.030, -1.885),  # 6th harmonic
]

# A Gaussian bump is added to the descending arm to simulate a physical "hump"
HUMP_AMPLITUDE = 0.15     # Height of the hump
HUMP_PHASE = 0.55          # Position of the hump in phase [0, 1]
HUMP_WIDTH = 0.05          # Width (standard deviation) of the hump

# --- Gaussian Process Hyperparameters ---
# The kernel choice: 'matern' or 'rbf'
# 'matern' with nu=2.5 is twice differentiable, physically realistic for stellar pulsations
GP_KERNEL_TYPE = "matern"
GP_MATERN_NU = 2.5

# Length scale bounds for the GP kernel optimizer
GP_LENGTH_SCALE_INIT = 0.15
GP_LENGTH_SCALE_MIN = 0.02
GP_LENGTH_SCALE_MAX = 0.8

# Amplitude (ConstantKernel) bounds
GP_AMP_INIT = 1.0
GP_AMP_MIN = 0.1
GP_AMP_MAX = 10.0

# Number of restarts for the GP optimizer to avoid local minima
GP_N_RESTARTS = 10

# Number of random function draws from the GP posterior distribution to plot
N_POSTERIOR_SAMPLES = 300

# Percentage of calculated posterior samples to actually plot (e.g., 10 for 10%)
PLOT_SAMPLES_PERCENT = 5

# --- Spline Fit Parameters (P-spline) ---
# Roughness penalty for the P-spline (larger -> smoother trend, ignoring noise)
SPLINE_PENALTY_LAMBDA = 0.01

