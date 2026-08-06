"""Tests for removing GP intervals with no lightcurve points."""

from unittest.mock import patch

import pandas as pd

from skvo_veb.utils.gp.flux import empty_interval_indices
from skvo_veb.utils.gp.prep_interval_bands import intervals_without_marked_indices


def test_empty_interval_indices():
    intervals = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    with patch("skvo_veb.utils.gp.flux.get_gp_flux_fragment") as gf:
        gf.side_effect = [
            pd.DataFrame(),
            pd.DataFrame({"jd": [3.5], "flux": [1.0]}),
            pd.DataFrame(),
        ]
        assert empty_interval_indices(intervals, "{}") == [0, 2]


def test_remove_empty_intervals_batch_filter():
    intervals = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    drop = [0, 2]
    assert intervals_without_marked_indices(intervals, drop) == [[3.0, 4.0]]
