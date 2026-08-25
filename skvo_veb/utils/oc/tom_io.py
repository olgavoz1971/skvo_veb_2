"""Load ToM times from compact GP/MAVKA ``.dat`` files or review stores."""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


def parse_compact_tom_dat(text: str) -> list[dict]:
    """Parses a compact GP or MAVKA extrema ``.dat`` body.

    Comment lines (``#``) are skipped. Each data line is two whitespace-separated
    numbers: observed JD and σ(JD) in days.

    Args:
        text (str): File contents.

    Returns:
        list[dict]: ``jd_ext`` and ``sigma_jd`` records, sorted by ``jd_ext``.

    Raises:
        ValueError: If there are no usable rows or a data line is malformed.
    """
    if text is None:
        raise ValueError("Timing file is empty.")
    records: list[dict] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            raise ValueError(
                f"Timing file line {line_no}: expected JD and σ(JD), got {raw!r}."
            )
        try:
            jd_ext = float(parts[0])
            sigma_jd = float(parts[1])
        except ValueError as exc:
            raise ValueError(
                f"Timing file line {line_no}: not two numbers ({raw!r})."
            ) from exc
        if not math.isfinite(jd_ext):
            raise ValueError(f"Timing file line {line_no}: JD is not finite.")
        if not math.isfinite(sigma_jd):
            sigma_jd = float("nan")
        records.append({"jd_ext": jd_ext, "sigma_jd": sigma_jd})
    if not records:
        raise ValueError("Timing file has no ToM data rows.")
    records.sort(key=lambda row: row["jd_ext"])
    logger.info("Parsed %s ToM(s) from compact timing file", len(records))
    return records


def toms_from_review_store(store: dict | None) -> list[dict]:
    """Extracts Keep-marked successful ToMs from a GP or MAVKA review store.

    Args:
        store (dict | None): ``store-results-data`` or ``store-mavka-results-data``.

    Returns:
        list[dict]: ``jd_ext`` and ``sigma_jd`` records, sorted by ``jd_ext``.

    Raises:
        ValueError: If the store is missing, empty, or has no kept successes.
    """
    if not store:
        raise ValueError("No extrema results are available for this source.")
    rows = store.get("rows") or []
    include = store.get("include") or []
    if len(include) != len(rows):
        raise ValueError(
            "Keep flags do not match the extrema result list "
            f"({len(include)} vs {len(rows)})."
        )
    records: list[dict] = []
    for flag, row in zip(include, rows, strict=True):
        if not flag or row.get("is_fail"):
            continue
        jd_ext = row.get("jd_peak")
        if jd_ext is None:
            raise ValueError("A kept extrema result is missing TOM (jd_peak).")
        sigma = row.get("jd_peak_std")
        sigma_jd = float(sigma) if sigma is not None else float("nan")
        records.append({"jd_ext": float(jd_ext), "sigma_jd": sigma_jd})
    if not records:
        raise ValueError(
            "No Keep-marked successful extrema. Tick Keep result on the "
            "review cards, or choose Upload."
        )
    records.sort(key=lambda row: row["jd_ext"])
    return records


def uploaded_toms_from_store(store: dict | list | None) -> list[dict]:
    """Extracts ToM records from the O-C upload store.

    Args:
        store (dict | list | None): ``store-oc-uploaded-toms`` payload.

    Returns:
        list[dict]: ``jd_ext`` / ``sigma_jd`` records.

    Raises:
        ValueError: If the store is missing, a legacy list, or has no rows.
    """
    if not store:
        raise ValueError("Load a compact ToM .dat, or choose GP / MAVKA.")
    if isinstance(store, list):
        raise ValueError(
            "Uploaded ToMs are missing the source filename. Load the timing file again."
        )
    if not isinstance(store, dict) or "records" not in store:
        raise ValueError(
            "Uploaded ToM store must be a filename-plus-records payload."
        )
    records = store.get("records") or []
    if not records:
        raise ValueError("Uploaded timing file has no ToM data rows.")
    return list(records)


def records_to_arrays(records: list[dict]) -> tuple[Any, Any]:
    """Stacks ToM records into JD and σ arrays.

    Args:
        records (list[dict]): Output of ``parse_compact_tom_dat`` or
            ``toms_from_review_store``.

    Returns:
        tuple: ``(jd_ext, sigma_jd)`` as Python lists of float.
    """
    jd_ext = [float(row["jd_ext"]) for row in records]
    sigma_jd = [float(row["sigma_jd"]) for row in records]
    return jd_ext, sigma_jd
