"""Load and validate O-C study YAML configuration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from time_scale import TimeScaleConfig, parse_time_scale_block

logger = logging.getLogger(__name__)

TASK_NAMES = frozenset(
    {"plot_oc_residuals", "fit_segment_periods", "fit_parabolic_ephemeris"}
)


@dataclass(frozen=True)
class CycleShift:
    """Manual cycle-index adjustment applied at or after ``at_jd``."""

    at_jd: float
    delta_E: int


@dataclass
class SegmentWindow:
    """JD segment for linear O-C period refinement."""

    name: str
    start_jd: float
    end_jd: float


@dataclass
class OcStudyConfig:
    """Resolved configuration for one O-C study run."""

    config_path: Path
    label: str
    manifest_time: TimeScaleConfig
    T0_jd: float
    P0: float
    cycle_shifts: list[tuple[float, int]]
    tasks: dict[str, bool]
    extrema_path: Path
    extrema_format: str
    extrema_file_time: TimeScaleConfig
    exclude_rejected: bool
    timing_method_filter: str | None
    ascii_columns: dict[str, int] | None
    lightcurve_path: Path | None
    photometry_domain: str | None
    output_dir: Path
    show_plots: bool
    plot_dpi: int
    segment_max_iter: int
    segment_tol: float
    segments: list[SegmentWindow]
    parabolic_fit_start_jd: float | None
    parabolic_fit_end_jd: float | None
    exports: dict[str, dict[str, str]]
    write_provenance: bool


def _resolve_path(base: Path, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` onto a copy of ``base``."""
    out = dict(base)
    for key, value in overlay.items():
        if key == "include":
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_yaml_with_includes(path: Path, *, _seen: set[Path] | None = None) -> dict[str, Any]:
    """Load YAML and merge ``include:`` profiles (paths relative to each file)."""
    path = path.resolve()
    seen = set() if _seen is None else _seen
    if path in seen:
        raise ValueError(f"circular include detected at {path}")
    seen.add(path)

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: root must be a mapping")

    include_raw = raw.get("include")
    merged: dict[str, Any] = {}
    if include_raw is not None:
        include_path = _resolve_path(path.parent, str(include_raw))
        merged = _load_yaml_with_includes(include_path, _seen=seen)

    return _deep_merge(merged, raw)


def _window_from_study(
    data: dict[str, Any],
    manifest_time: TimeScaleConfig,
    *,
    context: str,
) -> tuple[float, float]:
    if not isinstance(data, dict):
        raise ValueError(f"{context}: expected mapping with t_min/t_max")
    return (
        manifest_time.to_absolute_jd(float(data["t_min"])),
        manifest_time.to_absolute_jd(float(data["t_max"])),
    )


def _apply_from_template_run(study: dict[str, Any], base: Path) -> dict[str, Any]:
    """Fill missing study inputs from a template-timing manifest."""
    block = study.get("from_template_run")
    if not isinstance(block, dict):
        return study

    manifest_raw = block.get("manifest")
    if manifest_raw is None:
        raise ValueError("from_template_run.manifest required")
    manifest_path = _resolve_path(base, str(manifest_raw))

    import sys

    timing_dir = base.parent.parent / "template_timing"
    repo_root = base.parent.parent.parent
    for p in (repo_root, timing_dir):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))

    from manifest_config import load_manifest

    manifest = load_manifest(manifest_path, validate_intervals=False)
    study = dict(study)

    inputs = dict(study.get("inputs") or {})
    extrema = dict(inputs.get("extrema") or {})

    timing_mode = str(block.get("timing", "run_merged"))
    if "path" not in extrema:
        if timing_mode == "run_merged":
            extrema["path"] = str(manifest.run_dir / "timing.csv")
        else:
            raise ValueError(f"unsupported from_template_run.timing {timing_mode!r}")
        extrema.setdefault("format", "template_timing_csv")
        extrema.setdefault(
            "file_time",
            {"scale": "jd", "shift": 0.0},
        )

    if block.get("inherit_lightcurve", False):
        lc = dict(inputs.get("lightcurve") or {})
        lc.setdefault("path", str(manifest.lc_path))
        lc.setdefault("photometry_domain", manifest.photometry_domain)
        inputs["lightcurve"] = lc

    if block.get("inherit_ephemeris_trial", False):
        ephem = dict(study.get("ephemeris") or {})
        if "T0" not in ephem:
            ephem["T0"] = manifest.default_epoch
            study.setdefault("manifest_time", {"scale": "jd", "shift": 0.0})
        if "P0" not in ephem:
            ephem["P0"] = manifest.default_period
        study["ephemeris"] = ephem

    inputs["extrema"] = extrema
    study["inputs"] = inputs
    if "output_dir" not in study:
        study["output_dir"] = str(manifest.run_dir / "oc")
    return study


