"""Scientific defaults for Gaussian Process O-C extremum timing.

GP fits operate on normalised instrumental flux. Values are dimensionless, not
physical flux densities (no Jy or e/s labels in the GP UI). Page layout, plot
height, and display time live in ``extrema_modeller_appearance``. PhotCal
fallbacks for incomplete uploads live in ``lc_config``.
"""

# If True: ignore provided errors and estimate them from data scatter (robust MAD).
GUESS_SIGMA = False

# min or max -- what kind of extrema are we hunting
EXTREMA_MODE = "max"

KERNEL_TYPE = "matern"  # or "rbf"

# Multiplier applied to estimated or tabulated noise (effective = original * scale).
NOISE_SCALE = 1

# Minimum fraction of rows with finite ``flux_err`` in a GP interval (Guess sigma off)
# to use tabulated errors; missing rows get the median of finite values. Below this
# threshold the interval uses MAD noise guess for all points.
GP_MIN_FINITE_ERROR_FRACTION = 0.7

SAMPLING_SCALE_FACTOR = 3
INTERVAL_DIVISOR = 4
LENGTH_SCALE_FACTOR = 3

AMPLITUDE_INIT = 1.0
AMPLITUDE_MIN = 1e-4
AMPLITUDE_MAX = 20.0

LEN_MIN = 5

DEFAULT_FLOAT_PARAMS = {
    "noise_scale": NOISE_SCALE,
    "length_scale_init": 0.1,
    "length_scale_min": 0.01,
    "length_scale_max": 1.0,
    "amplitude_init": AMPLITUDE_INIT,
    "amplitude_min": AMPLITUDE_MIN,
    "amplitude_max": AMPLITUDE_MAX,
}

GP_FLOAT_PARAM_LABELS = {
    "noise_scale": "Noise scale",
    "length_scale_init": "Length scale (initial)",
    "length_scale_min": "Length scale (minimum)",
    "length_scale_max": "Length scale (maximum)",
    "amplitude_init": "Amplitude (initial)",
    "amplitude_min": "Amplitude (minimum)",
    "amplitude_max": "Amplitude (maximum)",
}


def parse_gp_float_param(name: str, value) -> float:
    """Parse one GP sidebar float parameter from a Dash number input.

    Args:
        name: Parameter key in ``DEFAULT_FLOAT_PARAMS`` (used in error text).
        value: Raw ``dbc.Input`` value (number, string, empty, or ``None``).

    Returns:
        float: Parsed parameter value.

    Raises:
        ValueError: When ``value`` is empty or cannot be converted to ``float``.
        KeyError: When ``name`` is not a known GP float parameter.
    """
    if name not in DEFAULT_FLOAT_PARAMS:
        raise KeyError(f"Unknown GP float parameter: {name!r}")
    label = GP_FLOAT_PARAM_LABELS.get(name, name)
    if value is None or value == "":
        raise ValueError(f"{label} is empty; enter a numeric value.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{label} must be a number; got {value!r}."
        ) from exc


def build_gp_float_params(ids: list[dict], values: list) -> dict[str, float]:
    """Build the GP float-parameter dict from pattern-matched sidebar inputs.

    Args:
        ids: ``State({'type': 'float-input', 'index': ALL}, 'id')`` list.
        values: Matching ``value`` list in the same order as ``ids``.

    Returns:
        dict[str, float]: Parsed float parameters keyed by ``index``.

    Raises:
        ValueError: When any parameter is empty or not numeric.
    """
    params: dict[str, float] = {}
    for val_id, val in zip(ids, values):
        key = val_id["index"]
        params[key] = parse_gp_float_param(key, val)
    return params
