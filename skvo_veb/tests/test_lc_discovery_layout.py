"""Tests for the Discovery results panel width arithmetic."""

import pytest

from skvo_veb.utils.lc_discovery_layout import GRID_FRAME_ALLOWANCE_PX, catalog_grid_width_px


def test_width_sums_visible_columns_plus_frame():
    state = [{'colId': 'a', 'width': 100}, {'colId': 'b', 'width': 50.4}, {'colId': 'c', 'width': 80, 'hide': True}]
    assert catalog_grid_width_px(state) == 150 + GRID_FRAME_ALLOWANCE_PX


def test_empty_state_gives_none():
    assert catalog_grid_width_px(None) is None
    assert catalog_grid_width_px([]) is None


def test_visible_column_without_width_fails_fast():
    with pytest.raises(ValueError, match='colId|x'):
        catalog_grid_width_px([{'colId': 'x'}])
