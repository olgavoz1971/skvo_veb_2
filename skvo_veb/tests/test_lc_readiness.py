"""Tests of the readiness report and its attachment to the ingested lightcurve."""

import json

import numpy as np
from astropy.table import Table
from volightcurve import VOLightCurve

from skvo_veb.utils.lc_bridge import volc_to_curvedash
from skvo_veb.utils.lc_config import METADATA_KEY_READINESS
from skvo_veb.utils.lc_readiness import readiness_report


def _volc(origin=2450000.0):
    """Builds a small magnitude product with no calibration.

    Args:
        origin (float or None): Declared time origin.

    Returns:
        VOLightCurve: Product with ``obs_time`` and ``mag``.
    """
    table = Table()
    table["obs_time"] = np.array([1.0, 2.0, 3.0])
    table["mag"] = np.array([12.0, 12.1, 12.2])
    volc = VOLightCurve.from_table(table)
    volc.timesys.timeorigin = origin
    return volc


def test_report_lists_gaps_and_suggestions_without_applying_them():
    """Undeclared time scale, position and calibration are reported with suggestions."""
    volc = _volc()
    report = readiness_report(volc, "mag")
    assert any("time scale" in text for text in report["time_problems"])
    assert report["conversion_problems"]
    assert report["suggestions"]["calibration"]["mag"]["zp_flux"] == 1.0
    assert "zp_flux" in report["suggestions"]["reasons"]
    assert volc.timesys.timescale is None
    assert volc.photdms.get("mag") is None or volc.photdms["mag"].photcal is None


def test_report_is_json_safe_and_attached_to_the_curvedash():
    """The report survives JSON and is stored under the readiness metadata key."""
    volc = _volc()
    lcd = volc_to_curvedash(volc, "x.dat")
    stored = lcd.metadata[METADATA_KEY_READINESS]
    assert json.loads(json.dumps(stored)) == stored
    assert stored["conversion_problems"]


def test_message_is_one_short_sentence_and_applies_nothing():
    """The user sees a single short sentence; the details stay in the report."""
    from skvo_veb.utils.lc_readiness import readiness_message

    volc = _volc()
    text = readiness_message(readiness_report(volc, "mag"))
    assert text == "Some metadata is missing. Open Calibration to review it and apply suggested values."
    assert "\n" not in text and len(text) < 100
    assert volc.timesys.timescale is None


def test_message_is_none_when_nothing_is_missing():
    """A complete report gives no message."""
    from skvo_veb.utils.lc_readiness import readiness_message

    assert readiness_message(None) is None
    assert readiness_message(
        {"time_problems": [], "unit_findings": {}, "conversion_problems": [], "suggestions": {}}
    ) is None


def test_packed_transport_carries_the_report():
    """The GP transport JSON carries the readiness report in its meta."""
    from skvo_veb.utils.lc_bridge import pack_volc_to_json

    volc = _volc()
    packet = json.loads(pack_volc_to_json(volc))
    assert packet["meta"][METADATA_KEY_READINESS]["conversion_problems"]
