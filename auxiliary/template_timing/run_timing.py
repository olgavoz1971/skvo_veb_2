"""Orchestrate Step 1 + Step 2 from a YAML manifest."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from manifest_config import (
    TIMING_METHODS,
    PieceConfig,
    load_manifest,
    overview_lc_segments,
    piece_fold_epoch,
    piece_fold_period,
    piece_lc_path,
)
from plot_style import apply_plot_style
from plot_overview import overview_time_span, plot_lc_with_maxima
from template_build import build_piece_template, plot_template_artifacts
from template_reuse import copy_piece_template, load_existing_template_dir
from template_fit import TemplateCurve
from template_fit_pipeline import (
    fit_mask_for_template,
    fit_piece_intervals,
    fit_result_from_summary_row,
    load_template_bundle,
    method_timing_record,
)
from timing_errors import sigma_t_max_rms_slope

logger = logging.getLogger(__name__)

TIMING_CSV_FIELDS = [
    "piece_id",
    "interval",
    "t_max",
    "sigma_t_max",
    "timing_method",
    "rms",
    "delta_t",
    "scale",
    "t_start",
    "t_end",
    "t_anchor",
    "n_points",
    "n_outliers_rejected_scale",
]

TIMING_CSV_FIELDS_OFFICIAL = [
    "piece_id",
    "interval",
    "t_max",
    "sigma_t_max",
    "timing_method",
    "rms_official",
    "delta_t_official",
    "scale_official",
    "t_start",
    "t_end",
    "t_anchor",
    "n_points",
    "n_outliers_rejected_scale",
]


def _attach_timing_errors(
    rows: list[dict],
    *,
    curve: TemplateCurve,
    error_model: str,
    timing_method: str,
) -> None:
    """Add ``sigma_t_max`` and ``sigma_t_max_<method>`` columns in place."""
    methods = sorted(TIMING_METHODS)
    if error_model == "none":
        for row in rows:
            for method in methods:
                row[f"sigma_t_max_{method}"] = float("nan")
            row["sigma_t_max"] = float("nan")
        return
    if error_model != "rms_slope":
        raise ValueError(f"unsupported error_model: {error_model}")

    for row in rows:
        for method in methods:
            fit = fit_result_from_summary_row(row, method)
            row[f"sigma_t_max_{method}"] = sigma_t_max_rms_slope(curve, fit)
        row["sigma_t_max"] = row[f"sigma_t_max_{timing_method}"]


def _write_timing_csv(path: Path, records: list[dict], *, fieldnames: list[str]) -> None:
    """Write one merged timing table."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def _write_all_method_timing_csvs(
    run_dir: Path,
    rows: list[dict],
    *,
    official_method: str,
) -> Path:
    """Write ``timing.csv`` (official) and ``timing_<method>.csv`` for every method."""
    official_path = run_dir / "timing.csv"
    official_records = []
    for row in rows:
        official = {
            **method_timing_record(row, official_method),
            "timing_method": official_method,
            "rms_official": row["rms_official"],
            "delta_t_official": row["delta_t_official"],
            "scale_official": row["scale_official"],
        }
        official_records.append(official)

    _write_timing_csv(official_path, official_records, fieldnames=TIMING_CSV_FIELDS_OFFICIAL)
    logger.info("Wrote %s (%s maxima, method=%s)", official_path, len(official_records), official_method)

    for method in sorted(TIMING_METHODS):
        path = run_dir / f"timing_{method}.csv"
        records = [method_timing_record(row, method) for row in rows]
        _write_timing_csv(path, records, fieldnames=TIMING_CSV_FIELDS)
        logger.info("Wrote %s (%s maxima)", path, len(records))

    return official_path


def _plot_reused_template(piece_dir: Path, piece: PieceConfig, *, show_plots: bool) -> None:
    """Draw a reused template with the fit window taken from the current manifest.

    Args:
        piece_dir (Path): Output directory holding the copied template artefacts.
        piece (PieceConfig): Piece whose ``fit`` settings define the window.
        show_plots (bool): Call ``plt.show()`` when true.
    """
    npz_path = piece_dir / "template.npz"
    meta_path = piece_dir / "template_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    tau_peak = float(np.load(npz_path)["tau_peak"])
    mask = fit_mask_for_template(
        meta,
        piece.fit,
        tau_peak=tau_peak,
        context=f"Piece {piece.piece_id}",
    )
    plot_template_artifacts(
        npz_path,
        meta_path,
        mask=mask,
        save_path=piece_dir / "template_gp.png",
        show=show_plots,
    )


