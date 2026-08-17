"""Load and validate template-timing run manifests (YAML)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from skvo_veb.utils.gp.intervals import load_intervals
from skvo_veb.utils.lc_config import DOMAIN_MAG, JD_TO_MJD
from fit_mask import validate_fit_mask_settings
from template_reuse import _require_template_files

logger = logging.getLogger(__name__)

TIMING_METHODS = frozenset({"cc", "nls", "nls_clean", "nls_scale_clean"})
ERROR_MODELS = frozenset({"rms_slope", "none"})
TIMING_MODES = frozenset({"per_interval", "segment_anchor"})
ANCHOR_EPOCH_KINDS = frozenset({"window_centre", "window_start", "window_end"})
TIME_SCALES = frozenset({"jd", "mjd", "jd_offset"})
PHOTOMETRY_DOMAINS = frozenset({"mag", "flux"})
EXTREMA_MODES = frozenset({"max", "min"})
PEAK_SELECT_RULES = frozenset({"dominant", "nearest_phase0"})

# Peak-selection keys removed in the prominence-based rewrite, with migration advice.
REMOVED_GP_KEYS = {
    "peak_local_order": "replaced by peak_min_separation_frac_period, a fraction of the period",
    "peak_pair_period_tol": "replaced by peak_duplicate_phase_tol, in phase units",
    "peak_pair_height_similarity_tol": "no longer needed: copies are grouped by phase",
    "mask_length_scale_factor": "the Step 2 window is now fit_mask_mode under fit_defaults / fit",
    "mask_min_half_width": "the Step 2 window is now fit_mask_mode under fit_defaults / fit",
    "mask_max_half_width_frac_period": (
        "replaced by fit_mask_half_width_phase under fit_defaults / fit"
    ),
}

# Step 2 keys removed together with the GP-derived mask.
REMOVED_FIT_KEYS = {
    "tau_mask_min_fallback": "the fit window is now always resolved from fit_mask_mode",
    "tau_mask_max_fallback": "the fit window is now always resolved from fit_mask_mode",
}


@dataclass(frozen=True)
class TimeScaleConfig:
    """Input time coordinates before conversion to absolute Julian Date."""

    scale: str
    zero: float | None = None

    def __post_init__(self) -> None:
        if self.scale not in TIME_SCALES:
            raise ValueError(
                f"time scale must be one of {sorted(TIME_SCALES)}, got {self.scale!r}"
            )
        if self.scale == "jd_offset" and self.zero is None:
            raise ValueError("zero is required when scale is jd_offset")
        if self.scale != "jd_offset" and self.zero is not None:
            raise ValueError(
                f"zero must be omitted unless scale is jd_offset "
                f"(got scale={self.scale!r})"
            )

    def to_absolute_jd(self, value: float) -> float:
        """Convert a manifest time value to absolute Julian Date (days)."""
        if self.scale == "jd":
            return float(value)
        if self.scale == "mjd":
            return float(value) + JD_TO_MJD
        assert self.zero is not None
        return float(value) + float(self.zero)


@dataclass
class TimeWindow:
    """Absolute JD interval ``[t_min, t_max]`` inclusive."""

    t_min: float
    t_max: float

    def __post_init__(self) -> None:
        if self.t_max < self.t_min:
            raise ValueError(f"time window invalid: {self.t_min} > {self.t_max}")


FOLD_EPHEMERIS_KINDS = frozenset({"quadratic", "quadratic_oc"})


@dataclass(frozen=True)
class FoldEphemerisConfig:
    """Step 1 quadratic O-C fold for template stacking."""

    kind: str
    oc_a: float
    oc_b: float
    oc_c: float
    tau_period: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in FOLD_EPHEMERIS_KINDS:
            raise ValueError(
                f"fold_ephemeris.kind must be one of {sorted(FOLD_EPHEMERIS_KINDS)}, "
                f"got {self.kind!r}"
            )


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
    peak_edge_margin_frac_period: float = 0.05
    peak_min_separation_frac_period: float = 0.15
    peak_min_prominence_frac: float = 0.25
    peak_duplicate_phase_tol: float = 0.05
    peak_select: str = "dominant"
    peak_tau_hint: float | None = None

    def __post_init__(self) -> None:
        if self.extrema_mode not in EXTREMA_MODES:
            raise ValueError(
                f"gp_template.extrema_mode must be one of {sorted(EXTREMA_MODES)}, "
                f"got {self.extrema_mode!r}"
            )
        if self.peak_select not in PEAK_SELECT_RULES:
            raise ValueError(
                f"gp_template.peak_select must be one of {sorted(PEAK_SELECT_RULES)}, "
                f"got {self.peak_select!r}"
            )


@dataclass
class FitDefaults:
    """Step 2 template shift fit controls."""

    fit_mask_mode: str = "whole_period"
    fit_mask_half_width_phase: float = 0.25
    delta_tau_margin: float = 0.003
    delta_tau_max: float = 0.02
    outlier_mad_k: float = 3.0
    outlier_max_iter: int = 8
    outlier_min_inliers: int = 8
    scale_min: float = 0.05
    scale_max: float = 5.0

    def __post_init__(self) -> None:
        validate_fit_mask_settings(
            self.fit_mask_mode,
            self.fit_mask_half_width_phase,
            context="fit",
        )


@dataclass
class PieceConfig:
    """One dense segment: build template and fit intervals."""

    piece_id: str
    fit_window: TimeWindow
    template_window: TimeWindow | None = None
    intervals_path: Path | None = None
    timing_mode: str = "per_interval"
    anchor_epoch: str = "window_centre"
    local_period: float | None = None
    local_epoch: float | None = None
    fold_ephemeris: FoldEphemerisConfig | None = None
    local_lc_path: Path | None = None
    reuse_template_from: str | None = None
    existing_template_dir: Path | None = None
    skip: bool = False
    gp_template: GPTemplateDefaults = field(default_factory=GPTemplateDefaults)
    fit: FitDefaults = field(default_factory=FitDefaults)

    def __post_init__(self) -> None:
        if self.timing_mode not in TIMING_MODES:
            raise ValueError(
                f"piece {self.piece_id}: timing_mode must be one of "
                f"{sorted(TIMING_MODES)}, got {self.timing_mode!r}"
            )
        if self.anchor_epoch not in ANCHOR_EPOCH_KINDS:
            raise ValueError(
                f"piece {self.piece_id}: anchor_epoch must be one of "
                f"{sorted(ANCHOR_EPOCH_KINDS)}, got {self.anchor_epoch!r}"
            )
        if self.timing_mode == "per_interval" and self.intervals_path is None:
            raise ValueError(
                f"piece {self.piece_id}: intervals_path required for timing_mode=per_interval"
            )
        if self.timing_mode == "segment_anchor" and self.fold_ephemeris is not None:
            raise ValueError(
                f"piece {self.piece_id}: segment_anchor ensemble ToM supports "
                f"constant period only; omit fold_ephemeris"
            )


@dataclass
class RunManifest:
    """Full orchestrator configuration."""

    manifest_path: Path
    lc_path: Path
    manifest_time: TimeScaleConfig
    intervals_time: TimeScaleConfig | None
    photometry_domain: str
    default_epoch: float
    default_period: float
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


def _parse_fold_ephemeris(
    entry: dict[str, Any],
    *,
    piece_id: str,
) -> FoldEphemerisConfig | None:
    """Parse optional ``fold_ephemeris`` on a piece."""
    raw = entry.get("fold_ephemeris")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"piece {piece_id}: fold_ephemeris must be a mapping")
    kind = str(raw.get("kind", "quadratic"))
    missing = [key for key in ("a", "b", "c") if key not in raw]
    if missing:
        raise ValueError(
            f"piece {piece_id}: fold_ephemeris requires {missing} for kind {kind!r}"
        )
    tau_raw = raw.get("tau_period")
    tau_period = None if tau_raw is None else float(tau_raw)
    return FoldEphemerisConfig(
        kind=kind,
        oc_a=float(raw["a"]),
        oc_b=float(raw["b"]),
        oc_c=float(raw["c"]),
        tau_period=tau_period,
    )


def _parse_time_scale_block(raw: dict[str, Any], *, block_name: str) -> TimeScaleConfig:
    """Parse a ``scale`` (+ optional ``zero``) mapping to :class:`TimeScaleConfig`."""
    if not isinstance(raw, dict):
        raise ValueError(f"{block_name} must be a mapping (scale: jd | mjd | jd_offset)")
    if "scale" not in raw:
        raise ValueError(f"{block_name}.scale required (jd | mjd | jd_offset)")
    scale = str(raw["scale"])
    zero_raw = raw.get("zero")
    zero = None if zero_raw is None else float(zero_raw)
    try:
        return TimeScaleConfig(scale=scale, zero=zero)
    except ValueError as exc:
        raise ValueError(f"{block_name}: {exc}") from exc


def _parse_manifest_time(global_cfg: dict[str, Any]) -> TimeScaleConfig:
    """Parse ``global.manifest_time`` (epochs and windows written in the YAML)."""
    if "time" in global_cfg:
        raise ValueError(
            "global.time is removed; use global.manifest_time for manifest "
            "epochs/windows and global.intervals_time for interval .dat files"
        )
    raw = global_cfg.get("manifest_time")
    if not isinstance(raw, dict):
        raise ValueError(
            "global.manifest_time required (scale: jd | mjd | jd_offset); "
            "applies to template_fold.default_epoch, piece windows, and local_epoch"
        )
    return _parse_time_scale_block(raw, block_name="global.manifest_time")


def _parse_intervals_time(
    global_cfg: dict[str, Any],
    *,
    required: bool,
) -> TimeScaleConfig | None:
    """Parse ``global.intervals_time`` for two-column interval .dat files."""
    raw = global_cfg.get("intervals_time")
    if raw is None:
        if required:
            raise ValueError(
                "global.intervals_time required when any active piece uses "
                "timing_mode=per_interval (scale: jd | mjd | jd_offset)"
            )
        return None
    return _parse_time_scale_block(raw, block_name="global.intervals_time")


def _parse_photometry_domain(global_cfg: dict[str, Any]) -> str:
    """Parse ``global.photometry_domain`` (default ``mag``)."""
    domain = str(global_cfg.get("photometry_domain", DOMAIN_MAG))
    if domain not in PHOTOMETRY_DOMAINS:
        raise ValueError(
            f"global.photometry_domain must be one of {sorted(PHOTOMETRY_DOMAINS)}, "
            f"got {domain!r}"
        )
    return domain


def _window_from_mapping(
    data: dict[str, Any],
    time: TimeScaleConfig,
    *,
    context: str,
) -> TimeWindow:
    """Parse ``t_min`` / ``t_max`` and convert to absolute JD."""
    if "t_min" not in data or "t_max" not in data:
        raise ValueError(f"{context}: time window requires t_min and t_max")
    t_min_raw = data["t_min"]
    t_max_raw = data["t_max"]
    if t_min_raw is None or t_max_raw is None:
        raise ValueError(f"{context}: t_min and t_max must not be null")
    t_min = time.to_absolute_jd(float(t_min_raw))
    t_max = time.to_absolute_jd(float(t_max_raw))
    return TimeWindow(t_min=t_min, t_max=t_max)


def resolve_anchor_jd(window: TimeWindow, anchor_epoch: str) -> float:
    """Map ``anchor_epoch`` to a calendar JD inside ``fit_window``.

    Args:
        window (TimeWindow): Step 2 fit window.
        anchor_epoch (str): ``window_centre``, ``window_start``, or ``window_end``.

    Returns:
        float: Reference time for :class:`~template_fit.IntervalFitContext`.
    """
    if anchor_epoch == "window_centre":
        return 0.5 * (window.t_min + window.t_max)
    if anchor_epoch == "window_start":
        return window.t_min
    if anchor_epoch == "window_end":
        return window.t_max
    raise ValueError(f"unsupported anchor_epoch: {anchor_epoch!r}")


def piece_template_window(piece: PieceConfig) -> TimeWindow:
    """Return the Step 1 template window for a piece."""
    if piece.template_window is not None:
        return piece.template_window
    if piece.timing_mode == "segment_anchor":
        return piece.fit_window
    raise ValueError(f"piece {piece.piece_id}: template_window required")


def _gp_from_mapping(data: dict[str, Any] | None, defaults: GPTemplateDefaults) -> GPTemplateDefaults:
    if not data:
        return defaults
    kept = {}
    for key, value in data.items():
        if key in REMOVED_GP_KEYS:
            logger.warning(
                "gp_template key %r was removed and is ignored (%s)",
                key,
                REMOVED_GP_KEYS[key],
            )
            continue
        kept[key] = value
    merged = {**defaults.__dict__, **kept}
    return GPTemplateDefaults(**merged)


def _fit_from_mapping(data: dict[str, Any] | None, defaults: FitDefaults) -> FitDefaults:
    if not data:
        return defaults
    kept = {}
    for key, value in data.items():
        if key in REMOVED_FIT_KEYS:
            logger.warning(
                "fit key %r was removed and is ignored (%s)",
                key,
                REMOVED_FIT_KEYS[key],
            )
            continue
        kept[key] = value
    merged = {**defaults.__dict__, **kept}
    return FitDefaults(**merged)


def _interval_bounds(t_start: float, t_end: float) -> tuple[float, float]:
    """Return ``(lo, hi)`` with ``lo <= hi``."""
    return (t_start, t_end) if t_start <= t_end else (t_end, t_start)


def interval_overlaps_fit_window(
    t_start: float,
    t_end: float,
    *,
    fit_t_min: float,
    fit_t_max: float,
) -> bool:
    """True if the interval intersects ``[fit_t_min, fit_t_max]`` (inclusive)."""
    lo, hi = _interval_bounds(t_start, t_end)
    return hi >= fit_t_min and lo <= fit_t_max


def load_intervals_absolute(
    path: Path,
    time: TimeScaleConfig,
) -> list[tuple[float, float]]:
    """Load interval pairs and convert file times to absolute JD.

    Args:
        path (Path): Two-column interval file.
        time (TimeScaleConfig): ``global.intervals_time`` block.

    Returns:
        list[tuple[float, float]]: ``(t_start, t_end)`` pairs in absolute JD.
    """
    with path.open(encoding="utf-8") as handle:
        raw = load_intervals(handle)
    if not raw:
        return []
    return [
        (time.to_absolute_jd(float(a)), time.to_absolute_jd(float(b)))
        for a, b in raw
    ]


def _validate_intervals_in_window(
    intervals_path: Path,
    window: TimeWindow,
    piece_id: str,
    time: TimeScaleConfig,
) -> None:
    """Require at least one interval overlapping ``fit_window``; extras may lie outside."""
    intervals = load_intervals_absolute(intervals_path, time)
    if not intervals:
        raise ValueError(f"piece {piece_id}: no intervals in {intervals_path}")
    n_overlap = 0
    for idx, (t_start, t_end) in enumerate(intervals):
        lo, hi = _interval_bounds(t_start, t_end)
        if interval_overlaps_fit_window(
            t_start, t_end, fit_t_min=window.t_min, fit_t_max=window.t_max
        ):
            n_overlap += 1
        else:
            logger.info(
                "piece %s: interval %s [%.5f, %.5f] does not overlap fit_window "
                "[%.5f, %.5f]; will skip at fit time",
                piece_id,
                idx,
                lo,
                hi,
                window.t_min,
                window.t_max,
            )
    if n_overlap == 0:
        raise ValueError(
            f"piece {piece_id}: no interval in {intervals_path.name} overlaps "
            f"fit_window [{window.t_min}, {window.t_max}]"
        )


def _parse_template_fold_block(
    global_cfg: dict[str, Any],
    time: TimeScaleConfig,
) -> tuple[float, float, float]:
    """Step 1 fold defaults: ``default_epoch``, ``default_period``, ``period_slope``.

    Accepts ``global.template_fold`` (preferred) or legacy ``global.ephemeris``.
    Epoch values are converted to absolute JD via ``time``.
    """
    block = global_cfg.get("template_fold")
    if block is None:
        block = global_cfg.get("ephemeris")
    if not isinstance(block, dict):
        raise ValueError(
            "global.template_fold required (default_epoch, default_period); "
            "legacy global.ephemeris also accepted"
        )
    if "default_epoch" in block:
        default_epoch = time.to_absolute_jd(float(block["default_epoch"]))
    elif "t_ref" in block:
        default_epoch = time.to_absolute_jd(float(block["t_ref"]))
        if global_cfg.get("template_fold") is not None:
            logger.warning(
                "template_fold.t_ref is deprecated; use template_fold.default_epoch"
            )
    else:
        raise ValueError("template_fold.default_epoch (or legacy t_ref) required")
    if "default_period" in block:
        default_period = float(block["default_period"])
    elif "p0" in block:
        default_period = float(block["p0"])
        logger.warning(
            "global.ephemeris.p0 is deprecated; use template_fold.default_period"
        )
    else:
        raise ValueError("template_fold.default_period (or legacy p0) required")
    period_slope = float(block.get("period_slope", 0.0))
    return default_epoch, default_period, period_slope


def _validate_piece_template_sources(pieces: list[PieceConfig]) -> None:
    """At most one Step 1 skip source per piece; paths and reuse graph valid."""
    ids = [p.piece_id for p in pieces]
    id_set = set(ids)
    if len(ids) != len(id_set):
        raise ValueError("piece_id values must be unique")

    index_of = {pid: i for i, pid in enumerate(ids)}
    skipped_ids = {p.piece_id for p in pieces if p.skip}

    for piece in pieces:
        if piece.skip:
            continue
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

        source_id = piece.reuse_template_from
        if source_id is None:
            continue
        if source_id == piece.piece_id:
            raise ValueError(f"piece {piece.piece_id}: cannot reuse_template_from itself")
        if source_id not in id_set:
            raise ValueError(
                f"piece {piece.piece_id}: reuse_template_from unknown piece {source_id!r}"
            )
        if source_id in skipped_ids:
            raise ValueError(
                f"piece {piece.piece_id}: reuse_template_from {source_id!r} "
                f"but that piece has skip: true"
            )
        if index_of[source_id] >= index_of[piece.piece_id]:
            raise ValueError(
                f"piece {piece.piece_id}: reuse_template_from {source_id!r} must appear "
                f"earlier in the pieces list (source is built first)"
            )


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

    if "mag0" in global_cfg:
        raise ValueError(
            "global.mag0 is removed; photometric zero points must come from "
            "light-curve metadata (e.g. # MAG0= in .dat or VOTable photcal)"
        )

    manifest_time = _parse_manifest_time(global_cfg)
    photometry_domain = _parse_photometry_domain(global_cfg)

    pieces_raw = raw.get("pieces")
    if not isinstance(pieces_raw, list) or not pieces_raw:
        raise ValueError("pieces must be a non-empty list")

    needs_intervals_time = any(
        not bool(entry.get("skip", False))
        and str(entry.get("timing_mode", "per_interval")) == "per_interval"
        for entry in pieces_raw
        if isinstance(entry, dict)
    )
    intervals_time = _parse_intervals_time(global_cfg, required=needs_intervals_time)

    default_epoch, default_period, period_slope = _parse_template_fold_block(
        global_cfg, manifest_time
    )

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
    overview_t_min = (
        None
        if overview_t_min is None
        else manifest_time.to_absolute_jd(float(overview_t_min))
    )
    overview_t_max = (
        None
        if overview_t_max is None
        else manifest_time.to_absolute_jd(float(overview_t_max))
    )

    gp_defaults = _gp_from_mapping(raw.get("gp_template_defaults"), GPTemplateDefaults())
    fit_defaults = _fit_from_mapping(raw.get("fit_defaults"), FitDefaults())

    lc_path = _resolve_path(base, str(global_cfg["lc_path"]))
    if not lc_path.is_file():
        raise FileNotFoundError(f"lc_path not found: {lc_path}")

    pieces: list[PieceConfig] = []
    for entry in pieces_raw:
        if not isinstance(entry, dict):
            raise ValueError("each piece must be a mapping")
        piece_id = str(entry["piece_id"])
        skip = bool(entry.get("skip", False))
        timing_mode = str(entry.get("timing_mode", "per_interval"))
        if timing_mode not in TIMING_MODES:
            raise ValueError(
                f"piece {piece_id}: unknown timing_mode {timing_mode!r}; "
                f"expected one of {sorted(TIMING_MODES)}"
            )
        template_raw = entry.get("template_window")
        fit_raw = entry.get("fit_window")
        if template_raw is not None:
            template_window = _window_from_mapping(
                template_raw,
                manifest_time,
                context=f"piece {piece_id} template_window",
            )
        else:
            template_window = None
        if fit_raw is None or fit_raw.get("t_min") is None or fit_raw.get("t_max") is None:
            if timing_mode == "segment_anchor" and template_window is not None:
                fit_window = template_window
            else:
                raise ValueError(f"piece {piece_id}: fit_window required")
        else:
            fit_window = _window_from_mapping(
                fit_raw,
                manifest_time,
                context=f"piece {piece_id} fit_window",
            )
        if template_window is None:
            if timing_mode == "segment_anchor":
                template_window = fit_window
            else:
                raise ValueError(f"piece {piece_id}: template_window required")
        anchor_epoch = str(entry.get("anchor_epoch", "window_centre"))
        if anchor_epoch not in ANCHOR_EPOCH_KINDS:
            raise ValueError(
                f"piece {piece_id}: unknown anchor_epoch {anchor_epoch!r}; "
                f"expected one of {sorted(ANCHOR_EPOCH_KINDS)}"
            )
        intervals_raw = entry.get("intervals_path")
        if timing_mode == "segment_anchor":
            intervals_path = (
                None
                if intervals_raw is None
                else _resolve_path(base, str(intervals_raw))
            )
        else:
            if intervals_raw is None:
                raise ValueError(
                    f"piece {piece_id}: intervals_path required for per_interval timing"
                )
            intervals_path = _resolve_path(base, str(intervals_raw))
        if (
            not skip
            and timing_mode == "per_interval"
            and intervals_path is not None
            and not intervals_path.is_file()
        ):
            raise FileNotFoundError(f"piece {piece_id}: intervals not found: {intervals_path}")
        local_period = entry.get("local_period")
        local_period = None if local_period is None else float(local_period)
        local_epoch_raw = entry.get("local_epoch")
        local_epoch = (
            None
            if local_epoch_raw is None
            else manifest_time.to_absolute_jd(float(local_epoch_raw))
        )
        fold_ephemeris = _parse_fold_ephemeris(entry, piece_id=piece_id)
        if not skip and timing_mode == "segment_anchor" and fold_ephemeris is not None:
            raise ValueError(
                f"piece {piece_id}: segment_anchor ensemble ToM supports "
                f"constant period only; omit fold_ephemeris"
            )
        local_lc_raw = entry.get("local_lc_path")
        local_lc_path = (
            None if local_lc_raw is None else _resolve_path(base, str(local_lc_raw))
        )
        if local_lc_path is not None and not local_lc_path.is_file():
            raise FileNotFoundError(
                f"piece {piece_id}: local_lc_path not found: {local_lc_path}"
            )
        reuse_raw = entry.get("reuse_template_from")
        reuse_template_from = None if reuse_raw is None else str(reuse_raw)
        existing_raw = entry.get("existing_template_dir")
        existing_template_dir = (
            None if existing_raw is None else _resolve_path(base, str(existing_raw))
        )
        if skip and (reuse_template_from is not None or existing_template_dir is not None):
            logger.warning(
                "piece %s: skip=true ignores existing_template_dir / reuse_template_from",
                piece_id,
            )
        gp_piece = _gp_from_mapping(entry.get("gp_template"), gp_defaults)
        fit_piece = _fit_from_mapping(entry.get("fit"), fit_defaults)
        if (
            validate_intervals
            and not skip
            and timing_mode == "per_interval"
            and intervals_time is not None
        ):
            assert intervals_path is not None
            _validate_intervals_in_window(
                intervals_path, fit_window, piece_id, intervals_time
            )
        pieces.append(
            PieceConfig(
                piece_id=piece_id,
                template_window=template_window,
                fit_window=fit_window,
                intervals_path=intervals_path,
                timing_mode=timing_mode,
                anchor_epoch=anchor_epoch,
                local_period=local_period,
                local_epoch=local_epoch,
                fold_ephemeris=fold_ephemeris,
                local_lc_path=local_lc_path,
                reuse_template_from=reuse_template_from,
                existing_template_dir=existing_template_dir,
                skip=skip,
                gp_template=gp_piece,
                fit=fit_piece,
            )
        )

    _validate_piece_template_sources(pieces)

    n_active = sum(1 for p in pieces if not p.skip)
    logger.info(
        "Loaded manifest %s: %s piece(s) (%s active), lc=%s, method=%s",
        manifest_path.name,
        len(pieces),
        n_active,
        lc_path.name,
        timing_method,
    )
    return RunManifest(
        manifest_path=manifest_path,
        lc_path=lc_path,
        manifest_time=manifest_time,
        intervals_time=intervals_time,
        photometry_domain=photometry_domain,
        default_epoch=default_epoch,
        default_period=default_period,
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


def piece_template_fold_period(piece: PieceConfig, default_period: float) -> float:
    """Step 1 fold period: ``local_period`` on the piece, else ``default_period``."""
    return piece.local_period if piece.local_period is not None else default_period


def piece_fold_period(piece: PieceConfig, default_period: float) -> float:
    """Alias for :func:`piece_template_fold_period`."""
    return piece_template_fold_period(piece, default_period)


def piece_template_fold_epoch(piece: PieceConfig, default_epoch: float) -> float:
    """Step 1 fold epoch: ``local_epoch`` on the piece, else ``default_epoch``."""
    return piece.local_epoch if piece.local_epoch is not None else default_epoch


def piece_fold_epoch(piece: PieceConfig, default_epoch: float) -> float:
    """Alias for :func:`piece_template_fold_epoch`."""
    return piece_template_fold_epoch(piece, default_epoch)


def piece_lc_path(piece: PieceConfig, default_lc_path: Path) -> Path:
    """LC file for this piece: ``local_lc_path`` if set, else global ``lc_path``."""
    return piece.local_lc_path if piece.local_lc_path is not None else default_lc_path


def overview_lc_segments(
    pieces: list[PieceConfig],
    default_lc_path: Path,
) -> list[tuple[Path, float, float]]:
    """Merge per-piece fit windows by LC path for overview plotting."""
    windows_by_path: dict[Path, list[tuple[float, float]]] = {}
    for piece in pieces:
        if piece.skip:
            continue
        lc = piece_lc_path(piece, default_lc_path)
        windows_by_path.setdefault(lc, []).append(
            (piece.fit_window.t_min, piece.fit_window.t_max)
        )
    segments: list[tuple[Path, float, float]] = []
    for lc, windows in windows_by_path.items():
        seg_lo = min(w[0] for w in windows)
        seg_hi = max(w[1] for w in windows)
        segments.append((lc, seg_lo, seg_hi))
    return segments
