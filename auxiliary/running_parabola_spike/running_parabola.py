"""Sliding centred-parabola smoothing on unfolded calendar time."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from astropy.modeling import models
from astropy.modeling.fitting import LinearLSQFitter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunningParabolaConfig:
    """Parameters for sliding parabola smoothing.

    Attributes:
        window_width_d (float): Full window width in days.
        step_d (float): Shift between consecutive window centres (days).
        min_points (int): Minimum in-window samples required to fit.
        use_weights (bool): Weight by ``1/phot_err^2`` when errors are finite.
    """

    window_width_d: float
    step_d: float
    min_points: int = 5
    use_weights: bool = False


@dataclass(frozen=True)
class SmoothedPoint:
    """One running-parabola sample at a window centre.

    Attributes:
        jd (float): Window centre (absolute JD).
        smooth (float): Parabola value at the centre (constant term).
        curvature (float): Quadratic coefficient ``c`` in ``a + b·dt + c·dt²``.
        rms (float): RMS of in-window residuals to the fitted parabola.
        n_points (int): Number of LC points in the window.
    """

    jd: float
    smooth: float
    curvature: float
    rms: float
    n_points: int


def window_centres(
    t_min: float,
    t_max: float,
    *,
    window_width_d: float,
    step_d: float,
) -> np.ndarray:
    """Return window-centre times that keep the full window inside ``[t_min, t_max]``.

    Args:
        t_min (float): Earliest observation time (absolute JD).
        t_max (float): Latest observation time (absolute JD).
        window_width_d (float): Full window width (days).
        step_d (float): Step between centres (days).

    Returns:
        numpy.ndarray: Centre times (may be empty).

    Raises:
        ValueError: If geometry parameters are invalid.
    """
    if window_width_d <= 0.0:
        raise ValueError(f"window_width_d must be positive, got {window_width_d}")
    if step_d <= 0.0:
        raise ValueError(f"step_d must be positive, got {step_d}")
    half = 0.5 * window_width_d
    lo = float(t_min + half)
    hi = float(t_max - half)
    if lo > hi:
        return np.asarray([], dtype=float)
    n = int(np.floor((hi - lo) / step_d)) + 1
    if n <= 0:
        return np.asarray([], dtype=float)
    return lo + step_d * np.arange(n, dtype=float)


def _fit_window_parabola(
    t: np.ndarray,
    y: np.ndarray,
    y_err: np.ndarray,
    *,
    t_centre: float,
    use_weights: bool,
) -> tuple[float, float, float, float]:
    """Fit ``y = a + b·(t−t_c) + c·(t−t_c)²`` and return centre value and diagnostics.

    Args:
        t (numpy.ndarray): In-window times (absolute JD).
        y (numpy.ndarray): Photometry.
        y_err (numpy.ndarray): Uncertainties (NaN where missing).
        t_centre (float): Window centre ``t_c``.
        use_weights (bool): Apply inverse-variance weights when errors are usable.

    Returns:
        tuple: ``(smooth, curvature, rms, n_points)`` with ``smooth = a``.

    Raises:
        ValueError: If the fit fails or yields non-finite coefficients.
    """
    dt = np.asarray(t, dtype=float) - float(t_centre)
    y_arr = np.asarray(y, dtype=float)
    n = dt.size
    if n < 3:
        raise ValueError(f"need at least 3 points to fit a parabola, got {n}")

    poly = models.Polynomial1D(degree=2)
    fitter = LinearLSQFitter()
    weights = None
    if use_weights:
        err = np.asarray(y_err, dtype=float)
        finite = np.isfinite(err) & (err > 0.0)
        if np.count_nonzero(finite) >= 3:
            inv_var = np.zeros_like(y_arr)
            inv_var[finite] = 1.0 / (err[finite] ** 2)
            weights = inv_var

    fitted = fitter(poly, dt, y_arr, weights=weights)
    a = float(getattr(fitted.c0, "value", fitted.c0))
    c = float(getattr(fitted.c2, "value", fitted.c2))
    y_model = fitted(dt)
    resid = y_arr - y_model
    dof = max(n - 3, 1)
    rms = float(np.sqrt(np.sum(resid**2) / dof))
    if not (np.isfinite(a) and np.isfinite(c) and np.isfinite(rms)):
        raise ValueError("parabola fit returned non-finite coefficients or RMS")
    return a, c, rms, n


def smooth_running_parabola(
    jd: np.ndarray,
    phot: np.ndarray,
    phot_err: np.ndarray,
    *,
    cfg: RunningParabolaConfig,
    t_min: float | None = None,
    t_max: float | None = None,
) -> list[SmoothedPoint]:
    """Build a smoothed curve by sliding centred parabolas along calendar time.

    Args:
        jd (numpy.ndarray): Observation times (absolute JD).
        phot (numpy.ndarray): Photometry in the working domain.
        phot_err (numpy.ndarray): Per-point uncertainties (may be NaN).
        cfg (RunningParabolaConfig): Window, step, and weight settings.
        t_min (float | None): Optional crop lower bound (JD).
        t_max (float | None): Optional crop upper bound (JD).

    Returns:
        list[SmoothedPoint]: One point per successful window centre.

    Raises:
        ValueError: If the cropped series is empty or no window yields a fit.
    """
    order = np.argsort(np.asarray(jd, dtype=float))
    t_all = np.asarray(jd, dtype=float)[order]
    y_all = np.asarray(phot, dtype=float)[order]
    e_all = np.asarray(phot_err, dtype=float)[order]

    lo = float(t_min) if t_min is not None else float(np.min(t_all))
    hi = float(t_max) if t_max is not None else float(np.max(t_all))
    if lo > hi:
        raise ValueError(f"invalid crop: t_min={lo} > t_max={hi}")
    in_crop = (t_all >= lo) & (t_all <= hi)
    t_all = t_all[in_crop]
    y_all = y_all[in_crop]
    e_all = e_all[in_crop]
    if t_all.size == 0:
        raise ValueError(f"no LC points in crop [{lo}, {hi}]")

    centres = window_centres(
        float(np.min(t_all)),
        float(np.max(t_all)),
        window_width_d=cfg.window_width_d,
        step_d=cfg.step_d,
    )
    if centres.size == 0:
        raise ValueError(
            "no window centres fit inside the data span "
            f"(width={cfg.window_width_d}, step={cfg.step_d})"
        )

    half = 0.5 * cfg.window_width_d
    out: list[SmoothedPoint] = []
    skipped = 0
    for t_c in centres:
        mask = (t_all >= t_c - half) & (t_all <= t_c + half)
        n_in = int(np.count_nonzero(mask))
        if n_in < cfg.min_points:
            skipped += 1
            continue
        try:
            smooth, curv, rms, n_pts = _fit_window_parabola(
                t_all[mask],
                y_all[mask],
                e_all[mask],
                t_centre=float(t_c),
                use_weights=cfg.use_weights,
            )
        except (ValueError, TypeError) as exc:
            logger.debug("skip centre jd=%.8f: %s", t_c, exc)
            skipped += 1
            continue
        out.append(
            SmoothedPoint(
                jd=float(t_c),
                smooth=smooth,
                curvature=curv,
                rms=rms,
                n_points=n_pts,
            )
        )

    if not out:
        raise ValueError(
            f"no successful parabola fits ({centres.size} centres, "
            f"{skipped} skipped, min_points={cfg.min_points})"
        )
    logger.info(
        "Running parabola: %s smoothed points from %s centres (%s skipped)",
        len(out),
        centres.size,
        skipped,
    )
    return out


def export_smoothed_ascii(
    path,
    points: list[SmoothedPoint],
    *,
    source_lc: str,
    cfg: RunningParabolaConfig,
    working_domain: str,
) -> None:
    """Write smoothed points as a simple ``#``-commented ASCII table.

    Columns: ``jd smooth curvature rms`` (photometry in the working domain).

    Args:
        path: Output file path.
        points (list[SmoothedPoint]): Smoothed series.
        source_lc (str): Provenance label for the input LC.
        cfg (RunningParabolaConfig): Settings used for the run.
        working_domain (str): ``mag`` or ``flux``.

    Returns:
        None.
    """
    from pathlib import Path

    out_path = Path(path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# tool: running_parabola_spike\n")
        handle.write(f"# source_lc: {source_lc}\n")
        handle.write(f"# working_domain: {working_domain}\n")
        handle.write(f"# window_width_d: {cfg.window_width_d}\n")
        handle.write(f"# step_d: {cfg.step_d}\n")
        handle.write(f"# use_weights: {cfg.use_weights}\n")
        handle.write(f"# min_points: {cfg.min_points}\n")
        handle.write("# columns: jd smooth curvature rms\n")
        handle.write("# jd smooth curvature rms\n")
        for pt in points:
            handle.write(
                f"{pt.jd:.8f}  {pt.smooth:.8f}  {pt.curvature:.8e}  {pt.rms:.8e}\n"
            )
    logger.info("Wrote %s (%s row(s))", out_path, len(points))
