"""Tests for paginated MAVKA review grid."""

from dash import dcc
import dash_bootstrap_components as dbc
import numpy as np
import pytest

from skvo_veb.components.extrema_modeller_appearance import PAGE_SIZE
from skvo_veb.utils.mavka.models import ApproxFitResult
from skvo_veb.utils.mavka.review_page import (
    build_review_store_payload,
    create_review_interval_card,
    render_review_page,
    review_page_label,
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
    """Review grid shows at most PAGE_SIZE cards."""
    entries = [
        {"is_fail": False, "figure_json": {"data": [], "layout": {}}, "badge_specs": []}
        for _ in range(25)
    ]
    include = [True] * 25
    page0 = render_review_page(entries, 0, include)
    page1 = render_review_page(entries, 1, include)
    assert len(page0) == PAGE_SIZE
    assert len(page1) == min(PAGE_SIZE, 25 - PAGE_SIZE)


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
    assert payload["max_half_width_d"] is None


def test_build_review_store_payload_records_half_width():
    """The review store keeps the half-width cap used for the run."""
    entries = [{"is_fail": False, "jd_peak": 1.0, "jd_peak_std": 0.1}]
    payload = build_review_store_payload(
        "run1", entries, method="WSAP", max_half_width_d=0.04
    )
    assert payload["max_half_width_d"] == pytest.approx(0.04)


def test_success_badge_specs_window_capped():
    """Capped windows add a warning badge after the usual MAVKA badges."""
    fit = ApproxFitResult(
        method="WSAP",
        ok=True,
        t_ext=2451000.0,
        sigma_t_ext=1e-5,
        y_ext=12.0,
        sigma_y_ext=0.01,
        c4=2450999.4,
        c5=2451000.8,
        eclipse_duration=float("nan"),
        sigma_duration=float("nan"),
        params=np.array([1.0]),
        rms=0.012,
        n_points=20,
    )
    specs = success_badge_specs(fit, window_capped=True)
    assert specs[-1]["label"] == "window capped"
    assert specs[-1]["color"] == "warning"


def test_review_page_label():
    """Caption reports 1-based page numbers and the visible fit range."""
    text = review_page_label(0, 25)
    assert "Page 1" in text
    assert f"1–{min(PAGE_SIZE, 25)}" in text


def test_failed_review_card_shows_reason_and_graph():
    """A failed MAVKA card keeps the plot size; the reason lives on the FAILED badge."""
    entry = {
        "is_fail": True,
        "jd_min": 2450000.0,
        "jd_max": 2450001.0,
        "error": "Need at least 6 points, got 2",
        "badge_specs": [{"label": "FAILED", "color": "danger"}],
        "figure_json": {"data": [{"x": [1.0], "y": [12.0]}], "layout": {}},
    }
    card = create_review_interval_card(entry, 0, include_in_export=False)
    assert _layout_has_type(card, dcc.Graph)
    assert _layout_has_type(card, dbc.Popover)
    assert not _layout_has_type(card, dbc.Alert)
