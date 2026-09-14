"""FAILED badge uses a hover-and-click popover, not an in-card banner."""

import dash_bootstrap_components as dbc

from skvo_veb.components.fail_fit_badge import failed_fit_badge


def test_failed_fit_badge_uses_legacy_popover():
    """Hover peeks and click pins, matching page ``?`` help."""
    children = failed_fit_badge(
        title="Parabola fit failed",
        reason="Curvature sign incompatible with minimum in 'mag'",
        jd_min=2460830.46,
        jd_max=2460830.48,
        target_id={"type": "parabola-fail-badge", "index": 3, "view": "review"},
    )
    assert len(children) == 2
    badge, popover = children
    assert isinstance(badge, dbc.Badge)
    assert "FAILED" in str(badge.children)
    assert "gp-fail-badge-hint" in str(badge.children)
    assert isinstance(popover, dbc.Popover)
    assert popover.trigger == "legacy"
    assert popover.placement == "top"
    body = str(popover.children)
    assert "MJD:" in body
    assert "2460830" not in body
