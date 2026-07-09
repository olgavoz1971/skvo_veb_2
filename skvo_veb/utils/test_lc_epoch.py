"""Tests for folding-epoch normalisation helpers."""

from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD,
    display_epoch_offset,
    resolve_catalog_epoch,
)


def test_resolve_catalog_epoch_rejects_missing_sentinels():
    """Missing Sky Patrol epochs must not be stored as absolute JD 0."""
    assert resolve_catalog_epoch(None) is None
    assert resolve_catalog_epoch(0) is None
    assert resolve_catalog_epoch(0.0) is None
    assert resolve_catalog_epoch(float("nan")) is None


def test_resolve_catalog_epoch_keeps_valid_jd():
    """Catalogue epochs in full Julian Date are preserved."""
    assert resolve_catalog_epoch(2459000.25) == 2459000.25


def test_display_epoch_offset_for_missing_epoch():
    """Missing epoch displays as 0 relative to DEFAULT_EPOCH_JD."""
    assert display_epoch_offset(None) == 0.0
    assert display_epoch_offset(0) == 0.0


def test_display_epoch_offset_for_catalog_epoch():
    """Valid catalogue epoch is shown relative to the display reference."""
    assert display_epoch_offset(2459000.25) == 2459000.25 - DEFAULT_EPOCH_JD


def test_curvedash_defaults_missing_epoch_to_display_reference():
    """CurveDash uses DEFAULT_EPOCH_JD when no catalogue epoch is supplied."""
    lcd = CurveDash(
        jd=[2459000.0, 2459001.0],
        flux=[1.0, 2.0],
        flux_err=[0.1, 0.1],
        epoch=None,
    )
    assert lcd.epoch == DEFAULT_EPOCH_JD
    assert display_epoch_offset(lcd.epoch) == 0.0
