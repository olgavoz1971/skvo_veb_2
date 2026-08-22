#!/usr/bin/env python3
"""Batch spike: fit AP / WSAP / WSL (optional A) on every interval and compare.

MAVKA-style workflow: same windows, several piecewise families, then pick a
preferred method per interval (default: smallest formal σ(TOM) among successful
fits).

Example::

    cd auxiliary/lc_approx_spike
    ../../.venv/bin/python scripts/run_batch_approx.py \\
        --lc data/NSV_807_sector_97_flatten.vot \\
        --intervals data/NSV_807_sector_97_prim.dat \\
        --domain flux --save-plots --plot-max 5
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import Counter
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
from plot_style import (  # noqa: E402
    FIGSIZE_INTERVAL,
    FONT_SIZE,
    apply_interval_plot_style,
)
from vendor.ila_models import METHODS, ApproxFitResult, fit_interval, model_curve  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_METHODS = ("AP", "WSAP", "WSL")

LONG_FIELDS = [
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
    "eclipse_duration_d",
    "sigma_duration_d",
    "rms",
    "warning",
    "fail_reason",
    "is_best",
]

METHOD_COLOURS = {
    "AP": "tab:green",
    "WSAP": "tab:blue",
    "WSL": "tab:orange",
    "A": "tab:purple",
}

PIECE_COLOURS = {
    "left": "#6a3d9a",
    "core": "#33a02c",
    "right": "#ff7f00",
}


def _parse_methods(raw: str) -> list[str]:
    """Parse a comma-separated method list.

    Args:
        raw (str): e.g. ``AP,WSAP,WSL``.

    Returns:
        list[str]: Upper-cased method ids.

    Raises:
        ValueError: If any method is unknown.
    """
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError("methods list is empty")
    unknown = [p for p in parts if p not in METHODS]
    if unknown:
        raise ValueError(f"unknown method(s) {unknown}; allowed {sorted(METHODS)}")
    return parts


def _sigma_s(result: ApproxFitResult) -> float:
    """Formal TOM uncertainty in seconds, or NaN.

    Args:
        result (ApproxFitResult): Fit outcome.

    Returns:
        float: ``sigma_t_ext`` in seconds.
    """
    if not np.isfinite(result.sigma_t_ext):
        return float("nan")
    return float(result.sigma_t_ext) * 86400.0


def _pick_best(
    results: dict[str, ApproxFitResult],
) -> str | None:
    """Choose the preferred method for one interval (min σ among ok fits).

    Args:
        results (dict[str, ApproxFitResult]): Method → fit.

    Returns:
        str | None: Winning method id, or None if none succeeded.
    """
    candidates: list[tuple[float, str]] = []
    for method, result in results.items():
        if not result.ok or not np.isfinite(result.sigma_t_ext):
            continue
        # Prefer finite positive σ; treat zero as tiny.
        sigma = max(float(result.sigma_t_ext), 1e-20)
        candidates.append((sigma, method))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _plot_piecewise_model(
    ax,
    method: str,
    result: ApproxFitResult,
    t_min: float,
    t_max: float,
) -> None:
    """Draw the fitted model with left / core / right pieces coloured.

    Args:
        ax: Matplotlib axes.
        method (str): Approximation method.
        result (ApproxFitResult): Successful fit with parameters.
        t_min (float): Plot time start.
        t_max (float): Plot time end.
    """
    if not result.ok or result.params.size == 0:
        return
    colour = METHOD_COLOURS.get(method, "tab:green")
    t_line = np.linspace(t_min, t_max, 500)
    y_line = model_curve(method, result.params, t_line)
    c4 = float(result.c4) if np.isfinite(result.c4) else float("nan")
    c5 = float(result.c5) if np.isfinite(result.c5) else float("nan")

    if method == "A" or not (np.isfinite(c4) and np.isfinite(c5)):
        ax.plot(t_line, y_line, color=colour, lw=2, label=method)
        return

    left = t_line < c4
    core = (t_line >= c4) & (t_line <= c5)
    right = t_line > c5
    if np.any(left):
        ax.plot(
            t_line[left],
            y_line[left],
            color=PIECE_COLOURS["left"],
            lw=2,
            label=f"{method} left",
        )
    if np.any(core):
        ax.plot(
            t_line[core],
            y_line[core],
            color=PIECE_COLOURS["core"],
            lw=2.5,
            label=f"{method} core",
        )
    if np.any(right):
        ax.plot(
            t_line[right],
            y_line[right],
            color=PIECE_COLOURS["right"],
            lw=2,
            label=f"{method} right",
        )
    ax.axvline(c4, color="maroon", lw=1, alpha=0.8)
    ax.axvline(c5, color="maroon", lw=1, alpha=0.8)
    if np.isfinite(result.t_ext):
        ax.axvline(result.t_ext, color="tab:red", ls="--", lw=1.2, label="TOM")
        if np.isfinite(result.sigma_t_ext):
            ax.axvspan(
                result.t_ext - result.sigma_t_ext,
                result.t_ext + result.sigma_t_ext,
                color="tab:red",
                alpha=0.12,
            )


def _plot_interval_panel(
    idx: int,
    t: np.ndarray,
    y: np.ndarray,
    results: dict[str, ApproxFitResult],
    methods: list[str],
    *,
    domain: str,
    best: str | None,
    t_start: float,
    t_end: float,
    out_path: Path | None,
    show: bool,
) -> None:
    """One figure with a subplot per method for a single interval.

    Uses the same canvas and font sizes as ``template_timing`` Step-2 interval
    panels (``FIGSIZE_INTERVAL``, ``FONT_SIZE``, ``apply_interval_plot_style``).

    Args:
        idx (int): Interval index.
        t (numpy.ndarray): Times.
        y (numpy.ndarray): Photometry.
        results (dict[str, ApproxFitResult]): Fits keyed by method.
        methods (list[str]): Method order.
        domain (str): ``flux`` or ``mag``.
        best (str | None): Preferred method for this interval.
        t_start (float): Interval start JD (for the figure caption).
        t_end (float): Interval end JD (for the figure caption).
        out_path (Path | None): PNG path, or None to skip save.
        show (bool): Whether to call ``plt.show()``.
    """
    apply_interval_plot_style()
    n = len(methods)
    fig, axes = plt.subplots(1, n, figsize=FIGSIZE_INTERVAL, sharey=True)
    if n == 1:
        axes = [axes]
    t_min = float(np.min(t))
    t_max = float(np.max(t))
    for ax, method in zip(axes, methods):
        result = results[method]
        ax.scatter(t, y, s=14, c="k", alpha=0.65, zorder=3)
        _plot_piecewise_model(ax, method, result, t_min, t_max)
        if domain == "mag":
            ax.invert_yaxis()
        ax.set_xlabel("JD")
        title = method
        if best == method:
            title += " ★"
        if result.ok:
            title += f"\nTOM={result.t_ext:.6f}  σ={_sigma_s(result):.1f}s"
        else:
            title += f"\nFAILED: {result.fail_reason}"
        if result.warning:
            title += f"\n{result.warning[:60]}"
        ax.set_title(title)
        ax.legend(loc="best")
    axes[0].set_ylabel(domain)
    fig.suptitle(
        f"Interval {idx}: [{t_start:.5f}, {t_end:.5f}]",
        fontsize=FONT_SIZE,
    )
    fig.tight_layout()
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=150)
        logger.info("Wrote %s", out_path)
    if show:
        # Block until the window is closed; then free the figure.
        plt.show(block=True)
    plt.close(fig)


def _row_from_result(
    idx: int,
    t_start: float,
    t_end: float,
    result: ApproxFitResult,
    *,
    is_best: bool,
) -> dict:
    """Build one long-format CSV row.

    Args:
        idx (int): Interval index.
        t_start (float): Window start JD.
        t_end (float): Window end JD.
        result (ApproxFitResult): Fit outcome.
        is_best (bool): Whether this method won the interval.

    Returns:
        dict: CSV row mapping.
    """
    return {
        "interval": idx,
        "t_start": t_start,
        "t_end": t_end,
        "n_points": result.n_points,
        "method": result.method,
        "ok": result.ok,
        "t_ext": result.t_ext if result.ok else "",
        "sigma_t_ext_s": _sigma_s(result) if result.ok else "",
        "y_ext": result.y_ext if np.isfinite(result.y_ext) else "",
        "sigma_y_ext": result.sigma_y_ext if np.isfinite(result.sigma_y_ext) else "",
        "c4": result.c4 if np.isfinite(result.c4) else "",
        "c5": result.c5 if np.isfinite(result.c5) else "",
        "eclipse_duration_d": (
            result.eclipse_duration if np.isfinite(result.eclipse_duration) else ""
        ),
        "sigma_duration_d": (
            result.sigma_duration if np.isfinite(result.sigma_duration) else ""
        ),
        "rms": result.rms if np.isfinite(result.rms) else "",
        "warning": result.warning or "",
        "fail_reason": result.fail_reason or "",
        "is_best": is_best,
    }


def _compare_row(
    idx: int,
    t_start: float,
    t_end: float,
    n_points: int,
    results: dict[str, ApproxFitResult],
    methods: list[str],
    best: str | None,
) -> dict:
    """Build one wide comparison row (one column group per method).

    Args:
        idx (int): Interval index.
        t_start (float): Window start.
        t_end (float): Window end.
        n_points (int): Points in the window.
        results (dict[str, ApproxFitResult]): Fits.
        methods (list[str]): Method order.
        best (str | None): Preferred method.

    Returns:
        dict: Wide CSV row.
    """
    row: dict = {
        "interval": idx,
        "t_start": t_start,
        "t_end": t_end,
        "n_points": n_points,
        "best_method": best or "",
    }
    for method in methods:
        result = results[method]
        prefix = method.lower()
        row[f"{prefix}_ok"] = result.ok
        row[f"{prefix}_t_ext"] = result.t_ext if result.ok else ""
        row[f"{prefix}_sigma_s"] = _sigma_s(result) if result.ok else ""
        row[f"{prefix}_rms"] = result.rms if np.isfinite(result.rms) else ""
        row[f"{prefix}_c4"] = result.c4 if np.isfinite(result.c4) else ""
        row[f"{prefix}_c5"] = result.c5 if np.isfinite(result.c5) else ""
        row[f"{prefix}_warning"] = result.warning or ""
        row[f"{prefix}_fail"] = result.fail_reason or ""
    if best and results[best].ok:
        row["best_t_ext"] = results[best].t_ext
        row["best_sigma_s"] = _sigma_s(results[best])
    else:
        row["best_t_ext"] = ""
        row["best_sigma_s"] = ""
    # Pairwise TOM differences in seconds (first method as reference when both ok).
    ref = methods[0]
    ref_r = results[ref]
    for method in methods[1:]:
        other = results[method]
        key = f"dt_{ref.lower()}_{method.lower()}_s"
        if ref_r.ok and other.ok:
            row[key] = (other.t_ext - ref_r.t_ext) * 86400.0
        else:
            row[key] = ""
    return row


def main() -> None:
    """CLI entry point for the multi-method batch."""
    parser = argparse.ArgumentParser(
        description="Batch AP/WSAP/WSL (optional A) on LC intervals and compare"
    )
    parser.add_argument(
        "--lc",
        type=Path,
        default=DATA_DIR / "NSV_807_sector_97_flatten.vot",
        help="Light curve (.vot / .dat / …)",
    )
    parser.add_argument(
        "--intervals",
        type=Path,
        default=DATA_DIR / "NSV_807_sector_97_prim.dat",
        help="Two-column interval file (absolute JD)",
    )
    parser.add_argument(
        "--domain",
        choices=("flux", "mag"),
        default="flux",
        help="Working photometry domain",
    )
    parser.add_argument(
        "--methods",
        default=",".join(DEFAULT_METHODS),
        help=f"Comma-separated subset of {sorted(METHODS)}",
    )
    parser.add_argument(
        "--max-intervals",
        type=int,
        default=0,
        help="Fit only the first N intervals (0 = all)",
    )
    parser.add_argument(
        "--min-points",
        type=int,
        default=8,
        help="Skip intervals with fewer points",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Directory for CSV / PNG outputs",
    )
    parser.add_argument(
        "--save-plots",
        action="store_true",
        help="Write multi-panel PNGs for intervals",
    )
    parser.add_argument(
        "--plot-max",
        type=int,
        default=0,
        help=(
            "Cap how many intervals are plotted for --save-plots / --show-plots "
            "(0 = all fitted intervals)"
        ),
    )
    parser.add_argument(
        "--show-plots",
        action="store_true",
        help="Interactive plt.show() after each plotted interval (blocks until closed)",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    methods = _parse_methods(args.methods)
    lc_path = args.lc.resolve()
    int_path = args.intervals.resolve()
    out_dir = (
        args.out_dir.resolve()
        if args.out_dir is not None
        else (_SPIKE / "data" / "runs" / f"{lc_path.stem}_{int_path.stem}")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    long_csv = out_dir / "approx_batch.csv"
    compare_csv = out_dir / "approx_compare.csv"

    df, _meta = load_full_lightcurve(lc_path, working_domain=args.domain)
    intervals = load_interval_pairs_jd(int_path)
    n_use = len(intervals) if int(args.max_intervals) <= 0 else min(
        int(args.max_intervals), len(intervals)
    )
    logger.info(
        "Batch methods=%s on first %s / %s interval(s) → %s",
        methods,
        n_use,
        len(intervals),
        out_dir,
    )

    long_rows: list[dict] = []
    compare_rows: list[dict] = []
    plots_written = 0
    n_ok_best = 0
    plot_cap = int(args.plot_max)
    # 0 means unlimited (same convention as --max-intervals).
    plot_limit = n_use if plot_cap <= 0 else plot_cap
    if args.show_plots or args.save_plots:
        logger.info(
            "Plotting up to %s interval(s) (save=%s show=%s)",
            plot_limit,
            args.save_plots,
            args.show_plots,
        )

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

        results: dict[str, ApproxFitResult] = {}
        for method in methods:
            results[method] = fit_interval(method, t, y)

        best = _pick_best(results)
        if best is not None:
            n_ok_best += 1
            logger.info(
                "Interval %s: best=%s  TOM=%.8f  σ=%.2f s  n=%s",
                idx,
                best,
                results[best].t_ext,
                _sigma_s(results[best]),
                t.size,
            )
        else:
            logger.error("Interval %s: no successful method", idx)

        for method in methods:
            long_rows.append(
                _row_from_result(
                    idx,
                    t_start,
                    t_end,
                    results[method],
                    is_best=(method == best),
                )
            )
        compare_rows.append(
            _compare_row(idx, t_start, t_end, int(t.size), results, methods, best)
        )

        if (args.save_plots or args.show_plots) and plots_written < plot_limit:
            png = (
                out_dir / f"interval_{idx:02d}_batch.png" if args.save_plots else None
            )
            logger.info(
                "Showing interval %s plot (%s / %s)%s",
                idx,
                plots_written + 1,
                plot_limit,
                f" → {png.name}" if png is not None else "",
            )
            _plot_interval_panel(
                idx,
                t,
                y,
                results,
                methods,
                domain=args.domain,
                best=best,
                t_start=t_start,
                t_end=t_end,
                out_path=png,
                show=args.show_plots,
            )
            plots_written += 1

    with long_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=LONG_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(long_rows)

    compare_fields = list(compare_rows[0].keys()) if compare_rows else [
        "interval",
        "t_start",
        "t_end",
        "n_points",
        "best_method",
        "best_t_ext",
        "best_sigma_s",
    ]
    with compare_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=compare_fields, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(compare_rows)

    best_counts = Counter(
        row["best_method"] for row in compare_rows if row.get("best_method")
    )
    logger.info("Wrote %s (%s row(s))", long_csv, len(long_rows))
    logger.info("Wrote %s (%s interval(s))", compare_csv, len(compare_rows))
    logger.info(
        "Intervals with a best method: %s / %s; counts=%s",
        n_ok_best,
        len(compare_rows),
        dict(best_counts),
    )


if __name__ == "__main__":
    main()
