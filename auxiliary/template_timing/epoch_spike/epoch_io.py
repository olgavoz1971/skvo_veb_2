"""Load stored templates and write spike ASCII/CSV exports."""

from __future__ import annotations

import copy
import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from astropy import units as u
from scipy.interpolate import CubicSpline

logger = logging.getLogger(__name__)

_REQUIRED_META = (
    "extrema_mode",
    "fold_period",
    "tau_data_min",
    "tau_data_max",
)
_REQUIRED_NPZ = ("tau", "mu", "sigma", "tau_peak")


@dataclass
class LoadedTemplate:
    """GP template grid plus fold metadata from disk."""

    tau: np.ndarray
    mu: np.ndarray
    sigma: np.ndarray
    tau_peak: float
    extrema_mode: str
    fold_period: float
    tau_data_min: float
    tau_data_max: float
    mu_spline: CubicSpline
    sigma_spline: CubicSpline
    dmu_spline: CubicSpline
    meta: dict
    npz_path: Path
    meta_path: Path


def days_to_seconds(delta_days: float) -> float:
    """Convert a time difference in days to seconds.

    Args:
        delta_days (float): Interval in days.

    Returns:
        float: Interval in seconds.
    """
    return float((delta_days * u.day).to(u.s).value)


def load_template_dir(template_dir: Path) -> LoadedTemplate:
    """Load ``template.npz`` and ``template_meta.json`` from a piece directory.

    Args:
        template_dir (Path): Directory holding the Step 1 artefacts.

    Returns:
        LoadedTemplate: Sorted grid, splines, and required metadata.

    Raises:
        FileNotFoundError: If an artefact file is missing.
        ValueError: If required keys are absent or the grid is unusable.
    """
    npz_path = template_dir / "template.npz"
    meta_path = template_dir / "template_meta.json"
    data = np.load(npz_path)
    missing_npz = [key for key in _REQUIRED_NPZ if key not in data]
    if missing_npz:
        raise ValueError(f"{npz_path}: missing arrays {missing_npz}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        raise ValueError(f"{meta_path}: root must be a mapping")
    missing_meta = [key for key in _REQUIRED_META if key not in meta]
    if missing_meta:
        raise ValueError(f"{meta_path}: missing keys {missing_meta}")

    extrema_mode = str(meta["extrema_mode"])
    if extrema_mode not in {"min", "max"}:
        raise ValueError(f"{meta_path}: extrema_mode must be min or max, got {extrema_mode!r}")

    order = np.argsort(np.asarray(data["tau"], dtype=float))
    tau = np.asarray(data["tau"], dtype=float)[order]
    mu = np.asarray(data["mu"], dtype=float)[order]
    sigma = np.asarray(data["sigma"], dtype=float)[order]
    if tau.size < 8:
        raise ValueError(f"{npz_path}: grid too short ({tau.size} points)")
    if np.any(np.diff(tau) <= 0):
        raise ValueError(f"{npz_path}: tau must be strictly increasing")
    if np.any(sigma <= 0):
        raise ValueError(f"{npz_path}: sigma must be positive")

    tau_peak = float(data["tau_peak"])
    tau_data_min = float(meta["tau_data_min"])
    tau_data_max = float(meta["tau_data_max"])
    if tau_data_max <= tau_data_min:
        raise ValueError(
            f"{meta_path}: empty data tau range [{tau_data_min}, {tau_data_max}]"
        )
    if not (tau_data_min <= tau_peak <= tau_data_max):
        raise ValueError(
            f"{npz_path}: tau_peak={tau_peak} lies outside data range "
            f"[{tau_data_min}, {tau_data_max}]"
        )

    mu_spline = CubicSpline(tau, mu, extrapolate=False)
    sigma_spline = CubicSpline(tau, sigma, extrapolate=False)
    loaded = LoadedTemplate(
        tau=tau,
        mu=mu,
        sigma=sigma,
        tau_peak=tau_peak,
        extrema_mode=extrema_mode,
        fold_period=float(meta["fold_period"]),
        tau_data_min=tau_data_min,
        tau_data_max=tau_data_max,
        mu_spline=mu_spline,
        sigma_spline=sigma_spline,
        dmu_spline=mu_spline.derivative(),
        meta=meta,
        npz_path=npz_path,
        meta_path=meta_path,
    )
    logger.info(
        "Loaded template %s: extrema_mode=%s tau_peak=%.6f P=%.8f d",
        npz_path.parent.name,
        loaded.extrema_mode,
        loaded.tau_peak,
        loaded.fold_period,
    )
    return loaded


def write_commented_table(
    path: Path,
    *,
    provenance: dict[str, str],
    fieldnames: list[str],
    rows: list[dict],
) -> None:
    """Write a CSV with ``# key: value`` provenance lines and Unix newlines.

    Args:
        path (Path): Output path.
        provenance (dict[str, str]): Comment metadata.
        fieldnames (list[str]): Column names.
        rows (list[dict]): Data rows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for key, value in provenance.items():
            handle.write(f"# {key}: {value}\n")
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    logger.info("Wrote %s (%s rows)", path, len(rows))


def default_provenance(*, study_label: str, template_dir: Path) -> dict[str, str]:
    """Build standard provenance for spike exports.

    Args:
        study_label (str): Human-readable study name.
        template_dir (Path): Template directory that was read.

    Returns:
        dict[str, str]: Provenance mapping.
    """
    return {
        "spike": "epoch_spike",
        "study": study_label,
        "template_dir": str(template_dir.resolve()),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "source template.npz and template_meta.json were not modified",
    }


def write_corrected_template(
    template: LoadedTemplate,
    *,
    tau_peak: float,
    method: str,
    dest_dir: Path,
    study_label: str,
    copy_lo: float,
    copy_hi: float,
) -> None:
    """Write a reusable template bundle with a relabelled ``tau_peak``.

    The GP grid (``tau``, ``mu``, ``sigma``) is copied unchanged. Only the painted
    extremum time is replaced. The source directory is never written.

    Args:
        template (LoadedTemplate): Source template (read-only).
        tau_peak (float): Corrected fold epoch in days.
        method (str): Estimator name stored in metadata.
        dest_dir (Path): New directory for ``template.npz`` and ``template_meta.json``.
        study_label (str): Spike study label for provenance.
        copy_lo (float): Isolated-copy lower bound used in the spike.
        copy_hi (float): Isolated-copy upper bound used in the spike.

    Raises:
        ValueError: If ``dest_dir`` is the source directory or ``tau_peak`` is
            outside the photometric copy window.
    """
    dest_dir = dest_dir.resolve()
    source_dir = template.npz_path.parent.resolve()
    if dest_dir == source_dir:
        raise ValueError(
            f"refusing to overwrite source template directory {source_dir}"
        )
    if not (copy_lo <= tau_peak <= copy_hi):
        raise ValueError(
            f"corrected tau_peak={tau_peak} lies outside the isolated copy window "
            f"[{copy_lo}, {copy_hi}]; choose another export_template.method "
            "or inspect the ladder"
        )
    if not (template.tau_data_min <= tau_peak <= template.tau_data_max):
        raise ValueError(
            f"corrected tau_peak={tau_peak} lies outside the photometric data range "
            f"[{template.tau_data_min}, {template.tau_data_max}]"
        )
    mu_peak = float(template.mu_spline(tau_peak))
    if not np.isfinite(mu_peak):
        raise ValueError(f"GP mean is non-finite at corrected tau_peak={tau_peak}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    np.savez(
        dest_dir / "template.npz",
        tau=template.tau,
        mu=template.mu,
        sigma=template.sigma,
        tau_peak=np.asarray(tau_peak),
    )

    meta = copy.deepcopy(template.meta)
    original = float(template.tau_peak)
    meta["tau_peak"] = tau_peak
    peak_sel = meta.get("peak_selection")
    if isinstance(peak_sel, dict):
        peak_sel = dict(peak_sel)
        peak_sel["tau_peak"] = tau_peak
        peak_sel["mu_peak"] = mu_peak
        peak_sel["phase"] = float((tau_peak / template.fold_period) % 1.0)
        old_reason = str(peak_sel.get("reason", ""))
        peak_sel["reason"] = (
            f"epoch_spike {method}: tau_peak relabelled from {original:.8f} d "
            f"to {tau_peak:.8f} d (GP grid unchanged). Original: {old_reason}"
        )
        meta["peak_selection"] = peak_sel
    meta["epoch_spike"] = {
        "study": study_label,
        "method": method,
        "source_template_dir": str(source_dir),
        "tau_peak_original": original,
        "tau_peak_corrected": tau_peak,
        "delta_seconds": days_to_seconds(tau_peak - original),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": (
            "GP mean/sigma grid copied; only tau_peak was changed. "
            "Point run_timing existing_template_dir at this folder."
        ),
    }
    meta_path = dest_dir / "template_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info(
        "Wrote corrected template for reuse (%s): tau_peak %.8f d -> %.8f d "
        "(%.3f s) in %s",
        method,
        original,
        tau_peak,
        days_to_seconds(tau_peak - original),
        dest_dir,
    )
