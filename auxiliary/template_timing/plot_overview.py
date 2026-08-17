"""Overview plot: light curve with template timing maxima marked."""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt

from lc_io import load_lightcurve_frame
from skvo_veb.utils.lc_config import DOMAIN_MAG

from plot_style import FIGSIZE_OVERVIEW, apply_plot_style

logger = logging.getLogger(__name__)


def plot_lc_with_maxima(
    timing_rows: list[dict],
    *,
    t_min: float,
    t_max: float,
    lc_segments: list[tuple[Path, float, float]],
    working_domain: str,
    save_path: Path,
    show: bool = False,
) -> None:
    """Plot photometry vs absolute JD with vertical markers at ``t_max``.

    Args:
        timing_rows: Accepted timing summary rows.
        t_min: Overview lower bound (absolute JD).
        t_max: Overview upper bound (absolute JD).
        lc_segments: ``(lc_path, segment_t_min, segment_t_max)`` per distinct LC file;
            each segment is clipped to ``[t_min, t_max]`` for plotting.
        working_domain: Manifest ``photometry_domain`` (``mag`` or ``flux``).
        save_path: Output PNG path.
        show: Call ``plt.show()`` when true.
    """
    apply_plot_style()
    if not lc_segments:
        raise ValueError("lc_segments must be non-empty")

    fig, ax = plt.subplots(figsize=FIGSIZE_OVERVIEW)
    plotted_lc = False
    for lc_path, seg_lo, seg_hi in lc_segments:
        lo = max(t_min, seg_lo)
        hi = min(t_max, seg_hi)
        if lo > hi:
            continue
        df, _meta = load_lightcurve_frame(lc_path, working_domain=working_domain)
        mask = (df["jd"] >= lo) & (df["jd"] <= hi)
        piece = df.loc[mask]
        if piece.empty:
            logger.warning("no LC points for %s in [%s, %s]", lc_path.name, lo, hi)
            continue
        ax.scatter(
            piece["jd"].to_numpy(dtype=float),
            piece["phot"].to_numpy(dtype=float),
            s=8,
            c="0.35",
            alpha=0.6,
            rasterized=True,
        )
        plotted_lc = True

    if not plotted_lc:
        raise ValueError(f"no LC points in overview range [{t_min}, {t_max}]")

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

    ax.set_xlim(t_min, t_max)
    if working_domain == DOMAIN_MAG:
        ax.invert_yaxis()
        y_label = "detrended magnitude"
    else:
        y_label = "flux"
    ax.set_xlabel("Julian Date")
    ax.set_ylabel(y_label)
    ax.set_title("Light curve with template timing maxima")
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
    t_mins = [p.fit_window.t_min for p in manifest_pieces if not getattr(p, "skip", False)]
    t_maxs = [p.fit_window.t_max for p in manifest_pieces if not getattr(p, "skip", False)]
    if not t_mins:
        t_lo, t_hi = 0.0, 1.0
    else:
        t_lo = min(t_mins)
        t_hi = max(t_maxs)
    if timing_rows:
        t_lo = min(t_lo, min(float(r["t_max"]) for r in timing_rows) - 0.02)
        t_hi = max(t_hi, max(float(r["t_max"]) for r in timing_rows) + 0.02)
    return t_lo, t_hi
