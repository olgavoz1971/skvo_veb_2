#!/usr/bin/env python3
"""CLI: Step 1 O-C from lc_approx spike TOM CSVs (with cycle corrections).

Example (NSV 807 sector 97 prim, WSAP)::

    cd auxiliary/lc_approx_spike/oc
    ../../../.venv/bin/python run_oc_step1.py \\
        --tom-csv ../data/runs/NSV_807_sector_97_flatten_NSV_807_sector_97_prim/approx_batch.csv \\
        --method WSAP \\
        --t0 57711.3539 --p0 0.3389614 --time-scale mjd \\
        --save-plot --show
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

_OC_DIR = Path(__file__).resolve().parent
_SPIKE = _OC_DIR.parent
if str(_SPIKE) not in sys.path:
    sys.path.insert(0, str(_SPIKE))
if str(_OC_DIR) not in sys.path:
    sys.path.insert(0, str(_OC_DIR))

from paths import ensure_import_paths  # noqa: E402

ensure_import_paths()

import matplotlib.pyplot as plt  # noqa: E402

from oc_step1 import (  # noqa: E402
    compute_step1_oc,
    export_step1_oc_csv,
    export_step1_oc_dat,
    parse_cycle_shifts,
    plot_step1_oc,
    to_absolute_jd,
)
from tom_io import KNOWN_METHODS, load_toms_from_approx_csv  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    """CLI entry point for spike Step 1 O-C."""
    parser = argparse.ArgumentParser(
        description=(
            "Spike Step 1 O-C from approx_batch / approx_compare CSV "
            "(cycle corrections + σ error bars)"
        )
    )
    parser.add_argument(
        "--tom-csv",
        type=Path,
        required=True,
        help="approx_batch.csv or approx_compare.csv from run_batch_approx",
    )
    parser.add_argument(
        "--method",
        default="WSAP",
        help=f"TOM method: {sorted(KNOWN_METHODS)} (default WSAP)",
    )
    parser.add_argument(
        "--t0",
        type=float,
        required=True,
        help="Trial epoch T0 (units given by --time-scale)",
    )
    parser.add_argument(
        "--p0",
        type=float,
        required=True,
        help="Trial period P0 in days",
    )
    parser.add_argument(
        "--time-scale",
        choices=("jd", "mjd"),
        default="mjd",
        help="Scale for --t0 and --cycle-shift times (default mjd)",
    )
    parser.add_argument(
        "--cycle-shift",
        action="append",
        default=[],
        metavar="AT:DELTA_E",
        help=(
            "Cycle correction: at_time:delta_E in --time-scale units "
            "(repeatable; applied for jd_ext >= at_time, same as auxiliary/oc)"
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: same folder as --tom-csv)",
    )
    parser.add_argument(
        "--out-csv",
        type=str,
        default=None,
        help=(
            "O-C CSV path or filename (default: oc_<method>.csv under --out-dir). "
            "The xmgrace .dat is written beside it as <csv_stem>_<method>.dat"
        ),
    )
    parser.add_argument(
        "--out-dat",
        type=str,
        default=None,
        help=(
            "Optional xmgrace .dat path override; default is "
            "<out-csv stem>_<method>.dat in the same folder as the CSV"
        ),
    )
    parser.add_argument(
        "--out-fig",
        type=str,
        default=None,
        help="Figure filename (default: oc_<method>.png)",
    )
    parser.add_argument(
        "--save-plot",
        action="store_true",
        help="Write the O-C PNG",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Interactive plt.show() for the O-C figure",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    method = str(args.method).upper()
    if method not in KNOWN_METHODS:
        parser.error(f"--method must be one of {sorted(KNOWN_METHODS)}")

    tom_csv = args.tom_csv.resolve()
    out_dir = (
        args.out_dir.resolve() if args.out_dir is not None else tom_csv.parent
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    method_tag = method.lower()
    if args.out_csv is not None:
        out_csv = Path(args.out_csv)
        if not out_csv.is_absolute():
            out_csv = out_dir / out_csv
    else:
        out_csv = out_dir / f"oc_{method_tag}.csv"
    out_csv = out_csv.resolve()
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    if args.out_dat is not None:
        out_dat = Path(args.out_dat)
        if not out_dat.is_absolute():
            out_dat = out_csv.parent / out_dat
        out_dat = out_dat.resolve()
    else:
        out_dat = out_csv.with_name(f"{out_csv.stem}_{method_tag}.dat")

    out_fig = out_dir / (args.out_fig if args.out_fig else f"oc_{method_tag}.png")

    t0_jd = to_absolute_jd(float(args.t0), scale=args.time_scale)
    p0 = float(args.p0)
    if p0 <= 0.0:
        parser.error("--p0 must be positive")
    cycle_shifts = parse_cycle_shifts(args.cycle_shift, scale=args.time_scale)

    records = load_toms_from_approx_csv(tom_csv, method)
    E, OC, jd_ext, sigma_jd, intervals = compute_step1_oc(
        records,
        t0_jd=t0_jd,
        p0=p0,
        cycle_shifts=cycle_shifts or None,
    )
    export_step1_oc_csv(
        out_csv,
        E=E,
        OC=OC,
        jd_ext=jd_ext,
        sigma_jd=sigma_jd,
        intervals=intervals,
        method=method,
        t0_jd=t0_jd,
        p0=p0,
        cycle_shifts=cycle_shifts,
    )
    export_step1_oc_dat(
        out_dat,
        E=E,
        OC=OC,
        sigma_jd=sigma_jd,
        method=method,
        t0_jd=t0_jd,
        p0=p0,
        cycle_shifts=cycle_shifts,
    )

    rms = float(np.sqrt(np.mean(OC**2)))
    logger.info(
        "O-C range [%.6f, %.6f] d; RMS=%.6f d (%.1f s); N=%s; shifts=%s",
        float(np.min(OC)),
        float(np.max(OC)),
        rms,
        rms * 86400.0,
        len(E),
        cycle_shifts,
    )

    if args.save_plot or args.show:
        fig = plot_step1_oc(
            E,
            OC,
            jd_ext,
            sigma_jd,
            t0_jd=t0_jd,
            p0=p0,
            method=method,
            intervals=intervals,
            show=args.show,
            save_path=out_fig if args.save_plot else None,
        )
        plt.close(fig)
    else:
        logger.info("Skipped plot (pass --save-plot and/or --show)")


if __name__ == "__main__":
    main()
