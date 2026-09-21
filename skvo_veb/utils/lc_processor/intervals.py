"""Processor rough-extrema intervals and uploaded reference marks.

Intervals are independent of extrema marks: they may be generated from
working extrema with a fixed half-width, or added/removed manually.
Uploaded reference extrema are JD times drawn as vertical lines (comparison
only; they are not photometry and are not used to build intervals).
"""

from __future__ import annotations

import logging
import math
import uuid
from typing import Any

import numpy as np

from skvo_veb.utils.gp.prep_interval_bands import (
    prep_interval_band_shape,
    prep_interval_band_shape_style,
)
from skvo_veb.utils.lc_figure import absolute_jd_to_plot_x
from skvo_veb.utils.lc_intervals import format_intervals_download
from skvo_veb.utils.lc_processor.extrema import (
    format_export_comment_lines,
    rough_tom_interval_pairs,
)

logger = logging.getLogger(__name__)

INTERVALS_BLOB = "intervals"
REF_EXTREMA_BLOB = "ref_extrema"
INTERVAL_DELETE_HIT_FRAC = 0.02
LCP_INTERVAL_SHAPE_PREFIX = "lcp-int-"


def interval_shape_name(interval_id: str) -> str:
    """Returns the Plotly layout shape name for one processor interval.

    Names are keyed by interval id, not list index: the Store sorts by
    start JD, so an index would move after every add.

    Args:
        interval_id (str): Stable id on the interval row.

    Returns:
        str: Shape name for clientside mark styling.
    """
    return f"{LCP_INTERVAL_SHAPE_PREFIX}{interval_id}"


def empty_intervals_payload() -> dict:
    """Returns an empty intervals session payload.

    Returns:
        dict: ``{"intervals": []}``.
    """
    return {"intervals": []}


def empty_ref_extrema_payload() -> dict:
    """Returns an empty uploaded-reference extrema payload.

    Returns:
        dict: ``{"jd0": 0.0, "times_jd": []}``.
    """
    return {"jd0": 0.0, "times_jd": []}


def _sorted_interval_rows(rows: list[dict]) -> list[dict]:
    """Sorts interval rows by start JD.

    Args:
        rows (list[dict]): Interval dicts with ``start_jd`` / ``end_jd``.

    Returns:
        list[dict]: Sorted copy.
    """
    return sorted(rows, key=lambda row: float(row["start_jd"]))


def normalize_intervals_payload(payload: dict | None) -> dict:
    """Normalises a cached intervals blob.

    Args:
        payload (dict | None): Session blob or ``None``.

    Returns:
        dict: Payload with a sorted ``intervals`` list.
    """
    if not payload:
        return empty_intervals_payload()
    rows = []
    for raw in payload.get("intervals") or []:
        start = float(raw["start_jd"])
        end = float(raw["end_jd"])
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("Interval bounds must be finite Julian Dates.")
        if start >= end:
            raise ValueError(
                f"Invalid interval: start={start} must be less than end={end}."
            )
        rows.append(
            {
                "id": str(raw.get("id") or uuid.uuid4()),
                "start_jd": start,
                "end_jd": end,
                "origin": str(raw.get("origin") or "manual"),
            }
        )
    return {"intervals": _sorted_interval_rows(rows)}


def intervals_as_pairs(payload: dict | None) -> list[list[float]]:
    """Returns ``[[start, end], ...]`` absolute JD pairs from the cache.

    Args:
        payload (dict | None): Intervals blob.

    Returns:
        list[list[float]]: Sorted pairs.
    """
    normalised = normalize_intervals_payload(payload)
    return [
        [float(row["start_jd"]), float(row["end_jd"])]
        for row in normalised["intervals"]
    ]


def generate_intervals_from_extrema(
    extrema_payload: dict | None,
    *,
    delta_time_d: float,
) -> dict:
    """Builds intervals ``[t±δ]`` around working rough extrema.

    Args:
        extrema_payload (dict | None): ``EXTREMA_BLOB`` payload.
        delta_time_d (float): Half-width in days.

    Returns:
        dict: New intervals payload (``origin="auto"``).

    Raises:
        ValueError: If there are no extrema or δ is invalid.
    """
    if not extrema_payload or not extrema_payload.get("hits"):
        raise ValueError("Find or add working extrema before generating intervals.")
    times = np.asarray(
        [float(hit["jd"]) for hit in extrema_payload["hits"]], dtype=float
    )
    pairs = rough_tom_interval_pairs(times, delta_time_d=float(delta_time_d))
    rows = [
        {
            "id": str(uuid.uuid4()),
            "start_jd": float(start),
            "end_jd": float(end),
            "origin": "auto",
        }
        for start, end in pairs
    ]
    logger.info(
        "Generated %s interval(s) from %s extrema (δ=%s d)",
        len(rows),
        len(times),
        delta_time_d,
    )
    return {"intervals": _sorted_interval_rows(rows)}


