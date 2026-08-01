"""Tests for live GP Processing View pagination."""

from skvo_veb.utils.gp.config import GP_LIVE_PAGE_SIZE
from skvo_veb.utils.gp.live_page import (
    build_live_page_slot_children,
    live_progress_label,
    live_visible_page_for_done_count,
)


def test_live_page_advances_after_full_page():
    assert live_visible_page_for_done_count(6) == 0
    assert live_visible_page_for_done_count(7) == 1
    assert live_visible_page_for_done_count(12) == 1
    assert live_visible_page_for_done_count(13) == 2


def test_live_grid_seventh_fit_first_slot_on_new_page():
    entries = [
        {"is_fail": False, "figure_json": {"data": [], "layout": {}}, "badge_specs": []}
        for _ in range(7)
    ]
    slots = build_live_page_slot_children(entries, visible_page=1)
    assert len(slots) == GP_LIVE_PAGE_SIZE
    # First slot on page 2 is extremum 7 (content built; not asserting DOM text)


def test_live_progress_label():
    assert live_progress_label(7, 150) == "7 extrema from 150 ready"
