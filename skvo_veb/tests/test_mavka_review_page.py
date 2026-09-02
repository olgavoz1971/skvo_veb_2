"""Tests for paginated MAVKA review grid."""

from skvo_veb.utils.mavka.config import MAVKA_REVIEW_PAGE_SIZE
from skvo_veb.utils.mavka.review_page import (
    build_review_store_payload,
    render_review_page,
    review_page_label,
)


def test_render_review_page_respects_page_size():
    """Review grid shows at most MAVKA_REVIEW_PAGE_SIZE cards."""
    entries = [
        {"is_fail": False, "figure_json": {"data": [], "layout": {}}, "badge_specs": []}
        for _ in range(25)
    ]
    include = [True] * 25
    page0 = render_review_page(entries, 0, include)
    page1 = render_review_page(entries, 1, include)
    assert len(page0) == MAVKA_REVIEW_PAGE_SIZE
    assert len(page1) == min(MAVKA_REVIEW_PAGE_SIZE, 25 - MAVKA_REVIEW_PAGE_SIZE)


def test_build_review_store_payload_include_defaults():
    """Failed rows are excluded from compact export by default."""
    entries = [
        {"is_fail": False, "jd_peak": 1.0, "jd_peak_std": 0.1},
        {"is_fail": True},
    ]
    payload = build_review_store_payload(
        "run1", entries, source_filename="NSV807.vot", method="WSL"
    )
    assert payload["include"] == [True, False]
    assert payload["rows"][0]["jd_peak"] == 1.0
    assert payload["source_filename"] == "NSV807.vot"
    assert payload["method"] == "WSL"


def test_review_page_label():
    """Caption reports 1-based page numbers and the visible fit range."""
    text = review_page_label(0, 25)
    assert "Page 1" in text
    assert f"1–{min(MAVKA_REVIEW_PAGE_SIZE, 25)}" in text
