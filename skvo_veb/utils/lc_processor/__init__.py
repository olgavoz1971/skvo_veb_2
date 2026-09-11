"""Lightcurve processor backend: view copies and later Smooth / Detrend modules."""

from skvo_veb.utils.lc_processor.figures import (
    empty_figure,
    figure_raw_with_trend,
    graph_config,
)
from skvo_veb.utils.lc_processor.view import (
    crop_curvedash_copy,
    display_mjd_to_absolute_jd,
    plot_uirevision,
    selected_perm_indices,
)

__all__ = [
    "crop_curvedash_copy",
    "display_mjd_to_absolute_jd",
    "empty_figure",
    "figure_raw_with_trend",
    "graph_config",
    "plot_uirevision",
    "selected_perm_indices",
]
