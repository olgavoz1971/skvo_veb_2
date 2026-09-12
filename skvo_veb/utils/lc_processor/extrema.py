"""Rough extrema on a smooth overlay (spike ``find_peaks`` algorithm).

Peaks are taken on finite \(T(t_i)\) only. Non-finite overlay samples and
gap-split boundaries break the series so a hole is not treated as adjacent
samples. This is not a parabola ToM refinement.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

from skvo_veb.utils.gp.intervals import format_intervals_download
from skvo_veb.utils.lc_processor.config import (
    DEFAULT_MIN_EXTREMA_SEGMENT_POINTS,
    MIN_EXTREMA_SEGMENT_POINTS_FLOOR,
)
from skvo_veb.utils.lc_processor.smooth import METHOD_LABELS, contiguous_segment_bounds

logger = logging.getLogger(__name__)

EXTREMA_BLOB = "extrema"
EXTREMA_DELETE_HIT_FRAC = 0.02


def normalize_extremum_kind(extremum: str) -> str:
    """Normalise an extremum selector to ``min`` or ``max``.

    Args:
        extremum (str): ``min`` or ``max`` in the working photometry domain.

    Returns:
        str: Normalised extremum kind.

    Raises:
        ValueError: If ``extremum`` is not ``min`` or ``max``.
    """
    kind = str(extremum).strip().lower()
    if kind not in ("min", "max"):
        raise ValueError(f"extremum must be 'min' or 'max', got {extremum!r}")
    return kind


def normalize_working_domain(working_domain: str) -> str:
    """Normalise the working photometry domain label.

    Args:
        working_domain (str): ``mag`` or ``flux``.

    Returns:
        str: Normalised domain label.

    Raises:
        ValueError: If ``working_domain`` is unsupported.
    """
    domain = str(working_domain).strip().lower()
    if domain not in ("mag", "flux"):
        raise ValueError(
            f"working_domain must be 'mag' or 'flux', got {working_domain!r}"
        )
    return domain


def extrema_signal(
    smooth: np.ndarray,
    *,
    working_domain: str,
    extremum_kind: str,
) -> np.ndarray:
    """Return a series whose peaks are the requested extrema on the smooth.

    Magnitude minima are peaks of the magnitude series. Flux minima are
    peaks of the negated flux. The mapping matches the running-parabola
    spike.

    Args:
        smooth (numpy.ndarray): Smoothed photometry samples.
        working_domain (str): ``mag`` or ``flux``.
        extremum_kind (str): ``min`` or ``max`` in that domain.

    Returns:
        numpy.ndarray: Signal passed to ``scipy.signal.find_peaks``.
    """
    domain = normalize_working_domain(working_domain)
    kind = normalize_extremum_kind(extremum_kind)
    values = np.asarray(smooth, dtype=float)
    if domain == "flux":
        return -values if kind == "min" else values
    return values if kind == "min" else -values


def finite_run_bounds(values: np.ndarray) -> list[tuple[int, int]]:
    """Return ``[l, h)`` index ranges of contiguous finite samples.

    Args:
        values (numpy.ndarray): Photometry or trend samples.

    Returns:
        list[tuple[int, int]]: Half-open runs where every sample is finite.
    """
    finite = np.isfinite(np.asarray(values, dtype=float))
    if finite.size == 0 or not np.any(finite):
        return []
    padded = np.concatenate(([False], finite, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    starts = edges[0::2]
    ends = edges[1::2]
    return [(int(lo), int(hi)) for lo, hi in zip(starts, ends)]


@dataclass(frozen=True)
class OverlayExtremaResult:
    """Extrema detected on a finite smooth overlay.

    Attributes:
        jd (numpy.ndarray): Extremum times (absolute JD).
        smooth (numpy.ndarray): Overlay photometry at each extremum.
        median_interval_d (float | None): Median spacing between consecutive
            extrema (days); ``None`` when fewer than two are found.
        min_distance_d (float): Minimum separation constraint (days).
        min_segment_points (int): Finite samples required in a run.
        n_extrema (int): Number of detected extrema.
        n_skipped_short (int): Runs skipped for being shorter than
            ``min_segment_points``.
        extremum_kind (str): ``min`` or ``max`` in the working domain.
        working_domain (str): ``mag`` or ``flux``.
    """

    jd: np.ndarray
    smooth: np.ndarray
    median_interval_d: float | None
    min_distance_d: float
    n_extrema: int
    extremum_kind: str
    working_domain: str
    min_segment_points: int = DEFAULT_MIN_EXTREMA_SEGMENT_POINTS
    n_skipped_short: int = 0


def find_overlay_extrema(
    times: np.ndarray,
    trend: np.ndarray,
    *,
    working_domain: str,
    extremum_kind: str,
    min_distance_d: float,
    break_tolerance: float | None,
    min_segment_points: int = DEFAULT_MIN_EXTREMA_SEGMENT_POINTS,
) -> OverlayExtremaResult:
    """Detect extrema on finite overlay samples with a minimum time separation.

    Uses ``scipy.signal.find_peaks`` on a domain-appropriate sign flip, as in
    the running-parabola spike. Each gap-split piece is further cut at
    non-finite \(T\) so a hole is not treated as neighbouring samples. The
    ``find_peaks`` sample distance is ``min_distance_d`` divided by the
    median \(\Delta t\) of that finite run. Runs shorter than
    ``min_segment_points`` are skipped.

    Args:
        times (numpy.ndarray): Observation times (absolute JD), time-ordered.
        trend (numpy.ndarray): Overlay \(T(t_i)\); non-finite samples are
            ignored.
        working_domain (str): ``mag`` or ``flux``.
        extremum_kind (str): ``min`` or ``max`` in that domain.
        min_distance_d (float): Minimum separation between extrema (days).
        break_tolerance (float | None): Gap used for the last smooth, in days.
        min_segment_points (int): Finite overlay samples required in a run.

    Returns:
        OverlayExtremaResult: Detected extrema and median interval.

    Raises:
        ValueError: If inputs are invalid or no finite overlay samples exist.
    """
    kind = normalize_extremum_kind(extremum_kind)
    domain = normalize_working_domain(working_domain)
    if min_distance_d <= 0.0:
        raise ValueError(f"min_distance_d must be positive, got {min_distance_d}")
    n_min = int(min_segment_points)
    if n_min < MIN_EXTREMA_SEGMENT_POINTS_FLOOR:
        raise ValueError(
            f"min_segment_points must be at least "
            f"{MIN_EXTREMA_SEGMENT_POINTS_FLOOR}, got {min_segment_points}"
        )
    jd = np.asarray(times, dtype=float)
    smooth = np.asarray(trend, dtype=float)
    if jd.size != smooth.size:
        raise ValueError("times and trend length mismatch")
    if jd.size == 0:
        raise ValueError("overlay is empty")
    if not np.any(np.isfinite(smooth)):
        raise ValueError("overlay has no finite trend samples.")

    ext_jd: list[float] = []
    ext_smooth: list[float] = []
    n_skipped_short = 0
    for seg_lo, seg_hi in contiguous_segment_bounds(jd, break_tolerance):
        t_seg = jd[seg_lo:seg_hi]
        y_seg = smooth[seg_lo:seg_hi]
        for run_lo, run_hi in finite_run_bounds(y_seg):
            t_run = t_seg[run_lo:run_hi]
            y_run = y_seg[run_lo:run_hi]
            if t_run.size < n_min:
                n_skipped_short += 1
                continue
            dt = np.diff(t_run)
            step_d = float(np.median(dt))
            if step_d <= 0.0:
                logger.warning(
                    "Skipping finite overlay run of %s point(s): non-positive "
                    "median dt",
                    t_run.size,
                )
                continue
            signal = extrema_signal(
                y_run, working_domain=domain, extremum_kind=kind
            )
            distance_samples = max(1, int(np.floor(float(min_distance_d) / step_d)))
            peak_idx, _props = find_peaks(signal, distance=distance_samples)
            for idx in peak_idx:
                ext_jd.append(float(t_run[idx]))
                ext_smooth.append(float(y_run[idx]))

    if n_skipped_short:
        logger.info(
            "Overlay extrema: skipped %s short run(s) (min_segment_points=%s)",
            n_skipped_short,
            n_min,
        )
    if not ext_jd:
        logger.warning(
            "No overlay %sima found (min_distance_d=%s, min_segment_points=%s)",
            kind,
            min_distance_d,
            n_min,
        )
        return OverlayExtremaResult(
            jd=np.asarray([], dtype=float),
            smooth=np.asarray([], dtype=float),
            median_interval_d=None,
            min_distance_d=float(min_distance_d),
            n_extrema=0,
            extremum_kind=kind,
            working_domain=domain,
            min_segment_points=n_min,
            n_skipped_short=n_skipped_short,
        )

    jd_arr = np.asarray(ext_jd, dtype=float)
    smooth_arr = np.asarray(ext_smooth, dtype=float)
    order = np.argsort(jd_arr)
    jd_arr = jd_arr[order]
    smooth_arr = smooth_arr[order]
    median_interval: float | None
    if jd_arr.size >= 2:
        median_interval = float(np.median(np.diff(jd_arr)))
    else:
        median_interval = None
    logger.info(
        "Overlay %sima: %s hit(s), median interval=%s d (min_distance=%s d)",
        kind,
        jd_arr.size,
        f"{median_interval:.6f}" if median_interval is not None else "n/a",
        min_distance_d,
    )
    return OverlayExtremaResult(
        jd=jd_arr,
        smooth=smooth_arr,
        median_interval_d=median_interval,
        min_distance_d=float(min_distance_d),
        n_extrema=int(jd_arr.size),
        extremum_kind=kind,
        working_domain=domain,
        min_segment_points=n_min,
        n_skipped_short=n_skipped_short,
    )


def pack_extrema_payload(
    result: OverlayExtremaResult,
    *,
    delta_time_d: float,
) -> dict:
    """Builds the session-cache rough-extrema payload.

    Args:
        result (OverlayExtremaResult): Detected extrema.
        delta_time_d (float): Interval half-width stored with the find (days).

    Returns:
        dict: JSON-safe extrema blob.

    Raises:
        ValueError: If ``delta_time_d`` is not positive.
    """
    if delta_time_d <= 0.0:
        raise ValueError(f"delta_time_d must be positive, got {delta_time_d}")
    hits = []
    for tom, value in zip(result.jd, result.smooth):
        hits.append(
            {
                "id": str(uuid.uuid4()),
                "jd": float(tom),
                "smooth": float(value),
                "kind": result.extremum_kind,
                "origin": "auto",
            }
        )
    return {
        "hits": hits,
        "kind": result.extremum_kind,
        "domain": result.working_domain,
        "min_distance_d": float(result.min_distance_d),
        "min_segment_points": int(result.min_segment_points),
        "n_skipped_short": int(result.n_skipped_short),
        "delta_time_d": float(delta_time_d),
        "median_interval_d": result.median_interval_d,
        "n_extrema": int(result.n_extrema),
    }


def _refresh_extrema_payload(payload: dict, hits: list[dict]) -> dict:
    """Rebuilds summary fields after a manual add or delete.

    Args:
        payload (dict): Existing extrema blob.
        hits (list[dict]): Updated hit list.

    Returns:
        dict: Payload with sorted hits and refreshed counts.
    """
    ordered = sorted(hits, key=lambda hit: float(hit["jd"]))
    times = np.asarray([float(hit["jd"]) for hit in ordered], dtype=float)
    median_interval = None
    if times.size >= 2:
        median_interval = float(np.median(np.diff(times)))
    updated = dict(payload)
    updated["hits"] = ordered
    updated["n_extrema"] = int(len(ordered))
    updated["median_interval_d"] = median_interval
    return updated


def add_manual_extremum(
    payload: dict | None,
    *,
    jd: float,
    smooth: float,
    kind: str,
    domain: str,
    min_distance_d: float,
    delta_time_d: float,
) -> dict:
    """Adds a manual hit at the clicked time, or returns the payload unchanged.

    The click JD is stored as given. A second click at the same JD is ignored.

    Args:
        payload (dict | None): Current extrema blob, or ``None``.
        jd (float): Clicked time (absolute JD).
        smooth (float): Clicked plot \(y\) (marker height only).
        kind (str): ``min`` or ``max``.
        domain (str): ``mag`` or ``flux``.
        min_distance_d (float): Finder separation stored on a new blob.
        delta_time_d (float): Interval half-width stored on a new blob.

    Returns:
        dict: Updated extrema blob.

    Raises:
        ValueError: If ``delta_time_d`` or ``min_distance_d`` is not positive.
    """
    if delta_time_d <= 0.0:
        raise ValueError(f"delta_time_d must be positive, got {delta_time_d}")
    if min_distance_d <= 0.0:
        raise ValueError(f"min_distance_d must be positive, got {min_distance_d}")
    kind_n = normalize_extremum_kind(kind)
    domain_n = normalize_working_domain(domain)
    if payload is None:
        payload = {
            "hits": [],
            "kind": kind_n,
            "domain": domain_n,
            "min_distance_d": float(min_distance_d),
            "min_segment_points": int(DEFAULT_MIN_EXTREMA_SEGMENT_POINTS),
            "n_skipped_short": 0,
            "delta_time_d": float(delta_time_d),
            "median_interval_d": None,
            "n_extrema": 0,
        }
    hits = list(payload.get("hits") or [])
    tom = float(jd)
    if any(abs(float(hit["jd"]) - tom) <= 1.0e-9 for hit in hits):
        return payload
    hits.append(
        {
            "id": str(uuid.uuid4()),
            "jd": tom,
            "smooth": float(smooth),
            "kind": kind_n,
            "origin": "manual",
        }
    )
    logger.info("Added manual rough extremum at JD=%s", tom)
    return _refresh_extrema_payload(payload, hits)


def remove_extremum_near_time(
    payload: dict | None,
    click_jd: float,
    *,
    hit_span_d: float,
    hit_frac: float = EXTREMA_DELETE_HIT_FRAC,
) -> dict | None:
    """Removes the nearest hit if it lies inside the hit window.

    Args:
        payload (dict | None): Current extrema blob.
        click_jd (float): Clicked time (absolute JD).
        hit_span_d (float): Visible time span used for the hit window (days).
        hit_frac (float): Fraction of ``hit_span_d`` that counts as near.

    Returns:
        dict | None: Updated blob, or the input when nothing was removed.
    """
    if not payload or not payload.get("hits"):
        return payload
    hits = list(payload["hits"])
    nearest = min(hits, key=lambda hit: abs(float(hit["jd"]) - float(click_jd)))
    span = max(float(hit_span_d), 1.0e-12)
    if abs(float(nearest["jd"]) - float(click_jd)) > float(hit_frac) * span:
        return payload
    remaining = [hit for hit in hits if hit["id"] != nearest["id"]]
    logger.info("Removed rough extremum at JD=%s", nearest["jd"])
    return _refresh_extrema_payload(payload, remaining)


def extrema_xy_from_payload(
    payload: dict | None,
    *,
    domain: str,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Returns marker coordinates when the blob matches the working domain.

    Args:
        payload (dict | None): Extrema blob from the session cache.
        domain (str): Current working photometric domain.

    Returns:
        tuple | None: ``(jd, smooth)``, or ``None`` when unused.
    """
    if not payload:
        return None
    if payload.get("domain") != domain:
        return None
    hits = payload.get("hits") or []
    if not hits:
        return None
    jd = np.asarray([float(hit["jd"]) for hit in hits], dtype=float)
    smooth = np.asarray([float(hit["smooth"]) for hit in hits], dtype=float)
    return jd, smooth


