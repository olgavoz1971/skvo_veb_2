"""Load and validate template-timing run manifests (YAML)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from skvo_veb.utils.gp.intervals import load_intervals
from template_reuse import _require_template_files

logger = logging.getLogger(__name__)

TIMING_METHODS = frozenset({"cc", "nls", "nls_clean", "nls_scale_clean"})
ERROR_MODELS = frozenset({"rms_slope", "none"})


@dataclass
class TimeWindow:
    """Truncated JD interval ``[t_min, t_max]`` inclusive."""

    t_min: float
    t_max: float

    def __post_init__(self) -> None:
        if self.t_max < self.t_min:
            raise ValueError(f"time window invalid: {self.t_min} > {self.t_max}")


@dataclass
class GPTemplateDefaults:
    """Step 1 Gaussian process template hyperparameters."""

    extended_fold: bool = True
    extrema_mode: str = "max"
    kernel_type: str = "matern"
    length_scale_init: float = 0.02
    length_scale_min: float = 0.01
    length_scale_max: float = 0.026
    amplitude_init: float = 0.3
    amplitude_min: float = 0.1
    amplitude_max: float = 0.7
    guess_sigma: bool = False
    noise_scale_divisor: float = 1.0
    n_grid: int = 2000
    n_restarts: int = 3
    peak_local_order: int = 20
    peak_pair_period_tol: float = 0.15
    peak_min_prominence_frac: float = 0.5
    mask_length_scale_factor: float = 2.5
    mask_min_half_width: float = 0.012


@dataclass
class FitDefaults:
    """Step 2 template shift fit controls."""

    delta_tau_margin: float = 0.003
    delta_tau_max: float = 0.02
    outlier_mad_k: float = 3.0
    outlier_max_iter: int = 8
    outlier_min_inliers: int = 8
    scale_min: float = 0.05
    scale_max: float = 5.0
    tau_mask_min_fallback: float = 0.035
    tau_mask_max_fallback: float = 0.095


@dataclass
class PieceConfig:
    """One dense segment: build template and fit intervals."""

    piece_id: str
    template_window: TimeWindow
    fit_window: TimeWindow
    intervals_path: Path
    local_period: float | None = None
    reuse_template_from: str | None = None
    existing_template_dir: Path | None = None
    gp_template: GPTemplateDefaults = field(default_factory=GPTemplateDefaults)
    fit: FitDefaults = field(default_factory=FitDefaults)


@dataclass
class RunManifest:
    """Full orchestrator configuration."""

    manifest_path: Path
    lc_path: Path
    mag0: float | None
    t_ref: float
    p0: float
    period_slope: float
    timing_method: str
    error_model: str
    run_dir: Path
    save_interval_plots: bool
    save_overview: bool
    overview_t_min: float | None
    overview_t_max: float | None
    gp_template_defaults: GPTemplateDefaults
    fit_defaults: FitDefaults
    pieces: list[PieceConfig]


def _resolve_path(base: Path, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def _window_from_mapping(data: dict[str, Any]) -> TimeWindow:
    return TimeWindow(t_min=float(data["t_min"]), t_max=float(data["t_max"]))


def _gp_from_mapping(data: dict[str, Any] | None, defaults: GPTemplateDefaults) -> GPTemplateDefaults:
    if not data:
        return defaults
    merged = {**defaults.__dict__, **data}
    return GPTemplateDefaults(**merged)


def _fit_from_mapping(data: dict[str, Any] | None, defaults: FitDefaults) -> FitDefaults:
    if not data:
        return defaults
    merged = {**defaults.__dict__, **data}
    return FitDefaults(**merged)


def _validate_intervals_in_window(intervals_path: Path, window: TimeWindow, piece_id: str) -> None:
    with intervals_path.open(encoding="utf-8") as handle:
        intervals = load_intervals(handle)
    if not intervals:
        raise ValueError(f"piece {piece_id}: no intervals in {intervals_path}")
    for idx, (t_start, t_end) in enumerate(intervals):
        lo, hi = (t_start, t_end) if t_start <= t_end else (t_end, t_start)
        if lo < window.t_min or hi > window.t_max:
            raise ValueError(
                f"piece {piece_id}: interval {idx} [{lo}, {hi}] "
                f"outside fit_window [{window.t_min}, {window.t_max}]"
            )


def _validate_piece_template_sources(pieces: list[PieceConfig], global_p0: float) -> None:
    """At most one Step 1 skip source per piece; paths and reuse graph valid."""
    ids = [p.piece_id for p in pieces]
    id_set = set(ids)
    if len(ids) != len(id_set):
        raise ValueError("piece_id values must be unique")

    index_of = {pid: i for i, pid in enumerate(ids)}

    for piece in pieces:
        n_sources = sum(
            1
            for flag in (piece.reuse_template_from, piece.existing_template_dir)
            if flag is not None
        )
        if n_sources > 1:
            raise ValueError(
                f"piece {piece.piece_id}: use only one of "
                f"existing_template_dir or reuse_template_from"
            )

        if piece.existing_template_dir is not None:
            _require_template_files(
                piece.existing_template_dir,
                context=f"piece {piece.piece_id} existing_template_dir",
            )
            meta = json.loads(
                (piece.existing_template_dir / "template_meta.json").read_text(
                    encoding="utf-8"
                )
            )
            loaded_p = meta.get("p0", global_p0)
            if piece_fold_period(piece, global_p0) != float(loaded_p):
                raise ValueError(
                    f"piece {piece.piece_id}: fold period {piece_fold_period(piece, global_p0)} "
                    f"does not match template meta p0={loaded_p} in "
                    f"{piece.existing_template_dir}"
                )

        source_id = piece.reuse_template_from
        if source_id is None:
            continue
        if source_id == piece.piece_id:
            raise ValueError(f"piece {piece.piece_id}: cannot reuse_template_from itself")
        if source_id not in id_set:
            raise ValueError(
                f"piece {piece.piece_id}: reuse_template_from unknown piece {source_id!r}"
            )
        if index_of[source_id] >= index_of[piece.piece_id]:
            raise ValueError(
                f"piece {piece.piece_id}: reuse_template_from {source_id!r} must appear "
                f"earlier in the pieces list (source is built first)"
            )
        source = pieces[index_of[source_id]]
        if piece_fold_period(piece, global_p0) != piece_fold_period(source, global_p0):
            raise ValueError(
                f"piece {piece.piece_id}: fold period must match reuse source {source_id} "
                f"(check local_period vs global ephemeris p0)"
            )


def _validate_reuse_template(pieces: list[PieceConfig], global_p0: float) -> None:
    _validate_piece_template_sources(pieces, global_p0)


def load_manifest(path: Path, *, validate_intervals: bool = True) -> RunManifest:
    """Parse YAML manifest; paths relative to the manifest file directory."""
    manifest_path = path.resolve()
    base = manifest_path.parent
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest root must be a mapping")

    global_cfg = raw.get("global")
    if not isinstance(global_cfg, dict):
        raise ValueError("global section required")

    ephem = global_cfg.get("ephemeris")
    if not isinstance(ephem, dict):
        raise ValueError("global.ephemeris required")
    t_ref = float(ephem["t_ref"])
    p0 = float(ephem["p0"])
    period_slope = float(ephem.get("period_slope", 0.0))

    timing = global_cfg.get("timing")
    if not isinstance(timing, dict):
        raise ValueError("global.timing required")
    timing_method = str(timing["method"])
    if timing_method not in TIMING_METHODS:
        raise ValueError(f"unknown timing.method {timing_method!r}")
    error_model = str(timing.get("error_model", "none"))
    if error_model not in ERROR_MODELS:
        raise ValueError(f"unknown timing.error_model {error_model!r}")

    output = global_cfg.get("output")
    if not isinstance(output, dict):
        raise ValueError("global.output required")
    run_dir = _resolve_path(base, str(output["run_dir"]))

    plots = global_cfg.get("plots") or {}
    save_interval_plots = bool(plots.get("save_interval_plots", True))
    save_overview = bool(plots.get("save_overview", True))
    overview_t_min = plots.get("overview_t_min")
    overview_t_max = plots.get("overview_t_max")
    overview_t_min = None if overview_t_min is None else float(overview_t_min)
    overview_t_max = None if overview_t_max is None else float(overview_t_max)

    gp_defaults = _gp_from_mapping(raw.get("gp_template_defaults"), GPTemplateDefaults())
    fit_defaults = _fit_from_mapping(raw.get("fit_defaults"), FitDefaults())

    lc_path = _resolve_path(base, str(global_cfg["lc_path"]))
    if not lc_path.is_file():
        raise FileNotFoundError(f"lc_path not found: {lc_path}")

    mag0_raw = global_cfg.get("mag0")
    mag0 = None if mag0_raw is None else float(mag0_raw)

    pieces_raw = raw.get("pieces")
    if not isinstance(pieces_raw, list) or not pieces_raw:
        raise ValueError("pieces must be a non-empty list")

    pieces: list[PieceConfig] = []
    for entry in pieces_raw:
        if not isinstance(entry, dict):
            raise ValueError("each piece must be a mapping")
        piece_id = str(entry["piece_id"])
        template_window = _window_from_mapping(entry["template_window"])
        fit_window = _window_from_mapping(entry["fit_window"])
        intervals_path = _resolve_path(base, str(entry["intervals_path"]))
        if not intervals_path.is_file():
            raise FileNotFoundError(f"piece {piece_id}: intervals not found: {intervals_path}")
        local_period = entry.get("local_period")
        local_period = None if local_period is None else float(local_period)
        reuse_raw = entry.get("reuse_template_from")
        reuse_template_from = None if reuse_raw is None else str(reuse_raw)
        existing_raw = entry.get("existing_template_dir")
        existing_template_dir = (
            None if existing_raw is None else _resolve_path(base, str(existing_raw))
        )
        gp_piece = _gp_from_mapping(entry.get("gp_template"), gp_defaults)
        fit_piece = _fit_from_mapping(entry.get("fit"), fit_defaults)
        if validate_intervals:
            _validate_intervals_in_window(intervals_path, fit_window, piece_id)
        pieces.append(
            PieceConfig(
                piece_id=piece_id,
                template_window=template_window,
                fit_window=fit_window,
                intervals_path=intervals_path,
                local_period=local_period,
                reuse_template_from=reuse_template_from,
                existing_template_dir=existing_template_dir,
                gp_template=gp_piece,
                fit=fit_piece,
            )
        )

    _validate_piece_template_sources(pieces, p0)

    logger.info(
        "Loaded manifest %s: %s piece(s), lc=%s, method=%s",
        manifest_path.name,
        len(pieces),
        lc_path.name,
        timing_method,
    )
    return RunManifest(
        manifest_path=manifest_path,
        lc_path=lc_path,
        mag0=mag0,
        t_ref=t_ref,
        p0=p0,
        period_slope=period_slope,
        timing_method=timing_method,
        error_model=error_model,
        run_dir=run_dir,
        save_interval_plots=save_interval_plots,
        save_overview=save_overview,
        overview_t_min=overview_t_min,
        overview_t_max=overview_t_max,
        gp_template_defaults=gp_defaults,
        fit_defaults=fit_defaults,
        pieces=pieces,
    )


def piece_fold_period(piece: PieceConfig, global_p0: float) -> float:
    """Period used to fold tau for a piece (local override or global)."""
    return piece.local_period if piece.local_period is not None else global_p0
