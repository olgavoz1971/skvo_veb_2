"""Tests for paginated GP review grid."""

from dash import dcc
import dash_bootstrap_components as dbc
import pytest

from skvo_veb.components.extrema_modeller_appearance import CARD_COL_WIDTH, PAGE_SIZE
from skvo_veb.utils.gp.review_page import (
    build_review_store_payload,
    create_review_interval_card,
    render_review_page,
    review_page_label,
    serialise_review_entry,
    success_badge_specs,
)


def _layout_has_type(comp, cls) -> bool:
    """True when a Dash layout tree contains an instance of ``cls``."""
    if isinstance(comp, cls):
        return True
    children = getattr(comp, "children", None)
    if children is None:
        return False
    if not isinstance(children, (list, tuple)):
        children = [children]
    return any(_layout_has_type(child, cls) for child in children)


def test_render_review_page_respects_page_size():
    entries = [
        {"is_fail": False, "figure_json": {"data": [], "layout": {}}, "badge_specs": []}
        for _ in range(25)
    ]
    include = [True] * 25
    page0 = render_review_page(entries, 0, include)
    page1 = render_review_page(entries, 1, include)
    assert len(page0) == PAGE_SIZE
    assert len(page1) == min(PAGE_SIZE, 25 - PAGE_SIZE)
    page2 = render_review_page(entries, 2, include)
    assert len(page2) == min(PAGE_SIZE, max(0, 25 - 2 * PAGE_SIZE))


def test_build_review_store_payload_include_defaults():
    entries = [
        {"is_fail": False, "jd_peak": 1.0, "jd_peak_std": 0.1, "scale_limit_flag": 2},
        {"is_fail": True},
    ]
    payload = build_review_store_payload(
        "run1", entries, source_filename="NSV807.vot"
    )
    assert payload["include"] == [True, False]
    assert payload["rows"][0]["jd_peak"] == 1.0
    assert payload["rows"][0]["scale_limit_flag"] == 2
    assert payload["source_filename"] == "NSV807.vot"
    assert payload["max_half_width_d"] is None


def test_build_review_store_payload_records_half_width():
    """The review store keeps the half-width cap used for the run."""
    entries = [
        {"is_fail": False, "jd_peak": 1.0, "jd_peak_std": 0.1, "scale_limit_flag": 0},
    ]
    payload = build_review_store_payload(
        "run1", entries, max_half_width_d=0.04
    )
    assert payload["max_half_width_d"] == pytest.approx(0.04)


def test_success_badge_specs_window_capped():
    """Capped windows add a warning badge after the usual GP badges."""
    specs = success_badge_specs(
        "matern", 0.12, "success", 1.5, "info", 0.001, window_capped=True
    )
    assert specs[-1]["label"] == "window capped"
    assert specs[-1]["color"] == "warning"


def test_review_page_label():
    text = review_page_label(0, 25)
    assert "Page 1" in text
    assert f"1–{min(PAGE_SIZE, 25)}" in text


def test_serialise_failed_entry_keeps_observations_figure():
    """Failed GP rows still cache the interval scatter for the card."""
    row = serialise_review_entry(
        {
            "is_fail": True,
            "jd_min": 2450000.0,
            "jd_max": 2450001.0,
            "error": "pipeline exploded",
            "badge_specs": [{"label": "FAILED", "color": "danger"}],
        },
        figure_json={"data": [{"x": [1], "y": [2]}], "layout": {}},
    )
    assert row["is_fail"] is True
    assert row["error"] == "pipeline exploded"
    assert row["figure_json"]["data"][0]["x"] == [1]


def test_failed_review_card_shows_reason_and_graph():
    """A failed card keeps the plot size; the reason lives on the FAILED badge."""
    entry = {
        "is_fail": True,
        "jd_min": 2450000.0,
        "jd_max": 2450001.0,
        "error": "pipeline exploded",
        "badge_specs": [{"label": "FAILED", "color": "danger"}],
        "figure_json": {"data": [{"x": [1.0], "y": [2.0]}], "layout": {}},
    }
    card = create_review_interval_card(entry, 0, include_in_export=False)
    assert card.width == CARD_COL_WIDTH
    assert _layout_has_type(card, dcc.Graph)
    assert _layout_has_type(card, dbc.Popover)
    assert not _layout_has_type(card, dbc.Alert)
