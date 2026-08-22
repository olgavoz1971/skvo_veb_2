"""Load TOM times and uncertainties from lc_approx spike CSV outputs."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

KNOWN_METHODS = frozenset({"AP", "WSAP", "WSL", "A", "BEST"})


@dataclass(frozen=True)
class TomRecord:
    """One timed extremum from an approx CSV.

    Attributes:
        interval (int): Interval index in the source table.
        jd_ext (float): Observed TOM (absolute JD).
        sigma_jd (float): Formal TOM uncertainty in days (NaN if missing).
        method (str): Method id that produced the TOM.
    """

    interval: int
    jd_ext: float
    sigma_jd: float
    method: str


def _truthy(value: str) -> bool:
    """Return True for common CSV boolean / ok encodings.

    Args:
        value (str): Cell text.

    Returns:
        bool: Parsed flag.
    """
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _sigma_s_to_days(sigma_s: str | float) -> float:
    """Convert a sigma cell in seconds to days.

    Args:
        sigma_s (str | float): Uncertainty in seconds, or empty.

    Returns:
        float: Uncertainty in days, or NaN if blank / invalid.
    """
    text = str(sigma_s).strip()
    if not text:
        return float("nan")
    return float(text) / 86400.0


def load_toms_from_approx_csv(path: Path, method: str) -> list[TomRecord]:
    """Load successful TOMs for one method from a spike CSV.

    Accepts either:

    * ``approx_batch.csv`` — long format with ``method``, ``ok``, ``t_ext``,
      ``sigma_t_ext_s``;
    * ``approx_compare.csv`` — wide format with ``{method}_ok``, ``{method}_t_ext``,
      ``{method}_sigma_s`` (or ``best_*`` when ``method`` is ``BEST``).

    Args:
        path (Path): CSV path.
        method (str): ``AP``, ``WSAP``, ``WSL``, ``A``, or ``BEST``.

    Returns:
        list[TomRecord]: Successful extrema sorted by ``jd_ext``.

    Raises:
        FileNotFoundError: If ``path`` is missing.
        ValueError: If the method is unknown or no usable rows are found.
    """
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"TOM CSV not found: {path}")
    method_u = method.strip().upper()
    if method_u not in KNOWN_METHODS:
        raise ValueError(
            f"method must be one of {sorted(KNOWN_METHODS)}, got {method!r}"
        )

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(
            line for line in handle if not line.lstrip().startswith("#")
        )
        rows = list(reader)
    if not rows:
        raise ValueError(f"no data rows in {path}")

    fieldnames = set(rows[0].keys())
    records: list[TomRecord] = []

    if "method" in fieldnames and "t_ext" in fieldnames:
        # Long batch table.
        if method_u == "BEST":
            if "is_best" not in fieldnames:
                raise ValueError(
                    f"{path.name}: BEST requires an is_best column in approx_batch.csv"
                )
            selected = [
                r
                for r in rows
                if _truthy(r.get("ok", "")) and _truthy(r.get("is_best", ""))
            ]
        else:
            selected = [
                r
                for r in rows
                if r.get("method", "").strip().upper() == method_u
                and _truthy(r.get("ok", ""))
            ]
        for row in selected:
            t_text = str(row.get("t_ext", "")).strip()
            if not t_text:
                continue
            records.append(
                TomRecord(
                    interval=int(row["interval"]),
                    jd_ext=float(t_text),
                    sigma_jd=_sigma_s_to_days(row.get("sigma_t_ext_s", "")),
                    method=str(row.get("method", method_u)).upper(),
                )
            )
    else:
        # Wide compare table.
        prefix = "best" if method_u == "BEST" else method_u.lower()
        ok_key = f"{prefix}_ok"
        t_key = f"{prefix}_t_ext" if method_u != "BEST" else "best_t_ext"
        s_key = f"{prefix}_sigma_s" if method_u != "BEST" else "best_sigma_s"
        if method_u == "BEST":
            ok_key = None  # best_* present only when a winner exists
        if t_key not in fieldnames:
            raise ValueError(
                f"{path.name}: expected column {t_key!r} for method {method_u}"
            )
        for row in rows:
            if ok_key is not None and not _truthy(row.get(ok_key, "")):
                continue
            t_text = str(row.get(t_key, "")).strip()
            if not t_text:
                continue
            records.append(
                TomRecord(
                    interval=int(row["interval"]),
                    jd_ext=float(t_text),
                    sigma_jd=_sigma_s_to_days(row.get(s_key, "")),
                    method=(
                        str(row.get("best_method", "BEST")).upper()
                        if method_u == "BEST"
                        else method_u
                    ),
                )
            )

    if not records:
        raise ValueError(f"no successful {method_u} TOMs in {path}")
    records.sort(key=lambda r: r.jd_ext)
    logger.info(
        "Loaded %s %s TOM(s) from %s",
        len(records),
        method_u,
        path.name,
    )
    return records


def records_to_arrays(
    records: list[TomRecord],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Stack records into JD / sigma / interval arrays.

    Args:
        records (list[TomRecord]): Extrema.

    Returns:
        tuple: ``(jd_ext, sigma_jd, intervals)``.
    """
    jd = np.asarray([r.jd_ext for r in records], dtype=float)
    sig = np.asarray([r.sigma_jd for r in records], dtype=float)
    idx = np.asarray([r.interval for r in records], dtype=int)
    return jd, sig, idx
