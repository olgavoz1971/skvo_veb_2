"""Matplotlib styling for running-parabola spike plots only.

Tweak sizes and fonts here; this file is not shared with ``template_timing``
or ``lc_approx_spike``. Initial values match those spikes for consistency.
"""

from __future__ import annotations

import matplotlib.pyplot as plt

FONT_SIZE = 20
FIGSIZE_OVERVIEW = (20, 8)
FIGSIZE_INTERVAL = (10, 8)


def apply_plot_style() -> None:
    """Global rcParams for overview figures."""
    plt.rcParams.update(
        {
            "font.size": FONT_SIZE,
            "axes.labelsize": FONT_SIZE,
            "axes.titlesize": FONT_SIZE,
            "xtick.labelsize": FONT_SIZE,
            "ytick.labelsize": FONT_SIZE,
            "legend.fontsize": FONT_SIZE,
        }
    )


def apply_interval_plot_style() -> None:
    """Global rcParams for per-window demo panels."""
    plt.rcParams.update(
        {
            "font.size": FONT_SIZE,
            "axes.labelsize": FONT_SIZE,
            "axes.titlesize": FONT_SIZE,
            "figure.titlesize": FONT_SIZE,
            "xtick.labelsize": FONT_SIZE * 0.85,
            "ytick.labelsize": FONT_SIZE * 0.85,
            "legend.fontsize": FONT_SIZE * 0.65,
        }
    )
