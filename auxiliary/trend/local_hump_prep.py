"""Sandbox: detrended light curve -> local folding prep (read CSV, plot)."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DETRENDED_CSV = Path(__file__).resolve().parent / "data" / "detrended_lk.csv"
# DETRENDED_CSV = Path(__file__).resolve().parent / "data" / "detrended_spline.csv"
TIME_COLUMN = "obs_time"
DETRENDED_COLUMN = "detrended"
ERR_COLUMN = "flux_error"

# P(t) = P0 + PERIOD_SLOPE * t  (time in days, period in days).
P0 = 0.0601828
PERIOD_SLOPE = 0.0

# Phase ephemeris: cycle count referenced to T_EPOCH.
T_EPOCH = 0.06012
# Local stack centre and half-width in cycles (window spans 2 * K_CYCLES * P).
K_CYCLES = 3
# Step between successive fold anchors along the light curve (days).
T_ANCHOR_STEP = 3 * P0

FIGSIZE = (20, 12)
FONT_SIZE = 20


def load_detrended_csv(path: Path) -> pd.DataFrame:
    """Load detrended light curve export written by ``plot_tcp_lc.detrend_and_plot``."""
    return pd.read_csv(path)


def instantaneous_period(t: np.ndarray | float, p0: float, period_slope: float) -> np.ndarray:
    """Instantaneous period ``P = p0 + period_slope * t`` (days)."""
    return p0 + period_slope * np.asarray(t, dtype=float)


def cycle_count(
    t: np.ndarray | float,
    t0: float,
    p0: float,
    period_slope: float,
) -> np.ndarray:
    """Cyclical epoch: integral of ``dt / P(t)`` for ``P(t) = p0 + period_slope * t``."""
    t = np.asarray(t, dtype=float)
    if period_slope == 0.0:
        return (t - t0) / p0

    denom0 = p0 + period_slope * t0
    denom = p0 + period_slope * t
    if denom0 <= 0 or np.any(denom <= 0):
        raise ValueError("P(t) must stay positive over the sample range")
    return (1.0 / period_slope) * np.log(denom / denom0)


def phase_centred(
    t: np.ndarray | float,
    t0: float,
    p0: float,
    period_slope: float,
) -> np.ndarray:
    """Phase in [-0.5, 0.5) from the ephemeris."""
    cycles = cycle_count(t, t0, p0, period_slope)
    return cycles - np.round(cycles)


def local_stack_at_anchor(
    df: pd.DataFrame,
    t_anchor: float,
    k_cycles: int,
    p0: float,
    period_slope: float,
    t_epoch: float,
) -> pd.DataFrame:
    """Select ``2 * k_cycles`` intervals about ``t_anchor`` and attach local phase metadata."""
    if k_cycles < 1:
        raise ValueError("k_cycles must be at least 1")

    times = df[TIME_COLUMN].to_numpy(dtype=float)
    p_anchor = float(instantaneous_period(t_anchor, p0, period_slope))
    half_span = k_cycles * p_anchor
    in_window = (times >= t_anchor - half_span) & (times <= t_anchor + half_span)
    out = df.loc[in_window].copy()

    t_sel = out[TIME_COLUMN].to_numpy(dtype=float)
    cycles = cycle_count(t_sel, t_epoch, p0, period_slope)
    cycles_anchor = float(cycle_count(t_anchor, t_epoch, p0, period_slope))

    out["phi_local"] = phase_centred(t_sel, t_epoch, p0, period_slope)
    out["cycle_id"] = np.round(cycles - cycles_anchor).astype(int)
    out["P_local"] = instantaneous_period(t_sel, p0, period_slope)
    out["t_anchor"] = t_anchor
    out["k_cycles"] = k_cycles
    return out


def anchor_times_for_lightcurve(
    df: pd.DataFrame,
    k_cycles: int,
    p0: float,
    period_slope: float,
    step_days: float,
) -> np.ndarray:
    """Anchor grid where a full ``2 * k_cycles`` window fits inside the series."""
    if step_days <= 0:
        raise ValueError("step_days must be positive")

    times = df[TIME_COLUMN].to_numpy(dtype=float)
    t_lo = float(np.min(times))
    t_hi = float(np.max(times))
    half_span = k_cycles * float(instantaneous_period(np.array([t_lo, t_hi]), p0, period_slope).max())
    start = t_lo + half_span
    end = t_hi - half_span
    if start > end:
        return np.array([0.5 * (t_lo + t_hi)])

    n = int(np.floor((end - start) / step_days)) + 1
    return start + step_days * np.arange(n)


def plot_detrended_lightcurve(df: pd.DataFrame) -> None:
    """Scatter plot of the detrended series."""
    plt.rcParams.update({"font.size": FONT_SIZE})
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(
        df[TIME_COLUMN],
        df[DETRENDED_COLUMN],
        ".",
        markersize=6,
        alpha=0.5,
        label="detrended",
    )
    ax.set_xlabel("obs_time (d)")
    ax.set_ylabel("flux / trend")
    ax.set_title("Detrended light curve")
    ax.legend()
    fig.tight_layout()
    plt.show()


def plot_local_phase_stack(stack: pd.DataFrame, t_anchor: float, p0: float) -> None:
    """Plot locally folded points: phase vs detrended, coloured by cycle index."""
    plt.rcParams.update({"font.size": FONT_SIZE})
    fig, ax = plt.subplots(figsize=FIGSIZE)
    sc = ax.scatter(
        stack["phi_local"],
        stack[DETRENDED_COLUMN],
        c=stack["cycle_id"],
        s=40,
        alpha=0.7,
        cmap="viridis",
    )
    ax.set_xlabel("phase (centred)")
    ax.set_ylabel("flux / trend")
    ax.set_title(
        f"Local fold at t_anchor = {t_anchor:.4f} d "
        f"({stack['k_cycles'].iloc[0]} cycles each side, P0 = {p0} d)"
    )
    fig.colorbar(sc, ax=ax, label="cycle_id (relative to anchor)")
    ax.axvline(0.0, color="k", linewidth=0.8, alpha=0.4)
    fig.tight_layout()
    plt.show()


def main() -> None:
    df = load_detrended_csv(DETRENDED_CSV)
    plot_detrended_lightcurve(df)
    
    t_anchor = 59860
    stack = local_stack_at_anchor(
            df,
            float(t_anchor),
            K_CYCLES,
            P0,
            PERIOD_SLOPE,
            T_EPOCH,
        )
    plot_local_phase_stack(stack, float(t_anchor), P0)

    anchors = anchor_times_for_lightcurve(
        df, K_CYCLES, P0, PERIOD_SLOPE, T_ANCHOR_STEP
    )
    for t_anchor in anchors:
        stack = local_stack_at_anchor(
            df,
            float(t_anchor),
            K_CYCLES,
            P0,
            PERIOD_SLOPE,
            T_EPOCH,
        )
        if stack.empty:
            continue
        plot_local_phase_stack(stack, float(t_anchor), P0)


if __name__ == "__main__":
    main()
