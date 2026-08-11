"""Scratch O-C plot from run_timing.py output. Not production — edit constants and run."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from astropy.modeling import fitting, models

from fold_stack import load_detrended_mag_dat
from plot_style import apply_plot_style

logger = logging.getLogger(__name__)

# --- edit these ---
TIMING_CSV = Path(__file__).resolve().parent / "data/runs/ground_R/timing.csv"
LC_DAT = Path(__file__).resolve().parent / "data/R_detrended_corrected.dat"
LC_EXPORT = LC_DAT.with_name(f"{LC_DAT.stem}_smart_folded.dat")
T0 = 59865.4936
P0_early = 0.05937839
P0 = P0_early
CYCLE_SHIFTS: list[tuple[float, int]] = [
    (59865.64, -1),
    (59870.21, -1),
    (59875.32, -1),
]
JD_OBS_FOR_FIT = (59865.0, 59874.0)

REGIME_LABELS = ("before", "parabolic", "after")
REGIME_COLOURS = {"before": "C0", "parabolic": "C1", "after": "C2"}
# REGIME_COLOURS = {"before": "red", "parabolic": "blue", "after": "green"}


@dataclass(frozen=True)
class QuadraticEphemeris:
    """O-C parabola and equivalent quadratic ephemeris for future smart folding.

    Trial linear ephemeris: ``t_lin(E) = T0 + P0 * E``.
    O-C fit on a JD fragment: ``OC(E) = oc0 + oc1*E + oc2*E^2``.

    Improved epoch prediction (same E assignment as now):
        ``t_pred(E) = T0_eff + P0_eff * E + 0.5 * P1 * E^2``

    with ``T0_eff = T0 + oc0``, ``P0_eff = P0 + oc1``, ``P1 = 2 * oc2`` (dP/dE).
    """

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
        """Predict maximum time at cycle ``E`` (days). For smart folding later."""
        E = np.asarray(E, dtype=float)
        return self.T0_eff + self.P0_eff * E + 0.5 * self.P1 * E**2

    def describe(self) -> str:
        """Human-readable summary for the plot annotation."""
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
class PiecewiseEphemeris:
    """Three-regime ephemeris for smart folding (jumps allowed at JD boundaries).

    Regime ``before``: ``t = T0 + P0 * E`` (constant ``P0``).
    Regime ``parabolic``: ``t = T0_eff + P0_eff * E + 0.5 * P1 * E²``.
    Regime ``after``: ``t = t_end + P_end * (E - E_end)`` with ``P_end`` frozen at
    the last in-window maximum from the timing fit.
    """

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
        """Build piecewise law; ``E_at_jd_end`` is cycle index at the last in-window maximum."""
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


def _cycle_from_quadratic(t: np.ndarray, quad: QuadraticEphemeris) -> np.ndarray:
    """Invert ``t(E)`` for the quadratic ephemeris; pick the root nearest ``t_pred(E)``."""
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
    """Assign regime, fractional cycle, phase, and local period to LC times.

    Args:
        t (numpy.ndarray): Truncated JD observation times.
        ephem (PiecewiseEphemeris): Piecewise ephemeris with allowed jumps.

    Returns:
        tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray, numpy.ndarray]:
        ``(regime_index, cycle_E, phase, period_local)`` where ``regime_index`` is
        0=before, 1=parabolic, 2=after; ``phase`` is in ``[-0.5, 0.5)`` cycles.
    """
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
    """Add smart-fold phase columns to a detrended LC dataframe.

    Args:
        df (pandas.DataFrame): LC with at least ``time_col`` and ``mag``.
        ephem (PiecewiseEphemeris): Piecewise ephemeris.
        time_col (str): Time column name (truncated JD).

    Returns:
        pandas.DataFrame: Copy of ``df`` with ``fold_regime``, ``cycle_E``,
        ``phase``, ``period_local``, and ``tau_days`` columns.
    """
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
    """Write LC with smart-fold columns as whitespace-separated ASCII.

    Args:
        df (pandas.DataFrame): Output of :func:`smart_fold_lightcurve`.
        path (Path): Destination ``.dat`` path.
        header (dict): ``jd0`` and optional ``mag0`` from the source LC header.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# JD0={}".format(header.get("jd0", 0.0))]
    if header.get("mag0") is not None:
        lines.append(f"# mag0={header['mag0']}")
    lines.append(
        "# JD mag dmag label fold_regime cycle_E phase period_local tau_days"
    )
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


def plot_smart_folded_lc(df: pd.DataFrame, *, show: bool = True) -> None:
    """Plot mag vs phase, coloured by folding regime."""
    apply_plot_style()
    fig, ax = plt.subplots(figsize=(16, 10))
    for regime in REGIME_LABELS:
        part = df.loc[df["fold_regime"] == regime]
        if part.empty:
            continue
        ax.plot(
            part["phase"],
            part["mag"],
            "o",
            ms=5,
            alpha=0.3,
            color=REGIME_COLOURS[regime],
            label=regime,
        )
    ax.set_xlabel("Phase (cycles, smart fold)")
    ax.set_ylabel("Detrended mag")
    ax.set_title("Smart-folded light curve")
    ax.legend()
    fig.tight_layout()
    if show:
        plt.show()
    else:
        plt.close(fig)


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