def add_manual_interval(
    payload: dict | None,
    *,
    start_jd: float,
    end_jd: float,
) -> dict:
    """Appends one manually marked interval.

    Args:
        payload (dict | None): Existing intervals blob.
        start_jd (float): Interval start (absolute JD).
        end_jd (float): Interval end (absolute JD).

    Returns:
        dict: Updated intervals payload.

    Raises:
        ValueError: If bounds are non-finite, inverted, or duplicate an
            existing interval window.
    """
    lo = float(min(start_jd, end_jd))
    hi = float(max(start_jd, end_jd))
    if not math.isfinite(lo) or not math.isfinite(hi):
        raise ValueError("Interval bounds must be finite Julian Dates.")
    if hi <= lo:
        raise ValueError("Interval has zero width; drag a horizontal range.")
    normalised = normalize_intervals_payload(payload)
    for row in normalised["intervals"]:
        if (
            abs(float(row["start_jd"]) - lo) <= 1e-8
            and abs(float(row["end_jd"]) - hi) <= 1e-8
        ):
            raise ValueError("That interval is already in the list.")
    normalised["intervals"].append(
        {
            "id": str(uuid.uuid4()),
            "start_jd": lo,
            "end_jd": hi,
            "origin": "manual",
        }
    )
    normalised["intervals"] = _sorted_interval_rows(normalised["intervals"])
    logger.info("Added manual interval [%.8f, %.8f]", lo, hi)
    return normalised


def remove_interval_near_time(
    payload: dict | None,
    *,
    jd: float,
    hit_window_d: float,
) -> tuple[dict, bool]:
    """Removes the interval whose midpoint is nearest to ``jd``.

    Args:
        payload (dict | None): Intervals blob.
        jd (float): Click time (absolute JD).
        hit_window_d (float): Maximum |jd − midpoint| for a hit (days).

    Returns:
        tuple: ``(updated_payload, removed)``.

    Raises:
        ValueError: If there are no intervals or no hit within the window.
    """
    normalised = normalize_intervals_payload(payload)
    rows = normalised["intervals"]
    if not rows:
        raise ValueError("No intervals to delete.")
    if hit_window_d <= 0.0:
        raise ValueError("Interval delete hit window must be positive.")
    target = float(jd)
    best_i = None
    best_dist = None
    for index, row in enumerate(rows):
        mid = 0.5 * (float(row["start_jd"]) + float(row["end_jd"]))
        dist = abs(mid - target)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_i = index
    if best_i is None or best_dist is None or best_dist > float(hit_window_d):
        raise ValueError("No interval near the click.")
    removed = rows.pop(best_i)
    logger.info(
        "Removed interval id=%s [%.8f, %.8f]",
        removed["id"],
        removed["start_jd"],
        removed["end_jd"],
    )
    return {"intervals": _sorted_interval_rows(rows)}, True


def intervals_without_marked_ids(
    payload: dict | None,
    marked_ids: list | None,
) -> dict:
    """Drops interval rows whose ids appear in ``marked_ids``.

    Args:
        payload (dict | None): Intervals Store payload.
        marked_ids (list | None): Interval ids marked for removal.

    Returns:
        dict: Remaining intervals, still sorted by start JD.
    """
    normalised = normalize_intervals_payload(payload)
    drop = {str(item) for item in (marked_ids or []) if item is not None}
    if not drop:
        return normalised
    kept = [row for row in normalised["intervals"] if str(row["id"]) not in drop]
    return {"intervals": kept}


def _plot_x_for_pick_store(value) -> float | str:
    """Serialises a plot x bound for JSON Store transport.

    Args:
        value: MJD offset (float) or calendar datetime from Astropy.

    Returns:
        float or str: JSON-safe coordinate.
    """
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
        if hasattr(value, "isoformat"):
            return value.isoformat()
    return float(value)


def build_processor_interval_pick_payload(
    payload: dict | None,
    *,
    time_axis_mode: str,
    display_epoch: float,
    timescale: str | None = None,
    enabled: bool = True,
) -> dict:
    """Builds clientside hit-test metadata for processor interval bands.

    Args:
        payload (dict | None): Intervals Store payload.
        time_axis_mode (str): Active MJD or date axis mode.
        display_epoch (float): JD reference for MJD display.
        timescale (str | None): ``TIMESYS/@timescale`` for date axis.
        enabled (bool): When false, bands are omitted (mode and Show both off).

    Returns:
        dict: ``{enabled, axis, styles, bands: [{id, x0, x1}, ...]}``.
    """
    styles = {
        "plain": prep_interval_band_shape_style(marked=False),
        "marked": prep_interval_band_shape_style(marked=True),
    }
    if not enabled:
        return {
            "enabled": False,
            "axis": time_axis_mode,
            "styles": styles,
            "bands": [],
        }
    normalised = normalize_intervals_payload(payload)
    bands = []
    for row in normalised["intervals"]:
        x0, x1 = absolute_jd_to_plot_x(
            [float(row["start_jd"]), float(row["end_jd"])],
            time_axis_mode,
            display_epoch,
            timescale=timescale,
        )
        bands.append(
            {
                "id": str(row["id"]),
                "x0": _plot_x_for_pick_store(x0),
                "x1": _plot_x_for_pick_store(x1),
            }
        )
    return {
        "enabled": True,
        "axis": time_axis_mode,
        "styles": styles,
        "bands": bands,
    }


