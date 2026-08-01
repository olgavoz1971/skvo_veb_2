"""Tests for paginated GP review grid."""

from skvo_veb.utils.gp.config import GP_REVIEW_PAGE_SIZE
from skvo_veb.utils.gp.review_page import (
    build_review_store_payload,
    render_review_page,
    review_page_label,
)


def test_render_review_page_respects_page_size():
    entries = [
        {"is_fail": False, "figure_json": {"data": [], "layout": {}}, "badge_specs": []}
        for _ in range(25)
    ]
    include = [True] * 25
    page0 = render_review_page(entries, 0, include)
    page1 = render_review_page(entries, 1, include)
    assert len(page0) == GP_REVIEW_PAGE_SIZE
    assert len(page1) == min(GP_REVIEW_PAGE_SIZE, 25 - GP_REVIEW_PAGE_SIZE)
    page2 = render_review_page(entries, 2, include)
    assert len(page2) == min(GP_REVIEW_PAGE_SIZE, max(0, 25 - 2 * GP_REVIEW_PAGE_SIZE))


def test_build_review_store_payload_include_defaults():
    entries = [
        {"is_fail": False, "jd_peak": 1.0, "jd_peak_std": 0.1},
        {"is_fail": True},
    ]
    payload = build_review_store_payload("run1", entries)
    assert payload["include"] == [True, False]
    assert payload["rows"][0]["jd_peak"] == 1.0


def test_review_page_label():
    text = review_page_label(0, 25)
    assert "Page 1" in text
    assert f"1–{min(GP_REVIEW_PAGE_SIZE, 25)}" in text
