"""Tests that the bridge never guesses the time origin of relative time columns."""

import numpy as np
import pytest
from astropy.table import Table
from volightcurve import VOLightCurve

from skvo_veb.utils.lc_bridge import _absolute_jd_from_time_column


def _volc(values, origin):
    """Builds a one-column product with an optional declared time origin.

    Args:
        values (list[float]): Time column values.
        origin (float or None): Declared time origin, or ``None`` when undeclared.

    Returns:
        VOLightCurve: Product with ``obs_time`` and ``mag`` columns.
    """
    table = Table()
    table["obs_time"] = np.asarray(values, dtype=float)
    table["mag"] = np.full(len(values), 12.0)
    volc = VOLightCurve.from_table(table)
    volc.timesys.timeorigin = origin
    return volc


def test_declared_origin_is_added_to_relative_values():
    """A declared origin makes relative values absolute."""
    jd = _absolute_jd_from_time_column(_volc([1.0, 2.0], 2450000.0), "obs_time")
    assert jd.tolist() == [2450001.0, 2450002.0]


def test_absolute_values_pass_without_origin():
    """Values that are already absolute need no origin."""
    jd = _absolute_jd_from_time_column(_volc([2450001.0, 2450002.0], None), "obs_time")
    assert jd.tolist() == [2450001.0, 2450002.0]


def test_relative_values_without_origin_raise():
    """Relative values with no declared origin fail, with no zero or MJD guess."""
    with pytest.raises(ValueError, match="not declared"):
        _absolute_jd_from_time_column(_volc([58000.0, 58001.0], None), "obs_time")