def load_oc_config(path: Path) -> OcStudyConfig:
    """Parse an O-C study YAML file into :class:`OcStudyConfig`."""
    config_path = path.resolve()
    base = config_path.parent
    raw = _load_yaml_with_includes(config_path)

    study_raw = raw.get("study")
    if not isinstance(study_raw, dict):
        raise ValueError("study section required")

    study = _apply_from_template_run(study_raw, base)

    label = str(study.get("label", config_path.stem))
    manifest_time = parse_time_scale_block(
        study["manifest_time"],
        block_name="study.manifest_time",
    )

    ephem = study.get("ephemeris")
    if not isinstance(ephem, dict):
        raise ValueError("study.ephemeris required (T0, P0)")
    T0_jd = manifest_time.to_absolute_jd(float(ephem["T0"]))
    P0 = float(ephem["P0"])

    cycle_shifts: list[tuple[float, int]] = []
    for entry in study.get("cycle_shifts") or []:
        if not isinstance(entry, dict):
            raise ValueError("cycle_shifts entries must be mappings")
        at_jd = manifest_time.to_absolute_jd(float(entry["at_time"]))
        cycle_shifts.append((at_jd, int(entry["delta_E"])))

    tasks_raw = study.get("tasks")
    if not isinstance(tasks_raw, dict):
        raise ValueError("study.tasks required")
    tasks = {name: bool(tasks_raw.get(name, False)) for name in TASK_NAMES}
    if not any(tasks.values()):
        raise ValueError("at least one task must be enabled in study.tasks")

    inputs = study.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("study.inputs required")
    extrema = inputs.get("extrema")
    if not isinstance(extrema, dict):
        raise ValueError("study.inputs.extrema required")

    extrema_path = _resolve_path(base, str(extrema["path"]))
    if not extrema_path.is_file():
        raise FileNotFoundError(f"extrema file not found: {extrema_path}")
    extrema_format = str(extrema.get("format", "template_timing_csv"))
    extrema_file_time = parse_time_scale_block(
        extrema.get("file_time") or {"scale": "jd", "shift": 0.0},
        block_name="study.inputs.extrema.file_time",
    )

    ascii_columns = extrema.get("columns")
    if ascii_columns is not None:
        ascii_columns = {str(k): int(v) for k, v in ascii_columns.items()}

    lightcurve_path = None
    photometry_domain = None
    lc_raw = inputs.get("lightcurve")
    if lc_raw is not None:
        if not isinstance(lc_raw, dict):
            raise ValueError("study.inputs.lightcurve must be a mapping")
        lightcurve_path = _resolve_path(base, str(lc_raw["path"]))
        photometry_domain = str(lc_raw.get("photometry_domain", "mag"))
        if not lightcurve_path.is_file():
            raise FileNotFoundError(f"light curve not found: {lightcurve_path}")

    if tasks["fit_parabolic_ephemeris"] and lightcurve_path is None:
        raise ValueError(
            "study.inputs.lightcurve required when fit_parabolic_ephemeris is enabled"
        )

    output_dir = _resolve_path(
        base,
        str(study.get("output_dir", extrema_path.parent / "oc")),
    )

    plot_cfg = study.get("plot") or raw.get("plot") or {}
    show_plots = bool(plot_cfg.get("show", True))
    plot_dpi = int(plot_cfg.get("dpi", 150))

    seg_defaults = raw.get("segment_period_fit") or {}
    segment_max_iter = int(seg_defaults.get("max_iter", 5))
    segment_tol = float(seg_defaults.get("tol", 1e-8))

    segments: list[SegmentWindow] = []
    seg_block = study.get("segment_period_fit") or {}
    for entry in seg_block.get("segments") or []:
        if not isinstance(entry, dict):
            raise ValueError("segment_period_fit.segments entries must be mappings")
        lo, hi = _window_from_study(
            entry,
            manifest_time,
            context=f"segment {entry.get('name', '?')}",
        )
        segments.append(
            SegmentWindow(name=str(entry["name"]), start_jd=lo, end_jd=hi)
        )

    if tasks["fit_segment_periods"] and not segments:
        raise ValueError(
            "study.segment_period_fit.segments required when fit_segment_periods is enabled"
        )

    parabolic_fit_start_jd = None
    parabolic_fit_end_jd = None
    parabolic_block = study.get("parabolic_ephemeris") or {}
    fit_window = parabolic_block.get("fit_window")
    if fit_window is not None:
        parabolic_fit_start_jd, parabolic_fit_end_jd = _window_from_study(
            fit_window,
            manifest_time,
            context="parabolic_ephemeris.fit_window",
        )
    if tasks["fit_parabolic_ephemeris"] and (
        parabolic_fit_start_jd is None or parabolic_fit_end_jd is None
    ):
        raise ValueError(
            "study.parabolic_ephemeris.fit_window required when "
            "fit_parabolic_ephemeris is enabled"
        )

    export_cfg = study.get("exports") or {}
    write_provenance = bool((raw.get("export") or {}).get("write_provenance", True))

    logger.info(
        "Loaded O-C study %r: %s extrema from %s; tasks=%s",
        label,
        extrema_format,
        extrema_path.name,
        [k for k, v in tasks.items() if v],
    )

    return OcStudyConfig(
        config_path=config_path,
        label=label,
        manifest_time=manifest_time,
        T0_jd=T0_jd,
        P0=P0,
        cycle_shifts=cycle_shifts,
        tasks=tasks,
        extrema_path=extrema_path,
        extrema_format=extrema_format,
        extrema_file_time=extrema_file_time,
        exclude_rejected=bool(extrema.get("exclude_rejected", True)),
        timing_method_filter=extrema.get("timing_method"),
        ascii_columns=ascii_columns,
        lightcurve_path=lightcurve_path,
        photometry_domain=photometry_domain,
        output_dir=output_dir,
        show_plots=show_plots,
        plot_dpi=plot_dpi,
        segment_max_iter=segment_max_iter,
        segment_tol=segment_tol,
        segments=segments,
        parabolic_fit_start_jd=parabolic_fit_start_jd,
        parabolic_fit_end_jd=parabolic_fit_end_jd,
        exports={str(k): dict(v) for k, v in export_cfg.items() if isinstance(v, dict)},
        write_provenance=write_provenance,
    )
