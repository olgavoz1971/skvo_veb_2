"""Extremum kind (min/max) helpers for the running-parabola spike."""

from __future__ import annotations

import numpy as np


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
        raise ValueError(f"working_domain must be 'mag' or 'flux', got {working_domain!r}")
    return domain


def extrema_signal(
    smooth: np.ndarray,
    *,
    working_domain: str,
    extremum_kind: str,
) -> np.ndarray:
    """Return a series whose peaks are the requested extrema on the smooth curve.

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


def expected_curvature_sign(*, working_domain: str, extremum_kind: str) -> float:
    """Return the required sign of parabola ``c2`` for the requested extremum.

    Args:
        working_domain (str): ``mag`` or ``flux``.
        extremum_kind (str): ``min`` or ``max`` in that domain.

    Returns:
        float: Expected sign of the quadratic coefficient.
    """
    domain = normalize_working_domain(working_domain)
    kind = normalize_extremum_kind(extremum_kind)
    if domain == "flux":
        return 1.0 if kind == "min" else -1.0
    return -1.0 if kind == "min" else 1.0
