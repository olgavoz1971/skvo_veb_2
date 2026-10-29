"""Regression test: TESS fits of the four Table 1 stars against Mikulasek (2015).

Runs the forward check (variants A to D) for every star. Takes about 15 s.
Recorded 2026-10-29. Pairs listed in ``AGREEING`` agree with the paper within
``MAX_DEVIATION_SIGMA``; known disagreements (V477 Lyr Gamma, EK Com C2) are not
asserted to agree, only to stay finite.
"""

from __future__ import annotations

import numpy as np
import pytest

from paper_forward_check import TEMPLATE_BUILDERS, run_forward_check

MAX_DEVIATION_SIGMA = 3.0
RMS_REL_TOL = 0.05
# Fit D rms (mmag) recorded on 2026-10-29.
RECORDED_RMS_D = {"EK_Com": 6.20, "V477_Lyr": 34.12, "AV_Del": 7.17, "AR_Aur": 1.69}
AGREEING = {
    "EK_Com": ["D1", "G1", "C1"],
    "V477_Lyr": ["D1", "C1"],
    "AV_Del": ["D1", "G1", "C1"],
    "AR_Aur": ["D1", "G1", "C1"],
}
# AR Aur period: the fitted value must be near the VOTable value, not the paper table value.
AR_AUR_PERIOD = 4.134649
AR_AUR_PERIOD_TOL = 5e-5


@pytest.fixture(scope="module")
def results():
    """Run the forward check for all stars once."""
    return {key: run_forward_check(key) for key in TEMPLATE_BUILDERS}


@pytest.mark.parametrize("star", sorted(AGREEING))
def test_shape_agrees_with_paper(results, star):
    """D, Gamma and C of the stars that agree with Table 1 stay within 3 sigma."""
    for key in AGREEING[star]:
        dev = results[star]["shape"][key]["deviation_sigma"]
        assert dev < MAX_DEVIATION_SIGMA, f"{star} {key}: {dev:.1f} sigma"


@pytest.mark.parametrize("star", sorted(RECORDED_RMS_D))
def test_fit_rms_unchanged(results, star):
    """The fit D rms stays at its recorded value."""
    assert results[star]["rms_mmag"]["D"] == pytest.approx(RECORDED_RMS_D[star], rel=RMS_REL_TOL)


def test_ar_aur_period_follows_data(results):
    """AR Aur: the fitted period is the data period, not the Table 1 value."""
    period, _ = results["AR_Aur"]["fitted_period"]
    assert abs(period - AR_AUR_PERIOD) < AR_AUR_PERIOD_TOL
    assert abs(period - results["AR_Aur"]["paper_period"]) > 1e-3


def test_known_disagreements_are_finite(results):
    """The documented disagreements stay finite numbers."""
    assert np.isfinite(results["V477_Lyr"]["shape"]["G1"]["deviation_sigma"])
    assert np.isfinite(results["EK_Com"]["shape"]["C2"]["deviation_sigma"])
