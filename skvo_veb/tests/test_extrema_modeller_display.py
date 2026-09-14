"""Extrema modeller page display time is configured in one place."""

import numpy as np
import pytest

from skvo_veb.components import extrema_modeller_appearance as appearance
from skvo_veb.components.extrema_modeller_appearance import (
    PAGE_DISPLAY_EPOCH_JD,
    format_page_fit_title,
    format_page_time_range,
    format_vertex_outside_window,
    from_page_time,
    page_epoch_addon_label,
    page_time_label,
    to_page_time,
)
from skvo_veb.utils.lc_config import JD_TO_MJD


def test_default_page_scale_is_mjd():
    """The page origin is the MJD offset unless a developer changes it."""
    assert PAGE_DISPLAY_EPOCH_JD == pytest.approx(JD_TO_MJD)
    assert page_time_label() == "MJD"
    assert page_epoch_addon_label() == "Epoch (MJD)"


def test_page_time_label_jd(monkeypatch):
    """Origin 0.0 is labelled JD, not JD-0."""
    monkeypatch.setattr(appearance, "PAGE_DISPLAY_EPOCH_JD", 0.0)
    assert appearance.page_time_label() == "JD"
    assert appearance.page_epoch_addon_label() == "Epoch (JD)"


def test_page_time_label_custom_origin(monkeypatch):
    """A non-MJD origin is labelled JD-<origin>; 2400000 is not MJD."""
    monkeypatch.setattr(appearance, "PAGE_DISPLAY_EPOCH_JD", 2450000.0)
    assert appearance.page_time_label() == "JD-2450000"
    monkeypatch.setattr(appearance, "PAGE_DISPLAY_EPOCH_JD", 2400000.0)
    assert appearance.page_time_label() == "JD-2400000"


def test_to_page_time_scalar_and_array():
    """Absolute JD converts with the page origin, not an ad-hoc subtract at the call site."""
    jd = 2460830.46
    assert to_page_time(jd) == pytest.approx(jd - PAGE_DISPLAY_EPOCH_JD)
    arr = to_page_time(np.array([jd, jd + 1.0]))
    np.testing.assert_allclose(
        arr, [jd - PAGE_DISPLAY_EPOCH_JD, jd + 1.0 - PAGE_DISPLAY_EPOCH_JD]
    )


def test_from_page_time_round_trip():
    """Display time maps back to absolute JD."""
    jd = 2458749.729
    assert from_page_time(to_page_time(jd)) == pytest.approx(jd)


def test_format_page_time_range_uses_page_label():
    """Failed-interval bounds are labelled in the page scale (MJD by default)."""
    text = format_page_time_range(2460830.46, 2460830.48)
    assert text is not None
    assert text.startswith("MJD:")
    assert "2460830" not in text
    lo = 2460830.46 - PAGE_DISPLAY_EPOCH_JD
    hi = 2460830.48 - PAGE_DISPLAY_EPOCH_JD
    assert f"{lo:.2f}" in text
    assert f"{hi:.2f}" in text


def test_format_page_fit_title_includes_scale():
    """Card titles name the scale, not a bare number."""
    jd = 2460830.46
    title = format_page_fit_title(jd, kind="Peak")
    assert "Peak (MJD):" in title
    assert f"{jd - PAGE_DISPLAY_EPOCH_JD:.2f}" in title
    assert "2460830" not in title


def test_format_vertex_outside_window_uses_page_scale():
    """Parabola out-of-window copy is page time, not absolute JD."""
    text = format_vertex_outside_window(2460830.50, 2460830.46, 2460830.48)
    assert "(MJD)" in text
    assert "2460830" not in text
    lo = 2460830.46 - PAGE_DISPLAY_EPOCH_JD
    hi = 2460830.48 - PAGE_DISPLAY_EPOCH_JD
    vertex = 2460830.50 - PAGE_DISPLAY_EPOCH_JD
    assert f"{vertex:.6f}" in text
    assert f"{lo:.6f}" in text
    assert f"{hi:.6f}" in text