def rough_tom_interval_pairs(
    times_jd: np.ndarray,
    *,
    delta_time_d: float,
) -> list[list[float]]:
    """Build ``[start, end]`` interval pairs centred on rough extrema.

    Each interval spans ``[tom - delta_time_d, tom + delta_time_d]`` in JD.

    Args:
        times_jd (numpy.ndarray): Extremum times (absolute JD).
        delta_time_d (float): Half-width of each interval (days).

    Returns:
        list[list[float]]: ``[interval_start, interval_end]`` pairs sorted
            by start time.

    Raises:
        ValueError: If ``delta_time_d`` is not positive or no times were given.
    """
    if delta_time_d <= 0.0:
        raise ValueError(f"delta_time_d must be positive, got {delta_time_d}")
    toms = np.sort(np.asarray(times_jd, dtype=float))
    if toms.size == 0:
        raise ValueError("cannot build intervals: no rough extrema found")
    pairs: list[list[float]] = []
    for tom in toms:
        start = float(tom) - float(delta_time_d)
        end = float(tom) + float(delta_time_d)
        if start >= end:
            raise ValueError(
                f"invalid interval from tom={tom}: start={start} >= end={end}"
            )
        pairs.append([start, end])
    return pairs


def _comment_token(value) -> str:
    """Formats one metadata value for a ``#`` comment line.

    Args:
        value: Scalar stored on the overlay or extrema blob.

    Returns:
        str: Single-line token.
    """
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = " ".join(str(value).split())
    if not text:
        return "none"
    return text


