"""Step 1b: rectify the painted template ToM without rebuilding the GP."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from template_reuse import _require_template_files

if TYPE_CHECKING:
    from manifest_config import RectifyTemplateTomConfig

logger = logging.getLogger(__name__)

_EPOCH_SPIKE_DIR = Path(__file__).resolve().parent / "epoch_spike"
if str(_EPOCH_SPIKE_DIR) not in sys.path:
    sys.path.insert(0, str(_EPOCH_SPIKE_DIR))

from epoch_config import EpochSpikeConfig  # noqa: E402
from epoch_core import run_epoch_estimators  # noqa: E402
from epoch_io import load_template_dir, write_corrected_template  # noqa: E402
from epoch_plot import (  # noqa: E402
    plot_bisector_ladder,
    plot_branch_overlay,
    plot_kvw_cost,
    plot_template_marks,
)

TOM_RECTIFIED_DIRNAME = "tom_rectified"
TOM_RECTIFY_DIAG_DIRNAME = "tom_rectify"


def tom_rectified_dir(piece_dir: Path) -> Path:
    """Return the fixed Step 1b product directory under ``piece_dir``.

    Args:
        piece_dir (Path): ``run_dir/pieces/<id>/``.

    Returns:
        Path: ``pieces/<id>/tom_rectified/``.
    """
    return piece_dir / TOM_RECTIFIED_DIRNAME


def resolve_fit_template_dir(
    *,
    piece_dir: Path,
    obtained_dir: Path,
    fit_template: str,
    piece_id: str,
) -> Path:
    """Choose which on-disk template Step 2 loads.

    Args:
        piece_dir (Path): This run's ``pieces/<id>/``.
        obtained_dir (Path): Directory produced by Step 1a (build/reuse/derive).
        fit_template (str): ``obtained`` or ``tom_rectified``.
        piece_id (str): Piece label for error messages.

    Returns:
        Path: Template directory Step 2 must load.

    Raises:
        ValueError: If ``fit_template`` is unknown.
        FileNotFoundError: If ``tom_rectified`` is requested but artefacts are missing.
    """
    if fit_template == "obtained":
        return obtained_dir.resolve()
    if fit_template == "tom_rectified":
        dest = tom_rectified_dir(piece_dir).resolve()
        _require_template_files(
            dest,
            context=(
                f"piece {piece_id} fit_template=tom_rectified "
                "(run rectify_template_tom first, or point at an existing product)"
            ),
        )
        return dest
    raise ValueError(
        f"piece {piece_id}: unknown fit_template {fit_template!r}"
    )


def rectify_template_tom(
    source_dir: Path,
    piece_dir: Path,
    cfg: RectifyTemplateTomConfig,
    *,
    piece_id: str,
    show_plots: bool | None = None,
) -> Path:
    """Relabel ``tau_peak`` via KvW / bisector and write ``tom_rectified/``.

    The source template directory is never overwritten. Diagnostics (plots and
    tables) go under ``pieces/<id>/tom_rectify/``.

    Args:
        source_dir (Path): Step 1a template directory (build, reuse, or derive).
        piece_dir (Path): This run's ``pieces/<id>/`` (owns the 1b product).
        cfg (RectifyTemplateTomConfig): Algorithm and knobs.
        piece_id (str): Piece label for logs and provenance.
        show_plots (bool | None): Override ``cfg.show_plots`` when not ``None``.

    Returns:
        Path: Directory containing the rectified ``template.npz`` / meta.

    Raises:
        FileNotFoundError: If the source artefacts are missing.
        ValueError: If ``tom_rectified`` would overwrite the source, or the
            estimator fails scientific checks inside the library.
    """
    source_dir = source_dir.resolve()
    piece_dir = piece_dir.resolve()
    _require_template_files(source_dir, context=f"piece {piece_id} ToM rectification")

    dest_dir = tom_rectified_dir(piece_dir).resolve()
    if dest_dir == source_dir:
        raise ValueError(
            f"piece {piece_id}: refusing to overwrite source template at {source_dir}; "
            "tom_rectified must be a separate directory"
        )

    diag_dir = (piece_dir / TOM_RECTIFY_DIAG_DIRNAME).resolve()
    do_show = cfg.show_plots if show_plots is None else bool(show_plots)

    spike_cfg = EpochSpikeConfig(
        config_path=piece_dir / "rectify_template_tom.yaml",
        label=f"piece_{piece_id}",
        template_dir=source_dir,
        output_dir=diag_dir,
        show_plots=do_show,
        plot_dpi=cfg.plot_dpi,
        kvw_half_width_phase=cfg.kvw_half_width_phase,
        kvw_search_half_width_phase=cfg.kvw_search_half_width_phase,
        depth_min=cfg.depth_min,
        depth_max=cfg.depth_max,
        n_levels=cfg.n_levels,
        min_accepted_levels=cfg.min_accepted_levels,
        kvw_n_pairs_min=cfg.kvw_n_pairs_min,
        weight_by_sigma=cfg.weight_by_sigma,
        export_method=cfg.method,
        export_template_dir=dest_dir,
    )

    logger.info(
        "Piece %s: ToM rectification (%s) source=%s -> %s",
        piece_id,
        cfg.method,
        source_dir,
        dest_dir,
    )
    template = load_template_dir(source_dir)
    result = run_epoch_estimators(template, spike_cfg)
    diag_dir.mkdir(parents=True, exist_ok=True)

    plot_kw = {"dpi": spike_cfg.plot_dpi, "show": spike_cfg.show_plots}
    plot_template_marks(result, diag_dir / "template_marks.png", **plot_kw)
    plot_bisector_ladder(result, diag_dir / "bisector_ladder.png", **plot_kw)
    plot_kvw_cost(result, diag_dir / "kvw_cost.png", **plot_kw)
    plot_branch_overlay(result, diag_dir / "branch_overlay.png", **plot_kw)

    tau_export = result.tau_for_method(cfg.method)
    write_corrected_template(
        template,
        tau_peak=tau_export,
        method=cfg.method,
        dest_dir=dest_dir,
        study_label=f"piece_{piece_id}",
        copy_lo=result.copy_lo,
        copy_hi=result.copy_hi,
    )
    _relabel_rectify_provenance(dest_dir, piece_id=piece_id, method=cfg.method)

    logger.info(
        "Piece %s: ToM rectification finished (%s); product in %s; diagnostics in %s",
        piece_id,
        cfg.method,
        dest_dir,
        diag_dir,
    )
    return dest_dir


def _relabel_rectify_provenance(
    dest_dir: Path, *, piece_id: str, method: str
) -> None:
    """Rename library ``epoch_spike`` meta key to ``rectify_template_tom``.

    Args:
        dest_dir (Path): Written ``tom_rectified/`` directory.
        piece_id (str): Piece identifier.
        method (str): Algorithm that painted the new ``tau_peak``.
    """
    meta_path = dest_dir / "template_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        raise ValueError(f"{meta_path}: root must be a mapping")
    spike = meta.pop("epoch_spike", None)
    if isinstance(spike, dict):
        spike = dict(spike)
        spike["piece_id"] = piece_id
        spike["note"] = (
            "GP mean/sigma grid copied; only tau_peak was changed by "
            "rectify_template_tom. Step 2 should load this tom_rectified folder."
        )
        meta["rectify_template_tom"] = spike
    else:
        meta["rectify_template_tom"] = {
            "piece_id": piece_id,
            "method": method,
            "note": "tau_peak relabelled; GP grid unchanged",
        }
    peak_sel = meta.get("peak_selection")
    if isinstance(peak_sel, dict):
        reason = str(peak_sel.get("reason", ""))
        peak_sel = dict(peak_sel)
        peak_sel["reason"] = reason.replace("epoch_spike", "rectify_template_tom", 1)
        meta["peak_selection"] = peak_sel
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
