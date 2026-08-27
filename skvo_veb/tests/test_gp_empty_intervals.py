"""Tests for removing GP intervals with no lightcurve points."""

from unittest.mock import patch

import numpy as np

from skvo_veb.utils.gp.flux import empty_interval_indices
from skvo_veb.utils.gp.prep_interval_bands import intervals_without_marked_indices


def _arrays(jd):
    """Minimal decoded-array payload for one photometry column."""
    jd = np.asarray(jd, dtype=float)
    return {
        "jd": jd,
        "flux": np.ones_like(jd),
        "flux_err": np.full_like(jd, np.nan),
    }


def test_empty_interval_indices():
    intervals = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    with patch(
        "skvo_veb.utils.gp.flux.decode_gp_flux_arrays",
        return_value=_arrays([3.5]),
    ):
        assert empty_interval_indices(intervals, "{}") == [0, 2]


def test_empty_interval_indices_includes_closed_bounds():
    """Points exactly on an interval edge count as inside."""
    intervals = [[1.0, 2.0], [3.0, 4.0]]
    with patch(
        "skvo_veb.utils.gp.flux.decode_gp_flux_arrays",
        return_value=_arrays([2.0]),
    ):
        assert empty_interval_indices(intervals, "{}") == [1]


def test_empty_interval_indices_decodes_lightcurve_once():
    """The transport packet is decoded once for the whole interval list."""
    intervals = [[float(i), float(i) + 0.5] for i in range(50)]
    with patch(
        "skvo_veb.utils.gp.flux.decode_gp_flux_arrays",
        return_value=_arrays([0.25]),
    ) as decode:
        empty_interval_indices(intervals, "{}")
    assert decode.call_count == 1


def test_remove_empty_intervals_batch_filter():
    intervals = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    drop = [0, 2]
    assert intervals_without_marked_indices(intervals, drop) == [[3.0, 4.0]]
