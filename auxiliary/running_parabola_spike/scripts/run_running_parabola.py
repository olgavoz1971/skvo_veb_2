#!/usr/bin/env python3
"""Sliding centred-parabola smooth on an unfolded light curve (spike).

Edit the CONFIG block below, or override from the CLI. Default step is
``WINDOW_WIDTH_D / 4`` unless ``--step`` is set explicitly.

Example::

    cd auxiliary/running_parabola_spike
    ../../.venv/bin/python scripts/run_running_parabola.py --show
    ../../.venv/bin/python scripts/run_running_parabola.py \\
        --step 0.0001 --weights --demo-windows 0 50 100 --demo-tom 0 10 20 --save-plots
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

_SPIKE = Path(__file__).resolve().parents[1]
if str(_SPIKE) not in sys.path:
    sys.path.insert(0, str(_SPIKE))

from paths import DATA_DIR, ensure_import_paths  # noqa: E402

ensure_import_paths()

from io_spike import load_full_lightcurve  # noqa: E402
from plot_running_parabola import plot_demo_windows, plot_overview, plot_tom_demo_windows  # noqa: E402
from running_parabola import (  # noqa: E402
    RunningParabolaConfig,
    export_smoothed_ascii,
    smooth_running_parabola,
)
from parabola_tom import (  # noqa: E402
    ParabolaTomConfig,
    export_parabola_tom_ascii,
    fit_parabola_tom,
)
from smooth_extrema import export_rough_tom_intervals_ascii, find_smooth_extrema  # noqa: E402

logger = logging.getLogger(__name__)

# --- CONFIG (defaults; CLI overrides) ---------------------------------------
LC_PATH = DATA_DIR / "NSV_807_sector_97_flatten.vot"
WORKING_DOMAIN = "flux"  # mag | flux
EXTREMUM = "min"  # min | max in working domain
WINDOW_WIDTH_D = 0.05
STEP_D: float | None = None  # None -> WINDOW_WIDTH_D / 4
USE_WEIGHTS = False
MIN_POINTS = 5
T_MIN: float | None = None
T_MAX: float | None = None
OUT_ASCII = _SPIKE / "data" / "runs" / "smoothed_running_parabola.dat"
OUT_TOM = _SPIKE / "data" / "runs" / "parabola_tom.dat"
OUT_ROUGH_INTERVALS = _SPIKE / "data" / "runs" / "rough_tom_intervals.dat"
SAVE_PLOTS = False
SHOW_PLOTS = False
DEMO_WINDOW_INDICES: list[int] = []  # indices into smoothed output, e.g. [0, 50, 100]
DEMO_TOM_INDICES: list[int] = []  # indices into tom.hits, e.g. [0, 10, 20]
MIN_PEAK_DISTANCE_D = 0.3  # minimum separation between detected minima (days)
INTERVAL_DELTA_D: float | None = None  # None -> WINDOW_WIDTH_D / 2
FIT_HALF_WIDTH_D: float | None = None  # None -> WINDOW_WIDTH_D / 2
# ---------------------------------------------------------------------------


def _resolve_step(window_width_d: float, step_arg: float | None) -> float:
    """Return explicit step or default ``window / 4``.

    Args:
        window_width_d (float): Window width in days.
        step_arg (float | None): CLI step override, if any.

    Returns:
        float: Step in days.
    """
    if step_arg is not None:
        return float(step_arg)
    return float(window_width_d) / 4.0


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Running-parabola smooth on unfolded calendar time"
    )
    parser.add_argument("--lc", type=Path, default=LC_PATH, help="Light-curve file")
    parser.add_argument(
        "--domain",
        choices=("mag", "flux"),
        default=WORKING_DOMAIN,
        help="Working photometry domain",
    )
    parser.add_argument(
        "--extremum",
        choices=("min", "max"),
        default=EXTREMUM,
        help="Search for minima or maxima in the working domain",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=WINDOW_WIDTH_D,
        help="Full window width in days",
    )
    parser.add_argument(
        "--step",
        type=float,
        default=None,
        help="Step between centres in days (default: window/4)",
    )
    parser.add_argument(
        "--weights",
        action="store_true",
        default=USE_WEIGHTS,
        help="Weight fits by 1/phot_err^2 where errors are finite",
    )
    parser.add_argument(
        "--no-weights",
        action="store_false",
        dest="weights",
        help="Disable error weighting",
    )
    parser.add_argument(
        "--min-points",
        type=int,
        default=MIN_POINTS,
        help="Minimum in-window points per fit",
    )
    parser.add_argument("--t-min", type=float, default=T_MIN, help="Crop start JD")
    parser.add_argument("--t-max", type=float, default=T_MAX, help="Crop end JD")
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_ASCII,
        help="Output ASCII path",
    )
    parser.add_argument("--save-plots", action="store_true", default=SAVE_PLOTS)
    parser.add_argument("--show", action="store_true", default=SHOW_PLOTS)
    parser.add_argument(
        "--demo-windows",
        type=int,
        nargs="*",
        default=DEMO_WINDOW_INDICES,
        metavar="IDX",
        help="Smoothed-point indices for parabola demo panels",
    )
    parser.add_argument(
        "--demo-tom",
        type=int,
        nargs="*",
        default=DEMO_TOM_INDICES,
        metavar="IDX",
        help="Parabola ToM hit indices for diagnostic fit panels",
    )
    parser.add_argument(
        "--min-peak-distance",
        type=float,
        default=MIN_PEAK_DISTANCE_D,
        help="Minimum separation between detected extrema on the smooth (days)",
    )
    parser.add_argument(
        "--fit-half-width",
        type=float,
        default=FIT_HALF_WIDTH_D,
        help="Parabola ToM fit half-width in days (default: window/2)",
    )
    parser.add_argument(
        "--out-tom",
        type=Path,
        default=OUT_TOM,
        help="Output ASCII path for parabola-refined ToM",
    )
    parser.add_argument(
        "--interval-delta-d",
        type=float,
        default=INTERVAL_DELTA_D,
        help="Half-width (days) for rough ToM interval export: [tom-d, tom+d]",
    )
    parser.add_argument(
        "--out-intervals",
        type=Path,
        default=OUT_ROUGH_INTERVALS,
        help="Output interval .dat path from rough smooth extrema",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    step_d = _resolve_step(float(args.window), args.step)
    fit_half_width_d = (
        float(args.fit_half_width)
        if args.fit_half_width is not None
        else float(args.window) / 2.0
    )
    interval_delta_d = (
        float(args.interval_delta_d)
        if args.interval_delta_d is not None
        else float(args.window) / 2.0
    )
    extremum_kind = str(args.extremum)
    cfg = RunningParabolaConfig(
        window_width_d=float(args.window),
        step_d=step_d,
        min_points=int(args.min_points),
        use_weights=bool(args.weights),
    )

    lc_path = args.lc.resolve()
    df, _meta = load_full_lightcurve(lc_path, working_domain=str(args.domain))
    jd = df["jd"].to_numpy(dtype=float)
    phot = df["phot"].to_numpy(dtype=float)
    if "phot_err" in df.columns:
        phot_err = df["phot_err"].to_numpy(dtype=float)
    else:
        phot_err = np.full_like(jd, np.nan)

    points = smooth_running_parabola(
        jd,
        phot,
        phot_err,
        cfg=cfg,
        t_min=args.t_min,
        t_max=args.t_max,
    )
    export_smoothed_ascii(
        args.out,
        points,
        source_lc=str(lc_path.name),
        cfg=cfg,
        working_domain=str(args.domain),
    )

    extrema = find_smooth_extrema(
        points,
        working_domain=str(args.domain),
        extremum_kind=extremum_kind,
        min_distance_d=float(args.min_peak_distance),
        step_d=step_d,
    )
    if extrema.median_interval_d is not None:
        logger.info(
            "Rough period (median %s spacing): %.6f d",
            extremum_kind,
            extrema.median_interval_d,
        )
    if extrema.n_extrema > 0:
        export_rough_tom_intervals_ascii(
            args.out_intervals,
            extrema,
            delta_time_d=interval_delta_d,
            source_lc=str(lc_path.name),
        )

    tom_cfg = ParabolaTomConfig(
        fit_half_width_d=fit_half_width_d,
        min_points=int(args.min_points),
        use_weights=bool(args.weights),
        extremum_kind=extremum_kind,
    )
    tom = fit_parabola_tom(
        jd,
        phot,
        phot_err,
        extrema,
        working_domain=str(args.domain),
        cfg=tom_cfg,
    )
    export_parabola_tom_ascii(
        args.out_tom,
        tom,
        source_lc=str(lc_path.name),
        working_domain=str(args.domain),
        cfg=tom_cfg,
    )
    if tom.n_ok >= 2:
        tom_jd = np.array([h.tom_jd for h in tom.hits], dtype=float)
        logger.info(
            "Rough period (median parabola ToM spacing): %.6f d",
            float(np.median(np.diff(np.sort(tom_jd)))),
        )

    crop_lo = float(args.t_min) if args.t_min is not None else float(np.min(jd))
    crop_hi = float(args.t_max) if args.t_max is not None else float(np.max(jd))
    crop = (jd >= crop_lo) & (jd <= crop_hi)
    jd_c = jd[crop]
    phot_c = phot[crop]
    err_c = phot_err[crop]

    out_dir = args.out.resolve().parent
    if args.save_plots or args.show:
        plot_overview(
            jd_c,
            phot_c,
            points,
            working_domain=str(args.domain),
            cfg=cfg,
            extrema=extrema,
            tom=tom,
            extremum_kind=extremum_kind,
            save_path=out_dir / "running_parabola_overview.png" if args.save_plots else None,
            show=args.show,
        )
    if args.demo_windows and (args.save_plots or args.show):
        plot_demo_windows(
            jd_c,
            phot_c,
            err_c,
            list(args.demo_windows),
            points,
            working_domain=str(args.domain),
            cfg=cfg,
            save_path=out_dir / "running_parabola_windows.png" if args.save_plots else None,
            show=args.show,
        )
    if args.demo_tom and (args.save_plots or args.show):
        plot_tom_demo_windows(
            jd_c,
            phot_c,
            err_c,
            list(args.demo_tom),
            tom,
            working_domain=str(args.domain),
            tom_cfg=tom_cfg,
            save_path=out_dir / "parabola_tom_windows.png" if args.save_plots else None,
            show=args.show,
        )


if __name__ == "__main__":
    main()
