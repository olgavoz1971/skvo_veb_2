"""Tests for live GP Processing View pagination."""

from skvo_veb.components.extrema_modeller_appearance import PAGE_SIZE
from skvo_veb.utils.gp.live_page import (
    build_live_page_slot_children,
    live_progress_label,
    live_visible_page_for_done_count,
)


def test_live_page_advances_after_full_page():
    assert live_visible_page_for_done_count(PAGE_SIZE) == 0
    assert live_visible_page_for_done_count(PAGE_SIZE + 1) == 1
    assert live_visible_page_for_done_count(2 * PAGE_SIZE) == 1
    assert live_visible_page_for_done_count(2 * PAGE_SIZE + 1) == 2


def test_live_grid_first_fit_on_new_page():
    entries = [
        {"is_fail": False, "figure_json": {"data": [], "layout": {}}, "badge_specs": []}
        for _ in range(PAGE_SIZE + 1)
    ]
    slots = build_live_page_slot_children(entries, visible_page=1)
    assert len(slots) == PAGE_SIZE


def test_live_progress_label():
    assert live_progress_label(7, 150) == "7 extrema from 150 ready"
