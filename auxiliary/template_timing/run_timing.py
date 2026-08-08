"""Orchestrate Step 1 + Step 2 from a YAML manifest."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from manifest_config import load_manifest, piece_fold_period
from plot_style import apply_plot_style
from plot_overview import overview_time_span, plot_lc_with_maxima
from template_build import build_piece_template
from template_reuse import copy_piece_template, load_existing_template_dir
from template_fit import ShiftFitResult, TemplateCurve
from template_fit_pipeline import fit_piece_intervals, load_template_bundle
from timing_errors import sigma_t_max_rms_slope

logger = logging.getLogger(__name__)


def _attach_timing_errors(
    rows: list[dict],
    *,
    curve: TemplateCurve,
    error_model: str,
    timing_method: str,
) -> None:
    """Add ``sigma_t_max`` column in place when configured."""
    if error_model == "none":
        for row in rows:
            row["sigma_t_max"] = float("nan")
        return
    if error_model != "rms_slope":
        raise ValueError(f"unsupported error_model: {error_model}")

    for row in rows:
        fit = ShiftFitResult(
            delta_tau=float(row["delta_tau_official"]),
            delta_y=0.0,
            t_max=float(row["t_max"]),
            rms=float(row["rms_official"]),
            n_used=int(row["n_points"]),
            method=timing_method,
            scale=float(row["scale_official"]),
        )
        row["sigma_t_max"] = sigma_t_max_rms_slope(
            curve,
            fit,
            tau_peak=float(row["tau_peak"]),
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
        logger.info("Dry run OK: %s piece(s)", len(manifest.pieces))
        return manifest.run_dir / "timing.csv"

    manifest.run_dir.mkdir(parents=True, exist_ok=True)
    all_timing: list[dict] = []
    piece_dirs: dict[str, Path] = {}

    for piece in manifest.pieces:
        piece_dir = manifest.run_dir / "pieces" / piece.piece_id
        piece_dir.mkdir(parents=True, exist_ok=True)
        piece_dirs[piece.piece_id] = piece_dir
        fold_p = piece_fold_period(piece, manifest.p0)

        if piece.existing_template_dir is not None:
            load_existing_template_dir(
                piece.existing_template_dir,
                piece_dir,
                piece_id=piece.piece_id,
                fit_t_min=piece.fit_window.t_min,
                fit_t_max=piece.fit_window.t_max,
            )
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
        else:
            build_piece_template(
                manifest.lc_path,
                piece_id=piece.piece_id,
                t_obs_min=piece.template_window.t_min,
                t_obs_max=piece.template_window.t_max,
                t_ref=manifest.t_ref,
                fold_period=fold_p,
                ephemeris_p0=manifest.p0,
                period_slope=manifest.period_slope,
                mag0=manifest.mag0,
                cfg=piece.gp_template,
                out_npz=piece_dir / "template.npz",
                out_meta=piece_dir / "template_meta.json",
                out_plot=piece_dir / "template_gp.png",
                show_plot=show_plots,
            )

        fits_dir = piece_dir / "fits" if manifest.save_interval_plots else None
        summary_rows = fit_piece_intervals(
            manifest.lc_path,
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
        )
        _attach_timing_errors(
            summary_rows,
            curve=curve,
            error_model=manifest.error_model,
            timing_method=manifest.timing_method,
        )
        all_timing.extend(summary_rows)

    all_timing.sort(key=lambda r: (float(r["t_max"]), str(r["piece_id"]), int(r["interval"])))
    timing_path = manifest.run_dir / "timing.csv"
    if all_timing:
        fieldnames = [
            "piece_id",
            "interval",
            "t_max",
            "sigma_t_max",
            "timing_method",
            "rms_official",
            "delta_tau_official",
            "scale_official",
            "t_start",
            "t_end",
            "t_anchor",
            "n_points",
            "n_outliers_rejected_scale",
        ]
        with timing_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_timing)
        logger.info("Wrote %s (%s maxima)", timing_path, len(all_timing))

    if manifest.save_overview and all_timing:
        t_lo, t_hi = overview_time_span(
            manifest.pieces,
            all_timing,
            manifest.overview_t_min,
            manifest.overview_t_max,
        )
        plot_lc_with_maxima(
            manifest.lc_path,
            all_timing,
            t_min=t_lo,
            t_max=t_hi,
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
