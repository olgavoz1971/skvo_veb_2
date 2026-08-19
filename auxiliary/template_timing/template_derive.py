"""Derive a secondary-eclipse template by relabelling ``tau_peak`` (no GP rebuild)."""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from template_peak import (
    peak_candidate_from_dict,
    select_secondary_class,
    symmetric_support,
)
from template_reuse import _require_template_files

if TYPE_CHECKING:
    from manifest_config import DeriveSecondaryConfig

logger = logging.getLogger(__name__)


def derive_secondary_template(
    source_dir: Path,
    dest_dir: Path,
    cfg: DeriveSecondaryConfig,
    *,
    piece_id: str,
) -> Path:
    """Copy a primary template grid and paint the other accepted minimum class.

    The source directory is never written. Destination receives a new
    ``template.npz`` / ``template_meta.json`` with the same ``tau`` / ``mu`` /
    ``sigma`` and a relabelled ``tau_peak``.

    Args:
        source_dir (Path): Primary template directory (read-only).
        dest_dir (Path): Directory for the secondary bundle (this run's piece folder).
        cfg (DeriveSecondaryConfig): Selection method and phase window.
        piece_id (str): Piece identifier stored on the derived metadata.

    Returns:
        Path: Resolved ``dest_dir``.

    Raises:
        FileNotFoundError: If the source bundle is incomplete.
        ValueError: If destination equals source, required meta is missing, or
            no other accepted class lies within ``phase_tolerance``.
    """
    source_dir = source_dir.resolve()
    dest_dir = dest_dir.resolve()
    _require_template_files(
        source_dir, context=f"piece {piece_id} derive_secondary source"
    )
    if dest_dir == source_dir:
        raise ValueError(
            f"piece {piece_id}: derive_secondary would overwrite the source "
            f"template directory {source_dir}; use a different run_dir"
        )

    npz_path = source_dir / "template.npz"
    meta_path = source_dir / "template_meta.json"
    data = np.load(npz_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    context = f"piece {piece_id} source {source_dir}"

    if "fold_period" not in meta:
        raise ValueError(f"{context}: template_meta.json lacks fold_period")
    if "tau_data_min" not in meta or "tau_data_max" not in meta:
        raise ValueError(
            f"{context}: template_meta.json lacks tau_data_min / tau_data_max; "
            "rebuild the primary template"
        )
    gp_cfg = meta.get("gp_template_config")
    if not isinstance(gp_cfg, dict) or "peak_duplicate_phase_tol" not in gp_cfg:
        raise ValueError(
            f"{context}: template_meta.json lacks "
            "gp_template_config.peak_duplicate_phase_tol"
        )
    peak_sel = meta.get("peak_selection")
    if not isinstance(peak_sel, dict):
        raise ValueError(f"{context}: template_meta.json lacks peak_selection")
    raw_cands = peak_sel.get("candidates")
    if not isinstance(raw_cands, list) or not raw_cands:
        raise ValueError(
            f"{context}: peak_selection.candidates missing or empty"
        )

    period = float(meta["fold_period"])
    tau_data_min = float(meta["tau_data_min"])
    tau_data_max = float(meta["tau_data_max"])
    tau_primary = float(np.asarray(data["tau_peak"]))
    duplicate_phase_tol = float(gp_cfg["peak_duplicate_phase_tol"])
    candidates = [peak_candidate_from_dict(item) for item in raw_cands]

    selection = select_secondary_class(
        candidates,
        tau_primary=tau_primary,
        period=period,
        phase_offset=cfg.phase_offset,
        phase_tolerance=cfg.phase_tolerance,
        duplicate_phase_tol=duplicate_phase_tol,
        tau_data_min=tau_data_min,
        tau_data_max=tau_data_max,
    )
    tau_peak = float(selection.chosen.tau)
    if not (tau_data_min <= tau_peak <= tau_data_max):
        raise ValueError(
            f"{context}: selected tau_peak={tau_peak} lies outside the "
            f"photometric data range [{tau_data_min}, {tau_data_max}]"
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "tau": np.asarray(data["tau"]),
        "mu": np.asarray(data["mu"]),
        "tau_peak": np.asarray(tau_peak),
    }
    if "sigma" in data.files:
        payload["sigma"] = np.asarray(data["sigma"])
    np.savez(dest_dir / "template.npz", **payload)

    support = symmetric_support(
        tau_peak, tau_data_min=tau_data_min, tau_data_max=tau_data_max
    )
    out_meta = copy.deepcopy(meta)
    out_meta["piece_id"] = piece_id
    out_meta["tau_peak"] = tau_peak
    peak_out = dict(peak_sel)
    peak_out["tau_peak"] = tau_peak
    peak_out["mu_peak"] = float(selection.chosen.mu)
    peak_out["prominence_frac"] = float(selection.chosen.prominence_frac)
    peak_out["phase"] = float(selection.chosen.phase)
    peak_out["class_tau"] = [float(t) for t in selection.class_tau]
    peak_out["support_half_width"] = float(support)
    peak_out["support_half_width_phase"] = float(support / period)
    old_reason = str(peak_out.get("reason", ""))
    peak_out["reason"] = (
        f"{selection.reason}. Original primary: {old_reason}"
    )
    out_meta["peak_selection"] = peak_out
    out_meta["derive_secondary"] = {
        "method": cfg.method,
        "phase_offset": float(cfg.phase_offset),
        "phase_tolerance": float(cfg.phase_tolerance),
        "source_template_dir": str(source_dir),
        "tau_peak_original": tau_primary,
        "tau_peak_secondary": tau_peak,
        "phase_primary": selection.phase_primary,
        "phase_target": selection.phase_target,
        "phase_selected": float(selection.chosen.phase),
        "phase_distance_to_target": selection.phase_distance,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": (
            "GP mean/sigma grid copied; only tau_peak was relabelled to the "
            "other accepted minimum class. Source template was not modified."
        ),
    }
    (dest_dir / "template_meta.json").write_text(
        json.dumps(out_meta, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "Piece %s: derived secondary template from %s -> %s "
        "(tau_peak %.8f d -> %.8f d, phase %.4f)",
        piece_id,
        source_dir,
        dest_dir,
        tau_primary,
        tau_peak,
        selection.chosen.phase,
    )
    return dest_dir
