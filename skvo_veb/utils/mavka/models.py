"""Phenomenological extrema models adapted from mpyat2/lc_approx (MIT).

Upstream: https://github.com/mpyat2/lc_approx.git
See ``NOTICE`` in this package for licence and literature citations.

Methods: AP, WSAP, WSL, A (Andrych / Andronov / Chinarova family).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.optimize import curve_fit

logger = logging.getLogger(__name__)

METHODS = frozenset({"AP", "WSAP", "WSL", "A"})


def f_ap(t: float, c1: float, c2: float, c3: float, c4: float, c5: float) -> float:
    """Asymptotic parabola (scalar)."""
    d = (c5 - c4) / 2.0
    v = t - (c5 + c4) / 2.0
    if d <= 0.0:
        return np.inf
    if t < c4:
        return c1 + c2 * (-2.0 * v - d) * d + c3 * v
    if t <= c5:
        return c1 + c2 * v * v + c3 * v
    return c1 + c2 * (2.0 * v - d) * d + c3 * v


def f_ap_vec(
    t_a: np.ndarray, c1: float, c2: float, c3: float, c4: float, c5: float
) -> np.ndarray:
    """Vectorised asymptotic parabola."""
    return np.asarray([f_ap(float(t), c1, c2, c3, c4, c5) for t in np.asarray(t_a)])


def f_wsap(t: float, c1: float, c2: float, c3: float, c4: float, c5: float) -> float:
    """Wall-supported asymptotic parabola (scalar)."""
    d = (c5 - c4) / 2.0
    v = t - (c5 + c4) / 2.0
    if d <= 0.0:
        return np.inf
    if t < c4:
        return c1 + c2 * (-2.0 * v - d) * d + c3 * abs(t - c4) ** 1.5
    if t <= c5:
        return c1 + c2 * v * v
    return c1 + c2 * (2.0 * v - d) * d + c3 * abs(t - c5) ** 1.5


def f_wsap_vec(
    t_a: np.ndarray, c1: float, c2: float, c3: float, c4: float, c5: float
) -> np.ndarray:
    """Vectorised wall-supported asymptotic parabola."""
    return np.asarray([f_wsap(float(t), c1, c2, c3, c4, c5) for t in np.asarray(t_a)])


def f_wsl(t: float, c1: float, c2: float, c3: float, c4: float, c5: float) -> float:
    """Wall-supported flat bottom (scalar)."""
    if c5 <= c4:
        return np.inf
    if c4 <= t <= c5:
        return c1
    x = c4 - t if t < c4 else t - c5
    return c1 + c2 * abs(x) ** 1.5 + c3 * abs(x) ** 3.5


def f_wsl_vec(
    t_a: np.ndarray, c1: float, c2: float, c3: float, c4: float, c5: float
) -> np.ndarray:
    """Vectorised wall-supported flat bottom."""
    return np.asarray([f_wsl(float(t), c1, c2, c3, c4, c5) for t in np.asarray(t_a)])


def f_a(t: float, c1: float, c2: float, c3: float, c4: float) -> float:
    """Broken linear extremum (scalar)."""
    if t < c4:
        return c1 + c2 * (t - c4)
    return c1 - c3 * (t - c4)


def f_a_vec(
    t_a: np.ndarray, c1: float, c2: float, c3: float, c4: float
) -> np.ndarray:
    """Vectorised broken linear extremum."""
    return np.asarray([f_a(float(t), c1, c2, c3, c4) for t in np.asarray(t_a)])


@dataclass(frozen=True)
class ApproxFitResult:
    """Outcome of one phenomenological fit on an interval.

    Attributes:
        method (str): ``AP``, ``WSAP``, ``WSL``, or ``A``.
        ok (bool): False when the fit or TOM extraction failed checks.
        t_ext (float): Time of extremum (same units as input times).
        sigma_t_ext (float): Formal uncertainty from parameter covariance.
        y_ext (float): Model value at the extremum.
        sigma_y_ext (float): Formal uncertainty on ``y_ext``.
        c4 (float): Left junction (NaN for method ``A`` duration fields only).
        c5 (float): Right junction (NaN for method ``A``).
        eclipse_duration (float): ``C5-C4`` for WSL, else NaN.
        sigma_duration (float): Formal uncertainty on duration (WSL).
        params (numpy.ndarray): Optimised parameter vector.
        rms (float): Residual RMS of the fit.
        n_points (int): Number of points used.
        warning (str | None): Non-fatal quality warning from TOM extraction.
        fail_reason (str | None): Why ``ok`` is false.
    """

    method: str
    ok: bool
    t_ext: float
    sigma_t_ext: float
    y_ext: float
    sigma_y_ext: float
    c4: float
    c5: float
    eclipse_duration: float
    sigma_duration: float
    params: np.ndarray
    rms: float
    n_points: int
    warning: str | None = None
    fail_reason: str | None = None


def approx(
    method: str,
    t_obs: np.ndarray,
    y_obs: np.ndarray,
    *,
    maxfev: int = 100_000,
) -> tuple[np.ndarray, np.ndarray, str | None]:
    """Fit one phenomenological model with time-centred ``curve_fit``.

    Args:
        method (str): ``AP``, ``WSAP``, ``WSL``, or ``A``.
        t_obs (numpy.ndarray): Observation times (days).
        y_obs (numpy.ndarray): Photometry in the working domain (mag or flux).
        maxfev (int): ``curve_fit`` iteration budget.

    Returns:
        tuple: ``(params_opt, params_cov, param_warning)`` with junction times
        restored to the original time zero-point.

    Raises:
        ValueError: If ``method`` is unknown or arrays are unusable.
    """
    method = method.upper()
    if method not in METHODS:
        raise ValueError(f"method must be one of {sorted(METHODS)}, got {method!r}")
    t_obs = np.asarray(t_obs, dtype=float)
    y_obs = np.asarray(y_obs, dtype=float)
    if t_obs.size != y_obs.size:
        raise ValueError("t_obs and y_obs length mismatch")
    if t_obs.size < 6:
        raise ValueError(f"need at least 6 points, got {t_obs.size}")

    mean_t = float(np.mean(t_obs))
    t_c = t_obs - mean_t
    t_min = float(np.min(t_c))
    t_max = float(np.max(t_c))
    c1 = float(np.mean(y_obs))
    c2 = 0.0
    c3 = 0.0
    c4 = t_min + (t_max - t_min) / 3.0
    c5 = t_max - (t_max - t_min) / 3.0
    param_warning: str | None = None

    if method in {"AP", "WSAP", "WSL"}:
        func = {"AP": f_ap_vec, "WSAP": f_wsap_vec, "WSL": f_wsl_vec}[method]
        params_opt, params_cov = curve_fit(
            func, t_c, y_obs, p0=[c1, c2, c3, c4, c5], maxfev=maxfev
        )
        c4_fit, c5_fit = float(params_opt[3]), float(params_opt[4])
        if c4_fit < t_min or c4_fit > t_max or c5_fit < t_min or c5_fit > t_max:
            param_warning = "Bad C4 or C5 or both. Try another method."
        params_opt = np.asarray(params_opt, dtype=float)
        params_opt[3] += mean_t
        params_opt[4] += mean_t
    else:
        c4 = 0.5 * (t_min + t_max)
        params_opt, params_cov = curve_fit(
            f_a_vec, t_c, y_obs, p0=[c1, c2, c3, c4], maxfev=maxfev
        )
        params_opt = np.asarray(params_opt, dtype=float)
        params_opt[3] += mean_t

    return params_opt, np.asarray(params_cov, dtype=float), param_warning


def method_result(
    method: str,
    params_opt: np.ndarray,
    params_cov: np.ndarray,
) -> tuple[float, float, float, float, float, float, str | None]:
    """Derive TOM and uncertainties from fitted parameters.

    Args:
        method (str): Approximation method id.
        params_opt (numpy.ndarray): Optimised parameters (absolute time).
        params_cov (numpy.ndarray): Parameter covariance.

    Returns:
        tuple: ``t_ext, sigma_t, y_ext, sigma_y, duration, sigma_duration, warning``.
    """
    method = method.upper()
    warning: str | None = None
    t_ext = mag_ext = sig_t = sig_m = duration = sig_dur = float("nan")

    if method in {"AP", "WSAP"}:
        c1, c2, c3, c4, c5 = (float(x) for x in params_opt)
        cov = params_cov.copy()
        if method == "AP":
            if abs(c2) < 1e-30:
                return (
                    float("nan"),
                    float("nan"),
                    float("nan"),
                    float("nan"),
                    float("nan"),
                    float("nan"),
                    "AP curvature C2 is zero; cannot form TOM",
                )
            t_ext = (c4 + c5) / 2.0 - c3 / (2.0 * c2)
        else:
            t_ext = (c4 + c5) / 2.0
        if c4 <= t_ext <= c5:
            if method == "AP":
                mag_ext = c1 - (c3 * c3) / (4.0 * c2)
                j_t = np.array([0.0, 0.5 * c3 / (c2 * c2), -0.5 / c2, 0.5, 0.5])
                j_m = np.array(
                    [1.0, (c3 * c3) / (4.0 * c2 * c2), -c3 / (2.0 * c2), 0.0, 0.0]
                )
            else:
                mag_ext = c1
                j_t = np.array([0.0, 0.0, 0.0, 0.5, 0.5])
                j_m = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
            sig_t = float(np.sqrt(j_t @ cov @ j_t.T))
            sig_m = float(np.sqrt(j_m @ cov @ j_m.T))
            if abs(c5 - c4) < sig_t:
                warning = (
                    "The parabolic part is shorter than the uncertainty! "
                    "Try another method."
                )
        else:
            warning = "The extremum is out of the parabolic part! Try another method."
            t_ext = sig_t = mag_ext = sig_m = float("nan")
    elif method == "WSL":
        c1, c2, c3, c4, c5 = (float(x) for x in params_opt)
        cov = params_cov
        j_t = np.array([0.0, 0.0, 0.0, 0.5, 0.5])
        t_ext = (c4 + c5) / 2.0
        sig_t = float(np.sqrt(j_t @ cov @ j_t.T))
        mag_ext = c1
        sig_m = float(np.sqrt(cov[0, 0]))
        duration = c5 - c4
        j_d = np.array([0.0, 0.0, 0.0, -1.0, 1.0])
        sig_dur = float(np.sqrt(j_d @ cov @ j_d.T))
        if abs(c5 - c4) < sig_t:
            warning = (
                "The flat part is shorter than the uncertainty! Try another method."
            )
    elif method == "A":
        c1, c2, c3, c4 = (float(x) for x in params_opt)
        cov = params_cov
        t_ext = c4
        sig_t = float(np.sqrt(cov[3, 3]))
        mag_ext = c1
        sig_m = float(np.sqrt(cov[0, 0]))
    else:
        raise ValueError(f"unsupported method: {method!r}")

    return t_ext, sig_t, mag_ext, sig_m, duration, sig_dur, warning


def model_curve(
    method: str, params_opt: np.ndarray, t_line: np.ndarray
) -> np.ndarray:
    """Evaluate the fitted model on an absolute-time grid.

    Args:
        method (str): Approximation method id.
        params_opt (numpy.ndarray): Optimised parameters.
        t_line (numpy.ndarray): Absolute times.

    Returns:
        numpy.ndarray: Model photometry.
    """
    method = method.upper()
    t_line = np.asarray(t_line, dtype=float)
    if method == "AP":
        return f_ap_vec(t_line, *params_opt)
    if method == "WSAP":
        return f_wsap_vec(t_line, *params_opt)
    if method == "WSL":
        return f_wsl_vec(t_line, *params_opt)
    if method == "A":
        return f_a_vec(t_line, *params_opt)
    raise ValueError(f"unsupported method: {method!r}")


def fit_interval(
    method: str,
    t_obs: np.ndarray,
    y_obs: np.ndarray,
    *,
    maxfev: int = 100_000,
) -> ApproxFitResult:
    """Fit one interval and extract TOM with fail-fast quality checks.

    Args:
        method (str): ``AP``, ``WSAP``, ``WSL``, or ``A``.
        t_obs (numpy.ndarray): Absolute times (JD).
        y_obs (numpy.ndarray): Photometry values.
        maxfev (int): Optimiser budget.

    Returns:
        ApproxFitResult: Structured fit outcome (``ok=False`` on failure).
    """
    method = method.upper()
    nan = float("nan")
    n = int(np.asarray(t_obs).size)
    try:
        params, cov, param_warning = approx(method, t_obs, y_obs, maxfev=maxfev)
    except Exception as exc:  # noqa: BLE001 - spike: surface optimiser failures
        logger.warning("%s fit failed: %s", method, exc)
        return ApproxFitResult(
            method=method,
            ok=False,
            t_ext=nan,
            sigma_t_ext=nan,
            y_ext=nan,
            sigma_y_ext=nan,
            c4=nan,
            c5=nan,
            eclipse_duration=nan,
            sigma_duration=nan,
            params=np.asarray([]),
            rms=nan,
            n_points=n,
            fail_reason=str(exc),
        )

    if method != "A" and float(params[3]) >= float(params[4]):
        return ApproxFitResult(
            method=method,
            ok=False,
            t_ext=nan,
            sigma_t_ext=nan,
            y_ext=nan,
            sigma_y_ext=nan,
            c4=float(params[3]),
            c5=float(params[4]),
            eclipse_duration=nan,
            sigma_duration=nan,
            params=params,
            rms=nan,
            n_points=n,
            warning=param_warning,
            fail_reason=f"C4 must be less than C5 (C4={params[3]}, C5={params[4]})",
        )

    t_ext, sig_t, y_ext, sig_y, dur, sig_dur, tom_warning = method_result(
        method, params, cov
    )
    y_model = model_curve(method, params, t_obs)
    dof = max(n - len(params), 1)
    rms = float(np.sqrt(np.sum((y_obs - y_model) ** 2) / dof))
    warning = "; ".join(w for w in (param_warning, tom_warning) if w)
    ok = bool(np.isfinite(t_ext))
    return ApproxFitResult(
        method=method,
        ok=ok,
        t_ext=float(t_ext) if ok else nan,
        sigma_t_ext=float(sig_t) if np.isfinite(sig_t) else nan,
        y_ext=float(y_ext) if np.isfinite(y_ext) else nan,
        sigma_y_ext=float(sig_y) if np.isfinite(sig_y) else nan,
        c4=float(params[3]) if method != "A" else float(params[3]),
        c5=float(params[4]) if method != "A" and len(params) > 4 else nan,
        eclipse_duration=float(dur) if np.isfinite(dur) else nan,
        sigma_duration=float(sig_dur) if np.isfinite(sig_dur) else nan,
        params=params,
        rms=rms,
        n_points=n,
        warning=warning or None,
        fail_reason=None if ok else (tom_warning or "TOM not finite"),
    )
