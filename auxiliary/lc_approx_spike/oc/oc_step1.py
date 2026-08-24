"""Step 1 O-C from spike TOMs: cycle assignment, residuals, plot with σ."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from paths import ensure_import_paths

ensure_import_paths()

from plot_oc import compute_OC  # noqa: E402
from plot_style import FONT_SIZE, apply_plot_style  # noqa: E402
from skvo_veb.utils.lc_config import JD_TO_MJD  # noqa: E402

from tom_io import TomRecord, records_to_arrays  # noqa: E402

logger = logging.getLogger(__name__)


def to_absolute_jd(value: float, *, scale: str) -> float:
    """Convert an ephemeris / shift time to absolute JD.

    Args:
        value (float): Time in the declared scale.
        scale (str): ``jd`` or ``mjd``.

    Returns:
        float: Absolute Julian Date.

    Raises:
        ValueError: If ``scale`` is unsupported.
    """
    scale_l = scale.strip().lower()
    if scale_l == "jd":
        return float(value)
    if scale_l == "mjd":
        return float(value) + float(JD_TO_MJD)
    raise ValueError(f"time scale must be 'jd' or 'mjd', got {scale!r}")


def parse_cycle_shifts(
    specs: list[str],
    *,
    scale: str,
) -> list[tuple[float, int]]:
    """Parse CLI cycle-shift tokens ``at_time:delta_E``.

    Args:
        specs (list[str]): Tokens such as ``60940:1`` or ``2460940.0:-1``.
        scale (str): Scale of ``at_time`` (``jd`` or ``mjd``).

    Returns:
        list[tuple[float, int]]: ``(at_jd, delta_E)`` pairs sorted by time.

    Raises:
        ValueError: If a token is malformed.
    """
    out: list[tuple[float, int]] = []
    for raw in specs:
        text = raw.strip()
        if not text:
            continue
        if ":" not in text:
            raise ValueError(
                f"cycle shift must be 'at_time:delta_E', got {raw!r}"
            )
        left, right = text.rsplit(":", 1)
        at_jd = to_absolute_jd(float(left), scale=scale)
        delta_e = int(right)
        out.append((at_jd, delta_e))
    out.sort(key=lambda item: item[0])
    return out


def compute_step1_oc(
    records: list[TomRecord],
    *,
    t0_jd: float,
    p0: float,
    cycle_shifts: list[tuple[float, int]] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Assign cycles and O-C residuals (days) for spike TOMs.

    Args:
        records (list[TomRecord]): Timed extrema.
        t0_jd (float): Trial epoch as absolute JD.
        p0 (float): Trial period in days.
        cycle_shifts (list[tuple[float, int]] | None): Optional
            ``(at_jd, delta_E)`` corrections (same rule as ``auxiliary/oc``).

    Returns:
        tuple: ``(E, OC, jd_ext, sigma_jd, intervals)``.
    """
    jd_ext, sigma_jd, intervals = records_to_arrays(records)
    E, OC = compute_OC(jd_ext, p0, t0_jd, cycle_shifts=cycle_shifts)
    return E, OC, jd_ext, sigma_jd, intervals


def plot_step1_oc(
    E: np.ndarray,
    OC: np.ndarray,
    jd_ext: np.ndarray,
    sigma_jd: np.ndarray,
    *,
    t0_jd: float,
    p0: float,
    method: str,
    intervals: np.ndarray | None = None,
    show: bool = False,
    save_path: Path | None = None,
) -> plt.Figure:
    """Plot Step 1 O-C vs cycle with TOM formal uncertainties as error bars.

    Args:
        E (numpy.ndarray): Cycle numbers.
        OC (numpy.ndarray): Residuals in days.
        jd_ext (numpy.ndarray): Observed TOM JD.
        sigma_jd (numpy.ndarray): TOM σ in days (NaN → no bar for that point).
        t0_jd (float): Trial epoch JD.
        p0 (float): Trial period (days).
        method (str): Method label for the title.
        intervals (numpy.ndarray | None): Interval indices for logging only.
        show (bool): Interactive ``plt.show(block=True)``.
        save_path (Path | None): Optional PNG path.

    Returns:
        matplotlib.figure.Figure: The figure (caller may close it).
    """
    del intervals  # reserved for future hover annotations
    apply_plot_style()
    fig, ax = plt.subplots(figsize=(16, 10))
    yerr = np.asarray(sigma_jd, dtype=float)
    finite = np.isfinite(yerr)
    if np.any(finite):
        ax.errorbar(
            E[finite],
            OC[finite],
            yerr=yerr[finite],
            fmt="o",
            markersize=10,
            alpha=0.85,
            color="C0",
            ecolor="0.35",
            elinewidth=1.2,
            capsize=3,
            label=f"{method} O-C ± σ(TOM)",
        )
    if np.any(~finite):
        ax.plot(
            E[~finite],
            OC[~finite],
            "o",
            markersize=10,
            alpha=0.85,
            color="C1",
            label=f"{method} (no σ)",
        )

    ax.axhline(0.0, color="0.35", ls="--")
    ax.set_xlabel("Cycle number E")
    ax.set_ylabel("O-C (days)")
    med_s = (
        float(np.nanmedian(yerr[finite])) * 86400.0 if np.any(finite) else float("nan")
    )
    title = (
        f"Spike Step 1 O-C  [{method}]  "
        f"(T0={t0_jd:.5f} JD, P0={p0:.8f} d)\n"
        f"observed JD {float(np.min(jd_ext)):.5f} … {float(np.max(jd_ext)):.5f}"
    )
    if np.isfinite(med_s):
        title += f"\nmedian σ(TOM) = {med_s:.1f} s"
    ax.set_title(title, fontsize=FONT_SIZE)
    ax.legend(loc="upper left")

    ax_top = ax.secondary_xaxis(
        "top",
        functions=(lambda e: t0_jd + e * p0, lambda jd: (jd - t0_jd) / p0),
    )
    ax_top.set_xlabel("Calculated JD  (T0 + E × P0; not observed TOM)")

    rms = float(np.sqrt(np.mean(OC**2)))
    ax.text(
        0.98,
        0.02,
        f"N={len(E)}  RMS={rms:.5f} d ({rms * 86400:.1f} s)",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=FONT_SIZE * 0.65,
    )

    fig.tight_layout()
    if save_path is not None:
        save_path = save_path.resolve()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        logger.info("Wrote %s", save_path)
    if show:
        plt.show(block=True)
    return fig