def format_export_comment_lines(
    *,
    source_file: str | None = None,
    smooth_payload: dict | None = None,
    extra: dict | None = None,
) -> list[str]:
    """Builds ``#`` metadata lines for a product file.

    Args:
        source_file (str | None): Original light-curve file name.
        smooth_payload (dict | None): Last Apply-smooth overlay.
        extra (dict | None): Extra ``key -> value`` comments (extrema knobs).

    Returns:
        list[str]: Comment lines, each ending with a newline.
    """
    lines: list[str] = []
    if source_file:
        lines.append(f"# source_file: {_comment_token(source_file)}\n")
    if smooth_payload:
        method = smooth_payload.get("method")
        if method:
            lines.append(f"# smooth_method: {_comment_token(method)}\n")
            label = METHOD_LABELS.get(str(method))
            if label:
                lines.append(f"# smooth_label: {_comment_token(label)}\n")
        params = smooth_payload.get("params")
        if not isinstance(params, dict) or not params:
            params = {}
            if "break_tolerance" in smooth_payload:
                params["break_tolerance_d"] = smooth_payload.get("break_tolerance")
            if smooth_payload.get("window_width_d") is not None:
                params["window_days"] = smooth_payload.get("window_width_d")
        for key in sorted(params):
            lines.append(f"# {key}: {_comment_token(params[key])}\n")
    if extra:
        for key in extra:
            if extra[key] is None:
                continue
            lines.append(f"# {key}: {_comment_token(extra[key])}\n")
    return lines


