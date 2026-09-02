"""Rough extremum times and period from a running-parabola smooth."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

from extremum_kind import extrema_signal, normalize_extremum_kind
from running_parabola import SmoothedPoint

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmoothExtremaResult:
    """Extrema detected on the smoothed curve and a rough period estimate.

    Attributes:
        jd (numpy.ndarray): Extremum times (JD at window centres).
        smooth (numpy.ndarray): Smoothed photometry at each extremum.
        indices (numpy.ndarray): Indices into the smoothed-point list.
        median_interval_d (float | None): Median spacing between consecutive
            extrema (days); ``None`` when fewer than two extrema are found.
        min_distance_d (float): Minimum separation constraint (days).
        n_extrema (int): Number of detected extrema.
        extremum_kind (str): ``min`` or ``max`` in the working domain.
    """

    jd: np.ndarray
    smooth: np.ndarray
    indices: np.ndarray
    median_interval_d: float | None
    min_distance_d: float
    n_extrema: int
    extremum_kind: str


def find_smooth_extrema(
    points: list[SmoothedPoint],
    *,
    working_domain: str,
    extremum_kind: str,
    min_distance_d: float,
    step_d: float,
) -> SmoothExtremaResult:
    """Detect extrema on the smoothed curve with a minimum calendar-time separation.

    Uses ``scipy.signal.find_peaks`` on a domain-appropriate sign flip. Rough
    period is the median interval between consecutive detected extrema.

    Args:
        points (list[SmoothedPoint]): Running-parabola output series.
        working_domain (str): ``mag`` or ``flux``.
        extremum_kind (str): ``min`` or ``max`` in the working domain.
        min_distance_d (float): Minimum separation between extrema (days).
        step_d (float): Nominal centre step (days), used to convert separation to
            sample distance for ``find_peaks``.

    Returns:
        SmoothExtremaResult: Detected extrema and median interval.

    Raises:
        ValueError: If inputs are invalid or the smoothed series is empty.
    """
    kind = normalize_extremum_kind(extremum_kind)
    if min_distance_d <= 0.0:
        raise ValueError(f"min_distance_d must be positive, got {min_distance_d}")
    if step_d <= 0.0:
        raise ValueError(f"step_d must be positive, got {step_d}")
    if not points:
        raise ValueError("points must not be empty")

    jd = np.array([p.jd for p in points], dtype=float)
    smooth = np.array([p.smooth for p in points], dtype=float)
    if jd.size != smooth.size:
        raise ValueError("jd and smooth length mismatch")

    signal = extrema_signal(smooth, working_domain=working_domain, extremum_kind=kind)
    distance_samples = max(1, int(np.floor(float(min_distance_d) / float(step_d))))
    peak_idx, _props = find_peaks(signal, distance=distance_samples)

    if peak_idx.size == 0:
        logger.warning(
            "No smooth %sima found (min_distance_d=%s, distance_samples=%s)",
            kind,
            min_distance_d,
            distance_samples,
        )
        return SmoothExtremaResult(
            jd=np.asarray([], dtype=float),
            smooth=np.asarray([], dtype=float),
            indices=np.asarray([], dtype=int),
            median_interval_d=None,
            min_distance_d=float(min_distance_d),
            n_extrema=0,
            extremum_kind=kind,
        )

    ext_jd = jd[peak_idx]
    ext_smooth = smooth[peak_idx]
    median_interval: float | None
    if ext_jd.size >= 2:
        intervals = np.diff(np.sort(ext_jd))
        median_interval = float(np.median(intervals))
    else:
        median_interval = None

    logger.info(
        "Smooth %sima: %s hit(s), median interval=%s d (min_distance=%s d, "
        "distance_samples=%s)",
        kind,
        peak_idx.size,
        f"{median_interval:.6f}" if median_interval is not None else "n/a",
        min_distance_d,
        distance_samples,
    )
    return SmoothExtremaResult(
        jd=ext_jd,
        smooth=ext_smooth,
        indices=peak_idx.astype(int),
        median_interval_d=median_interval,
        min_distance_d=float(min_distance_d),
        n_extrema=int(peak_idx.size),
        extremum_kind=kind,
    )


def find_smooth_minima(
    points: list[SmoothedPoint],
    *,
    working_domain: str,
    min_distance_d: float,
    step_d: float,
) -> SmoothExtremaResult:
    """Detect minima on the smoothed curve (``extremum_kind='min'`` wrapper).

    Args:
        points (list[SmoothedPoint]): Running-parabola output series.
        working_domain (str): ``mag`` or ``flux``.
        min_distance_d (float): Minimum separation between minima (days).
        step_d (float): Nominal centre step (days).

    Returns:
        SmoothExtremaResult: Detected minima and median interval.
    """
    return find_smooth_extrema(
        points,
        working_domain=working_domain,
        extremum_kind="min",
        min_distance_d=min_distance_d,
        step_d=step_d,
    )


def rough_tom_interval_pairs(
    extrema: SmoothExtremaResult,
    *,
    delta_time_d: float,
) -> list[tuple[float, float]]:
    """Build ``[start, end]`` interval pairs centred on rough smooth extrema.

    Each interval spans ``[tom - delta_time_d, tom + delta_time_d]`` in JD.

    Args:
        extrema (SmoothExtremaResult): Rough extrema from the smoothed curve.
        delta_time_d (float): Half-width of each interval (days).

    Returns:
        list[tuple[float, float]]: ``(interval_start, interval_end)`` pairs sorted
            by start time.

    Raises:
        ValueError: If ``delta_time_d`` is not positive or no extrema were found.
    """
    if delta_time_d <= 0.0:
        raise ValueError(f"delta_time_d must be positive, got {delta_time_d}")
    if extrema.n_extrema == 0:
        raise ValueError(
            f"cannot build intervals: no rough {extrema.extremum_kind}ima found"
        )

    pairs: list[tuple[float, float]] = []
    for tom in np.sort(np.asarray(extrema.jd, dtype=float)):
        start = float(tom) - float(delta_time_d)
        end = float(tom) + float(delta_time_d)
        if start >= end:
            raise ValueError(
                f"invalid interval from tom={tom}: start={start} >= end={end}"
            )
        pairs.append((start, end))
    return pairs


def export_rough_tom_intervals_ascii(
    path,
    extrema: SmoothExtremaResult,
    *,
    delta_time_d: float,
    source_lc: str,
) -> None:
    """Write rough-extremum interval windows in GP interval ``.dat`` layout.

    Header: ``# Interval_Start  Interval_End``. Each row is
    ``tom - delta_time_d`` and ``tom + delta_time_d`` for one rough extremum.

    Args:
        path: Output file path.
        extrema (SmoothExtremaResult): Rough extrema from the smoothed curve.
        delta_time_d (float): Half-width applied symmetrically about each ToM (days).
        source_lc (str): Input light-curve label for provenance comments.

    Returns:
        None.

    Raises:
        ValueError: If interval construction fails.
    """
    from pathlib import Path

    pairs = rough_tom_interval_pairs(extrema, delta_time_d=delta_time_d)
    out_path = Path(path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# tool: running_parabola_spike\n")
        handle.write("# step: rough_tom_intervals\n")
        handle.write(f"# source_lc: {source_lc}\n")
        handle.write(f"# extremum: {extrema.extremum_kind}\n")
        handle.write(f"# delta_time_d: {delta_time_d}\n")
        handle.write(f"# n_intervals: {len(pairs)}\n")
        handle.write("# Interval_Start  Interval_End\n")
        for start, end in pairs:
            handle.write(f"{start:<20} {end:<20}\n")
    logger.info(
        "Wrote %s (%s interval(s), extremum=%s, delta_time_d=%s)",
        out_path,
        len(pairs),
        extrema.extremum_kind,
        delta_time_d,
    )
