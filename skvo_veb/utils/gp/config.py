"""Configuration defaults for Gaussian Process O-C extremum timing.

GP fits operate on normalised instrumental flux; photometric zero points used only
to obtain a monotonic flux proxy from magnitude uploads. Values are dimensionless,
not physical flux densities (no Jy or e/s labels in the GP UI).
"""

# If True: ignore provided errors and estimate them from data scatter (robust MAD).
GUESS_SIGMA = False

# min or max -- what kind of extrema are we hunting
EXTREMA_MODE = "max"

KERNEL_TYPE = "matern"  # or "rbf"

# Scaling factor applied to estimated or tabulated noise.
NOISE_SCALE_DIVISOR = 1

SAMPLING_SCALE_FACTOR = 3
INTERVAL_DIVISOR = 4
LENGTH_SCALE_FACTOR = 3

AMPLITUDE_INIT = 1.0
AMPLITUDE_MIN = 1e-4
AMPLITUDE_MAX = 20.0

LEN_MIN = 5

# Reference magnitude for mag-to-instrumental-flux conversion when upload metadata
# lacks a complete PhotCal pair (legacy VSNET-style files). Paired with
# GP_ZP_FLUX_DIMENSIONLESS via volightcurve.PhotCal (Pogson relation).
DEFAULT_REFERENCE_MAG = 20.0

# Dimensionless instrumental zero-point flux paired with DEFAULT_REFERENCE_MAG.
GP_ZP_FLUX_DIMENSIONLESS = 1.0

DEFAULT_FLOAT_PARAMS = {
    "noise_scale_divisor": NOISE_SCALE_DIVISOR,
    "length_scale_init": 0.1,
    "length_scale_min": 0.01,
    "length_scale_max": 1.0,
    "amplitude_init": AMPLITUDE_INIT,
    "amplitude_min": AMPLITUDE_MIN,
    "amplitude_max": AMPLITUDE_MAX,
}
