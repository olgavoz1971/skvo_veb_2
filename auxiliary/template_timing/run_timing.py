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
    load_intervals_absolute,
    load_manifest,
    piece_fold_epoch,
    piece_fold_period,
    piece_lc_path,
    piece_template_window,
)
from plot_style import apply_plot_style
from plot_overview import overview_time_span, plot_lc_with_maxima
from template_build import build_piece_template, plot_template_artifacts
from template_derive import derive_secondary_template
from mavka_template import build_piece_template_mavka
from template_reuse import bind_reused_template_dir, resolve_piece_template_dir
from template_tom_rectify import rectify_template_tom, resolve_fit_template_dir
from template_fit import TemplateCurve
from template_fit_pipeline import (
    fit_mask_for_template,
    fit_piece_intervals,
    fit_piece_segment_anchor,
    fit_result_from_summary_row,
    fit_summary_table_rows,
    load_fit_summary_rows,
    load_fit_summary_table,
    load_template_bundle,
    method_timing_record,
    review_piece_from_summary,
    sync_official_columns,
    write_fit_summary_table,
)
from fit_review import normalise_review_fields, parse_rejected_flag
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


def _write_csv_rows(
    path: Path,
    records: list[dict],
    *,
    fieldnames: list[str],
    comment_rejected: bool = True,
) -> None:
    """Write CSV rows, prefixing rejected rows with ``#`` when requested."""
    import io

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            buffer = io.StringIO()
            row_writer = csv.DictWriter(
                buffer, fieldnames=fieldnames, extrasaction="ignore"
            )
            row_writer.writerow(row)
            line = buffer.getvalue()
            if comment_rejected and parse_rejected_flag(row.get("rejected")):
                handle.write(f"#{line}")
            else:
                handle.write(line)


def _write_timing_csv(path: Path, records: list[dict], *, fieldnames: list[str]) -> None:
    """Write one merged timing table, commenting rejected rows."""
    _write_csv_rows(path, records, fieldnames=fieldnames, comment_rejected=True)


def _official_timing_record(row: dict) -> dict:
    """Build one official timing export row from a wide summary row."""
    method = row["selected_method"]
    record = {
        **method_timing_record(row, method),
        "timing_method": method,
        "rms_official": row[f"rms_{method}"],
        "delta_t_official": row[f"delta_t_{method}"],
        "scale_official": (
            float(row["scale_nls_scale_clean"])
            if method == "nls_scale_clean"
            else 1.0
        ),
        "rejected": row.get("rejected", "false"),
    }
    if f"sigma_t_max_{method}" in row:
        record["sigma_t_max"] = row[f"sigma_t_max_{method}"]
    return record


def _write_all_method_timing_csvs(out_dir: Path, rows: list[dict]) -> Path:
    """Write ``timing.csv`` (per-row official method) and ``timing_<method>.csv`` under ``out_dir``."""
    official_path = out_dir / "timing.csv"
    official_records = [_official_timing_record(row) for row in rows]

    _write_timing_csv(official_path, official_records, fieldnames=TIMING_CSV_FIELDS_OFFICIAL)
    logger.info("Wrote %s (%s maxima, per-row selected_method)", official_path, len(official_records))

    for method in sorted(TIMING_METHODS):
        path = out_dir / f"timing_{method}.csv"
        records = [
            {**method_timing_record(row, method), "rejected": row.get("rejected", "false")}
            for row in rows
        ]
        _write_timing_csv(path, records, fieldnames=TIMING_CSV_FIELDS + ["rejected"])
        logger.info("Wrote %s (%s maxima)", path, len(records))

    return official_path


def _write_piece_timing_exports(piece_dir: Path, rows: list[dict]) -> Path | None:
    """Write final timing tables for one segment under ``pieces/<piece_id>/``."""
    if not rows:
        return None
    return _write_all_method_timing_csvs(piece_dir, rows)


def _write_fit_summary_csv(path: Path, rows: list[dict]) -> None:
    """Write a piece-level wide summary, commenting rejected rows."""
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    if "rejected" not in fieldnames:
        fieldnames = [*fieldnames, "rejected"]
    _write_csv_rows(path, rows, fieldnames=fieldnames, comment_rejected=True)


