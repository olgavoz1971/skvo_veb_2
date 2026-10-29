"""Regression tests on the real TESS light curves (numbers recorded 2026-10-29).

These run the full staged pipeline and take a few seconds each. Reference values
live in ``references/stars_manifest.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from minima_timing import HALF_ORBIT_WINDOW, time_both_walls
from mikulasek_fit_pipeline import run_staged_fit
from votable_loader import load_tess_votable
from workflow_helpers import absolute_jd_to_mjd

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / "references" / "stars_manifest.json").read_text())
ADOPTED_RMS_REL_TOL = 0.01


@pytest.fixture(scope="module")
def ek_com_run():
    """Fit EK Com with the settings of ``fit_ek_com_s49.py`` and return the pieces."""
    import fit_ek_com_s49 as star

    payload = load_tess_votable(star.VOTABLE_PATH)
    pipeline = run_staged_fit(
        absolute_jd_to_mjd(payload["t"]), payload["mag"], payload["sig"],
        payload["period"], payload["epoch_jd"], star.FIT_CONFIG,
    )
    return payload, pipeline


@pytest.mark.parametrize("which,key", [("primary", "timing_primary_n"),
                                        ("secondary", "timing_secondary_n")])
def test_ek_com_timing_counts(ek_com_run, which, key):
    """Both-sides timing counts for EK Com match the recorded reference."""
    payload, pl = ek_com_run
    vm = time_both_walls(
        pl.t_mjd, pl.mag, pl.sig, pl.model, pl.adopted, HALF_ORBIT_WINDOW,
        which, payload["epoch_jd"], payload["period"],
        require_contact_walls=False, clip_outliers=False,
    )
    expected = MANIFEST["stars"]["EK_Com"]["regression_reference"][key]
    assert len(vm["T"]) == expected


def test_ek_com_adopted_rms(ek_com_run):
    """The adopted EK Com fit keeps its recorded rms."""
    _, pl = ek_com_run
    expected = MANIFEST["stars"]["EK_Com"]["regression_reference"]["adopted_rms_mag"]
    assert pl.adopted.rms == pytest.approx(expected, rel=ADOPTED_RMS_REL_TOL)