def format_intervals_from_payload(
    payload: dict | None,
    *,
    delta_time_d: float,
    source_file: str | None = None,
    smooth_payload: dict | None = None,
) -> str:
    """Format GP-layout interval ``.dat`` contents from a cached find.

    Args:
        payload (dict | None): Extrema blob from the session cache.
        delta_time_d (float): Half-width applied at export time (days).
        source_file (str | None): Original light-curve file name.
        smooth_payload (dict | None): Last Apply-smooth overlay.

    Returns:
        str: File body with ``#`` metadata then ``# Interval_Start  Interval_End``.

    Raises:
        ValueError: If there are no hits or the half-width is invalid.
    """
    if not payload or not payload.get("hits"):
        raise ValueError("Find extrema first.")
    times = np.asarray([float(hit["jd"]) for hit in payload["hits"]], dtype=float)
    header = "".join(
        format_export_comment_lines(
            source_file=source_file,
            smooth_payload=smooth_payload,
            extra={
                "extremum": payload.get("kind"),
                "interval_half_width_d": float(delta_time_d),
                "min_peak_distance_d": payload.get("min_distance_d"),
                "min_segment_points": payload.get("min_segment_points"),
            },
        )
    )
    return header + format_intervals_download(
        rough_tom_interval_pairs(times, delta_time_d=delta_time_d)
    )


