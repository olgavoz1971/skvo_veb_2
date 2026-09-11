#!/usr/bin/env python3
"""Sliding centred-parabola smooth on an unfolded light curve (spike).

Edit the CONFIG block below, or override from the CLI. Default step is
``WINDOW_WIDTH_D / 4`` unless ``--step`` is set explicitly.

Example::

    cd auxiliary/running_parabola_spike
    ../../.venv/bin/python scripts/run_running_parabola.py --show
    ../../.venv/bin/python scripts/run_running_parabola.py \\
        --out-dir data/runs/nsv807 --step 0.0001 --weights \\
        --demo-windows 0 50 100 --demo-tom 0 10 20 --save-plots
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
from lc_segments import (  # noqa: E402
    concatenate_parabola_tom,
    concatenate_smooth_extrema,
    split_index_ranges_by_min_gap,
)
from plot_running_parabola import plot_demo_windows, plot_overview, plot_tom_demo_windows  # noqa: E402
from running_parabola import (  # noqa: E402
    RunningParabolaConfig,
    SmoothedPoint,
    export_smoothed_ascii,
    smooth_running_parabola,
)
from parabola_tom import (  # noqa: E402
    ParabolaTomConfig,
    ParabolaTomResult,
    export_parabola_tom_ascii,
    fit_parabola_tom,
)
from smooth_extrema import (  # noqa: E402
    SmoothExtremaResult,
    export_rough_tom_intervals_ascii,
    find_smooth_extrema,
)

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
MIN_GAP_D: float | None = None  # None -> do not split
OUT_DIR = _SPIKE / "data" / "runs"
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


def _lc_stem(lc_path: Path) -> str:
    """Return the light-curve file base name without directories or extension.

    Args:
        lc_path (pathlib.Path): Input light-curve path.

    Returns:
        str: Stem used as the output-file prefix.
    """
    stem = lc_path.stem
    if not stem:
        raise ValueError("light-curve path has an empty base name")
    return stem


def _prepare_out_dir(out_dir: Path) -> Path:
    """Create the output directory if needed and return its resolved path.

    Args:
        out_dir (pathlib.Path): Requested output directory.

    Returns:
        pathlib.Path: Absolute directory path.
    """
    resolved = out_dir.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _output_path(out_dir: Path, lc_stem: str, suffix: str) -> Path:
    """Build ``{stem}_{suffix}`` inside ``out_dir``.

    Args:
        out_dir (pathlib.Path): Output directory.
        lc_stem (str): Light-curve base name.
        suffix (str): Product suffix including extension (e.g. ``parabola_tom.dat``).

    Returns:
        pathlib.Path: Full output path.
    """
    return out_dir / f"{lc_stem}_{suffix}"


def _crop_sorted_series(
    jd: np.ndarray,
    phot: np.ndarray,
    phot_err: np.ndarray,
    *,
    t_min: float | None,
    t_max: float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Time-sort and optionally crop a light curve.

    Args:
        jd (numpy.ndarray): Observation times (absolute JD).
        phot (numpy.ndarray): Photometry in the working domain.
        phot_err (numpy.ndarray): Per-point uncertainties.
        t_min (float | None): Optional crop lower bound (JD).
        t_max (float | None): Optional crop upper bound (JD).

    Returns:
        tuple: Sorted cropped ``(jd, phot, phot_err)``.

    Raises:
        ValueError: If the crop is empty or inverted.
    """
    order = np.argsort(np.asarray(jd, dtype=float), kind="mergesort")
    t = np.asarray(jd, dtype=float)[order]
    y = np.asarray(phot, dtype=float)[order]
    e = np.asarray(phot_err, dtype=float)[order]
    lo = float(t_min) if t_min is not None else float(np.min(t))
    hi = float(t_max) if t_max is not None else float(np.max(t))
    if lo > hi:
        raise ValueError(f"invalid crop: t_min={lo} > t_max={hi}")
    in_crop = (t >= lo) & (t <= hi)
    t = t[in_crop]
    y = y[in_crop]
    e = e[in_crop]
    if t.size == 0:
        raise ValueError(f"no LC points in crop [{lo}, {hi}]")
    return t, y, e