def export_step1_oc_csv(
    path: Path,
    *,
    E: np.ndarray,
    OC: np.ndarray,
    jd_ext: np.ndarray,
    sigma_jd: np.ndarray,
    intervals: np.ndarray,
    method: str,
    t0_jd: float,
    p0: float,
    cycle_shifts: list[tuple[float, int]],
) -> None:
    """Write Step 1 O-C table with provenance comment header.

    Args:
        path (Path): Output CSV.
        E (numpy.ndarray): Cycles.
        OC (numpy.ndarray): Residuals (days).
        jd_ext (numpy.ndarray): Observed TOM JD.
        sigma_jd (numpy.ndarray): TOM σ (days).
        intervals (numpy.ndarray): Source interval indices.
        method (str): Method id.
        t0_jd (float): Trial epoch JD.
        p0 (float): Trial period (days).
        cycle_shifts (list[tuple[float, int]]): Applied shifts.
    """
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "interval",
        "cycle_number",
        "jd_ext",
        "OC",
        "sigma_jd_ext",
        "sigma_s",
        "method",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# oc_tool: lc_approx_spike/oc/run_oc_step1\n")
        handle.write("# task: plot_oc_residuals (step 1 only)\n")
        handle.write(
            "# algorithm: O-C = jd_ext - (T0 + E*P0); "
            "E = round((jd_ext-T0)/P0) after cycle_shifts\n"
        )
        handle.write(f"# method: {method}\n")
        handle.write(f"# ephemeris_T0_JD: {t0_jd:.8f}\n")
        handle.write(f"# ephemeris_P0_d: {p0:.10f}\n")
        handle.write(f"# cycle_shifts_applied: {len(cycle_shifts)}\n")
        for at_jd, delta in cycle_shifts:
            handle.write(f"# cycle_shift: at_jd={at_jd:.8f} delta_E={delta}\n")
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for i in range(len(E)):
            sig = float(sigma_jd[i])
            writer.writerow(
                {
                    "interval": int(intervals[i]),
                    "cycle_number": int(E[i]),
                    "jd_ext": float(jd_ext[i]),
                    "OC": float(OC[i]),
                    "sigma_jd_ext": sig if np.isfinite(sig) else "",
                    "sigma_s": sig * 86400.0 if np.isfinite(sig) else "",
                    "method": method,
                }
            )
    logger.info("Wrote %s (%s row(s))", path, len(E))


def export_step1_oc_dat(
    path: Path,
    *,
    E: np.ndarray,
    OC: np.ndarray,
    sigma_jd: np.ndarray,
    method: str,
    t0_jd: float,
    p0: float,
    cycle_shifts: list[tuple[float, int]],
) -> None:
    """Write a compact xmgrace ``.dat`` (double-space columns).

    Non-data lines (provenance and the column header) are ``#``-commented.
    Columns, in order: ``cycle_number``, ``OC``, ``sigma_jd_ext``.

    Args:
        path (Path): Output ``.dat`` path.
        E (numpy.ndarray): Cycles.
        OC (numpy.ndarray): Residuals (days).
        sigma_jd (numpy.ndarray): TOM σ (days).
        method (str): Method id.
        t0_jd (float): Trial epoch JD.
        p0 (float): Trial period (days).
        cycle_shifts (list[tuple[float, int]]): Applied shifts.
    """
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    sep = "  "
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# oc_tool: lc_approx_spike/oc/run_oc_step1\n")
        handle.write("# task: plot_oc_residuals (step 1 only)\n")
        handle.write(
            "# algorithm: O-C = jd_ext - (T0 + E*P0); "
            "E = round((jd_ext-T0)/P0) after cycle_shifts\n"
        )
        handle.write(f"# method: {method}\n")
        handle.write(f"# ephemeris_T0_JD: {t0_jd:.8f}\n")
        handle.write(f"# ephemeris_P0_d: {p0:.10f}\n")
        handle.write(f"# cycle_shifts_applied: {len(cycle_shifts)}\n")
        for at_jd, delta in cycle_shifts:
            handle.write(f"# cycle_shift: at_jd={at_jd:.8f} delta_E={delta}\n")
        handle.write(f"# cycle_number{sep}OC{sep}sigma_jd_ext\n")
        for i in range(len(E)):
            sig = float(sigma_jd[i])
            sig_txt = f"{sig:.10e}" if np.isfinite(sig) else "nan"
            handle.write(
                f"{int(E[i])}{sep}{float(OC[i]):.10e}{sep}{sig_txt}\n"
            )
    logger.info("Wrote %s (%s row(s))", path, len(E))
