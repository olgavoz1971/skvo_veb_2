"""Install pre-built Step 1 template artefacts (skip GP rebuild)."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_TEMPLATE_FILES = ("template.npz", "template_meta.json")
_OPTIONAL_PLOT = "template_gp.png"


def _require_template_files(source_dir: Path, *, context: str) -> None:
    for name in _TEMPLATE_FILES:
        if not (source_dir / name).is_file():
            raise FileNotFoundError(f"{context}: missing {source_dir / name}")


def install_template_from_dir(
    source_dir: Path,
    dest_piece_dir: Path,
    *,
    piece_id: str,
    fit_t_min: float,
    fit_t_max: float,
    provenance: dict[str, str],
) -> None:
    """Copy ``template.npz`` / meta from ``source_dir`` into the current run piece folder.

    Args:
        source_dir: Directory containing ``template.npz`` and ``template_meta.json``.
        dest_piece_dir: Output ``pieces/<piece_id>/`` for this run.
        piece_id: Piece label for this run.
        fit_t_min: Fit window start (recorded in meta).
        fit_t_max: Fit window end (recorded in meta).
        provenance: Extra keys merged into ``template_meta.json`` (e.g. load path).
    """
    source_dir = source_dir.resolve()
    dest_piece_dir = dest_piece_dir.resolve()
    _require_template_files(source_dir, context=f"template source {source_dir}")

    if source_dir == dest_piece_dir:
        logger.info(
            "Piece %s: existing_template_dir is the run output folder; skipping copy",
            piece_id,
        )
        meta_path = dest_piece_dir / "template_meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["piece_id"] = piece_id
            meta["fit_t_min"] = fit_t_min
            meta["fit_t_max"] = fit_t_max
            meta.update(provenance)
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return

    dest_piece_dir.mkdir(parents=True, exist_ok=True)
    for name in _TEMPLATE_FILES:
        shutil.copy2(source_dir / name, dest_piece_dir / name)

    plot_src = source_dir / _OPTIONAL_PLOT
    if plot_src.is_file():
        shutil.copy2(plot_src, dest_piece_dir / _OPTIONAL_PLOT)

    meta_path = dest_piece_dir / "template_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["piece_id"] = piece_id
    meta["fit_t_min"] = fit_t_min
    meta["fit_t_max"] = fit_t_max
    meta.update(provenance)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def copy_piece_template(
    source_piece_dir: Path,
    dest_piece_dir: Path,
    *,
    piece_id: str,
    reuse_template_from: str,
    fit_t_min: float,
    fit_t_max: float,
) -> None:
    """Reuse template from another piece in the same manifest run."""
    install_template_from_dir(
        source_piece_dir,
        dest_piece_dir,
        piece_id=piece_id,
        fit_t_min=fit_t_min,
        fit_t_max=fit_t_max,
        provenance={"reuse_template_from": reuse_template_from},
    )
    logger.info(
        "Piece %s: reused template from piece %s (no GP build)",
        piece_id,
        reuse_template_from,
    )


def load_existing_template_dir(
    existing_dir: Path,
    dest_piece_dir: Path,
    *,
    piece_id: str,
    fit_t_min: float,
    fit_t_max: float,
) -> None:
    """Load template from a previous run or manual Step 1 output on disk."""
    install_template_from_dir(
        existing_dir,
        dest_piece_dir,
        piece_id=piece_id,
        fit_t_min=fit_t_min,
        fit_t_max=fit_t_max,
        provenance={"template_loaded_from": str(existing_dir.resolve())},
    )
    logger.info(
        "Piece %s: loaded existing template from %s (no GP build)",
        piece_id,
        existing_dir,
    )
