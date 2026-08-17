"""Scratch O-C workflow from run_timing.py output. Not production — edit constants."""

from __future__ import annotations

import csv
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[1]
_AUX_ROOT = _SCRIPT_DIR.parent
for _path in (_REPO_ROOT, _SCRIPT_DIR, _AUX_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from astropy.modeling import fitting, models

from lc_io import load_lightcurve_frame
from plot_style import apply_plot_style
from smart_folding.model_free_folding import (
    TimingContinuityRules,
    WindowFit,
    fold_interpolated,
    local_period_pairs,
    sliding_local_period,
)

logger = logging.getLogger(__name__)

# --- edit these ---
RUN_STEP1 = True
RUN_STEP2 = False
RUN_STEP3 = False
# RUN_PERIOD_SEGMENTS = True
RUN_PERIOD_SEGMENTS = False

# JD0 = 2400000
JD0 = 0
PHOTOMETRY_DOMAIN = "mag"
# TIMING_FILE = Path(__file__).resolve().parent / "data/runs/ground_R/timing.csv"
# TIMING_FILE = Path(__file__).resolve().parent / "data/runs/R_TESS_1/timing.csv"
TIMING_FILE = Path(__file__).resolve().parent / "data/runs/NSV_807_30_TESS_SPOC_main/timing.csv"
# TIMING_FILE = Path(__file__).resolve().parent / "data/runs/NSV_807_30_SPOC_main/timing.csv"
# TIMING_FILE = Path(__file__).resolve().parent / "data/R_detrended_corrected_max_gp.dat"
# TIMING_FILE = Path(__file__).resolve().parent / "data/timing_max_vlada.dat"
# TIMING_FILE = Path(__file__).resolve().parent / "data/runs/merged/timing_ensemble.csv"
# TIMING_FILE = Path(__file__).resolve().parent / "data/GP_max/R_TESS_all.dat"
# OC_EXPORT = TIMING_FILE.with_name("oc_calculated_max_vlada.csv")
OC_EXPORT = TIMING_FILE.with_name("oc_NSV_807_30_TESS_SPOC_main.csv")
# OC_EXPORT = TIMING_FILE.with_name("oc_NSV_807_30_SPOC_main.csv")
# OC_EXPORT = TIMING_FILE.with_name("oc_calculated_max_GP.csv")
# TIMING_PAIRS_EXPORT = TIMING_FILE.with_name("oc_timing_pairs_max_vlada.csv")
TIMING_PAIRS_EXPORT = TIMING_FILE.with_name("oc_timing_pairs_max_template_merged.csv")
LC_DAT = Path(__file__).resolve().parent / "data/R_detrended_corrected.dat"
LC_EXPORT = LC_DAT.with_name(f"{LC_DAT.stem}_smart_folded.dat")
MF_LC_EXPORT = LC_DAT.with_name(f"{LC_DAT.stem}_model_free_folded.dat")


def _load_lc_mag_frame(path: Path) -> tuple[pd.DataFrame, dict]:
    """Load a light curve and expose legacy ``mag`` / ``dmag`` column names."""
    df, meta = load_lightcurve_frame(path, working_domain=PHOTOMETRY_DOMAIN)
    out = df.rename(columns={"phot": "mag", "phot_err": "dmag"})
    return out, {"photcal": meta.get("photcal")}


def _export_header_lines(header: dict) -> list[str]:
    """Build optional comment header lines for folded LC exports."""
    photcal = header.get("photcal") or {}
    zp_mag = photcal.get("zp_mag")
    if zp_mag is None:
        return []
    return [f"# MAG0={zp_mag}"]


# T0 = JD0 + 59865.4936
T0 = 2457711.8539
# P0 = 0.05937839
# P0 = 0.060
P0 = 0.3389614
# CYCLE_SHIFTS: list[tuple[float, int]] = [
#     (JD0 + 59858.63, 1),
#     (JD0 + 59865.38, 1),
#     (JD0 + 59866.25, -1),
#     # (JD0 + 59875.0, 1),
#     (JD0 + 59878.4, 1),
#     # (JD0 + 59880.34, -2),
# ]

CYCLE_SHIFTS: list[tuple[float, int]] = []

JD_OBS_FOR_FIT = (JD0 + 59865.0, JD0 + 59874.0)

# Step 1b: linear O-C segments — period / epoch correction (after CYCLE_SHIFTS)
# Each entry is (label, jd_start, jd_end) inclusive on observed JD.
PERIOD_SEGMENTS: list[tuple[str, float, float]] = [
    ("early", JD0 + 59854.8, JD0 + 59865.46),
    ("A", JD0 + 59865.45, JD0 + 59867.10),
    ("B", JD0 + 59867.09, JD0 + 59874.12),
    ("B1", JD0 + 59875.20, JD0 + 59877.07),
    # ("late", JD0 + 59875.9, JD0 + 59883.5),
]

PERIOD_CORRECT_MAX_ITER = 5
PERIOD_CORRECT_TOL = 1e-8
SEGMENT_PERIOD_EXPORT = TIMING_FILE.with_name("oc_segment_periods.csv")

# Step 3: model-free folding
MF_MIN_CYCLE_GAP = 1.0
MF_MAX_CYCLE_GAP = 30.0
MF_MAX_NEIGHBOUR_DE = 1.0
MF_KNOWN_JD_GAPS: list[tuple[float, float]] = [
    # Example: (JD0 + 59856.0, JD0 + 59856.5),
]
MF_SLIDING_WINDOW = 5
MF_ANCHOR_INDEX = 0
MF_GALLERY_MAX_WINDOWS = 12
MF_OVERLAY_MAX_WINDOWS = 24

REGIME_LABELS = ("before", "parabolic", "after")
REGIME_DISPLAY = {"before": "BEFORE", "parabolic": "PARABOLIC", "after": "AFTER"}
REGIME_COLOURS = {"before": "C0", "parabolic": "C1", "after": "C2"}
REGIME_ZORDER = {"parabolic": 1, "after": 2, "before": 3}


@dataclass(frozen=True)
class QuadraticEphemeris:
    """O-C parabola fit on a JD fragment (Step 2 only)."""

    oc0: float
    oc1: float
    oc2: float
    T0_eff: float
    P0_eff: float
    P1: float
    Pdot_dt: float
    jd_min: float
    jd_max: float
    n_points: int
    rms: float

    def t_pred(self, E: np.ndarray | float) -> np.ndarray | float:
        """Predict maximum time at cycle ``E`` (days)."""
        E = np.asarray(E, dtype=float)
        return self.T0_eff + self.P0_eff * E + 0.5 * self.P1 * E**2

    def describe(self) -> str:
        """Human-readable summary for terminal output."""
        return (
            f"fragment JD obs {self.jd_min:.2f} .. {self.jd_max:.2f}  "
            f"({self.n_points} pts, RMS={self.rms:.5f} d)\n"
            f"OC(E) = {self.oc0:+.5f} {self.oc1:+.3e} E {self.oc2:+.3e} E²\n"
            f"t(E) = {self.T0_eff:.5f} + {self.P0_eff:.8f} E "
            f"{0.5 * self.P1:+.3e} E²\n"
            f"P1 = dP/dE = {self.P1:.3e} d/cycle²,  "
            f"Pdot ≈ {self.Pdot_dt:.3e} d/d/cycle"
        )


@dataclass(frozen=True)
class LinearSegmentEphemeris:
    """Constant-period ephemeris from a linear O-C segment (Step 1b).

    Period correction follows the ``correct_period`` idea: fit ``O-C`` vs
    observed JD within the segment (cycle numbers ``E`` stay fixed after
    ``CYCLE_SHIFTS``), then ``P_corr = P / (1 - slope)`` and
    ``T0_corr = T0 + intercept``, iterated until the time slope vanishes.
    """

    name: str
    jd_min: float
    jd_max: float
    T0: float
    P: float
    T0_trial: float
    P_trial: float
    slope_oc_vs_jd: float
    intercept_oc_vs_jd: float
    slope_oc_vs_E: float
    intercept_oc_vs_E: float
    n_points: int
    n_used: int
    rms: float
    n_iter: int

    def describe(self) -> str:
        """Human-readable summary for terminal output."""
        dP = self.P - self.P_trial
        dT0 = self.T0 - self.T0_trial
        return (
            f"segment {self.name!r}  JD {self.jd_min:.5f} .. {self.jd_max:.5f}  "
            f"({self.n_used}/{self.n_points} pts, RMS={self.rms:.5f} d, "
            f"{self.n_iter} iter)\n"
            f"  P = {self.P:.8f} d  (ΔP = {dP:+.3e} d vs trial)\n"
            f"  T0 = {self.T0:.5f}  (ΔT0 = {dT0:+.5f} d vs trial)\n"
            f"  OC vs JD (centred): slope={self.slope_oc_vs_jd:.3e}\n"
            f"  OC vs E:  slope={self.slope_oc_vs_E:.3e} d/cycle "
            f"(≈ ΔP), intercept={self.intercept_oc_vs_E:+.5f} d (≈ ΔT0)"
        )


@dataclass(frozen=True)
class PiecewiseEphemeris:
    """Three-regime ephemeris for smart folding (Step 2 only)."""

    T0: float
    P0: float
    quad: QuadraticEphemeris
    jd_start: float
    jd_end: float
    E_end: float
    t_end: float
    P_end: float

    @classmethod
    def from_quadratic(
        cls,
        *,
        T0: float,
        P0: float,
        quad: QuadraticEphemeris,
        jd_window: tuple[float, float],
        E_at_jd_end: float,
    ) -> PiecewiseEphemeris:
        """Build piecewise law from the Step 2 parabolic fit."""
        E_end = float(E_at_jd_end)
        t_end = float(quad.t_pred(E_end))
        P_end = float(quad.P0_eff + quad.P1 * E_end)
        return cls(
            T0=T0,
            P0=P0,
            quad=quad,
            jd_start=float(jd_window[0]),
            jd_end=float(jd_window[1]),
            E_end=E_end,
            t_end=t_end,
            P_end=P_end,
        )

    def describe(self) -> str:
        """Human-readable summary for terminal output."""
        return (
            f"{self.quad.describe()}\n"
            f"piecewise folding JD {self.jd_start:.2f} .. {self.jd_end:.2f}\n"
            f"E_end={self.E_end:.0f}, t_end={self.t_end:.5f}, P_end={self.P_end:.8f} d"
        )


def compute_OC(
    jd_max: np.ndarray,
    P0: float,
    T0: float,
    cycle_shifts: list[tuple[float, int]] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return corrected cycle numbers E and O-C residuals in days."""
    jd_max = np.asarray(jd_max, dtype=float)
    E_naive = np.round((jd_max - T0) / P0)

    delta = np.zeros_like(E_naive)
    if cycle_shifts:
        for jd_b, d in sorted(cycle_shifts):
            delta += np.where(jd_max >= jd_b, d, 0)

    E = E_naive + delta
    OC = jd_max - (T0 + E * P0)
    return E, OC


def assign_jd_regime_labels(
    jd: np.ndarray,
    jd_window: tuple[float, float],
) -> list[str]:
    """Label each JD as before / parabolic / after relative to the fit window.

    Args:
        jd (numpy.ndarray): Timestamps (days).
        jd_window (tuple[float, float]): ``(jd_start, jd_end)`` parabolic segment.

    Returns:
        list[str]: Regime label per timestamp (``REGIME_LABELS`` values).
    """
    jd_lo, jd_hi = jd_window
    labels: list[str] = []
    for t in np.asarray(jd, dtype=float):
        if t < jd_lo:
            labels.append("before")
        elif t <= jd_hi:
            labels.append("parabolic")
        else:
            labels.append("after")
    return labels


def load_timing_csv(path: Path) -> list[dict]:
    """Load ``run_timing.py`` CSV output, skipping ``#`` comment rows."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(
            line for line in handle if not line.lstrip().startswith("#")
        )
        return list(reader)


def load_gp_minimum_dat(path: Path) -> list[dict]:
    """Load extrema timing from a whitespace ``.dat`` file.

    Comment lines (``# ...``) are skipped. Each data row is::

        jd [uncertainty]

    The first column is truncated JD (``t_max``). If a second column is
    present it is stored as ``sigma_t_max``; a single-column file is JD only.

    Args:
        path (Path): Path to the ``.dat`` file.

    Returns:
        list[dict]: Normalised rows with ``t_max`` and optional ``sigma_t_max``.
    """
    df = pd.read_csv(path, sep=r"\s+", comment="#", header=None)
    if df.empty:
        raise ValueError(f"{path}: no data rows")

    jd = df.iloc[:, 0].to_numpy(dtype=float)
    has_sigma = df.shape[1] >= 2
    sigma = df.iloc[:, 1].to_numpy(dtype=float) if has_sigma else None

    rows: list[dict] = []
    for i, t_max in enumerate(jd):
        out: dict[str, str] = {"t_max": repr(float(t_max))}
        if sigma is not None and pd.notna(sigma[i]):
            out["sigma_t_max"] = repr(float(sigma[i]))
        rows.append(out)
    return rows


def load_timing_rows(path: Path) -> list[dict]:
    """Load timing maxima from CSV (pipeline) or simple GP minimum ``.dat``.

    Args:
        path (Path): ``timing.csv`` or GP minimum ``.dat``.

    Returns:
        list[dict]: Rows normalised for O-C (``t_max``, optional ``sigma_t_max``).
    """
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_timing_csv(path)
    if suffix == ".dat":
        return load_gp_minimum_dat(path)
    raise ValueError(f"unsupported timing file extension {suffix!r}: {path}")


def export_calculated_oc(
    path: Path,
    rows: list[dict],
    E: np.ndarray,
    OC: np.ndarray,
) -> None:
    """Write Step 1 O-C table: cycle_number, OC, optional sigma_t_max.

    Args:
        path (Path): Output CSV path.
        rows (list[dict]): Timing rows (same order as ``E`` / ``OC``).
        E (numpy.ndarray): Cycle numbers.
        OC (numpy.ndarray): O-C residuals in days.
    """
    if len(rows) != len(E):
        raise ValueError("rows and E must have the same length")
    has_sigma = bool(rows) and "sigma_t_max" in rows[0]
    fieldnames = ["cycle_number", "OC"]
    if has_sigma:
        fieldnames.append("sigma_t_max")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row, e_val, oc_val in zip(rows, E, OC):
            record = {
                "cycle_number": int(e_val),
                "OC": float(oc_val),
            }
            if has_sigma:
                record["sigma_t_max"] = row["sigma_t_max"]
            writer.writerow(record)
    logger.info("Wrote %s (%s rows)", path, len(rows))


def export_timing_pairs(
    path: Path,
    jd_obs: np.ndarray,
    E: np.ndarray,
    rows: list[dict],
) -> None:
    """Write Step 3 timing handoff: ``jd_obs``, ``cycle_number``, optional sigma.

    Args:
        path (Path): Output CSV path.
        jd_obs (numpy.ndarray): Observed maximum times (full JD, days).
        E (numpy.ndarray): Corrected cycle numbers.
        rows (list[dict]): Source timing rows for optional uncertainties.
    """
    if len(rows) != len(E):
        raise ValueError("rows and E must have the same length")
    has_sigma = bool(rows) and "sigma_t_max" in rows[0]
    fieldnames = ["jd_obs", "cycle_number"]
    if has_sigma:
        fieldnames.append("timing_sigma")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row, jd_val, e_val in zip(rows, jd_obs, E):
            record = {
                "jd_obs": float(jd_val),
                "cycle_number": int(e_val),
            }
            if has_sigma:
                record["timing_sigma"] = float(row["sigma_t_max"])
            writer.writerow(record)
    logger.info("Wrote %s (%s rows)", path, len(rows))


def _timing_sigma(rows: list[dict]) -> np.ndarray | None:
    """Return per-point timing uncertainties when present in ``rows``."""
    if not rows or "sigma_t_max" not in rows[0]:
        return None
    return np.array([float(r["sigma_t_max"]) for r in rows], dtype=float)


def _mf_continuity_rules() -> TimingContinuityRules:
    """Build Step 3 continuity rules from script constants."""
    return TimingContinuityRules(
        min_cycle_gap=MF_MIN_CYCLE_GAP,
        max_cycle_gap=MF_MAX_CYCLE_GAP,
        max_neighbour_dE=MF_MAX_NEIGHBOUR_DE,
        known_jd_gaps=tuple(MF_KNOWN_JD_GAPS),
    )


def _subsample_window_fits(
    fits: list[WindowFit],
    max_count: int,
) -> list[WindowFit]:
    """Evenly subsample window fits for crowded diagnostic plots."""
    if max_count <= 0:
        raise ValueError("max_count must be positive")
    if len(fits) <= max_count:
        return fits
    idx = np.unique(np.round(np.linspace(0, len(fits) - 1, max_count)).astype(int))
    return [fits[i] for i in idx]


def plot_pairwise_local_period(
    t_mid: np.ndarray,
    P_local: np.ndarray,
    dE: np.ndarray,
    *,
    P0: float,
    show: bool = True,
) -> None:
    """Step 3 diagnostic: pairwise ``P(t)`` cloud."""
    apply_plot_style()
    fig, ax = plt.subplots(figsize=(16, 8))
    sc = ax.scatter(
        t_mid,
        P_local,
        c=np.abs(dE),
        cmap="viridis",
        s=40,
        alpha=0.35,
        edgecolors="none",
    )
    ax.axhline(P0, color="C3", ls="--", lw=1.5, label=f"trial P0 = {P0:.8f} d")
    ax.set_xlabel("Midpoint JD (observed maxima pairs)")
    ax.set_ylabel("Local period (days)")
    ax.set_title("Step 3: pairwise local period estimates")
    cb = fig.colorbar(sc, ax=ax, pad=0.02)
    cb.set_label("|ΔE| (cycles)")
    ax.legend(loc="best")
    fig.tight_layout()
    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_sliding_local_period(
    t_center: np.ndarray,
    P_win: np.ndarray,
    P_win_err: np.ndarray,
    *,
    P0: float,
    show: bool = True,
) -> None:
    """Step 3 diagnostic: sliding-window ``P(t)`` with uncertainties."""
    apply_plot_style()
    fig, ax = plt.subplots(figsize=(16, 8))
    ax.errorbar(
        t_center,
        P_win,
        yerr=P_win_err,
        fmt="o-",
        ms=6,
        lw=1.5,
        capsize=3,
        color="C0",
        label="sliding-window P(t)",
    )
    ax.axhline(P0, color="C3", ls="--", lw=1.5, label=f"trial P0 = {P0:.8f} d")
    ax.set_xlabel("Window centre JD")
    ax.set_ylabel("Local period (days)")
    ax.set_title("Step 3: sliding-window local period")
    ax.legend(loc="best")
    fig.tight_layout()
    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_window_fit_gallery(
    fits: list[WindowFit],
    *,
    window_size: int,
    show: bool = True,
) -> None:
    """Step 3 diagnostic: subsampled panels of each sliding-window line fit."""
    sampled = _subsample_window_fits(fits, MF_GALLERY_MAX_WINDOWS)
    n_panels = len(sampled)
    n_cols = min(4, n_panels)
    n_rows = int(np.ceil(n_panels / n_cols))
    apply_plot_style()
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(4.5 * n_cols, 4.0 * n_rows))
    axes_flat = np.atleast_1d(axes).ravel()

    for ax, wf in zip(axes_flat, sampled):
        E_line = np.linspace(float(wf.E.min()), float(wf.E.max()), 50)
        jd_line = wf.T0 + wf.P * E_line
        ax.plot(wf.E, wf.jd, "o", ms=8, color="C0", label="maxima")
        ax.plot(E_line, jd_line, "-", color="C3", lw=2, label="fit")
        ax.set_title(
            f"w#{wf.start_idx}  P={wf.P:.7f} d\n"
            f"JD centre {wf.t_center:.3f}",
            fontsize=10,
        )
        ax.set_xlabel("E")
        ax.set_ylabel("JD obs")
        ax.grid(True, alpha=0.25)

    for ax in axes_flat[n_panels:]:
        ax.axis("off")

    fig.suptitle(
        f"Step 3: sliding-window fit gallery "
        f"({n_panels} of {len(fits)} windows shown)",
        fontsize=14,
    )
    fig.tight_layout()
    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_window_fits_overlay(
    fits: list[WindowFit],
    *,
    jd_obs: np.ndarray,
    E: np.ndarray,
    show: bool = True,
) -> None:
    """Step 3 diagnostic: subsampled window fits overlaid on all maxima."""
    sampled = _subsample_window_fits(fits, MF_OVERLAY_MAX_WINDOWS)
    apply_plot_style()
    fig, ax = plt.subplots(figsize=(16, 10))
    ax.plot(E, jd_obs, "o", ms=9, color="0.15", alpha=0.55, label="all maxima", zorder=1)

    e_lo = float(np.min(E))
    e_hi = float(np.max(E))
    E_line = np.linspace(e_lo, e_hi, 100)
    for k, wf in enumerate(sampled):
        jd_line = wf.T0 + wf.P * E_line
        ax.plot(
            E_line,
            jd_line,
            "-",
            color="C3",
            lw=1.0,
            alpha=0.22,
            zorder=2,
            label="window fits" if k == 0 else None,
        )
        ax.plot(wf.E, wf.jd, "o", ms=6, color="C0", alpha=0.35, zorder=3)

    ax.set_xlabel("Cycle number E")
    ax.set_ylabel("JD obs")
    ax.set_title(
        f"Step 3: overlaid window fits "
        f"({len(sampled)} of {len(fits)} windows)"
    )
    ax.legend(loc="best")
    fig.tight_layout()
    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_window_membership_track(
    fits: list[WindowFit],
    *,
    n_maxima: int,
    jd_obs: np.ndarray,
    window_size: int,
    show: bool = True,
) -> None:
    """Step 3 diagnostic: which maxima each sliding window includes."""
    apply_plot_style()
    fig, ax = plt.subplots(figsize=(16, max(6, 0.18 * len(fits) + 2)))
    bar_h = 0.8
    for w_idx, wf in enumerate(fits):
        start = wf.start_idx
        end = wf.start_idx + window_size - 1
        ax.barh(
            w_idx,
            width=end - start,
            left=start,
            height=bar_h,
            color="C0",
            alpha=0.35,
            edgecolor="C0",
            linewidth=0.5,
        )

    ax.set_xlabel("Maximum index (time-sorted)")
    ax.set_ylabel("Window index (valid fits only)")
    ax.set_title(
        f"Step 3: window membership track "
        f"({len(fits)} windows x {window_size} maxima)"
    )
    ax.set_xlim(-0.5, n_maxima - 0.5)
    ax.set_ylim(-0.5, len(fits) - 0.5)

    ax_top = ax.secondary_xaxis(
        "top",
        functions=(
            lambda idx: np.interp(idx, np.arange(n_maxima), jd_obs),
            lambda jd: np.interp(jd, jd_obs, np.arange(n_maxima)),
        ),
    )
    ax_top.set_xlabel("JD obs (interpolated at maximum index)")
    fig.tight_layout()
    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_phases_at_maxima(
    jd_obs: np.ndarray,
    E: np.ndarray,
    phase: np.ndarray,
    *,
    show: bool = True,
) -> None:
    """Step 3 diagnostic: recovered phase at input maxima."""
    apply_plot_style()
    fig, ax = plt.subplots(figsize=(16, 8))
    ax.plot(jd_obs, phase, "o", ms=10, alpha=0.8, color="C0")
    ax.set_xlabel("JD obs")
    ax.set_ylabel("Recovered phase")
    ax.set_title("Step 3: model-free phase at observed maxima")
    ax.set_ylim(-0.05, 1.05)
    fig.tight_layout()
    if show:
        plt.show()
    else:
        plt.close(fig)


