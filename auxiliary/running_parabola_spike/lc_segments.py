"""Split a light curve into independent segments at calendar-time gaps."""

from __future__ import annotations

import logging

import numpy as np

from parabola_tom import ParabolaTomResult
from smooth_extrema import SmoothExtremaResult

logger = logging.getLogger(__name__)


def split_index_ranges_by_min_gap(
    times_sorted: np.ndarray,
    min_gap_d: float | None,
) -> list[tuple[int, int]]:
    """Return ``[l, h)`` index ranges split where consecutive Δt exceeds ``min_gap_d``.

    Args:
        times_sorted (numpy.ndarray): Time-ordered sample times (JD).
        min_gap_d (float | None): Minimum gap in days that starts a new segment.
            ``None`` disables splitting (one range covering the whole series).

    Returns:
        list[tuple[int, int]]: Half-open index intervals covering the series.

    Raises:
        ValueError: If ``min_gap_d`` is not positive when splitting is requested,
            or if ``times_sorted`` is empty.
    """
    t = np.asarray(times_sorted, dtype=float)
    n = int(t.size)
    if n == 0:
        raise ValueError("cannot split an empty time series")
    if min_gap_d is None:
        return [(0, n)]
    gap = float(min_gap_d)
    if gap <= 0.0:
        raise ValueError(f"min_gap_d must be positive when splitting, got {min_gap_d}")
    if n == 1:
        return [(0, 1)]

    dt = t[1:] - t[:-1]
    if np.any(~np.isfinite(dt)):
        raise ValueError("time series contains non-finite intervals")
    if np.any(dt < 0.0):
        raise ValueError("times_sorted must be non-decreasing")

    cut = np.where(dt > gap)[0] + 1
    lows = np.concatenate(([0], cut))
    highs = np.concatenate((cut, [n]))
    ranges = [(int(lo), int(hi)) for lo, hi in zip(lows, highs)]
    logger.info(
        "Split into %s segment(s) at gaps > %.6f d",
        len(ranges),
        gap,
    )
    return ranges


def concatenate_smooth_extrema(
    parts: list[SmoothExtremaResult],
    *,
    index_offsets: list[int],
) -> SmoothExtremaResult:
    """Merge per-segment extrema, shifting indices into the concatenated smooth.

    Median spacing uses all consecutive extrema on the combined time-ordered
    list (the usual median is robust to one large inter-segment gap).

    Args:
        parts (list[SmoothExtremaResult]): One result per segment (may be empty).
        index_offsets (list[int]): Index of the first smoothed point of each
            segment in the concatenated smooth.

    Returns:
        SmoothExtremaResult: Combined extrema.

    Raises:
        ValueError: If ``parts`` and ``index_offsets`` lengths differ, or if
            metadata (kind / min distance) is inconsistent.
    """
    if len(parts) != len(index_offsets):
        raise ValueError(
            f"parts and index_offsets length mismatch: {len(parts)} vs {len(index_offsets)}"
        )
    if not parts:
        raise ValueError("parts must not be empty")

    kind = parts[0].extremum_kind
    min_distance_d = float(parts[0].min_distance_d)
    jd_blocks: list[np.ndarray] = []
    smooth_blocks: list[np.ndarray] = []
    idx_blocks: list[np.ndarray] = []
    for part, offset in zip(parts, index_offsets):
        if part.extremum_kind != kind:
            raise ValueError(
                f"extremum_kind mismatch: {part.extremum_kind!r} vs {kind!r}"
            )
        if float(part.min_distance_d) != min_distance_d:
            raise ValueError(
                f"min_distance_d mismatch: {part.min_distance_d} vs {min_distance_d}"
            )
        if part.n_extrema == 0:
            continue
        jd_blocks.append(np.asarray(part.jd, dtype=float))
        smooth_blocks.append(np.asarray(part.smooth, dtype=float))
        idx_blocks.append(np.asarray(part.indices, dtype=int) + int(offset))

    if not jd_blocks:
        return SmoothExtremaResult(
            jd=np.asarray([], dtype=float),
            smooth=np.asarray([], dtype=float),
            indices=np.asarray([], dtype=int),
            median_interval_d=None,
            min_distance_d=min_distance_d,
            n_extrema=0,
            extremum_kind=kind,
        )

    ext_jd = np.concatenate(jd_blocks)
    ext_smooth = np.concatenate(smooth_blocks)
    ext_idx = np.concatenate(idx_blocks)
    order = np.argsort(ext_jd)
    ext_jd = ext_jd[order]
    ext_smooth = ext_smooth[order]
    ext_idx = ext_idx[order]
    median_interval: float | None
    if ext_jd.size >= 2:
        median_interval = float(np.median(np.diff(ext_jd)))
    else:
        median_interval = None
    return SmoothExtremaResult(
        jd=ext_jd,
        smooth=ext_smooth,
        indices=ext_idx.astype(int),
        median_interval_d=median_interval,
        min_distance_d=min_distance_d,
        n_extrema=int(ext_jd.size),
        extremum_kind=kind,
    )


def concatenate_parabola_tom(parts: list[ParabolaTomResult]) -> ParabolaTomResult:
    """Merge per-segment parabola ToM results in time order.

    Args:
        parts (list[ParabolaTomResult]): One result per segment.

    Returns:
        ParabolaTomResult: Combined hits and counts.

    Raises:
        ValueError: If ``parts`` is empty or fit metadata disagrees.
    """
    if not parts:
        raise ValueError("parts must not be empty")
    kind = parts[0].extremum_kind
    half = float(parts[0].fit_half_width_d)
    hits = []
    n_attempted = 0
    n_failed = 0
    for part in parts:
        if part.extremum_kind != kind:
            raise ValueError(
                f"extremum_kind mismatch: {part.extremum_kind!r} vs {kind!r}"
            )
        if float(part.fit_half_width_d) != half:
            raise ValueError(
                f"fit_half_width_d mismatch: {part.fit_half_width_d} vs {half}"
            )
        hits.extend(part.hits)
        n_attempted += int(part.n_attempted)
        n_failed += int(part.n_failed)
    hits.sort(key=lambda h: h.tom_jd)
    return ParabolaTomResult(
        hits=hits,
        n_attempted=n_attempted,
        n_failed=n_failed,
        fit_half_width_d=half,
        extremum_kind=kind,
    )
