"""Configuration defaults for MAVKA phenomenological extrema timing."""

from __future__ import annotations

# Wall-supported asymptotic parabola: default for flux and mag minima.
DEFAULT_METHOD = "WSAP"

# v1 times troughs in the working photometry (eclipses in mag or flux).
DEFAULT_EXTREMA_MODE = "min"

# Matches ``approx()`` in ``models.py`` (need at least 6 points).
MIN_POINTS = 6

# Live grid while fitting (two columns per row).
MAVKA_LIVE_PAGE_SIZE = 6

# Review and export cards per page (two columns per row).
MAVKA_REVIEW_PAGE_SIZE = 6

METHOD_OPTIONS = (
    {"label": "AP", "value": "AP"},
    {"label": "WSAP", "value": "WSAP"},
    {"label": "WSL", "value": "WSL"},
    {"label": "A", "value": "A"},
)

MAXIMA_NOT_AVAILABLE = (
    "MAVKA maxima search is not available in this version. Select Search minima."
)

# Piecewise model colours (same as auxiliary/lc_approx_spike batch plots).
MAVKA_PIECE_COLOURS = {
    "left": "#6a3d9a",
    "core": "#33a02c",
    "right": "#ff7f00",
}
MAVKA_METHOD_A_COLOUR = "#9467bd"