def _prepare_summary_rows(
    rows: list[dict],
    *,
    curve: TemplateCurve,
    error_model: str,
    default_method: str,
) -> None:
    """Normalise review fields, timing errors, and official columns in place."""
    _attach_timing_errors(
        rows,
        curve=curve,
        error_model=error_model,
        timing_method=default_method,
    )
    for row in rows:
        normalise_review_fields(row, default_method=default_method)
        if not parse_rejected_flag(row["rejected"]):
            sync_official_columns(row, row["selected_method"])
            row["sigma_t_max"] = row[f"sigma_t_max_{row['selected_method']}"]


def _load_all_piece_summary_rows(run_dir: Path) -> list[dict]:
    """Load wide summary rows from every ``pieces/*/fit_summary.csv`` on disk."""
    rows: list[dict] = []
    pieces_dir = run_dir / "pieces"
    if not pieces_dir.is_dir():
        return rows
    for piece_dir in sorted(pieces_dir.iterdir()):
        if not piece_dir.is_dir():
            continue
        summary_path = piece_dir / "fit_summary.csv"
        if not summary_path.is_file():
            continue
        piece_rows = load_fit_summary_rows(summary_path, include_rejected=True)
        rows.extend(piece_rows)
        logger.info(
            "Loaded %s row(s) from %s",
            len(piece_rows),
            summary_path,
        )
    return rows


def _overview_lc_segments_for_timing(
    timing_rows: list[dict],
    manifest,
) -> list[tuple[Path, float, float]]:
    """Build overview LC clip windows from merged timing rows and the manifest."""
    piece_by_id = {piece.piece_id: piece for piece in manifest.pieces}
    windows_by_path: dict[Path, list[tuple[float, float]]] = {}
    for row in timing_rows:
        piece_id = str(row["piece_id"])
        piece = piece_by_id.get(piece_id)
        if piece is None:
            logger.warning(
                "Overview: piece_id %s not in manifest; using global lc_path",
                piece_id,
            )
            lc = manifest.lc_path
        else:
            lc = piece_lc_path(piece, manifest.lc_path)
        windows_by_path.setdefault(lc, []).append(
            (float(row["t_start"]), float(row["t_end"]))
        )
    segments: list[tuple[Path, float, float]] = []
    for lc, windows in windows_by_path.items():
        seg_lo = min(w[0] for w in windows)
        seg_hi = max(w[1] for w in windows)
        segments.append((lc, seg_lo, seg_hi))
    return segments


def _write_piece_overview(
    piece_dir: Path,
    rows: list[dict],
    *,
    manifest,
    piece: PieceConfig,
    show: bool,
) -> None:
    """Save (and optionally show) an LC overview for one segment's accepted maxima."""
    if not manifest.save_overview:
        return
    accepted = [r for r in rows if not parse_rejected_flag(r.get("rejected"))]
    if not accepted:
        return
    t_lo, t_hi = overview_time_span(
        [piece],
        accepted,
        manifest.overview_t_min,
        manifest.overview_t_max,
    )
    plot_lc_with_maxima(
        accepted,
        t_min=t_lo,
        t_max=t_hi,
        lc_segments=_overview_lc_segments_for_timing(accepted, manifest),
        working_domain=manifest.photometry_domain,
        save_path=piece_dir / "overview_lc_maxima.png",
        show=show,
    )


def _export_merged_run_outputs(
    manifest,
    *,
    show_plots: bool,
) -> Path:
    """Explicit merge: all piece folders -> ``run_dir/timing.csv`` and run overview."""
    all_timing = _load_all_piece_summary_rows(manifest.run_dir)
    timing_path = manifest.run_dir / "timing.csv"
    all_timing.sort(key=lambda r: (float(r["t_max"]), str(r["piece_id"]), int(r["interval"])))
    if all_timing:
        timing_path = _write_all_method_timing_csvs(manifest.run_dir, all_timing)
        logger.info(
            "Merged run export: %s row(s) from %s piece(s) -> %s",
            len(all_timing),
            len({str(r["piece_id"]) for r in all_timing}),
            timing_path,
        )

    accepted = [r for r in all_timing if not parse_rejected_flag(r.get("rejected"))]
    if manifest.save_overview and accepted:
        t_lo, t_hi = overview_time_span(
            manifest.pieces,
            accepted,
            manifest.overview_t_min,
            manifest.overview_t_max,
        )
        plot_lc_with_maxima(
            accepted,
            t_min=t_lo,
            t_max=t_hi,
            lc_segments=_overview_lc_segments_for_timing(accepted, manifest),
            working_domain=manifest.photometry_domain,
            save_path=manifest.run_dir / "overview_lc_maxima.png",
            show=show_plots,
        )
    elif manifest.save_overview and not accepted:
        logger.warning("No accepted maxima; run overview not written")
    return timing_path


