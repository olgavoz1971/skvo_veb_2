"""Load extrema timing files and write provenance headers for O-C exports."""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from time_scale import TimeScaleConfig

logger = logging.getLogger(__name__)

EXTREMA_FORMATS = frozenset({"template_timing_csv", "gp_extrema_dat", "ascii_columns"})


@dataclass
class ExtremaRecord:
    """One timed extremum for O-C analysis."""

    jd_ext: float
    sigma_jd_ext: float | None = None
    extrema_kind: str = "unknown"
    interval_start: float | None = None
    interval_end: float | None = None
    piece_id: str | None = None
    interval_index: int | None = None
    timing_method: str | None = None
    rejected: bool = False
    extra: dict = field(default_factory=dict)


def provenance_header_lines(meta: dict[str, str]) -> list[str]:
    """Format ``# key: value`` provenance lines for export files."""
    return [f"# {key}: {value}" for key, value in meta.items()]


def write_csv_with_provenance(
    path: Path,
    *,
    provenance: dict[str, str],
    fieldnames: list[str],
    rows: list[dict],
) -> None:
    """Write a CSV with comment provenance header rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for line in provenance_header_lines(provenance):
            handle.write(line + "\n")
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    logger.info("Wrote %s (%s rows)", path, len(rows))


def load_extrema_file(
    path: Path,
    *,
    fmt: str,
    file_time: TimeScaleConfig,
    exclude_rejected: bool = True,
    timing_method: str | None = None,
    ascii_columns: dict | None = None,
) -> list[ExtremaRecord]:
    """Load extrema epochs from a supported file format.

    Args:
        path (Path): Input file path.
        fmt (str): ``template_timing_csv``, ``gp_extrema_dat``, or ``ascii_columns``.
        file_time (TimeScaleConfig): Scale/shift for numeric times in the file.
        exclude_rejected (bool): Drop rejected rows for template timing CSV.
        timing_method (str | None): Keep only this ``timing_method`` when set.
        ascii_columns (dict | None): Column indices for ``ascii_columns`` format.

    Returns:
        list[ExtremaRecord]: Sorted by ``jd_ext``.
    """
    if fmt not in EXTREMA_FORMATS:
        raise ValueError(f"unsupported extrema format {fmt!r}")

    if fmt == "template_timing_csv":
        records = _load_template_timing_csv(
            path,
            file_time=file_time,
            exclude_rejected=exclude_rejected,
            timing_method=timing_method,
        )
    elif fmt == "gp_extrema_dat":
        records = _load_gp_extrema_dat(path, file_time=file_time)
    else:
        records = _load_ascii_columns(path, file_time=file_time, columns=ascii_columns or {})

    records.sort(key=lambda r: r.jd_ext)
    logger.info("Loaded %s extrema from %s (%s)", len(records), path.name, fmt)
    return records


def _parse_rejected(value: str | None) -> bool:
    if value is None or value == "":
        return False
    return str(value).strip().lower() in {"1", "true", "yes"}


def _load_template_timing_csv(
    path: Path,
    *,
    file_time: TimeScaleConfig,
    exclude_rejected: bool,
    timing_method: str | None,
) -> list[ExtremaRecord]:
    """Load ``run_timing`` ``timing.csv`` (maps ``t_max`` column to ``jd_ext``)."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(
            line for line in handle if not line.lstrip().startswith("#")
        )
        raw_rows = list(reader)
    if not raw_rows:
        raise ValueError(f"{path}: no timing rows")

    records: list[ExtremaRecord] = []
    for row in raw_rows:
        if exclude_rejected and _parse_rejected(row.get("rejected")):
            continue
        method = row.get("timing_method")
        if timing_method is not None and method != timing_method:
            continue
        if "t_max" not in row:
            raise ValueError(f"{path}: timing CSV missing t_max column")
        jd_ext = file_time.to_absolute_jd(float(row["t_max"]))
        sigma_raw = row.get("sigma_t_max")
        sigma = None if not sigma_raw else float(sigma_raw)
        interval_start = row.get("t_start")
        interval_end = row.get("t_end")
        piece_id = row.get("piece_id")
        interval_raw = row.get("interval")
        records.append(
            ExtremaRecord(
                jd_ext=jd_ext,
                sigma_jd_ext=sigma,
                extrema_kind="unknown",
                interval_start=(
                    None if interval_start is None else file_time.to_absolute_jd(float(interval_start))
                ),
                interval_end=(
                    None if interval_end is None else file_time.to_absolute_jd(float(interval_end))
                ),
                piece_id=str(piece_id) if piece_id is not None else None,
                interval_index=int(interval_raw) if interval_raw not in (None, "") else None,
                timing_method=str(method) if method else None,
                rejected=_parse_rejected(row.get("rejected")),
            )
        )
    if not records:
        raise ValueError(f"{path}: no extrema rows after filters")
    return records