def load_timing_rows(path: Path) -> list[dict]:
    """Load timing rows, skipping comment lines that start with ``#``."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(
            line for line in handle if not line.lstrip().startswith("#")
        )
        return list(reader)


def fit_oc_parabola(
    E: np.ndarray,
    OC: np.ndarray,
    jd_obs: np.ndarray,
    *,
    jd_window: tuple[float, float],
    T0: float,
    P0: float,
) -> tuple[QuadraticEphemeris, models.Polynomial1D]:
    """Fit ``OC(E)`` with a parabola for points inside an observed-JD window.

    Args:
        E (numpy.ndarray): Corrected cycle numbers.
        OC (numpy.ndarray): O-C residuals in days.
        jd_obs (numpy.ndarray): Observed maximum times (truncated JD).
        jd_window (tuple[float, float]): Inclusive ``(jd_min, jd_max)`` on ``jd_obs``.
        T0 (float): Trial epoch used to build O-C.
        P0 (float): Trial period used to build O-C.

    Returns:
        tuple[QuadraticEphemeris, Polynomial1D]: Derived ephemeris and fitted model.

    Raises:
        ValueError: If fewer than three points fall inside ``jd_window``.
    """
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


rows = load_timing_rows(TIMING_CSV)
rows.sort(key=lambda r: float(r["t_max"]))
jd_max = np.array([float(r["t_max"]) for r in rows])

E, OC = compute_OC(jd_max, P0, T0, cycle_shifts=CYCLE_SHIFTS or None)

logging.basicConfig(level=logging.INFO, format="%(message)s")
ephem, oc_model = fit_oc_parabola(
    E, OC, jd_max, jd_window=JD_OBS_FOR_FIT, T0=T0, P0=P0
)

fit_mask = (jd_max >= JD_OBS_FOR_FIT[0]) & (jd_max <= JD_OBS_FOR_FIT[1])
if not np.any(fit_mask):
    raise ValueError("no timing maxima inside JD_OBS_FOR_FIT")
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

lc_df, lc_header = load_detrended_mag_dat(LC_DAT)
folded_lc = smart_fold_lightcurve(lc_df, piecewise)
export_smart_folded_lc(folded_lc, LC_EXPORT, header=lc_header)

E_line = np.linspace(float(np.min(E[fit_mask])), float(np.max(E[fit_mask])), 200)
OC_line = oc_model(E_line)

apply_plot_style()
fig, ax = plt.subplots(figsize=(16, 10))
ax.plot(E[~fit_mask], OC[~fit_mask], "o", markersize=10, alpha=0.25, color="C0", label="outside fit window")
ax.plot(E[fit_mask], OC[fit_mask], "o", markersize=15, alpha=0.75, color="C0", label="fit window")
ax.plot(E_line, OC_line, "-", color="C3", lw=2.5, label="OC parabola fit")
ax.axhline(0.0, color="0.35", ls="--")
ax.set_xlabel("Cycle number E")
ax.set_ylabel("O-C (days)")
ax.set_title(f"T0={T0}, P0={P0}")
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


def _nearest_point_index(event) -> int | None:
    """Index of the closest marker within a few pixels of the cursor."""
    if event.inaxes is not ax or event.x is None or event.y is None:
        return None
    xy_display = ax.transData.transform(np.column_stack([E, OC]))
    dist2 = (xy_display[:, 0] - event.x) ** 2 + (xy_display[:, 1] - event.y) ** 2
    idx = int(np.argmin(dist2))
    if dist2[idx] > 18**2:
        return None
    return idx


def _on_hover(event) -> None:
    idx = _nearest_point_index(event)
    if idx is None:
        hover_note.set_visible(False)
        fig.canvas.draw_idle()
        return
    e_val = float(E[idx])
    oc_val = float(OC[idx])
    jd_obs = float(jd_max[idx])
    jd_calc = T0 + e_val * P0
    row = rows[idx]
    hover_note.xy = (e_val, oc_val)
    hover_note.set_text(
        f"{row.get('piece_id', '?')} #{row.get('interval', '?')}\n"
        f"E = {e_val:.0f}\n"
        f"JD calc = {jd_calc:.5f}\n"
        f"JD obs  = {jd_obs:.5f}\n"
        f"O-C = {oc_val:.5f} d"
    )
    hover_note.set_visible(True)
    fig.canvas.draw_idle()


fig.canvas.mpl_connect("motion_notify_event", _on_hover)

fig.tight_layout()
plt.show()

plot_smart_folded_lc(folded_lc)
