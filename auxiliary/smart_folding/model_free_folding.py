"""Model-free period evolution and phase folding from (JD_obs, E) timing pairs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from astropy.modeling import fitting, models
from scipy.interpolate import interp1d

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimingContinuityRules:
    """Filters for pairwise and sliding-window period estimates."""

    min_cycle_gap: float = 1.0
    max_cycle_gap: float = 30.0
    max_neighbour_dE: float = 1.0
    known_jd_gaps: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        if self.min_cycle_gap < 1.0:
            raise ValueError("min_cycle_gap must be >= 1")
        if self.max_cycle_gap < self.min_cycle_gap:
            raise ValueError("max_cycle_gap must be >= min_cycle_gap")


@dataclass(frozen=True)
class WindowFit:
    """One sliding-window linear ephemeris fit."""

    start_idx: int
    jd: np.ndarray
    E: np.ndarray
    T0: float
    P: float
    P_err: float
    t_center: float


def pair_spans_known_gap(
    jd_a: float,
    jd_b: float,
    known_gaps: Sequence[tuple[float, float]],
) -> bool:
    """Return True when the JD interval between two maxima crosses a known gap.

    Args:
        jd_a (float): First observed time (days).
        jd_b (float): Second observed time (days).
        known_gaps (Sequence[tuple[float, float]]): Forbidden ``(jd_lo, jd_hi)`` gaps.

    Returns:
        bool: True if the pair straddles any listed gap.
    """
    lo, hi = min(jd_a, jd_b), max(jd_a, jd_b)
    for g0, g1 in known_gaps:
        g_lo, g_hi = min(g0, g1), max(g0, g1)
        if lo <= g_lo and hi >= g_hi:
            return True
    return False


def segment_continuous_in_E(
    E: np.ndarray,
    i: int,
    j: int,
    *,
    max_neighbour_dE: float,
) -> bool:
    """Return True when sorted indices ``i..j`` have no missing-cycle breaks.

    Args:
        E (numpy.ndarray): Corrected cycle numbers (time-sorted).
        i (int): Start index (inclusive).
        j (int): End index (inclusive).
        max_neighbour_dE (float): Maximum allowed ``ΔE`` between neighbours.

    Returns:
        bool: True if every adjacent step satisfies the neighbour rule.
    """
    if j <= i:
        return True
    for k in range(i, j):
        if float(E[k + 1] - E[k]) > max_neighbour_dE:
            return False
    return True


def pair_passes_continuity_rules(
    jd_obs: np.ndarray,
    E: np.ndarray,
    i: int,
    j: int,
    rules: TimingContinuityRules,
) -> bool:
    """Check whether timing pair ``(i, j)`` is allowed under continuity rules."""
    dE = float(E[j] - E[i])
    if abs(dE) < rules.min_cycle_gap or abs(dE) > rules.max_cycle_gap:
        return False
    if not segment_continuous_in_E(
        E, i, j, max_neighbour_dE=rules.max_neighbour_dE
    ):
        return False
    if pair_spans_known_gap(float(jd_obs[i]), float(jd_obs[j]), rules.known_jd_gaps):
        return False
    return True


def window_passes_continuity_rules(
    jd_obs: np.ndarray,
    E: np.ndarray,
    start: int,
    window: int,
    rules: TimingContinuityRules,
) -> bool:
    """Check whether a consecutive sliding window is allowed."""
    end = start + window - 1
    dE_span = float(E[end] - E[start])
    if dE_span > rules.max_cycle_gap:
        return False
    if not segment_continuous_in_E(
        E, start, end, max_neighbour_dE=rules.max_neighbour_dE
    ):
        return False
    if pair_spans_known_gap(
        float(jd_obs[start]), float(jd_obs[end]), rules.known_jd_gaps
    ):
        return False
    return True


def local_period_pairs(
    jd_obs: np.ndarray,
    E: np.ndarray,
    *,
    rules: TimingContinuityRules | None = None,
    min_cycle_gap: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pairwise local period estimates from corrected cycle assignments.

    For each allowed pair ``(i, j)``:

        P_local = (JD_obs_j - JD_obs_i) / (E_j - E_i)

    Args:
        jd_obs (numpy.ndarray): Observed maximum times (days).
        E (numpy.ndarray): Corrected cycle numbers.
        rules (TimingContinuityRules | None): Continuity filters.
        min_cycle_gap (float | None): Deprecated alias for ``rules.min_cycle_gap``.

    Returns:
        tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
            Midpoint times, local period estimates, and cycle baselines ``dE``.
    """
    if rules is None:
        rules = TimingContinuityRules(
            min_cycle_gap=min_cycle_gap if min_cycle_gap is not None else 1.0
        )
    elif min_cycle_gap is not None:
        raise ValueError("pass either rules or min_cycle_gap, not both")

    jd_obs = np.asarray(jd_obs, dtype=float)
    E = np.asarray(E, dtype=float)
    n = len(E)
    t_mid: list[float] = []
    P_local: list[float] = []
    dE_arr: list[float] = []
    n_skipped = 0

    for i in range(n):
        for j in range(i + 1, n):
            if not pair_passes_continuity_rules(jd_obs, E, i, j, rules):
                n_skipped += 1
                continue
            dE = float(E[j] - E[i])
            P_local.append((jd_obs[j] - jd_obs[i]) / dE)
            t_mid.append(0.5 * (jd_obs[i] + jd_obs[j]))
            dE_arr.append(dE)

    logger.info(
        "Pairwise periods: kept %s pairs, skipped %s (continuity rules)",
        len(P_local),
        n_skipped,
    )
    return (
        np.asarray(t_mid, dtype=float),
        np.asarray(P_local, dtype=float),
        np.asarray(dE_arr, dtype=float),
    )


