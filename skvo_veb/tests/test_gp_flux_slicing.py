"""Tests for the GP decode-once / slice-per-interval flux path."""

from __future__ import annotations

import json

import numpy as np
import pytest

from skvo_veb.tests.test_gp_lc_export import _minimal_flux_packet
from skvo_veb.tests.test_gp_manual_detrend import _minimal_mag_packet
from skvo_veb.utils.gp.flux import (
    decode_gp_flux_arrays,
    get_gp_flux_fragment,
    slice_gp_flux_arrays,
)
from skvo_veb.utils.gp.plot_data import transport_revision_token


@pytest.fixture
def flux_packet():
    """Flux-native transport with five points one day apart."""
    jds = [2459000.0, 2459001.0, 2459002.0, 2459003.0, 2459004.0]
    fluxes = [1.0, 1.2, 1.4, 1.2, 1.0]
    return _minimal_flux_packet(fluxes, jds)


def test_decode_returns_equal_length_arrays(flux_packet):
    arrays = decode_gp_flux_arrays(flux_packet)
    assert set(arrays) == {"jd", "flux", "flux_err"}
    assert arrays["jd"].shape == arrays["flux"].shape == arrays["flux_err"].shape
    assert arrays["jd"].shape == (5,)


def test_slice_uses_closed_bounds(flux_packet):
    arrays = decode_gp_flux_arrays(flux_packet)
    frag = slice_gp_flux_arrays(arrays, 2459001.0, 2459003.0)
    np.testing.assert_allclose(
        frag["jd"].to_numpy(), [2459001.0, 2459002.0, 2459003.0]
    )


def test_slice_outside_span_is_empty(flux_packet):
    arrays = decode_gp_flux_arrays(flux_packet)
    assert len(slice_gp_flux_arrays(arrays, 2459010.0, 2459011.0)) == 0


def test_slice_preserves_row_order(flux_packet):
    """Slicing must not reorder rows; the GP fit consumes them as given."""
    arrays = decode_gp_flux_arrays(flux_packet)
    frag = slice_gp_flux_arrays(arrays, 2459000.0, 2459004.0)
    np.testing.assert_allclose(frag["jd"].to_numpy(), arrays["jd"])
    np.testing.assert_allclose(frag["flux"].to_numpy(), arrays["flux"])


def test_wrapper_matches_decode_then_slice(flux_packet):
    """``get_gp_flux_fragment`` stays equivalent to the two-step path."""
    arrays = decode_gp_flux_arrays(flux_packet)
    stepwise = slice_gp_flux_arrays(arrays, 2459001.0, 2459003.0)
    oneshot = get_gp_flux_fragment(flux_packet, 2459001.0, 2459003.0)
    np.testing.assert_allclose(
        oneshot["jd"].to_numpy(), stepwise["jd"].to_numpy()
    )
    np.testing.assert_allclose(
        oneshot["flux"].to_numpy(), stepwise["flux"].to_numpy()
    )


def test_decoding_once_matches_per_interval_decoding(flux_packet):
    """Decoding once then slicing gives the same fragments as decoding per call."""
    intervals = [
        (2459000.0, 2459001.0),
        (2459001.0, 2459002.5),
        (2459002.0, 2459004.0),
    ]
    arrays = decode_gp_flux_arrays(flux_packet)
    for jd_min, jd_max in intervals:
        batched = slice_gp_flux_arrays(arrays, jd_min, jd_max)
        per_call = get_gp_flux_fragment(flux_packet, jd_min, jd_max)
        np.testing.assert_allclose(
            batched["jd"].to_numpy(), per_call["jd"].to_numpy()
        )


def test_flux_native_with_photcal_pair_matches_bridge_fragment():
    """Flux-native transport agrees with the bridge slicer, pair present or not.

    ``get_gp_flux_fragment`` used to branch to ``lc_bridge.get_flux_fragment``
    when both zero points were present. Both branches unpack in the flux domain
    and apply the same closed-bound mask, so the branch was redundant; this test
    keeps that equivalence honest.
    """
    from skvo_veb.utils.lc_bridge import get_flux_fragment

    jds = [2459000.0, 2459001.0, 2459002.0, 2459003.0]
    packet = json.loads(_minimal_flux_packet([1.0, 1.5, 1.5, 1.0], jds))
    packet["meta"]["photcal"] = {
        "zp_mag": 20.0,
        "zp_flux": 1.0,
        "zp_mag_unit": "mag",
        "zp_flux_unit": "",
    }
    with_pair = json.dumps(packet)

    ours = get_gp_flux_fragment(with_pair, 2459001.0, 2459002.0)
    bridge = get_flux_fragment(with_pair, 2459001.0, 2459002.0)
    np.testing.assert_allclose(ours["jd"].to_numpy(), bridge["jd"].to_numpy())
    np.testing.assert_allclose(ours["flux"].to_numpy(), bridge["flux"].to_numpy())
    np.testing.assert_allclose(
        ours["flux_err"].to_numpy(), bridge["flux_err"].to_numpy()
    )


def test_mag_native_packet_converts_to_flux():
    """Magnitude uploads decode to flux; brighter (smaller mag) means more flux."""
    jds = [2459000.0, 2459001.0, 2459002.0]
    packet = _minimal_mag_packet([15.0, 14.0, 15.0], jds)
    arrays = decode_gp_flux_arrays(packet)
    flux = arrays["flux"]
    assert flux[1] > flux[0]
    assert flux[1] > flux[2]
    assert np.all(np.isfinite(arrays["flux_err"]))


def test_revision_token_is_short_and_content_sensitive(flux_packet):
    other = _minimal_flux_packet([1.0, 1.0], [2459000.0, 2459001.0])
    token = transport_revision_token(flux_packet)
    assert len(token) == 16
    assert token == transport_revision_token(flux_packet)
    assert token != transport_revision_token(other)


def test_revision_token_empty_for_missing_lightcurve():
    assert transport_revision_token("") == ""
    assert transport_revision_token(None) == ""
