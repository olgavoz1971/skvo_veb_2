"""Overview plot: detrended light curve with template timing maxima marked."""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fold_stack import load_detrended_mag_dat

from plot_style import FIGSIZE_OVERVIEW, apply_plot_style

logger = logging.getLogger(__name__)


def plot_lc_with_maxima(
    lc_path: Path,
    timing_rows: list[dict],
    *,
    t_min: float,
    t_max: float,
    save_path: Path,
    show: bool = False,
) -> None:
    """Plot detrended mag vs truncated JD with vertical markers at ``t_max``."""
    apply_plot_style()
    df, _header = load_detrended_mag_dat(lc_path)
    mask = (df["jd"] >= t_min) & (df["jd"] <= t_max)
    piece = df.loc[mask]
    if piece.empty:
        raise ValueError(f"no LC points in overview range [{t_min}, {t_max}]")

    fig, ax = plt.subplots(figsize=FIGSIZE_OVERVIEW)
    ax.scatter(
        piece["jd"].to_numpy(dtype=float),
        piece["mag"].to_numpy(dtype=float),
        s=8,
        c="0.35",
        alpha=0.6,
        label="detrended mag",
        rasterized=True,
    )

    piece_ids = sorted({str(row["piece_id"]) for row in timing_rows})
    cmap = plt.get_cmap("tab10")
    colour_for = {pid: cmap(i % 10) for i, pid in enumerate(piece_ids)}

    for row in timing_rows:
        t_max_val = float(row["t_max"])
        if t_max_val < t_min or t_max_val > t_max:
            continue
        pid = str(row["piece_id"])
        ax.axvline(
            t_max_val,
            color=colour_for[pid],
            ls="--",
            lw=1.2,
            alpha=0.85,
        )

    for pid in piece_ids:
        ax.plot([], [], color=colour_for[pid], ls="--", label=f"maxima ({pid})")

    ax.set_xlim(t_min, t_max)
    ax.set_xlabel("truncated JD")
    ax.set_ylabel("detrended mag")
    ax.set_title("Light curve with template timing maxima")
    ax.legend(loc="upper right")
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150)
    logger.info("Wrote overview %s", save_path)
    if show:
        plt.show()
    else:
        plt.close(fig)


def overview_time_span(
    manifest_pieces: list,
    timing_rows: list[dict],
    overview_t_min: float | None,
    overview_t_max: float | None,
) -> tuple[float, float]:
    """Resolve overview JD limits from manifest or data."""
    if overview_t_min is not None and overview_t_max is not None:
        return overview_t_min, overview_t_max
    t_mins = [p.fit_window.t_min for p in manifest_pieces]
    t_maxs = [p.fit_window.t_max for p in manifest_pieces]
    t_lo = min(t_mins)
    t_hi = max(t_maxs)
    if timing_rows:
        t_lo = min(t_lo, min(float(r["t_max"]) for r in timing_rows) - 0.02)
        t_hi = max(t_hi, max(float(r["t_max"]) for r in timing_rows) + 0.02)
    return t_lo, t_hi