def _fit_window_line(
    Ew: np.ndarray,
    Tw: np.ndarray,
    sigma_w: np.ndarray | None,
) -> tuple[float, float, float]:
    """Fit ``JD = T0 + P * E`` for one window; return ``T0``, ``P``, ``P_err``."""
    line = models.Polynomial1D(degree=1)
    fitter = fitting.LinearLSQFitter()
    weights = None
    if sigma_w is not None:
        if np.any(sigma_w <= 0):
            raise ValueError("timing uncertainties must be positive")
        weights = 1.0 / np.asarray(sigma_w, dtype=float) ** 2

    fitted = fitter(line, Ew, Tw, weights=weights)
    T0_local = float(fitted.c0.value)
    P_local = float(fitted.c1.value)

    resid = Tw - fitted(Ew)
    dof = len(Ew) - 2
    if dof > 0:
        if weights is not None:
            s2 = float(np.sum(weights * resid**2) / dof)
        else:
            s2 = float(np.sum(resid**2) / dof)
        design = np.vstack([np.ones_like(Ew), Ew]).T
        if weights is not None:
            w_sqrt = np.sqrt(weights)
            design_w = design * w_sqrt[:, None]
            cov = s2 * np.linalg.inv(design_w.T @ design_w)
        else:
            cov = s2 * np.linalg.inv(design.T @ design)
        P_err = float(np.sqrt(cov[1, 1]))
    else:
        P_err = float("nan")

    return T0_local, P_local, P_err


def sliding_local_period(
    jd_obs: np.ndarray,
    E: np.ndarray,
    *,
    window: int = 5,
    sigma: np.ndarray | None = None,
    rules: TimingContinuityRules | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[WindowFit]]:
    """Sliding-window linear ephemeris ``JD = T0 + P * E``.

    Windows that fail continuity rules are skipped.

    Args:
        jd_obs (numpy.ndarray): Observed maximum times (days).
        E (numpy.ndarray): Corrected cycle numbers.
        window (int): Number of consecutive maxima per fit (>= 3 recommended).
        sigma (numpy.ndarray | None): Optional per-point timing uncertainties (days).
        rules (TimingContinuityRules | None): Continuity filters.

    Returns:
        tuple: ``t_center``, ``P_win``, ``P_win_err``, ``T0_win``, and ``WindowFit`` list.
    """
    if rules is None:
        rules = TimingContinuityRules()

    jd_obs = np.asarray(jd_obs, dtype=float)
    E = np.asarray(E, dtype=float)
    n = len(E)
    if window < 2:
        raise ValueError("window must be >= 2")
    if n < window:
        raise ValueError(f"need at least {window} timing points, got {n}")

    t_center: list[float] = []
    P_win: list[float] = []
    P_win_err: list[float] = []
    T0_win: list[float] = []
    fits: list[WindowFit] = []
    n_skipped = 0

    for start in range(0, n - window + 1):
        if not window_passes_continuity_rules(jd_obs, E, start, window, rules):
            n_skipped += 1
            continue

        sl = slice(start, start + window)
        Ew = E[sl]
        Tw = jd_obs[sl]
        sigma_w = None if sigma is None else np.asarray(sigma[sl], dtype=float)

        T0_local, P_local, P_err = _fit_window_line(Ew, Tw, sigma_w)
        t_ctr = float(np.mean(Tw))

        t_center.append(t_ctr)
        P_win.append(P_local)
        P_win_err.append(P_err)
        T0_win.append(T0_local)
        fits.append(
            WindowFit(
                start_idx=start,
                jd=np.asarray(Tw, dtype=float),
                E=np.asarray(Ew, dtype=float),
                T0=T0_local,
                P=P_local,
                P_err=P_err,
                t_center=t_ctr,
            )
        )

    if not fits:
        raise ValueError(
            "no valid sliding windows after continuity filtering; "
            "relax rules or check timing gaps"
        )

    logger.info(
        "Sliding windows: kept %s fits, skipped %s (continuity rules)",
        len(fits),
        n_skipped,
    )
    return (
        np.asarray(t_center, dtype=float),
        np.asarray(P_win, dtype=float),
        np.asarray(P_win_err, dtype=float),
        np.asarray(T0_win, dtype=float),
        fits,
    )