def format_cached_intervals_download(
    payload: dict | None,
    *,
    source_file: str | None = None,
    smooth_payload: dict | None = None,
    extrema_payload: dict | None = None,
) -> str:
    """Formats GP-layout interval ``.dat`` from the cached interval list.

    Does **not** regenerate from extrema; exports surviving intervals only,
    sorted by start JD.

    Args:
        payload (dict | None): Intervals blob.
        source_file (str | None): Light-curve file name.
        smooth_payload (dict | None): Smooth overlay metadata.
        extrema_payload (dict | None): Working extrema metadata for comments.

    Returns:
        str: File body.

    Raises:
        ValueError: If there are no intervals.
    """
    pairs = intervals_as_pairs(payload)
    if not pairs:
        raise ValueError("No intervals to export. Generate or mark intervals first.")
    extra: dict[str, Any] = {"n_intervals": len(pairs)}
    if extrema_payload:
        extra["extremum"] = extrema_payload.get("kind")
        extra["min_peak_distance_d"] = extrema_payload.get("min_distance_d")
        extra["min_segment_points"] = extrema_payload.get("min_segment_points")
    header = "".join(
        format_export_comment_lines(
            source_file=source_file,
            smooth_payload=smooth_payload,
            extra=extra,
        )
    )
    return header + format_intervals_download(pairs)


def parse_uploaded_extrema_jds(text: str) -> dict:
    """Parses Julian Dates from the first column of each data row.

    Extra columns on a row (σ, labels, flags, ``nan``, …) are ignored.
    The first field itself must be a finite number; a malformed token is
    not repaired. Optional metadata comments ``# JD0 = …`` or ``# JD = …``
    set the additive origin (default ``0``). Absolute JD is
    ``JD0 + first_column``.

    Args:
        text (str): File contents.

    Returns:
        dict: ``{"jd0": float, "times_jd": [absolute JD, ...]}`` sorted.

    Raises:
        ValueError: If the file is empty or the first field of a data
            line is not a finite number.
    """
    if text is None:
        raise ValueError("Uploaded extrema file is empty.")
    jd0 = 0.0
    times: list[float] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            body = stripped.lstrip("#").strip()
            if not body:
                continue
            if "=" in body:
                key, _, value = body.partition("=")
                if key.strip().upper() in {"JD0", "JD"}:
                    try:
                        jd0 = float(value.strip())
                    except ValueError as exc:
                        raise ValueError(
                            f"Uploaded extrema line {line_no}: invalid JD0 "
                            f"({raw!r})."
                        ) from exc
            continue
        first = stripped.replace(",", " ").split(None, 1)[0]
        try:
            value = float(first)
        except ValueError as exc:
            raise ValueError(
                f"Uploaded extrema line {line_no}: first column must be a "
                f"Julian Date ({raw!r})."
            ) from exc
        if not math.isfinite(value):
            raise ValueError(
                f"Uploaded extrema line {line_no}: first-column JD is not "
                f"finite."
            )
        times.append(float(jd0) + value)
    if not times:
        raise ValueError("Uploaded extrema file has no JD rows.")
    times_sorted = sorted(times)
    logger.info(
        "Parsed %s uploaded reference extrema (JD0=%s)", len(times_sorted), jd0
    )
    return {"jd0": float(jd0), "times_jd": times_sorted}


def processor_interval_band_shapes(
    payload: dict | None,
    *,
    time_axis_mode: str,
    display_epoch: float,
    marked_ids: list | None = None,
) -> list[dict]:
    """Builds Plotly rectangle shapes for processor intervals.

    Args:
        payload (dict | None): Intervals Store payload.
        time_axis_mode (str): ``mjd`` or ``date``.
        display_epoch (float): Display origin for MJD axis.
        marked_ids (list | None): Interval ids currently marked for removal.

    Returns:
        list[dict]: Shape dicts for ``layout.shapes``.
    """
    normalised = normalize_intervals_payload(payload)
    rows = normalised["intervals"]
    if not rows:
        return []
    marked = {str(item) for item in (marked_ids or []) if item is not None}
    shapes: list[dict] = []
    for row in rows:
        interval_id = str(row["id"])
        x0 = absolute_jd_to_plot_x(
            float(row["start_jd"]), time_axis_mode, display_epoch
        )
        x1 = absolute_jd_to_plot_x(
            float(row["end_jd"]), time_axis_mode, display_epoch
        )
        shapes.append(
            prep_interval_band_shape(
                x0,
                x1,
                name=interval_shape_name(interval_id),
                marked=interval_id in marked,
            )
        )
    return shapes
