"""Tests for cooperative GP batch stop flag."""

from skvo_veb.utils.gp.run_control import (
    clear_gp_batch_stop,
    gp_batch_stop_requested,
    request_gp_batch_stop,
)


def test_gp_batch_stop_flag():
    clear_gp_batch_stop()
    assert gp_batch_stop_requested() is False
    request_gp_batch_stop()
    assert gp_batch_stop_requested() is True
    clear_gp_batch_stop()
    assert gp_batch_stop_requested() is False