def export_model_free_folded_lc(
    df: pd.DataFrame,
    path: Path,
    *,
    header: dict,
) -> None:
    """Write LC with model-free fold columns (Step 3)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = _export_header_lines(header)
    lines.append("# JD mag dmag label fold_regime cycle_E phase period_local tau_days")
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
        for row in df.itertuples(index=False):
            dmag = getattr(row, "dmag", np.nan)
            label = getattr(row, "label", 0)
            dmag_s = "" if pd.isna(dmag) else f"{float(dmag):.6g}"
            regime = getattr(row, "fold_regime", "")
            handle.write(
                f"{float(row.jd):.4f} {float(row.mag):.6g} {dmag_s} {label} "
                f"{regime} {float(row.cycle_E):.6f} {float(row.phase):.6f} "
                f"{float(row.period_local):.8f} {float(row.tau_days):.8f}\n"
            )
    logger.info("Wrote %s (%s rows)", path, len(df))


def plot_regime_folded_lc(
    df: pd.DataFrame,
    *,
    title: str,
    xlabel: str,
    regime_col: str = "fold_regime",
    show: bool = True,
) -> None:
    """Folded LC coloured by JD regime; BEFORE drawn above PARABOLIC and AFTER."""
    apply_plot_style()
    fig, ax = plt.subplots(figsize=(16, 10))
    for regime in ("parabolic", "after", "before"):
        part = df.loc[df[regime_col] == regime]
        if part.empty:
            continue
        ax.plot(
            part["phase"],
            part["mag"],
            "o",
            ms=5,
            alpha=0.3,
            color=REGIME_COLOURS[regime],
            label=REGIME_DISPLAY[regime],
            zorder=REGIME_ZORDER[regime],
        )
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Detrended mag")
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_model_free_folded_lc(df: pd.DataFrame, *, show: bool = True) -> None:
    """Step 3: model-free folded light curve with JD regime overlay."""
    plot_regime_folded_lc(
        df,
        title="Step 3: model-free folded light curve",
        xlabel="Phase (cycles, model-free fold)",
        show=show,
    )


def model_free_fold_lightcurve(
    df: pd.DataFrame,
    t_center: np.ndarray,
    P_win: np.ndarray,
    *,
    t_anchor: float,
    E_anchor: float,
    time_col: str = "jd",
) -> pd.DataFrame:
    """Apply interpolated model-free folding to a light-curve dataframe.

    Args:
        df (pandas.DataFrame): Light curve with a time column.
        t_center (numpy.ndarray): Sliding-window centre times.
        P_win (numpy.ndarray): Local period at each centre time.
        t_anchor (float): Anchor time (days).
        E_anchor (float): Cycle number at the anchor.
        time_col (str): Name of the time column.

    Returns:
        pandas.DataFrame: Copy with ``cycle_E``, ``phase``, ``period_local``, ``tau_days``.
    """
    out = df.copy()
    times = out[time_col].to_numpy(dtype=float)
    phase, cycle_e = fold_interpolated(
        times, t_center, P_win, t_anchor, E_anchor
    )
    P_interp = np.interp(times, t_center, P_win)
    out["cycle_E"] = cycle_e
    out["phase"] = phase
    out["period_local"] = P_interp
    out["tau_days"] = phase * P_interp
    return out


def fit_linear_oc_vs_jd(
    jd: np.ndarray,
    oc: np.ndarray,
    sigma: np.ndarray | None = None,
    *,
    outlier_sigma: float = 3.0,
) -> tuple[float, float, np.ndarray]:
    """Weighted linear ``O-C`` vs observed JD with 3σ outlier rejection.

    Args:
        jd (numpy.ndarray): Observed maximum times (days).
        oc (numpy.ndarray): O-C residuals (days).
        sigma (numpy.ndarray | None): Timing uncertainties for weighting.
        outlier_sigma (float): Rejection threshold in residual RMS units.

    Returns:
        tuple: ``(slope, intercept, inlier_mask)`` for ``oc ≈ intercept + slope * jd``.
    """
    jd = np.asarray(jd, dtype=float)
    oc = np.asarray(oc, dtype=float)
    weights = None
    if sigma is not None:
        safe = np.where(sigma == 0, 1e-6, sigma)
        weights = 1.0 / safe**0.75

    line = models.Linear1D()
    fitter = fitting.LinearLSQFitter()
    if weights is not None:
        fitted = fitter(line, jd, oc, weights=weights)
    else:
        fitted = fitter(line, jd, oc)

    resid = oc - fitted(jd)
    std = float(np.std(resid))
    inlier = np.abs(resid) < outlier_sigma * std if std > 0 else np.ones(len(jd), dtype=bool)
    if not np.any(inlier):
        inlier = np.ones(len(jd), dtype=bool)

    jd_in = jd[inlier]
    oc_in = oc[inlier]
    w_in = weights[inlier] if weights is not None else None
    line_final = models.Linear1D()
    if w_in is not None:
        fitted_final = fitter(line_final, jd_in, oc_in, weights=w_in)
    else:
        fitted_final = fitter(line_final, jd_in, oc_in)

    return (
        float(fitted_final.slope.value),
        float(fitted_final.intercept.value),
        inlier,
    )


def fit_linear_oc_vs_E(
    E: np.ndarray,
    oc: np.ndarray,
    sigma: np.ndarray | None = None,
) -> tuple[float, float]:
    """Linear ``O-C`` vs cycle number (diagnostic / plot overlay).

    Args:
        E (numpy.ndarray): Cycle numbers after ``CYCLE_SHIFTS``.
        oc (numpy.ndarray): O-C residuals (days).
        sigma (numpy.ndarray | None): Timing uncertainties for weighting.

    Returns:
        tuple: ``(slope, intercept)`` with ``slope ≈ P_true - P_trial``.
    """
    E = np.asarray(E, dtype=float)
    oc = np.asarray(oc, dtype=float)
    line = models.Linear1D()
    fitter = fitting.LinearLSQFitter()
    if sigma is not None:
        safe = np.where(sigma == 0, 1e-6, sigma)
        weights = 1.0 / safe**0.75
        fitted = fitter(line, E, oc, weights=weights)
    else:
        fitted = fitter(line, E, oc)
    return float(fitted.slope.value), float(fitted.intercept.value)


def correct_period_in_segment(
    jd: np.ndarray,
    E: np.ndarray,
    OC: np.ndarray,
    *,
    name: str,
    jd_window: tuple[float, float],
    T0: float,
    P0: float,
    sigma: np.ndarray | None = None,
    max_iter: int = PERIOD_CORRECT_MAX_ITER,
    tol: float = PERIOD_CORRECT_TOL,
) -> LinearSegmentEphemeris:
    """Correct constant ``P`` and ``T0`` inside one linear O-C segment.

    Cycle numbers ``E`` are held fixed (post ``CYCLE_SHIFTS``). Each iteration
    refits ``O-C`` vs JD on the segment and applies
    ``P ← P / (1 - slope)``, ``T0 ← T0 + intercept`` (see ``correct_period``
    in ``binary_processor.py``).

    Args:
        jd (numpy.ndarray): Observed maximum times (days).
        E (numpy.ndarray): Corrected cycle numbers.
        OC (numpy.ndarray): Step 1 O-C residuals (days).
        name (str): Segment label.
        jd_window (tuple[float, float]): Inclusive JD bounds.
        T0 (float): Trial epoch (days).
        P0 (float): Trial period (days).
        sigma (numpy.ndarray | None): Per-point timing sigma.
        max_iter (int): Maximum correction iterations.
        tol (float): Stop when ``|slope_oc_vs_jd|`` falls below this value.

    Returns:
        LinearSegmentEphemeris: Corrected segment ephemeris and fit diagnostics.
    """
    jd_lo, jd_hi = jd_window
    mask = (jd >= jd_lo) & (jd <= jd_hi)
    n_points = int(np.count_nonzero(mask))
    if n_points < 2:
        raise ValueError(
            f"segment {name!r}: need at least 2 maxima in "
            f"JD [{jd_lo:.5f}, {jd_hi:.5f}], got {n_points}"
        )

    jd_seg = np.asarray(jd[mask], dtype=float)
    E_seg = np.asarray(E[mask], dtype=float)
    sigma_seg = np.asarray(sigma[mask], dtype=float) if sigma is not None else None

    P_work = float(P0)
    T0_work = float(T0)
    slope = float("nan")
    intercept_at_jd0 = float("nan")
    inlier = np.ones(n_points, dtype=bool)
    n_iter = 0

    for n_iter in range(1, max_iter + 1):
        oc_seg = jd_seg - T0_work - E_seg * P_work
        jd_ref = float(np.mean(jd_seg))
        slope, intercept_at_jd0, inlier = fit_linear_oc_vs_jd(
            jd_seg - jd_ref, oc_seg, sigma_seg
        )
        P_work = P_work / (1.0 - slope)
        oc_after_p = jd_seg[inlier] - T0_work - E_seg[inlier] * P_work
        T0_work = T0_work + float(np.mean(oc_after_p))
        logger.info(
            "  %s iter %d: slope=%.3e, P=%.8f, T0=%.5f, mean OC=%.5f d",
            name,
            n_iter,
            slope,
            P_work,
            T0_work,
            float(np.mean(jd_seg[inlier] - T0_work - E_seg[inlier] * P_work)),
        )
        if abs(slope) < tol:
            break

    oc_final = jd_seg[inlier] - T0_work - E_seg[inlier] * P_work
    rms = float(np.sqrt(np.mean(oc_final**2))) if len(oc_final) else float("nan")

    oc_trial_seg = np.asarray(OC[mask], dtype=float)
    slope_e, intercept_e = fit_linear_oc_vs_E(
        E_seg, oc_trial_seg, sigma=sigma_seg
    )

    return LinearSegmentEphemeris(
        name=name,
        jd_min=jd_lo,
        jd_max=jd_hi,
        T0=T0_work,
        P=P_work,
        T0_trial=T0,
        P_trial=P0,
        slope_oc_vs_jd=slope,
        intercept_oc_vs_jd=intercept_at_jd0,
        slope_oc_vs_E=slope_e,
        intercept_oc_vs_E=intercept_e,
        n_points=n_points,
        n_used=int(np.count_nonzero(inlier)),
        rms=rms,
        n_iter=n_iter,
    )


def export_segment_periods(
    path: Path,
    segments: list[LinearSegmentEphemeris],
) -> None:
    """Write segment period-correction summary CSV.

    Args:
        path (Path): Output CSV path.
        segments (list[LinearSegmentEphemeris]): One row per fitted segment.
    """
    fieldnames = [
        "segment",
        "jd_min",
        "jd_max",
        "P_trial",
        "P_corrected",
        "delta_P",
        "T0_trial",
        "T0_corrected",
        "delta_T0",
        "slope_oc_vs_jd",
        "slope_oc_vs_E",
        "n_points",
        "n_used",
        "rms",
        "n_iter",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for seg in segments:
            writer.writerow(
                {
                    "segment": seg.name,
                    "jd_min": f"{seg.jd_min:.5f}",
                    "jd_max": f"{seg.jd_max:.5f}",
                    "P_trial": f"{seg.P_trial:.8f}",
                    "P_corrected": f"{seg.P:.8f}",
                    "delta_P": f"{seg.P - seg.P_trial:.3e}",
                    "T0_trial": f"{seg.T0_trial:.5f}",
                    "T0_corrected": f"{seg.T0:.5f}",
                    "delta_T0": f"{seg.T0 - seg.T0_trial:.5f}",
                    "slope_oc_vs_jd": f"{seg.slope_oc_vs_jd:.3e}",
                    "slope_oc_vs_E": f"{seg.slope_oc_vs_E:.3e}",
                    "n_points": seg.n_points,
                    "n_used": seg.n_used,
                    "rms": f"{seg.rms:.5f}",
                    "n_iter": seg.n_iter,
                }
            )
    logger.info("Wrote %s (%s segments)", path, len(segments))


def plot_oc_segment_period_fits(
    E: np.ndarray,
    OC: np.ndarray,
    jd_max: np.ndarray,
    segments: list[LinearSegmentEphemeris],
    *,
    T0: float,
    P0: float,
    show: bool = True,
) -> None:
    """Step 1b: O-C diagram with linear segment fits and corrected ephemerides.

    Args:
        E (numpy.ndarray): Cycle numbers.
        OC (numpy.ndarray): Step 1 O-C residuals (days).
        jd_max (numpy.ndarray): Observed maximum times.
        segments (list[LinearSegmentEphemeris]): Fitted segment results.
        T0 (float): Trial epoch used in Step 1.
        P0 (float): Trial period used in Step 1.
        show (bool): Call ``plt.show()`` when true.
    """
    apply_plot_style()
    seg_colours = plt.cm.tab10(np.linspace(0, 0.9, max(len(segments), 1)))

    fig, (ax_e, ax_jd) = plt.subplots(
        2, 1, figsize=(16, 12), sharex=False, height_ratios=[2, 1]
    )

    ax_e.plot(E, OC, "o", markersize=10, alpha=0.35, color="0.55", label="all O-C")
    ax_e.axhline(0.0, color="0.35", ls="--")

    for colour, seg in zip(seg_colours, segments, strict=False):
        mask = (jd_max >= seg.jd_min) & (jd_max <= seg.jd_max)
        E_seg = E[mask]
        OC_seg = OC[mask]
        ax_e.plot(
            E_seg,
            OC_seg,
            "o",
            markersize=14,
            alpha=0.85,
            color=colour,
            label=f"{seg.name} data",
        )
        e_line = np.linspace(float(np.min(E_seg)), float(np.max(E_seg)), 50)
        oc_line = seg.intercept_oc_vs_E + seg.slope_oc_vs_E * e_line
        ax_e.plot(
            e_line,
            oc_line,
            "-",
            lw=2.5,
            color=colour,
            label=f"{seg.name} linear (P={seg.P:.6f} d)",
        )
        ax_e.axvspan(
            float(np.min(E_seg)),
            float(np.max(E_seg)),
            alpha=0.08,
            color=colour,
        )

    ax_e.set_ylabel("O-C (days)")
    ax_e.set_xlabel("Cycle number E")
    ax_e.set_title(
        f"Step 1b: linear segment period correction  "
        f"(trial T0={T0:.5f}, P0={P0:.8f} d)"
    )
    ax_e.legend(loc="upper left", fontsize=11, ncol=2)

    ax_jd.barh(
        range(len(segments)),
        [seg.P - seg.P_trial for seg in segments],
        color=seg_colours[: len(segments)],
        alpha=0.85,
    )
    ax_jd.axvline(0.0, color="0.35", ls="--")
    ax_jd.set_yticks(range(len(segments)))
    ax_jd.set_yticklabels([seg.name for seg in segments])
    ax_jd.set_xlabel("ΔP (days) vs trial period")
    ax_jd.set_title("Segment period corrections")

    fig.tight_layout()
    if show:
        plt.show()
    else:
        plt.close(fig)


def run_step_period_segments(
    E: np.ndarray,
    OC: np.ndarray,
    jd_max: np.ndarray,
    rows: list[dict],
    *,
    T0: float,
    P0: float,
) -> list[LinearSegmentEphemeris]:
    """Fit linear O-C segments and export corrected local periods (Step 1b).

    Args:
        E (numpy.ndarray): Cycle numbers after ``CYCLE_SHIFTS``.
        OC (numpy.ndarray): Step 1 O-C residuals (days).
        jd_max (numpy.ndarray): Observed maximum times (days).
        rows (list[dict]): Timing metadata (for sigma).
        T0 (float): Trial epoch.
        P0 (float): Trial period.

    Returns:
        list[LinearSegmentEphemeris]: One result per entry in ``PERIOD_SEGMENTS``.
    """
    sigma = _timing_sigma(rows)
    results: list[LinearSegmentEphemeris] = []

    logger.info(
        "Step 1b: period correction in %s segment(s), trial T0=%.5f P0=%.8f",
        len(PERIOD_SEGMENTS),
        T0,
        P0,
    )
    for name, jd_lo, jd_hi in PERIOD_SEGMENTS:
        mask = (jd_max >= jd_lo) & (jd_max <= jd_hi)
        n_in = int(np.count_nonzero(mask))
        if n_in < 2:
            logger.warning(
                "Step 1b segment %r: skipping — only %s point(s) in "
                "JD [%.5f, %.5f] (need ≥2 for linear fit)",
                name,
                n_in,
                jd_lo,
                jd_hi,
            )
            continue
        logger.info("Step 1b segment %r: JD %.5f .. %.5f", name, jd_lo, jd_hi)
        seg = correct_period_in_segment(
            jd_max,
            E,
            OC,
            name=name,
            jd_window=(jd_lo, jd_hi),
            T0=T0,
            P0=P0,
            sigma=sigma,
        )
        logger.info("%s", seg.describe())
        results.append(seg)

    if not results:
        logger.warning("Step 1b: no segments fitted — check PERIOD_SEGMENTS and timing data")
        return results

    export_segment_periods(SEGMENT_PERIOD_EXPORT, results)
    plot_oc_segment_period_fits(E, OC, jd_max, results, T0=T0, P0=P0)
    return results


def plot_calculated_oc(
    E: np.ndarray,
    OC: np.ndarray,
    jd_max: np.ndarray,
    rows: list[dict],
    *,
    T0: float,
    P0: float,
    show: bool = True,
) -> tuple[plt.Figure, plt.Axes]:
    """Step 1: raw O-C vs cycle number, no fit overlay.

    Args:
        E (numpy.ndarray): Cycle numbers.
        OC (numpy.ndarray): O-C residuals in days.
        jd_max (numpy.ndarray): Observed maximum times.
        rows (list[dict]): Timing metadata for hover text.
        T0 (float): Trial epoch used in the O-C calculation.
        P0 (float): Trial period used in the O-C calculation.
        show (bool): Call ``plt.show()`` when true.

    Returns:
        tuple[Figure, Axes]: The figure and axes (for optional Step 2 reuse).
    """
    apply_plot_style()
    fig, ax = plt.subplots(figsize=(16, 10))
    ax.plot(E, OC, "o", markersize=12, alpha=0.75, color="C0", label="calculated O-C")
    ax.axhline(0.0, color="0.35", ls="--")
    ax.set_xlabel("Cycle number E")
    ax.set_ylabel("O-C (days)")
    ax.set_title(f"Step 1: calculated O-C  (T0={T0:.5f}, P0={P0:.8f} d)")
    ax.legend(loc="upper left")

    ax_top = ax.secondary_xaxis(
        "top",
        functions=(lambda e: T0 + e * P0, lambda jd: (jd - T0) / P0),
    )
    ax_top.set_xlabel("Calculated JD  (T0 + E × P0; not observed t_max)")

    ax.format_coord = lambda e, oc: (
        f"E={e:.0f}, JD calc={T0 + e * P0:.5f}, O-C={oc:.5f} d"
    )

    hover_note = ax.annotate(
        "",
        xy=(0, 0),
        xytext=(14, 14),
        textcoords="offset points",
        bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "0.45", "alpha": 0.95},
        fontsize=14,
    )
    hover_note.set_visible(False)

    def nearest_index(event) -> int | None:
        if event.inaxes is not ax or event.x is None or event.y is None:
            return None
        xy_display = ax.transData.transform(np.column_stack([E, OC]))
        dist2 = (xy_display[:, 0] - event.x) ** 2 + (xy_display[:, 1] - event.y) ** 2
        idx = int(np.argmin(dist2))
        if dist2[idx] > 18**2:
            return None
        return idx

    def on_hover(event) -> None:
        idx = nearest_index(event)
        if idx is None:
            hover_note.set_visible(False)
            fig.canvas.draw_idle()
            return
        e_val = float(E[idx])
        oc_val = float(OC[idx])
        jd_obs = float(jd_max[idx])
        row = rows[idx]
        hover_note.xy = (e_val, oc_val)
        hover_note.set_text(
            f"{row.get('piece_id', '?')} #{row.get('interval', '?')}\n"
            f"E = {e_val:.0f}\n"
            f"JD calc = {T0 + e_val * P0:.5f}\n"
            f"JD obs  = {jd_obs:.5f}\n"
            f"O-C = {oc_val:.5f} d"
        )
        hover_note.set_visible(True)
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("motion_notify_event", on_hover)
    fig.tight_layout()
    if show:
        plt.show()
    return fig, ax


def fit_oc_parabola(
    E: np.ndarray,
    OC: np.ndarray,
    jd_obs: np.ndarray,
    *,
    jd_window: tuple[float, float],
    T0: float,
    P0: float,
) -> tuple[QuadraticEphemeris, models.Polynomial1D]:
    """Fit ``OC(E)`` with a parabola (Step 2)."""
    jd_lo, jd_hi = jd_window
    mask = (jd_obs >= jd_lo) & (jd_obs <= jd_hi)
    n_pts = int(np.count_nonzero(mask))
    if n_pts < 3:
        raise ValueError(
            f"need at least 3 maxima in JD window [{jd_lo}, {jd_hi}], got {n_pts}"
        )

    E_fit = np.asarray(E[mask], dtype=float)
    OC_fit = np.asarray(OC[mask], dtype=float)

    poly = models.Polynomial1D(degree=2)
    fitted = fitting.LinearLSQFitter()(poly, E_fit, OC_fit)
    oc0 = float(fitted.c0.value)
    oc1 = float(fitted.c1.value)
    oc2 = float(fitted.c2.value)

    T0_eff = T0 + oc0
    P0_eff = P0 + oc1
    P1 = 2.0 * oc2
    Pdot_dt = P1 / P0_eff if P0_eff > 0 else float("nan")
    resid = OC_fit - fitted(E_fit)
    rms = float(np.sqrt(np.mean(resid**2)))

    ephem = QuadraticEphemeris(
        oc0=oc0,
        oc1=oc1,
        oc2=oc2,
        T0_eff=T0_eff,
        P0_eff=P0_eff,
        P1=P1,
        Pdot_dt=Pdot_dt,
        jd_min=jd_lo,
        jd_max=jd_hi,
        n_points=n_pts,
        rms=rms,
    )
    return ephem, fitted


def _cycle_from_quadratic(t: np.ndarray, quad: QuadraticEphemeris) -> np.ndarray:
    """Invert ``t(E)`` for the quadratic ephemeris."""
    t = np.asarray(t, dtype=float)
    if np.allclose(quad.P1, 0.0):
        return (t - quad.T0_eff) / quad.P0_eff
    disc = quad.P0_eff**2 - 2.0 * quad.P1 * (quad.T0_eff - t)
    if np.any(disc < 0):
        bad = int(np.count_nonzero(disc < 0))
        raise ValueError(
            f"{bad} time(s) have no real quadratic ephemeris inverse "
            f"(discriminant < 0)"
        )
    sqrt_d = np.sqrt(disc)
    e1 = (-quad.P0_eff + sqrt_d) / quad.P1
    e2 = (-quad.P0_eff - sqrt_d) / quad.P1
    pred1 = quad.T0_eff + quad.P0_eff * e1 + 0.5 * quad.P1 * e1**2
    pred2 = quad.T0_eff + quad.P0_eff * e2 + 0.5 * quad.P1 * e2**2
    use1 = np.abs(pred1 - t) <= np.abs(pred2 - t)
    return np.where(use1, e1, e2)


def assign_smart_fold_phases(
    t: np.ndarray,
    ephem: PiecewiseEphemeris,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Assign regime, cycle, phase, and local period (Step 2 smart fold)."""
    t = np.asarray(t, dtype=float)
    n = len(t)
    regime = np.full(n, -1, dtype=int)
    cycle_e = np.full(n, np.nan, dtype=float)
    phase = np.full(n, np.nan, dtype=float)
    period = np.full(n, np.nan, dtype=float)

    before = t < ephem.jd_start
    middle = (t >= ephem.jd_start) & (t <= ephem.jd_end)
    after = t > ephem.jd_end

    if np.any(before):
        e = (t[before] - ephem.T0) / ephem.P0
        cycle_e[before] = e
        phase[before] = e - np.round(e)
        period[before] = ephem.P0
        regime[before] = 0

    if np.any(middle):
        e = _cycle_from_quadratic(t[middle], ephem.quad)
        cycle_e[middle] = e
        phase[middle] = e - np.round(e)
        period[middle] = ephem.quad.P0_eff + ephem.quad.P1 * np.round(e)
        regime[middle] = 1

    if np.any(after):
        e = ephem.E_end + (t[after] - ephem.t_end) / ephem.P_end
        cycle_e[after] = e
        phase[after] = e - np.round(e)
        period[after] = ephem.P_end
        regime[after] = 2

    return regime, cycle_e, phase, period


