"""Tests of the GP calibration form helpers."""

import json

import numpy as np
from astropy.table import Table
from volightcurve import VOLightCurve

from skvo_veb.utils.gp.photcal_form import (
    apply_photcal_form_to_packet,
    photcal_form_values_for_packet,
)
from skvo_veb.utils.lc_bridge import pack_volc_to_json


def _packet() -> str:
    """Builds a transport packet of a magnitude lightcurve with no calibration.

    Returns:
        str: Transport JSON.
    """
    table = Table()
    table["obs_time"] = np.array([2459000.0, 2459001.0])
    table["mag"] = np.array([12.0, 12.1])
    volc = VOLightCurve.from_table(table)
    volc.timesys.timeorigin = 0.0
    return pack_volc_to_json(volc)


def test_form_is_prefilled_with_suggestions_and_the_packet_is_unchanged():
    """Gaps appear as suggested values in the form; the stored packet stays as it was."""
    packet = _packet()
    values = photcal_form_values_for_packet(packet)
    assert (values["zp_flux"], values["zp_mag"], values["mag_sys"]) == (1.0, 0.0, "Vega")
    assert json.loads(packet)["meta"]["photcal"].get("zp_flux") is None


def test_apply_writes_the_calibration_and_drops_the_stale_report():
    """Apply stores the form values; the photometry arrays and the rest stay."""
    packet = _packet()
    values = photcal_form_values_for_packet(packet)
    updated, warnings = apply_photcal_form_to_packet(packet, **values)
    meta = json.loads(updated)["meta"]
    assert meta["photcal"]["zp_flux"] == 1.0
    assert meta["photcal"]["zp_mag"] == 0.0
    assert meta["photcal"]["mag_sys"] == "Vega"
    assert "readiness" not in meta
    before, after = json.loads(packet), json.loads(updated)
    assert {k: v for k, v in after.items() if k != "meta"} == {
        k: v for k, v in before.items() if k != "meta"
    }
    assert warnings == []


def test_applied_packet_can_convert_for_gp():
    """After Apply the GP conversion check passes."""
    from skvo_veb.utils.gp.flux import resolve_gp_photcal

    packet = _packet()
    updated, _ = apply_photcal_form_to_packet(packet, **photcal_form_values_for_packet(packet))
    resolve_gp_photcal(json.loads(updated)["meta"])