def _finish_piece_outputs(
    piece_dir: Path,
    rows: list[dict],
    *,
    manifest,
    piece: PieceConfig,
    show_overview: bool,
) -> Path | None:
    """Write segment-local timing exports and optional segment overview."""
    timing_path = _write_piece_timing_exports(piece_dir, rows)
    _write_piece_overview(
        piece_dir,
        rows,
        manifest=manifest,
        piece=piece,
        show=show_overview,
    )
    return timing_path


def _show_reused_template(
    template_dir: Path,
    piece: PieceConfig,
    *,
    show_plots: bool,
) -> None:
    """Optionally display a reused template; never write into the piece folder.

    Args:
        template_dir (Path): Read-only directory with ``template.npz`` / meta.
        piece (PieceConfig): Piece whose ``fit`` settings define the window.
        show_plots (bool): Call ``plt.show()`` when true.
    """
    if not show_plots:
        return
    npz_path = template_dir / "template.npz"
    meta_path = template_dir / "template_meta.json"
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
        save_path=None,
        show=True,
    )


def run_manifest(
    manifest_path: Path,
    *,
    dry_run: bool = False,
    show_plots: bool = False,
    review_fits: bool = False,
    template_only: bool = False,
    fit_only: bool = False,
) -> Path:
    """Execute full pipeline; return path to ``timing.csv``.

    Args:
        manifest_path (Path): Timing manifest YAML.
        dry_run (bool): Validate only.
        show_plots (bool): Interactive figures where supported.
        review_fits (bool): Interactive interval review after each fit.
        template_only (bool): Run Step 1a and optional 1b; skip fitting.
        fit_only (bool): Skip Step 1a/1b rebuild; fit using on-disk templates
            (prefer ``tom_rectified/`` when present).

    Returns:
        Path: Last piece ``timing.csv`` path (or run-level placeholder).
    """
    if template_only and fit_only:
        raise ValueError("use only one of --template-only and --fit-only")
    manifest = load_manifest(manifest_path)
    apply_plot_style()
    if dry_run:
        n_active = sum(1 for p in manifest.pieces if not p.skip)
        logger.info("Dry run OK: %s active piece(s)", n_active)
        return manifest.run_dir / "timing.csv"

    manifest.run_dir.mkdir(parents=True, exist_ok=True)
    last_timing_path: Path | None = None
    last_piece: PieceConfig | None = None
    last_rows: list[dict] = []
    piece_dirs: dict[str, Path] = {}
    obtained_dirs: dict[str, Path] = {}
    template_dirs: dict[str, Path] = {}

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

        if fit_only:
            if piece.reuse_template_from is not None:
                source_id = piece.reuse_template_from
                if source_id not in obtained_dirs:
                    raise ValueError(
                        f"piece {piece.piece_id}: --fit-only reuse_template_from "
                        f"{source_id!r} must appear earlier in the manifest"
                    )
                obtained_dir = obtained_dirs[source_id]
            else:
                obtained_dir = resolve_piece_template_dir(
                    piece,
                    run_dir=manifest.run_dir,
                    pieces=manifest.pieces,
                )
            obtained_dirs[piece.piece_id] = obtained_dir
            if piece.reuse_template_from is not None and not piece.rectify_template_tom.enabled:
                fit_piece_dir = piece_dirs[piece.reuse_template_from]
            else:
                fit_piece_dir = piece_dir
            template_dirs[piece.piece_id] = resolve_fit_template_dir(
                piece_dir=fit_piece_dir,
                obtained_dir=obtained_dir,
                fit_template=piece.fit_template,
                piece_id=piece.piece_id,
            )
            logger.info(
                "Piece %s: --fit-only fit_template=%s -> %s",
                piece.piece_id,
                piece.fit_template,
                template_dirs[piece.piece_id],
            )
        else:
            if piece.derive_secondary is not None:
                if piece.existing_template_dir is None:
                    raise ValueError(
                        f"piece {piece.piece_id}: derive_secondary requires "
                        "existing_template_dir"
                    )
                dest = piece_dir.resolve()
                derive_secondary_template(
                    piece.existing_template_dir,
                    dest,
                    piece.derive_secondary,
                    piece_id=piece.piece_id,
                )
                obtained_dir = dest
                derived_npz = dest / "template.npz"
                derived_meta_path = dest / "template_meta.json"
                derived_meta = json.loads(derived_meta_path.read_text(encoding="utf-8"))
                derived_tau_peak = float(np.load(derived_npz)["tau_peak"])
                mask = fit_mask_for_template(
                    derived_meta,
                    piece.fit,
                    tau_peak=derived_tau_peak,
                    context=f"Piece {piece.piece_id}",
                )
                plot_template_artifacts(
                    derived_npz,
                    derived_meta_path,
                    mask=mask,
                    save_path=dest / "template_gp.png",
                    show=show_plots,
                )
            elif piece.existing_template_dir is not None:
                obtained_dir = bind_reused_template_dir(
                    piece, template_dirs=obtained_dirs
                )
                _show_reused_template(obtained_dir, piece, show_plots=show_plots)
            elif piece.reuse_template_from is not None:
                obtained_dir = bind_reused_template_dir(
                    piece, template_dirs=obtained_dirs
                )
                _show_reused_template(obtained_dir, piece, show_plots=show_plots)
            else:
                tw = piece_template_window(piece)
                if manifest.template_engine == "mavka":
                    if piece.intervals_path is None:
                        raise ValueError(
                            f"piece {piece.piece_id}: MAVKA build requires intervals_path"
                        )
                    if manifest.intervals_time is None:
                        raise ValueError(
                            "global.intervals_time required for MAVKA template build"
                        )
                    intervals = load_intervals_absolute(
                        piece.intervals_path, manifest.intervals_time
                    )
                    build_piece_template_mavka(
                        piece_lc,
                        piece_id=piece.piece_id,
                        t_obs_min=tw.t_min,
                        t_obs_max=tw.t_max,
                        fold_epoch=fold_epoch,
                        fold_period=fold_p,
                        default_epoch=manifest.default_epoch,
                        default_period=manifest.default_period,
                        period_slope=manifest.period_slope,
                        working_domain=manifest.photometry_domain,
                        intervals=intervals,
                        intervals_path=piece.intervals_path,
                        mavka_cfg=manifest.mavka_template,
                        fit_cfg=piece.fit,
                        out_npz=piece_dir / "template.npz",
                        out_meta=piece_dir / "template_meta.json",
                        out_plot=piece_dir / "template_mavka.png",
                        show_plot=show_plots,
                    )
                else:
                    build_piece_template(
                        piece_lc,
                        piece_id=piece.piece_id,
                        t_obs_min=tw.t_min,
                        t_obs_max=tw.t_max,
                        fold_epoch=fold_epoch,
                        fold_period=fold_p,
                        default_epoch=manifest.default_epoch,
                        default_period=manifest.default_period,
                        period_slope=manifest.period_slope,
                        working_domain=manifest.photometry_domain,
                        cfg=piece.gp_template,
                        fit_cfg=piece.fit,
                        fold_ephemeris=piece.fold_ephemeris,
                        out_npz=piece_dir / "template.npz",
                        out_meta=piece_dir / "template_meta.json",
                        out_plot=piece_dir / "template_gp.png",
                        show_plot=show_plots,
                    )
                obtained_dir = piece_dir.resolve()

            obtained_dirs[piece.piece_id] = obtained_dir

            if piece.rectify_template_tom.enabled:
                if manifest.template_engine == "mavka":
                    logger.info(
                        "Piece %s: skipping rectify_template_tom "
                        "(not used with template_engine: mavka; "
                        "tau_peak is the MAVKA TOM)",
                        piece.piece_id,
                    )
                else:
                    rectify_template_tom(
                        obtained_dir,
                        piece_dir,
                        piece.rectify_template_tom,
                        piece_id=piece.piece_id,
                        show_plots=show_plots,
                    )

            fit_piece_dir = piece_dir
            if (
                piece.reuse_template_from is not None
                and not piece.rectify_template_tom.enabled
            ):
                fit_piece_dir = piece_dirs[piece.reuse_template_from]
            template_dirs[piece.piece_id] = resolve_fit_template_dir(
                piece_dir=fit_piece_dir,
                obtained_dir=obtained_dir,
                fit_template=piece.fit_template,
                piece_id=piece.piece_id,
            )
            logger.info(
                "Piece %s: Step 2 will use fit_template=%s -> %s",
                piece.piece_id,
                piece.fit_template,
                template_dirs[piece.piece_id],
            )

        if template_only:
            logger.info(
                "Piece %s: --template-only; skipping Step 2 (template=%s)",
                piece.piece_id,
                template_dirs[piece.piece_id],
            )
            continue

        template_dir = template_dirs[piece.piece_id]
        template_npz = template_dir / "template.npz"
        template_meta = template_dir / "template_meta.json"

        fits_dir = piece_dir / "fits" if manifest.save_interval_plots else None
        if piece.timing_mode == "segment_anchor":
            summary_rows = fit_piece_segment_anchor(
                piece_lc,
                piece_id=piece.piece_id,
                fit_t_min=piece.fit_window.t_min,
                fit_t_max=piece.fit_window.t_max,
                anchor_epoch=piece.anchor_epoch,
                piece_period=fold_p,
                template_npz=template_npz,
                template_meta_path=template_meta,
                working_domain=manifest.photometry_domain,
                fit_cfg=piece.fit,
                timing_method=manifest.timing_method,
                out_summary=piece_dir / "fit_summary.csv",
                fits_dir=fits_dir,
                show_plots=show_plots,
                review_fits=review_fits,
            )
        else:
            summary_rows = fit_piece_intervals(
                piece_lc,
                piece_id=piece.piece_id,
                fit_t_min=piece.fit_window.t_min,
                fit_t_max=piece.fit_window.t_max,
                intervals_path=piece.intervals_path,
                template_npz=template_npz,
                template_meta_path=template_meta,
                working_domain=manifest.photometry_domain,
                time_scale=manifest.intervals_time,
                fit_cfg=piece.fit,
                timing_method=manifest.timing_method,
                out_summary=piece_dir / "fit_summary.csv",
                fits_dir=fits_dir,
                show_plots=show_plots,
                review_fits=review_fits,
            )

        curve, _meta = load_template_bundle(
            template_npz,
            template_meta,
            context=f"Piece {piece.piece_id}",
        )
        _prepare_summary_rows(
            summary_rows,
            curve=curve,
            error_model=manifest.error_model,
            default_method=manifest.timing_method,
        )
        if summary_rows:
            _write_fit_summary_csv(piece_dir / "fit_summary.csv", summary_rows)
            last_timing_path = _finish_piece_outputs(
                piece_dir,
                summary_rows,
                manifest=manifest,
                piece=piece,
                show_overview=False,
            )
            last_piece = piece
            last_rows = summary_rows

    if review_fits and last_piece is not None and last_rows:
        _write_piece_overview(
            manifest.run_dir / "pieces" / last_piece.piece_id,
            last_rows,
            manifest=manifest,
            piece=last_piece,
            show=True,
        )

    if last_timing_path is None:
        return manifest.run_dir / "pieces" / "timing.csv"
    return last_timing_path