def smart_fold_lightcurve(
    df: pd.DataFrame,
    ephem: PiecewiseEphemeris,
    *,
    time_col: str = "jd",
) -> pd.DataFrame:
    """Add smart-fold phase columns (Step 2)."""
    out = df.copy()
    regime, cycle_e, phase, period = assign_smart_fold_phases(
        out[time_col].to_numpy(dtype=float), ephem
    )
    out["fold_regime"] = [REGIME_LABELS[i] for i in regime]
    out["cycle_E"] = cycle_e
    out["phase"] = phase
    out["period_local"] = period
    out["tau_days"] = phase * period
    return out


def export_smart_folded_lc(df: pd.DataFrame, path: Path, *, header: dict) -> None:
    """Write LC with smart-fold columns (Step 2)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = _export_header_lines(header)
    lines.append("# JD mag dmag label fold_regime cycle_E phase period_local tau_days")
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
        for row in df.itertuples(index=False):
            dmag = getattr(row, "dmag", np.nan)
            label = getattr(row, "label", 0)
            dmag_s = "" if pd.isna(dmag) else f"{float(dmag):.6g}"
            handle.write(
                f"{float(row.jd):.4f} {float(row.mag):.6g} {dmag_s} {label} "
                f"{row.fold_regime} {float(row.cycle_E):.6f} {float(row.phase):.6f} "
                f"{float(row.period_local):.8f} {float(row.tau_days):.8f}\n"
            )
    logger.info("Wrote %s (%s rows)", path, len(df))


def plot_oc_parabolic_fit(
    E: np.ndarray,
    OC: np.ndarray,
    jd_max: np.ndarray,
    *,
    fit_mask: np.ndarray,
    oc_model: models.Polynomial1D,
    T0: float,
    P0: float,
    show: bool = True,
) -> None:
    """Step 2: O-C with parabolic fit overlay (separate figure)."""
    apply_plot_style()
    E_line = np.linspace(float(np.min(E[fit_mask])), float(np.max(E[fit_mask])), 200)
    OC_line = oc_model(E_line)

    fig, ax = plt.subplots(figsize=(16, 10))
    ax.plot(E[~fit_mask], OC[~fit_mask], "o", markersize=10, alpha=0.25, color="C0")
    ax.plot(E[fit_mask], OC[fit_mask], "o", markersize=15, alpha=0.75, color="C0")
    ax.plot(E_line, OC_line, "-", color="C3", lw=2.5, label="OC parabola fit")
    ax.axhline(0.0, color="0.35", ls="--")
    ax.set_xlabel("Cycle number E")
    ax.set_ylabel("O-C (days)")
    ax.set_title(f"Step 2: parabolic O-C fit  (T0={T0:.5f}, P0={P0:.8f} d)")
    ax.legend(loc="upper left")
    fig.tight_layout()
    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_smart_folded_lc(df: pd.DataFrame, *, show: bool = True) -> None:
    """Step 2: smart-folded LC with BEFORE drawn above PARABOLIC and AFTER."""
    plot_regime_folded_lc(
        df,
        title="Step 2: smart-folded light curve",
        xlabel="Phase (cycles, smart fold)",
        show=show,
    )


def run_step1(
    rows: list[dict],
    E: np.ndarray,
    OC: np.ndarray,
    jd_max: np.ndarray,
    *,
    T0: float,
    P0: float,
) -> None:
    """Export and plot calculated O-C only."""
    export_calculated_oc(OC_EXPORT, rows, E, OC)
    plot_calculated_oc(E, OC, jd_max, rows, T0=T0, P0=P0)
    logger.info(
        "Step 1: OC range [%.5f, %.5f] d, RMS=%.5f d",
        float(np.min(OC)),
        float(np.max(OC)),
        float(np.sqrt(np.mean(OC**2))),
    )


def run_step2(
    rows: list[dict],
    E: np.ndarray,
    OC: np.ndarray,
    jd_max: np.ndarray,
    *,
    T0: float,
    P0: float,
) -> None:
    """Parabolic fit, fit plot, and smart folding (separate from Step 1)."""
    ephem, oc_model = fit_oc_parabola(
        E, OC, jd_max, jd_window=JD_OBS_FOR_FIT, T0=T0, P0=P0
    )
    logger.info("%s", ephem.describe())

    fit_mask = (jd_max >= JD_OBS_FOR_FIT[0]) & (jd_max <= JD_OBS_FOR_FIT[1])
    if not np.any(fit_mask):
        raise ValueError("no timing maxima inside JD_OBS_FOR_FIT")

    plot_oc_parabolic_fit(
        E, OC, jd_max, fit_mask=fit_mask, oc_model=oc_model, T0=T0, P0=P0
    )

    E_end_idx = int(np.argmax(jd_max[fit_mask]))
    E_end = float(E[fit_mask][E_end_idx])
    piecewise = PiecewiseEphemeris.from_quadratic(
        T0=T0,
        P0=P0,
        quad=ephem,
        jd_window=JD_OBS_FOR_FIT,
        E_at_jd_end=E_end,
    )
    logger.info("%s", piecewise.describe())

    lc_df, lc_header = _load_lc_mag_frame(LC_DAT)
    folded_lc = smart_fold_lightcurve(lc_df, piecewise)
    export_smart_folded_lc(folded_lc, LC_EXPORT, header=lc_header)
    plot_smart_folded_lc(folded_lc)


def run_step3(
    rows: list[dict],
    E: np.ndarray,
    jd_max: np.ndarray,
    *,
    P0: float,
) -> None:
    """Model-free ``P(t)`` diagnostics and LC folding (Step 3)."""
    export_timing_pairs(TIMING_PAIRS_EXPORT, jd_max, E, rows)

    sigma = _timing_sigma(rows)
    t_mid, P_pair, dE = local_period_pairs(
        jd_max, E, min_cycle_gap=MF_MIN_CYCLE_GAP
    )
    if len(t_mid) == 0:
        raise ValueError("no pairwise local period estimates; check MIN_CYCLE_GAP")
    plot_pairwise_local_period(t_mid, P_pair, dE, P0=P0)

    t_center, P_win, P_win_err, _T0_win = sliding_local_period(
        jd_max,
        E,
        window=MF_SLIDING_WINDOW,
        sigma=sigma,
    )
    plot_sliding_local_period(t_center, P_win, P_win_err, P0=P0)

    anchor_idx = int(MF_ANCHOR_INDEX)
    if not 0 <= anchor_idx < len(jd_max):
        raise ValueError(
            f"MF_ANCHOR_INDEX={anchor_idx} out of range for {len(jd_max)} points"
        )
    t_anchor = float(jd_max[anchor_idx])
    E_anchor = float(E[anchor_idx])
    logger.info(
        "Step 3 anchor: JD=%.5f, E=%.0f (index %s)",
        t_anchor,
        E_anchor,
        anchor_idx,
    )

    phase_at_max, _E_at_max = fold_interpolated(
        jd_max, t_center, P_win, t_anchor, E_anchor
    )
    plot_phases_at_maxima(jd_max, E, phase_at_max)
    logger.info(
        "Step 3 phase at maxima: mean=%.4f, std=%.4f cycles",
        float(np.mean(phase_at_max)),
        float(np.std(phase_at_max)),
    )

    lc_df, lc_header = _load_lc_mag_frame(LC_DAT)
    lc_df = lc_df.copy()

    t_cov_lo = float(t_center.min())
    t_cov_hi = float(t_center.max())
    lc_lo = float(lc_df["jd"].min())
    lc_hi = float(lc_df["jd"].max())
    if lc_lo < t_cov_lo or lc_hi > t_cov_hi:
        logger.warning(
            "LC JD range [%.5f, %.5f] extends outside sliding-window coverage "
            "[%.5f, %.5f]; edge P values are held constant",
            lc_lo,
            lc_hi,
            t_cov_lo,
            t_cov_hi,
        )

    folded_lc = model_free_fold_lightcurve(
        lc_df,
        t_center,
        P_win,
        t_anchor=t_anchor,
        E_anchor=E_anchor,
    )
    folded_lc["fold_regime"] = assign_jd_regime_labels(
        folded_lc["jd"].to_numpy(dtype=float),
        JD_OBS_FOR_FIT,
    )
    export_model_free_folded_lc(folded_lc, MF_LC_EXPORT, header=lc_header)
    plot_model_free_folded_lc(folded_lc)


def main() -> None:
    """Run selected workflow steps."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    rows = load_timing_rows(TIMING_FILE)
    rows.sort(key=lambda r: float(r["t_max"]))
    jd_max = np.array([float(r["t_max"]) for r in rows]) + JD0
    E, OC = compute_OC(jd_max, P0, T0, cycle_shifts=CYCLE_SHIFTS or None)

    if RUN_STEP1:
        run_step1(rows, E, OC, jd_max, T0=T0, P0=P0)
    if RUN_PERIOD_SEGMENTS:
        run_step_period_segments(E, OC, jd_max, rows, T0=T0, P0=P0)
    if RUN_STEP2:
        run_step2(rows, E, OC, jd_max, T0=T0, P0=P0)
    if RUN_STEP3:
        run_step3(rows, E, jd_max, P0=P0)


if __name__ == "__main__":
    main()
