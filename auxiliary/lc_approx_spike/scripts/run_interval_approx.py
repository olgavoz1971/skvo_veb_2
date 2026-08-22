#!/usr/bin/env python3
"""Step 1 spike: fit AP/WSAP/… on the first N intervals of a VOTable LC.

Uses the same LC / interval ingestion path as ``template_timing`` (imports only;
nothing outside ``auxiliary/lc_approx_spike`` is modified).

Example::

    cd auxiliary/lc_approx_spike
    ../../.venv/bin/python scripts/run_interval_approx.py \\
        --lc data/NWCam_sector_59_ffi_flat.vot \\
        --intervals data/NWCam_59_prim.dat \\
        --domain flux --method AP --max-intervals 3 --show-plots
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

_SPIKE = Path(__file__).resolve().parents[1]
if str(_SPIKE) not in sys.path:
    sys.path.insert(0, str(_SPIKE))

from paths import DATA_DIR, ensure_import_paths  # noqa: E402

ensure_import_paths()

from io_spike import (  # noqa: E402
    interval_arrays,
    load_full_lightcurve,
    load_interval_pairs_jd,
    slice_interval,
)
from vendor.ila_models import METHODS, fit_interval, model_curve  # noqa: E402

logger = logging.getLogger(__name__)

CSV_FIELDS = [
    "interval",
    "t_start",
    "t_end",
    "n_points",
    "method",
    "ok",
    "t_ext",
    "sigma_t_ext_s",
    "y_ext",
    "sigma_y_ext",
    "c4",
    "c5",
    "rms",
    "warning",
    "fail_reason",
]


def _plot_interval(
    idx: int,
    t: np.ndarray,
    y: np.ndarray,
    result,
    *,
    domain: str,
    out_path: Path | None,
    show: bool,
) -> None:
    """Save/show one interval with data, model, junctions, and TOM."""
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.scatter(t, y, s=18, c="k", alpha=0.7, label="data")
    if result.ok and result.params.size:
        t_line = np.linspace(float(np.min(t)), float(np.max(t)), 400)
        y_line = model_curve(result.method, result.params, t_line)
        ax.plot(t_line, y_line, color="tab:green", lw=2, label=result.method)
        if np.isfinite(result.c4):
            ax.axvline(result.c4, color="maroon", lw=1, label="C4/C5")
        if np.isfinite(result.c5):
            ax.axvline(result.c5, color="maroon", lw=1)
        ax.axvline(result.t_ext, color="tab:red", ls="--", label="TOM")
        if np.isfinite(result.sigma_t_ext):
            ax.axvspan(
                result.t_ext - result.sigma_t_ext,
                result.t_ext + result.sigma_t_ext,
                color="tab:red",
                alpha=0.15,
            )
    if domain == "mag":
        ax.invert_yaxis()
    ax.set_xlabel("JD")
    ax.set_ylabel(domain)
    title = f"Interval {idx}: {result.method}"
    if result.ok:
        title += f"  TOM={result.t_ext:.6f}  σ={result.sigma_t_ext * 86400:.1f}s"
    else:
        title += f"  FAILED: {result.fail_reason}"
    if result.warning:
        title += f"\n{result.warning}"
    ax.set_title(title, fontsize=10)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=120)
        logger.info("Wrote %s", out_path)
    if show:
        plt.show()
    else:
        plt.close(fig)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Spike: AP/WSAP extrema on template_timing-style LC + intervals"
    )
    parser.add_argument(
        "--lc",
        type=Path,
        default=DATA_DIR / "NWCam_sector_59_ffi_flat.vot",
        help="Light curve (.vot / .dat / …)",
    )
    parser.add_argument(
        "--intervals",
        type=Path,
        default=DATA_DIR / "NWCam_59_prim.dat",
        help="Two-column interval file (absolute JD)",
    )
    parser.add_argument(
        "--domain",
        choices=("flux", "mag"),
        default="flux",
        help="Working photometry domain (matches template_timing manifests)",
    )
    parser.add_argument(
        "--method",
        default="AP",
        help=f"One of {sorted(METHODS)} (default AP)",
    )
    parser.add_argument(
        "--max-intervals",
        type=int,
        default=3,
        help="Fit only the first N intervals (default 3)",
    )
    parser.add_argument(
        "--min-points",
        type=int,
        default=8,
        help="Skip intervals with fewer points",
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=None,
        help="Output CSV (default: data/runs/<lc_stem>_<method>.csv)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Directory for CSV and optional PNGs",
    )
    parser.add_argument(
        "--save-plots",
        action="store_true",
        help="Write one PNG per fitted interval",
    )
    parser.add_argument(
        "--show-plots",
        action="store_true",
        help="Interactive plt.show() after each interval",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    method = str(args.method).upper()
    if method not in METHODS:
        parser.error(f"method must be one of {sorted(METHODS)}")

    lc_path = args.lc.resolve()
    int_path = args.intervals.resolve()
    out_dir = (
        args.out_dir.resolve()
        if args.out_dir is not None
        else (_SPIKE / "data" / "runs" / f"{lc_path.stem}_{int_path.stem}")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = (
        args.out_csv.resolve()
        if args.out_csv is not None
        else out_dir / f"approx_{method.lower()}.csv"
    )

    df, _meta = load_full_lightcurve(lc_path, working_domain=args.domain)
    intervals = load_interval_pairs_jd(int_path)
    n_use = min(int(args.max_intervals), len(intervals))
    logger.info(
        "Fitting method=%s on first %s / %s interval(s)",
        method,
        n_use,
        len(intervals),
    )

    rows: list[dict] = []
    for idx in range(n_use):
        t_start, t_end = intervals[idx]
        piece = slice_interval(df, t_start, t_end)
        t, y, _err = interval_arrays(piece)
        if t.size < int(args.min_points):
            logger.warning(
                "Interval %s [%.5f, %.5f]: only %s points; skip",
                idx,
                t_start,
                t_end,
                t.size,
            )
            continue
        result = fit_interval(method, t, y)
        sigma_s = (
            result.sigma_t_ext * 86400.0 if np.isfinite(result.sigma_t_ext) else float("nan")
        )
        row = {
            "interval": idx,
            "t_start": t_start,
            "t_end": t_end,
            "n_points": result.n_points,
            "method": result.method,
            "ok": result.ok,
            "t_ext": result.t_ext,
            "sigma_t_ext_s": sigma_s,
            "y_ext": result.y_ext,
            "sigma_y_ext": result.sigma_y_ext,
            "c4": result.c4,
            "c5": result.c5,
            "rms": result.rms,
            "warning": result.warning or "",
            "fail_reason": result.fail_reason or "",
        }
        rows.append(row)
        if result.ok:
            logger.info(
                "Interval %s: TOM=%.8f  σ=%.2f s  n=%s  rms=%.5g%s",
                idx,
                result.t_ext,
                sigma_s,
                result.n_points,
                result.rms,
                f"  ({result.warning})" if result.warning else "",
            )
        else:
            logger.error(
                "Interval %s: FAILED %s",
                idx,
                result.fail_reason,
            )
        if args.save_plots or args.show_plots:
            png = out_dir / f"interval_{idx:02d}_{method.lower()}.png"
            _plot_interval(
                idx,
                t,
                y,
                result,
                domain=args.domain,
                out_path=png if args.save_plots else None,
                show=args.show_plots,
            )

    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %s (%s row(s))", out_csv, len(rows))


if __name__ == "__main__":
    main()