_GP_HEADER_RE = re.compile(r"GP\s+(Minimum|Maximum)\s+Results", re.I)


def _load_gp_extrema_dat(path: Path, *, file_time: TimeScaleConfig) -> list[ExtremaRecord]:
    """Load compact GP extrema export (``# GP Minimum Results`` header)."""
    extrema_kind = "unknown"
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("#"):
                break
            match = _GP_HEADER_RE.search(line)
            if match:
                extrema_kind = match.group(1).lower()

    df = pd.read_csv(path, sep=r"\s+", comment="#", header=None)
    if df.empty:
        raise ValueError(f"{path}: no data rows")

    records: list[ExtremaRecord] = []
    for i in range(len(df)):
        jd_ext = file_time.to_absolute_jd(float(df.iloc[i, 0]))
        sigma = None
        if df.shape[1] >= 2 and pd.notna(df.iloc[i, 1]):
            sigma = float(df.iloc[i, 1])
        records.append(
            ExtremaRecord(
                jd_ext=jd_ext,
                sigma_jd_ext=sigma,
                extrema_kind=extrema_kind,
            )
        )
    return records


def _load_ascii_columns(
    path: Path,
    *,
    file_time: TimeScaleConfig,
    columns: dict,
) -> list[ExtremaRecord]:
    """Load whitespace-separated extrema list with configurable column indices."""
    time_col = int(columns.get("time", 0))
    sigma_col = columns.get("sigma")
    df = pd.read_csv(path, sep=r"\s+", comment="#", header=None)
    if df.empty:
        raise ValueError(f"{path}: no data rows")

    records: list[ExtremaRecord] = []
    for i in range(len(df)):
        jd_ext = file_time.to_absolute_jd(float(df.iloc[i, time_col]))
        sigma = None
        if sigma_col is not None and df.shape[1] > int(sigma_col):
            val = df.iloc[i, int(sigma_col)]
            if pd.notna(val):
                sigma = float(val)
        records.append(ExtremaRecord(jd_ext=jd_ext, sigma_jd_ext=sigma))
    return records


def extrema_jd_array(records: list[ExtremaRecord]):
    """Return ``jd_ext`` and optional sigma arrays aligned with ``records``."""
    import numpy as np

    jd = np.asarray([r.jd_ext for r in records], dtype=float)
    if any(r.sigma_jd_ext is not None for r in records):
        sigma = np.asarray(
            [r.sigma_jd_ext if r.sigma_jd_ext is not None else np.nan for r in records],
            dtype=float,
        )
    else:
        sigma = None
    return jd, sigma


def default_provenance(
    *,
    task: str,
    study_label: str,
    source_format: str,
    source_path: Path,
    algorithm: str,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build standard provenance metadata for an export file."""
    meta = {
        "oc_tool": "run_oc",
        "task": task,
        "study": study_label,
        "source_format": source_format,
        "source_path": str(source_path.resolve()),
        "algorithm": algorithm,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if extra:
        meta.update(extra)
    return meta
