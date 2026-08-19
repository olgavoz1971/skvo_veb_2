"""Load YAML configuration for the template-epoch spike."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

EXPORT_METHODS = frozenset({"kvw", "bisector_core", "bisector_extrap"})


@dataclass
class EpochSpikeConfig:
    """Resolved settings for one read-only template epoch experiment."""

    config_path: Path
    label: str
    template_dir: Path
    output_dir: Path
    show_plots: bool
    plot_dpi: int
    kvw_half_width_phase: float
    kvw_search_half_width_phase: float
    depth_min: float
    depth_max: float
    n_levels: int
    min_accepted_levels: int
    kvw_n_pairs_min: int
    weight_by_sigma: bool
    export_method: str
    export_template_dir: Path


def _resolve_path(base: Path, raw: str) -> Path:
    """Resolve ``raw`` against ``base`` unless it is already absolute."""
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


def load_epoch_config(path: Path) -> EpochSpikeConfig:
    """Parse a spike YAML file into :class:`EpochSpikeConfig`.

    Args:
        path (Path): Study YAML path.

    Returns:
        EpochSpikeConfig: Resolved configuration.

    Raises:
        ValueError: If a required mapping or numeric bound is missing or invalid.
        FileNotFoundError: If the template directory or artefacts are missing.
    """
    config_path = path.resolve()
    base = config_path.parent
    raw = _load_yaml_with_includes(config_path)

    study = raw.get("study")
    if not isinstance(study, dict):
        raise ValueError("study section required")
    if "template_dir" not in study:
        raise ValueError("study.template_dir required")
    if "output_dir" not in study:
        raise ValueError("study.output_dir required")

    template_dir = _resolve_path(base, str(study["template_dir"]))
    if not template_dir.is_dir():
        raise FileNotFoundError(f"template directory not found: {template_dir}")
    npz_path = template_dir / "template.npz"
    meta_path = template_dir / "template_meta.json"
    if not npz_path.is_file():
        raise FileNotFoundError(f"missing {npz_path}")
    if not meta_path.is_file():
        raise FileNotFoundError(f"missing {meta_path}")

    if raw.get("core") is not None:
        raise ValueError(
            "top-level 'core' is no longer used; put half_width_phase and "
            "search_half_width_phase under kvw"
        )

    plot_cfg = raw.get("plot") or {}
    bis_cfg = raw.get("bisector") or {}
    kvw_cfg = raw.get("kvw") or {}
    if not isinstance(kvw_cfg, dict):
        raise ValueError("kvw section required")

    depth_min = float(bis_cfg.get("depth_min", 0.20))
    depth_max = float(bis_cfg.get("depth_max", 0.70))
    if not (0.0 < depth_min < depth_max < 1.0):
        raise ValueError(
            f"bisector depths must satisfy 0 < depth_min < depth_max < 1; "
            f"got {depth_min}, {depth_max}"
        )
    n_levels = int(bis_cfg.get("n_levels", 31))
    if n_levels < 3:
        raise ValueError(f"bisector.n_levels must be >= 3, got {n_levels}")
    min_accepted = int(bis_cfg.get("min_accepted_levels", 8))
    if min_accepted < 3:
        raise ValueError(
            f"bisector.min_accepted_levels must be >= 3, got {min_accepted}"
        )

    core_hw = float(kvw_cfg.get("half_width_phase", 0.08))
    search_hw = float(kvw_cfg.get("search_half_width_phase", 0.04))
    if core_hw <= 0 or search_hw <= 0:
        raise ValueError("kvw half-widths must be positive")
    if search_hw >= core_hw:
        raise ValueError(
            "kvw.search_half_width_phase must be smaller than kvw.half_width_phase "
            f"(got search={search_hw}, half_width={core_hw})"
        )

    n_pairs_min = int(kvw_cfg.get("n_pairs_min", 8))
    if n_pairs_min < 2:
        raise ValueError(f"kvw.n_pairs_min must be >= 2, got {n_pairs_min}")

    if isinstance(study.get("export_template"), dict):
        raise ValueError(
            "export_template belongs at the YAML root (same level as kvw), "
            "not under study"
        )

    export_cfg = raw.get("export_template") or {}
    if not isinstance(export_cfg, dict):
        raise ValueError("export_template must be a mapping")
    if "method" not in export_cfg:
        raise ValueError(
            "export_template.method required "
            f"(one of {sorted(EXPORT_METHODS)})"
        )
    export_method = str(export_cfg["method"])
    if export_method not in EXPORT_METHODS:
        raise ValueError(
            f"export_template.method must be one of {sorted(EXPORT_METHODS)}, "
            f"got {export_method!r}"
        )

    output_dir = _resolve_path(base, str(study["output_dir"]))
    if export_cfg.get("output_dir") is not None:
        export_template_dir = _resolve_path(base, str(export_cfg["output_dir"]))
    else:
        export_template_dir = output_dir / f"template_{export_method}"
    if export_template_dir.resolve() == template_dir.resolve():
        raise ValueError(
            "export_template.output_dir must not be the source template_dir; "
            "the spike never overwrites the original artefacts"
        )

    cfg = EpochSpikeConfig(
        config_path=config_path,
        label=str(study.get("label", config_path.stem)),
        template_dir=template_dir,
        output_dir=output_dir,
        show_plots=bool(plot_cfg.get("show", True)),
        plot_dpi=int(plot_cfg.get("dpi", 150)),
        kvw_half_width_phase=core_hw,
        kvw_search_half_width_phase=search_hw,
        depth_min=depth_min,
        depth_max=depth_max,
        n_levels=n_levels,
        min_accepted_levels=min_accepted,
        kvw_n_pairs_min=n_pairs_min,
        weight_by_sigma=bool(kvw_cfg.get("weight_by_sigma", True)),
        export_method=export_method,
        export_template_dir=export_template_dir,
    )
    logger.info(
        "Loaded epoch spike %r: template %s",
        cfg.label,
        cfg.template_dir,
    )
    return cfg