def _process_independent_segments(
    jd: np.ndarray,
    phot: np.ndarray,
    phot_err: np.ndarray,
    *,
    cfg: RunningParabolaConfig,
    tom_cfg: ParabolaTomConfig,
    working_domain: str,
    extremum_kind: str,
    min_peak_distance_d: float,
    min_gap_d: float | None,
) -> tuple[list[SmoothedPoint], list[int], SmoothExtremaResult, ParabolaTomResult]:
    """Run smooth, extrema, and ToM independently on each gap-split segment.

    Args:
        jd (numpy.ndarray): Time-sorted cropped observation times.
        phot (numpy.ndarray): Cropped photometry.
        phot_err (numpy.ndarray): Cropped uncertainties.
        cfg (RunningParabolaConfig): Smoothing settings.
        tom_cfg (ParabolaTomConfig): Parabola ToM settings.
        working_domain (str): ``mag`` or ``flux``.
        extremum_kind (str): ``min`` or ``max``.
        min_peak_distance_d (float): Minimum extremum separation on the smooth.
        min_gap_d (float | None): Gap threshold in days, or ``None`` for one segment.

    Returns:
        tuple: Concatenated smoothed points, per-segment smooth lengths, merged
            extrema, merged parabola ToM.

    Raises:
        ValueError: If every segment fails to smooth.
    """
    ranges = split_index_ranges_by_min_gap(jd, min_gap_d)
    all_points: list[SmoothedPoint] = []
    segment_n_points: list[int] = []
    extrema_parts: list[SmoothExtremaResult] = []
    tom_parts: list[ParabolaTomResult] = []
    index_offsets: list[int] = []
    n_seg = len(ranges)
    n_skipped = 0
    for i, (lo, hi) in enumerate(ranges, start=1):
        jd_s = jd[lo:hi]
        phot_s = phot[lo:hi]
        err_s = phot_err[lo:hi]
        logger.info(
            "Segment %s/%s: %s points, JD %.6f .. %.6f",
            i,
            n_seg,
            jd_s.size,
            float(jd_s[0]),
            float(jd_s[-1]),
        )
        try:
            points_s = smooth_running_parabola(jd_s, phot_s, err_s, cfg=cfg)
        except ValueError as exc:
            n_skipped += 1
            logger.warning(
                "Skipping segment %s/%s (JD %.6f-%.6f, %s points): %s",
                i,
                n_seg,
                float(jd_s[0]),
                float(jd_s[-1]),
                jd_s.size,
                exc,
            )
            continue
        index_offsets.append(len(all_points))
        all_points.extend(points_s)
        segment_n_points.append(len(points_s))
        extrema_s = find_smooth_extrema(
            points_s,
            working_domain=working_domain,
            extremum_kind=extremum_kind,
            min_distance_d=min_peak_distance_d,
            step_d=cfg.step_d,
        )
        extrema_parts.append(extrema_s)
        tom_parts.append(
            fit_parabola_tom(
                jd_s,
                phot_s,
                err_s,
                extrema_s,
                working_domain=working_domain,
                cfg=tom_cfg,
            )
        )
    if not all_points:
        raise ValueError(
            f"all {n_seg} segment(s) failed to smooth "
            f"(width={cfg.window_width_d}, step={cfg.step_d})"
        )
    logger.info(
        "Kept %s/%s segment(s) (%s skipped)",
        n_seg - n_skipped,
        n_seg,
        n_skipped,
    )
    extrema = concatenate_smooth_extrema(extrema_parts, index_offsets=index_offsets)
    tom = concatenate_parabola_tom(tom_parts)
    return all_points, segment_n_points, extrema, tom


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
        "--min-gap",
        type=float,
        default=MIN_GAP_D,
        help=(
            "Split into independent segments where consecutive points are "
            "separated by more than this many days (default: do not split)"
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUT_DIR,
        help="Directory for all ASCII and plot products",
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
        "--interval-delta-d",
        type=float,
        default=INTERVAL_DELTA_D,
        help="Half-width (days) for rough ToM interval export: [tom-d, tom+d]",
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
    lc_stem = _lc_stem(lc_path)
    out_dir = _prepare_out_dir(args.out_dir)
    path_smoothed = _output_path(out_dir, lc_stem, "smoothed.dat")
    path_tom = _output_path(out_dir, lc_stem, "parabola_tom.dat")
    path_intervals = _output_path(out_dir, lc_stem, "rough_tom_intervals.dat")
    path_overview = _output_path(out_dir, lc_stem, "overview.png")
    path_windows = _output_path(out_dir, lc_stem, "windows.png")
    path_tom_windows = _output_path(out_dir, lc_stem, "tom_windows.png")
    logger.info("Writing products to %s (prefix %s)", out_dir, lc_stem)

    df, _meta = load_full_lightcurve(lc_path, working_domain=str(args.domain))
    jd_raw = df["jd"].to_numpy(dtype=float)
    phot_raw = df["phot"].to_numpy(dtype=float)
    if "phot_err" in df.columns:
        phot_err_raw = df["phot_err"].to_numpy(dtype=float)
    else:
        phot_err_raw = np.full_like(jd_raw, np.nan)

    jd_c, phot_c, err_c = _crop_sorted_series(
        jd_raw,
        phot_raw,
        phot_err_raw,
        t_min=args.t_min,
        t_max=args.t_max,
    )
    tom_cfg = ParabolaTomConfig(
        fit_half_width_d=fit_half_width_d,
        min_points=int(args.min_points),
        use_weights=bool(args.weights),
        extremum_kind=extremum_kind,
    )
    points, segment_n_points, extrema, tom = _process_independent_segments(
        jd_c,
        phot_c,
        err_c,
        cfg=cfg,
        tom_cfg=tom_cfg,
        working_domain=str(args.domain),
        extremum_kind=extremum_kind,
        min_peak_distance_d=float(args.min_peak_distance),
        min_gap_d=args.min_gap,
    )
    n_segments = len(segment_n_points)
    export_smoothed_ascii(
        path_smoothed,
        points,
        source_lc=str(lc_path.name),
        cfg=cfg,
        working_domain=str(args.domain),
        min_gap_d=args.min_gap,
        n_segments=n_segments,
    )

    if extrema.median_interval_d is not None:
        logger.info(
            "Rough period (median %s spacing): %.6f d",
            extremum_kind,
            extrema.median_interval_d,
        )
    if extrema.n_extrema > 0:
        export_rough_tom_intervals_ascii(
            path_intervals,
            extrema,
            delta_time_d=interval_delta_d,
            source_lc=str(lc_path.name),
            min_gap_d=args.min_gap,
            n_segments=n_segments,
        )

    export_parabola_tom_ascii(
        path_tom,
        tom,
        source_lc=str(lc_path.name),
        working_domain=str(args.domain),
        cfg=tom_cfg,
        min_gap_d=args.min_gap,
        n_segments=n_segments,
    )
    if tom.n_ok >= 2:
        tom_jd = np.array([h.tom_jd for h in tom.hits], dtype=float)
        logger.info(
            "Rough period (median parabola ToM spacing): %.6f d",
            float(np.median(np.diff(np.sort(tom_jd)))),
        )

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
            segment_n_points=segment_n_points,
            save_path=path_overview if args.save_plots else None,
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
            save_path=path_windows if args.save_plots else None,
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
            save_path=path_tom_windows if args.save_plots else None,
            show=args.show,
        )


if __name__ == "__main__":
    main()
