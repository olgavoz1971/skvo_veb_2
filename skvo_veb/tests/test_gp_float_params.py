"""Tests for GP sidebar float-parameter parsing."""

import pytest

from skvo_veb.utils.gp.config import (
    build_gp_float_params,
    parse_gp_float_param,
)


def test_parse_gp_float_param_accepts_multi_decimal_noise_scale():
    assert parse_gp_float_param("noise_scale", 0.25) == 0.25
    assert parse_gp_float_param("noise_scale", "0.25") == 0.25
    assert parse_gp_float_param("noise_scale", "0.125") == 0.125


def test_parse_gp_float_param_rejects_empty():
    with pytest.raises(ValueError, match="Noise scale is empty"):
        parse_gp_float_param("noise_scale", None)
    with pytest.raises(ValueError, match="Noise scale is empty"):
        parse_gp_float_param("noise_scale", "")


def test_parse_gp_float_param_rejects_non_numeric():
    with pytest.raises(ValueError, match="Noise scale must be a number"):
        parse_gp_float_param("noise_scale", "not-a-number")


def test_build_gp_float_params_preserves_noise_scale():
    ids = [
        {"type": "float-input", "index": "noise_scale"},
        {"type": "float-input", "index": "length_scale_init"},
    ]
    values = [0.25, 0.1]
    params = build_gp_float_params(ids, values)
    assert params["noise_scale"] == 0.25
    assert params["length_scale_init"] == 0.1