def format_rough_toms_download(
    payload: dict | None,
    *,
    source_file: str | None = None,
    smooth_payload: dict | None = None,
) -> str:
    """Format a compact ToM ``.dat`` body (JD and empty σ).

    σ(JD) is written as ``nan``. This file is a rough finder product, not a
    GP or MAVKA timing. ``parse_compact_tom_contents`` accepts the layout.

    Args:
        payload (dict | None): Extrema blob from the session cache.
        source_file (str | None): Original light-curve file name.
        smooth_payload (dict | None): Last Apply-smooth overlay.

    Returns:
        str: File body with header comments and two columns.

    Raises:
        ValueError: If there are no hits.
    """
    if not payload or not payload.get("hits"):
        raise ValueError("Find extrema first.")
    kind = normalize_extremum_kind(payload.get("kind") or "min")
    mode_label = "Minimum" if kind == "min" else "Maximum"
    lines = format_export_comment_lines(
        source_file=source_file,
        smooth_payload=smooth_payload,
        extra={
            "extremum": kind,
            "min_peak_distance_d": payload.get("min_distance_d"),
            "min_segment_points": payload.get("min_segment_points"),
        },
    )
    lines.extend(
        [
            f"# Rough {mode_label} times\n",
            f"# JD_{mode_label}\n",
            "# JD_Std\n",
        ]
    )
    times = np.sort(
        np.asarray([float(hit["jd"]) for hit in payload["hits"]], dtype=float)
    )
    for tom in times:
        lines.append(f"{float(tom):.10f}  nan\n")
    return "".join(lines)


