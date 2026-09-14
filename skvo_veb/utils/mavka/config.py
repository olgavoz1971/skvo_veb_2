"""Scientific defaults for MAVKA phenomenological extrema timing."""

from __future__ import annotations

# Wall-supported asymptotic parabola: default for flux and mag minima.
DEFAULT_METHOD = "WSAP"

# v1 times troughs in the working photometry (eclipses in mag or flux).
DEFAULT_EXTREMA_MODE = "min"

# Matches ``approx()`` in ``models.py`` (need at least 6 points).
MIN_POINTS = 6

METHOD_OPTIONS = (
    {"label": "AP", "value": "AP"},
    {"label": "WSAP", "value": "WSAP"},
    {"label": "WSL", "value": "WSL"},
    {"label": "A", "value": "A"},
)

MAXIMA_NOT_AVAILABLE = (
    "MAVKA maxima search is not available in this version. Select Search minima."
)
