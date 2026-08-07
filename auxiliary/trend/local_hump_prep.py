"""Sandbox: detrended light curve -> local folding prep (read CSV, plot)."""

from pathlib import Path

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
from matplotlib import cm
import numpy as np
import pandas as pd

# DETRENDED_CSV = Path(__file__).resolve().parent / "data" / "detrended_lk.csv"
# DETRENDED_CSV = Path(__file__).resolve().parent / "data" / "detrended_spline.csv"
# DETRENDED_CSV = Path(__file__).resolve().parent / "data" / "shug.dat"
DETRENDED_CSV = Path(__file__).resolve().parent / "data" / "R_detrended_sorted.dat"

TIME_COLUMN = "obs_time"
DETRENDED_COLUMN = "detrended"
ERR_COLUMN = "flux_error"

# P(t) = P0 + PERIOD_SLOPE * t  (time in days, period in days).
P0 = 0.0601828
PERIOD_SLOPE = 0.0

# Phase ephemeris: cycle count referenced to T_EPOCH.
T_EPOCH = 59866.4533
# Local stack centre and half-width in cycles (window spans 2 * K_CYCLES * P).
K_CYCLES = 3
# Step between successive fold anchors along the light curve (days).
T_ANCHOR_STEP = 6 * P0

FIGSIZE = (20, 12)
FIGSIZE_FOLD_VIEW = (20, 20)
FONT_SIZE = 20
FOLDED_STACK_EXPORT = Path(__file__).resolve().parent / "data" / "folded_stack.dat"


def _discrete_cycle_colormap(cycle_ids: np.ndarray) -> tuple[cm.ScalarMappable, np.ndarray]:
    """Build a discrete normalisation and colormap for integer ``cycle_id`` values."""
    unique_ids = np.sort(np.unique(cycle_ids.astype(int)))
    n = len(unique_ids)
    base = plt.get_cmap("tab10" if n <= 10 else "tab20")
    colors = [base(i % base.N) for i in range(n)]
    cmap = mcolors.ListedColormap(colors)
    if n == 1:
        bounds = np.array([unique_ids[0] - 0.5, unique_ids[0] + 0.5], dtype=float)
    else:
        mid = (unique_ids[:-1].astype(float) + unique_ids[1:].astype(float)) / 2.0
        bounds = np.concatenate(
            [[float(unique_ids[0]) - 0.5], mid, [float(unique_ids[-1]) + 0.5]]
        )
    norm = mcolors.BoundaryNorm(bounds, cmap.N)
    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    return sm, unique_ids


def load_detrended_csv(path: Path) -> pd.DataFrame:
    """Load detrended light curve export written by ``plot_tcp_lc.detrend_and_plot``."""

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    
    elif path.suffix.lower() == ".dat":
        df = pd.read_csv(
            path,
            sep=r"\s+",
            comment="#",
            names=["obs_time", "detrended", "flux_error"]
        )
        # df['obs_time'] = df['obs_time'] - 0.5       # to mjd
    else:
        raise ValueError(f"unsupported file type: {path.suffix}")
    return df


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