def export_manifest(manifest_path: Path, *, show_plots: bool = False) -> Path:
    """Merge all segment folders into ``run_dir/timing.csv`` (explicit opt-in)."""
    manifest = load_manifest(manifest_path)
    apply_plot_style()
    logger.info(
        "Export-only: merging segment timing under %s -> run_dir (no refit, no review)",
        manifest.run_dir,
    )
    pieces_dir = manifest.run_dir / "pieces"
    if pieces_dir.is_dir():
        for piece_dir in sorted(pieces_dir.iterdir()):
            if not piece_dir.is_dir():
                continue
            summary_path = piece_dir / "fit_summary.csv"
            if not summary_path.is_file():
                continue
            rows = load_fit_summary_rows(summary_path, include_rejected=True)
            if rows:
                _write_piece_timing_exports(piece_dir, rows)
    return _export_merged_run_outputs(manifest, show_plots=show_plots)


def review_manifest(manifest_path: Path, *, show_plots: bool = False) -> Path:
    """Re-review existing fit summaries without refitting or rebuilding templates."""
    manifest = load_manifest(manifest_path)
    apply_plot_style()
    last_timing_path: Path | None = None
    last_piece: PieceConfig | None = None
    last_rows: list[dict] = []

    for piece in manifest.pieces:
        if piece.skip:
            logger.info("Piece %s: skip=true; review not run", piece.piece_id)
            continue
        piece_dir = manifest.run_dir / "pieces" / piece.piece_id
        summary_path = piece_dir / "fit_summary.csv"
        try:
            summary_table = load_fit_summary_table(summary_path)
        except FileNotFoundError:
            logger.warning("Piece %s: no fit_summary at %s", piece.piece_id, summary_path)
            continue
        if not any(not entry.commented for entry in summary_table.entries):
            logger.warning(
                "Piece %s: no active intervals to review in %s",
                piece.piece_id,
                summary_path,
            )
            continue

        piece_lc = piece_lc_path(piece, manifest.lc_path)
        try:
            template_dir = resolve_piece_template_dir(
                piece,
                run_dir=manifest.run_dir,
                pieces=manifest.pieces,
            )
        except FileNotFoundError as exc:
            logger.warning(
                "Piece %s: no template for review (%s)",
                piece.piece_id,
                exc,
            )
            continue
        template_npz = template_dir / "template.npz"
        template_meta = template_dir / "template_meta.json"
        summary_table = review_piece_from_summary(
            piece_lc,
            piece_id=piece.piece_id,
            fit_t_min=piece.fit_window.t_min,
            fit_t_max=piece.fit_window.t_max,
            template_npz=template_npz,
            template_meta_path=template_meta,
            working_domain=manifest.photometry_domain,
            default_method=manifest.timing_method,
            fit_cfg=piece.fit,
            summary_table=summary_table,
        )
        modified_rows = [
            entry.row
            for entry in summary_table.entries
            if entry.modified and not entry.commented
        ]
        if modified_rows:
            curve, _meta = load_template_bundle(
                template_npz,
                template_meta,
                context=f"Piece {piece.piece_id}",
            )
            _prepare_summary_rows(
                modified_rows,
                curve=curve,
                error_model=manifest.error_model,
                default_method=manifest.timing_method,
            )
        write_fit_summary_table(summary_path, summary_table)
        all_rows = fit_summary_table_rows(summary_table)
        n_modified = sum(1 for entry in summary_table.entries if entry.modified)
        last_timing_path = _finish_piece_outputs(
            piece_dir,
            all_rows,
            manifest=manifest,
            piece=piece,
            show_overview=False,
        )
        if n_modified:
            logger.info(
                "Piece %s: updated fit_summary (%s row(s)) and segment timing.csv",
                piece.piece_id,
                n_modified,
            )
        else:
            logger.info(
                "Piece %s: fit_summary unchanged; segment timing.csv written from summary",
                piece.piece_id,
            )
        last_piece = piece
        last_rows = all_rows

    if last_piece is not None and last_rows:
        _write_piece_overview(
            manifest.run_dir / "pieces" / last_piece.piece_id,
            last_rows,
            manifest=manifest,
            piece=last_piece,
            show=True,
        )

    if last_timing_path is None:
        return manifest.run_dir / "pieces" / "timing.csv"
    return last_timing_path


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
        help="Interactive plt.show() after each saved figure (not used during --review-fits)",
    )
    parser.add_argument(
        "--review-fits",
        action="store_true",
        help="After each interval fit, open a 4-panel review window (keys 1-4/c/n/l/s, r=reject)",
    )
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="Skip Step 1 and refitting; re-review existing fit_summary.csv files and rewrite exports",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Rebuild run_dir/timing.csv from all pieces/*/fit_summary.csv (explicit merge; does not run fits)",
    )
    parser.add_argument(
        "--template-only",
        action="store_true",
        help="Run Step 1a and optional ToM rectification (1b); skip interval/segment fitting",
    )
    parser.add_argument(
        "--fit-only",
        action="store_true",
        help=(
            "Skip Step 1a/1b rebuild; fit using on-disk templates. "
            "Which folder is used is controlled by fit_template "
            "(obtained | tom_rectified), not by auto-preference."
        ),
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = args.config.resolve()
    exclusive = sum(
        bool(flag)
        for flag in (
            args.export_only,
            args.review_only,
            args.template_only,
            args.fit_only,
        )
    )
    if exclusive > 1:
        parser.error(
            "use only one of --export-only, --review-only, --template-only, --fit-only"
        )
    if args.export_only:
        export_manifest(config, show_plots=args.show_plots)
    elif args.review_only:
        review_manifest(config, show_plots=args.show_plots)
    else:
        run_manifest(
            config,
            dry_run=args.dry_run,
            show_plots=args.show_plots,
            review_fits=args.review_fits,
            template_only=args.template_only,
            fit_only=args.fit_only,
        )


if __name__ == "__main__":
    main()