def run_manifest(
    manifest_path: Path,
    *,
    dry_run: bool = False,
    show_plots: bool = False,
) -> Path:
    """Execute full pipeline; return path to ``timing.csv``."""
    manifest = load_manifest(manifest_path)
    apply_plot_style()
    if dry_run:
        n_active = sum(1 for p in manifest.pieces if not p.skip)
        logger.info("Dry run OK: %s active piece(s)", n_active)
        return manifest.run_dir / "timing.csv"

    manifest.run_dir.mkdir(parents=True, exist_ok=True)
    all_timing: list[dict] = []
    piece_dirs: dict[str, Path] = {}

    for piece in manifest.pieces:
        if piece.skip:
            logger.info("Piece %s: skip=true; Step 1 and Step 2 not run", piece.piece_id)
            continue
        piece_dir = manifest.run_dir / "pieces" / piece.piece_id
        piece_dir.mkdir(parents=True, exist_ok=True)
        piece_dirs[piece.piece_id] = piece_dir
        fold_p = piece_fold_period(piece, manifest.default_period)
        fold_epoch = piece_fold_epoch(piece, manifest.default_epoch)
        piece_lc = piece_lc_path(piece, manifest.lc_path)

        if piece.existing_template_dir is not None:
            load_existing_template_dir(
                piece.existing_template_dir,
                piece_dir,
                piece_id=piece.piece_id,
                fit_t_min=piece.fit_window.t_min,
                fit_t_max=piece.fit_window.t_max,
            )
            _plot_reused_template(piece_dir, piece, show_plots=show_plots)
        elif piece.reuse_template_from is not None:
            source_dir = piece_dirs[piece.reuse_template_from]
            copy_piece_template(
                source_dir,
                piece_dir,
                piece_id=piece.piece_id,
                reuse_template_from=piece.reuse_template_from,
                fit_t_min=piece.fit_window.t_min,
                fit_t_max=piece.fit_window.t_max,
            )
            _plot_reused_template(piece_dir, piece, show_plots=show_plots)
        else:
            build_piece_template(
                piece_lc,
                piece_id=piece.piece_id,
                t_obs_min=piece.template_window.t_min,
                t_obs_max=piece.template_window.t_max,
                fold_epoch=fold_epoch,
                fold_period=fold_p,
                default_epoch=manifest.default_epoch,
                default_period=manifest.default_period,
                period_slope=manifest.period_slope,
                mag0=manifest.mag0,
                cfg=piece.gp_template,
                fit_cfg=piece.fit,
                fold_ephemeris=piece.fold_ephemeris,
                out_npz=piece_dir / "template.npz",
                out_meta=piece_dir / "template_meta.json",
                out_plot=piece_dir / "template_gp.png",
                show_plot=show_plots,
            )

        fits_dir = piece_dir / "fits" if manifest.save_interval_plots else None
        summary_rows = fit_piece_intervals(
            piece_lc,
            piece_id=piece.piece_id,
            fit_t_min=piece.fit_window.t_min,
            fit_t_max=piece.fit_window.t_max,
            intervals_path=piece.intervals_path,
            template_npz=piece_dir / "template.npz",
            template_meta_path=piece_dir / "template_meta.json",
            mag0=manifest.mag0,
            fit_cfg=piece.fit,
            timing_method=manifest.timing_method,
            out_summary=piece_dir / "fit_summary.csv",
            fits_dir=fits_dir,
            show_plots=show_plots,
        )

        curve, _meta = load_template_bundle(
            piece_dir / "template.npz",
            piece_dir / "template_meta.json",
            context=f"Piece {piece.piece_id}",
        )
        _attach_timing_errors(
            summary_rows,
            curve=curve,
            error_model=manifest.error_model,
            timing_method=manifest.timing_method,
        )
        if summary_rows:
            summary_path = piece_dir / "fit_summary.csv"
            with summary_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
                writer.writeheader()
                writer.writerows(summary_rows)
        all_timing.extend(summary_rows)

    all_timing.sort(key=lambda r: (float(r["t_max"]), str(r["piece_id"]), int(r["interval"])))
    timing_path = manifest.run_dir / "timing.csv"
    if all_timing:
        timing_path = _write_all_method_timing_csvs(
            manifest.run_dir,
            all_timing,
            official_method=manifest.timing_method,
        )

    if manifest.save_overview and all_timing:
        t_lo, t_hi = overview_time_span(
            manifest.pieces,
            all_timing,
            manifest.overview_t_min,
            manifest.overview_t_max,
        )
        plot_lc_with_maxima(
            all_timing,
            t_min=t_lo,
            t_max=t_hi,
            lc_segments=overview_lc_segments(manifest.pieces, manifest.lc_path),
            save_path=manifest.run_dir / "overview_lc_maxima.png",
            show=show_plots,
        )

    return timing_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Template timing two-step orchestrator")
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to manifest YAML",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate manifest and paths only",
    )
    parser.add_argument(
        "--show-plots",
        action="store_true",
        help="Interactive plt.show() after each figure",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_manifest(args.config.resolve(), dry_run=args.dry_run, show_plots=args.show_plots)


if __name__ == "__main__":
    main()
