"""MAVKA phenomenological extrema timing (Andrych / Andronov / Chinarova)."""

from skvo_veb.utils.mavka.config import (
    DEFAULT_EXTREMA_MODE,
    DEFAULT_METHOD,
    MAVKA_LIVE_PAGE_SIZE,
    MAVKA_REVIEW_PAGE_SIZE,
    MAXIMA_NOT_AVAILABLE,
    METHOD_OPTIONS,
    MIN_POINTS,
)
from skvo_veb.utils.mavka.figure import figure_from_mavka_result
from skvo_veb.utils.mavka.pipeline import fit_interval, slice_interval_photometry

__all__ = [
    "DEFAULT_EXTREMA_MODE",
    "DEFAULT_METHOD",
    "MAVKA_LIVE_PAGE_SIZE",
    "MAVKA_REVIEW_PAGE_SIZE",
    "MAXIMA_NOT_AVAILABLE",
    "METHOD_OPTIONS",
    "MIN_POINTS",
    "figure_from_mavka_result",
    "fit_interval",
    "slice_interval_photometry",
]