def fold_interpolated(
    t_lc: np.ndarray,
    t_center: np.ndarray,
    P_win: np.ndarray,
    t_anchor: float,
    E_anchor: float,
    *,
    n_grid: int = 5000,
) -> tuple[np.ndarray, np.ndarray]:
    """Fold a light curve by integrating ``dE/dt = 1/P(t)``.

    Args:
        t_lc (numpy.ndarray): Light-curve timestamps (days).
        t_center (numpy.ndarray): Times for local period samples.
        P_win (numpy.ndarray): Local period at each ``t_center``.
        t_anchor (float): Reference time for cycle anchoring.
        E_anchor (float): Cycle number at ``t_anchor``.
        n_grid (int): Integration grid size.

    Returns:
        tuple[numpy.ndarray, numpy.ndarray]: Fractional phase and cycle number ``E(t)``.
    """
    t_lc = np.asarray(t_lc, dtype=float)
    t_center = np.asarray(t_center, dtype=float)
    P_win = np.asarray(P_win, dtype=float)
    if len(t_center) < 2:
        raise ValueError("need at least two sliding-window period samples")

    if np.any(P_win <= 0):
        raise ValueError("local period estimates must be positive")

    P_interp = interp1d(
        t_center,
        P_win,
        kind="linear",
        bounds_error=False,
        fill_value=(float(P_win[0]), float(P_win[-1])),
    )

    t_lo = min(t_anchor, float(t_lc.min()))
    t_hi = max(t_anchor, float(t_lc.max()))
    t_grid = np.linspace(t_lo, t_hi, n_grid)
    integrand = 1.0 / P_interp(t_grid)
    cum_E = np.concatenate(
        [[0.0], np.cumsum(0.5 * (integrand[1:] + integrand[:-1]) * np.diff(t_grid))]
    )
    E_of_t = interp1d(
        t_grid, cum_E, kind="linear", bounds_error=False, fill_value="extrapolate"
    )
    E_anchor_grid = float(E_of_t(t_anchor))
    E_lc = E_anchor + (E_of_t(t_lc) - E_anchor_grid)
    phase = E_lc - np.floor(E_lc)
    return phase, E_lc


def fold_nearest_local(
    t_lc: np.ndarray,
    t_center: np.ndarray,
    T0_win: np.ndarray,
    P_win: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Fold by assigning each LC point to the nearest sliding-window ephemeris.

    Args:
        t_lc (numpy.ndarray): Light-curve timestamps (days).
        t_center (numpy.ndarray): Window centre times.
        T0_win (numpy.ndarray): Local ``T0`` per window.
        P_win (numpy.ndarray): Local period per window.

    Returns:
        tuple[numpy.ndarray, numpy.ndarray]: Fractional phase and selected window index.
    """
    t_lc = np.asarray(t_lc, dtype=float)
    idx = np.searchsorted(t_center, t_lc)
    idx = np.clip(idx, 1, len(t_center) - 1)
    left = idx - 1
    right = idx
    use_right = np.abs(t_lc - t_center[right]) < np.abs(t_lc - t_center[left])
    sel = np.where(use_right, right, left)

    T0_loc = T0_win[sel]
    P_loc = P_win[sel]
    if np.any(P_loc <= 0):
        raise ValueError("local period estimates must be positive")
    E_loc = (t_lc - T0_loc) / P_loc
    phase = E_loc - np.floor(E_loc)
    return phase, sel