def extended_phase_fold(stack: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Centred fold plus a +1 phase copy (phase panel and export span [-0.5, 1.5))."""
    phi = stack["phi_local"].to_numpy(dtype=float)
    y = stack[DETRENDED_COLUMN].to_numpy(dtype=float)
    phi_ext = np.concatenate([phi, phi + 1.0])
    y_ext = np.concatenate([y, y])
    return phi_ext, y_ext


def anchor_cycle_jd_from_phases(
    stack: pd.DataFrame,
    phi: np.ndarray,
    p0: float,
    period_slope: float,
) -> np.ndarray:
    """Map phase values (including extended copies) to JD around ``t_anchor``."""
    t_anchor = float(stack["t_anchor"].iloc[0])
    p_anchor = float(instantaneous_period(t_anchor, p0, period_slope))
    return t_anchor + np.asarray(phi, dtype=float) * p_anchor


def export_folded_stack_ascii(
    stack: pd.DataFrame,
    path: Path,
    p0: float,
    period_slope: float,
) -> None:
    """Export extended single-cycle fold as JD, detrended (matches phase panel [-0.5, 1.5))."""
    if stack.empty:
        raise ValueError("cannot export an empty stack")

    phi_ext, y_ext = extended_phase_fold(stack)
    t_jd = anchor_cycle_jd_from_phases(stack, phi_ext, p0, period_slope)
    values = y_ext
    order = np.argsort(t_jd)
    t_jd = t_jd[order]
    values = values[order]
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(path, np.column_stack([t_jd, values]), fmt="%.10f")


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
    """Scatter plot of the detrended series with flux errors when available."""
    plt.rcParams.update({"font.size": FONT_SIZE})
    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = df[TIME_COLUMN].to_numpy(dtype=float)
    y = df[DETRENDED_COLUMN].to_numpy(dtype=float)
    yerr = None
    if ERR_COLUMN in df.columns:
        err = df[ERR_COLUMN].to_numpy(dtype=float)
        if np.any(np.isfinite(err) & (err > 0)):
            yerr = err

    ax.errorbar(
        x,
        y,
        yerr=yerr,
        fmt=".",
        markersize=6,
        alpha=0.5,
        elinewidth=0.6,
        capsize=0,
        label="detrended",
    )
    ax.set_xlabel("obs_time (d)")
    ax.set_ylabel("flux / trend")
    ax.set_title("Detrended light curve")
    ax.legend()
    fig.tight_layout()
    plt.show()


def plot_local_phase_stack(
    df: pd.DataFrame,
    stack: pd.DataFrame,
    t_anchor: float,
    p0: float,
) -> None:
    """Three-panel fold view: phase fold, stack window only, full light curve."""
    if stack.empty:
        t_lo = float(df[TIME_COLUMN].min())
        t_hi = float(df[TIME_COLUMN].max())
        raise ValueError(
            f"empty stack at t_anchor={t_anchor}: no points in the fold window "
            f"(light curve spans {t_lo:.4f} to {t_hi:.4f} d)"
        )

    plt.rcParams.update({"font.size": FONT_SIZE})
    fig, (ax_phase, ax_zoom, ax_time) = plt.subplots(
        3,
        1,
        figsize=FIGSIZE_FOLD_VIEW,
        sharex=False,
        gridspec_kw={"height_ratios": [1, 0.85, 1.15]},
    )

    cycle_ids = stack["cycle_id"].to_numpy(dtype=int)
    sm, _ = _discrete_cycle_colormap(cycle_ids)
    k_cycles = int(stack["k_cycles"].iloc[0])

    phi_ext, y_plot = extended_phase_fold(stack)
    c_plot = np.concatenate([cycle_ids, cycle_ids])

    ax_phase.scatter(
        phi_ext,
        y_plot,
        c=c_plot,
        cmap=sm.cmap,
        norm=sm.norm,
        s=80,
        alpha=0.85,
        edgecolors="k",
        linewidths=0.3,
    )
    ax_phase.set_xlim(-0.5, 1.5)
    ax_phase.set_xlabel("phase (centred)")
    ax_phase.set_ylabel("flux / trend")
    ax_phase.set_title(
        f"Local fold at t_anchor = {t_anchor:.4f} d "
        f"({k_cycles} cycles each side, P0 = {p0} d)"
    )
    ax_phase.axvline(0.0, color="k", linewidth=0.8, alpha=0.4)

    p_anchor = float(instantaneous_period(t_anchor, p0, PERIOD_SLOPE))
    half_span = k_cycles * p_anchor
    t_window_lo = t_anchor - half_span
    t_window_hi = t_anchor + half_span

    in_stack = df.index.isin(stack.index)
    bg = df.loc[~in_stack]
    hi = df.loc[in_stack]
    hi_cycle = hi.join(stack[["cycle_id"]], how="left")
    hi_colors = hi_cycle["cycle_id"].to_numpy(dtype=int)

    ax_zoom.scatter(
        hi_cycle[TIME_COLUMN],
        hi_cycle[DETRENDED_COLUMN],
        c=hi_colors,
        cmap=sm.cmap,
        norm=sm.norm,
        s=120,
        alpha=0.95,
        edgecolors="k",
        linewidths=0.4,
    )
    ax_zoom.axvline(t_anchor, color="C1", linewidth=1.2, linestyle="--", alpha=0.8)
    pad = 0.02 * max(t_window_hi - t_window_lo, 1e-9)
    ax_zoom.set_xlim(t_window_lo - pad, t_window_hi + pad)
    ax_zoom.set_xlabel("obs_time (d)")
    ax_zoom.set_ylabel("flux / trend")
    ax_zoom.set_title("Stack interval only (coloured by cycle_id)")

    ax_time.plot(
        bg[TIME_COLUMN],
        bg[DETRENDED_COLUMN],
        ".",
        markersize=4,
        alpha=0.25,
        color="0.55",
        label="outside stack",
    )
    ax_time.scatter(
        hi_cycle[TIME_COLUMN],
        hi_cycle[DETRENDED_COLUMN],
        c=hi_colors,
        cmap=sm.cmap,
        norm=sm.norm,
        s=120,
        alpha=0.95,
        edgecolors="k",
        linewidths=0.4,
        label="in stack",
        zorder=3,
    )
    ax_time.axvspan(t_window_lo, t_window_hi, color="C1", alpha=0.12, label="fold window")
    ax_time.axvline(t_anchor, color="C1", linewidth=1.2, linestyle="--", alpha=0.8, label="anchor")
    ax_time.set_xlabel("obs_time (d)")
    ax_time.set_ylabel("flux / trend")
    ax_time.set_title("Full detrended light curve (stack interval highlighted)")
    ax_time.legend(loc="upper right", fontsize=FONT_SIZE * 0.55)
    fig.tight_layout()
    plt.show()


def main() -> None:
    df = load_detrended_csv(DETRENDED_CSV)
    plot_detrended_lightcurve(df)
    
    t_anchor = 59857.25
    p0 = 0.0591
    stack = local_stack_at_anchor(
        df,
        t_anchor=t_anchor,
        k_cycles=8,
        p0=p0,
        period_slope=PERIOD_SLOPE,
        t_epoch=T_EPOCH,
    )
    if not stack.empty:
        export_folded_stack_ascii(stack, FOLDED_STACK_EXPORT, p0, PERIOD_SLOPE)
        plot_local_phase_stack(df, stack, t_anchor, p0)

    t_anchor = 59866.2
    p0 = 0.06066
    stack = local_stack_at_anchor(
        df,
        t_anchor=t_anchor,
        k_cycles=7,
        p0=p0,
        period_slope=PERIOD_SLOPE,
        t_epoch=T_EPOCH,
    )
    if not stack.empty:
        # export_folded_stack_ascii(stack, FOLDED_STACK_EXPORT, p0, PERIOD_SLOPE)
        plot_local_phase_stack(df, stack, t_anchor, p0)

    anchors = anchor_times_for_lightcurve(
        df, K_CYCLES, P0, PERIOD_SLOPE, T_ANCHOR_STEP
    )
    import sys
    sys.exit(0)

    for t_anchor in anchors:
        stack = local_stack_at_anchor(
            df,
            t_anchor=float(t_anchor),
            k_cycles=K_CYCLES,
            p0=P0,
            period_slope=PERIOD_SLOPE,
            t_epoch=T_EPOCH,
        )
        if stack.empty:
            continue
        plot_local_phase_stack(df, stack, float(t_anchor), P0)


if __name__ == "__main__":
    main()
