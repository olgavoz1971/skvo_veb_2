"""Shared matplotlib styling for template-timing figures."""

from __future__ import annotations

import matplotlib.pyplot as plt

FONT_SIZE = 20
FIGSIZE_TEMPLATE = (20, 12)
FIGSIZE_INTERVAL = (36, 12)
FIGSIZE_OVERVIEW = (24, 8)


def apply_plot_style() -> None:
    """Global rcParams for Step 1 template and overview plots (matches ``build_template``)."""
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
    """Global rcParams for Step 2 multi-panel interval fits (matches ``fit_template_sniff``)."""
    plt.rcParams.update(
        {
            "font.size": FONT_SIZE,
            "axes.labelsize": FONT_SIZE,
            "axes.titlesize": FONT_SIZE,
            "xtick.labelsize": FONT_SIZE * 0.85,
            "ytick.labelsize": FONT_SIZE * 0.85,
            "legend.fontsize": FONT_SIZE * 0.65,
        }
    )