def find_extrema_from_smooth(
    smooth_payload: dict | None,
    times: np.ndarray,
    *,
    domain: str,
    method: str,
    extremum_kind: str,
    min_distance_d: float,
    delta_time_d: float,
    min_segment_points: int = DEFAULT_MIN_EXTREMA_SEGMENT_POINTS,
) -> dict:
    """Finds rough extrema on the last matching Apply-smooth overlay.

    Args:
        smooth_payload (dict | None): Last Apply-smooth overlay.
        times (numpy.ndarray): Current (cropped) absolute JD.
        domain (str): Working photometric domain.
        method (str): Active smooth method id.
        extremum_kind (str): ``min`` or ``max``.
        min_distance_d (float): Minimum separation (days).
        delta_time_d (float): Interval half-width stored with the find (days).
        min_segment_points (int): Finite overlay samples required in a run.

    Returns:
        dict: Extrema payload for the session cache.

    Raises:
        ValueError: If there is no matching overlay or the widgets are invalid.
    """
    from skvo_veb.utils.lc_processor.apply import overlay_trend

    trend = overlay_trend(
        smooth_payload,
        times,
        domain=domain,
        method=method,
    )
    if trend is None:
        raise ValueError("Apply smooth first.")
    result = find_overlay_extrema(
        times,
        trend,
        working_domain=domain,
        extremum_kind=extremum_kind,
        min_distance_d=min_distance_d,
        break_tolerance=(
            None if smooth_payload is None else smooth_payload.get("break_tolerance")
        ),
        min_segment_points=min_segment_points,
    )
    return pack_extrema_payload(result, delta_time_d=delta_time_d)
