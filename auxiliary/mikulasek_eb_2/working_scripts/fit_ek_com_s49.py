"""Fit EK Com (TIC 450335412, TESS-SPOC sector 49) with a contact-binary Mikulasek model.

Period and folding epoch (T0) come from the VOTable TABLE PARAMs. The optimiser
uses MJD; plots and times of minima use absolute Julian Date (J0 = 0).
Figures and ``*.dat`` ToM files go to ``results/``.

Configuration is for *this* light curve, not copied from AA And:

- Science goal: phenomenological template on this sector (shape first).
- Geometry: two deep, wide minima; folded primary is rounded/flat at 10-min
  cadence. Profile 1 (Mikulasek Table 2 #1).
- Contact-like: P ~ 0.27 d, FWHM ~ 0.15 in phase, strong out-of-eclipse
  curvature. Harmonics (2, 3) as in XY Boo; H1 off until residuals demand it.
- O'Connell: S1 on. An early 7 mmag quadrature-median test looked weak; the
  folded curve still shows unequal maxima, so the sine term is enabled.
- Secondary sits near phase 0.5 from the *data* primary. A1/A2 ~ 1.17 so P/2
  is possible; we keep the VOTable period and warn.
- Shared eclipse shape first; unlock D2/G2 if chi-squared drops by >= 1%.
- One ~5.4 d downlink gap: split baselines there (GAP_SPLIT_DAYS = 1 d, longer
  than an orbit). Polynomial degree 0 on TESS-SPOC.
- Two-component primary on (extension, not Mikulasek 2015): the primary is
  flat; a single Gamma cannot make floor and walls. The usual rms/noise > 1.5
  gate is disabled here because OOE scatter is ellipsoidal, not white noise.
  10-min cadence may still leave rounded contacts. Adopt only if the pipeline
  shape checks pass.
- Extra eclipse weight (experiment 2): freeze M0, P0 and H2/H3, then refit
  eclipse shape with weight 3 in both minima (|phase| < 0.12 of 0 and 0.5).
  Judge on unweighted residuals; weighted chi-squared is not catalogue GOF.

Run::

    cd auxiliary/mikulasek_eb_2
    .venv/bin/python working_scripts/fit_ek_com_s49.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
from astropy.time import Time

_WORK = Path(__file__).resolve().parent
_ROOT = _WORK.parent
_ENGINE = _ROOT / "scripts"
for _p in (_WORK, _ENGINE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mikulasek_fit_pipeline import FitConfig, run_staged_fit  # noqa: E402
from minima_timing import (  # noqa: E402
    HALF_ORBIT_WINDOW,
    has_timings,
    time_both_walls,
    write_timing_ascii,
)
from votable_loader import load_tess_votable  # noqa: E402
from workflow_helpers import (  # noqa: E402
    absolute_jd_to_mjd,
    plot_global_fit,
    predicted_magnitude,
)

logger = logging.getLogger(__name__)

VOTABLE_PATH = _ROOT / "data" / "EK_Com_sector_49.vot"
FIGURE_OUTPUT_PATH = _ROOT / "results" / "fit_ek_com_s49.png"
RESULTS_DIR = _ROOT / "results"
TIMING_STEM = "ek_com_s49"

# Gaps longer than this are TESS downlink, not an orbit (P ~ 0.27 d).
GAP_SPLIT_DAYS = 1.0

FIT_CONFIG = FitConfig(
    profile=1,
    harmonics=(2, 3),
    ocon=True,
    baseline_order=0,
    gap_split_days=GAP_SPLIT_DAYS,
    allow_two_component=True,
    # Contact curve: OOE "noise" is ellipsoidal (~20 mmag), so rms/noise never
    # exceeds 1.5 even with a bad primary floor. Try two-component anyway.
    rms_noise_two_comp_threshold=0.0,
    # Experiment 2: minima count ninefold in chi-squared (sigma / 3).
    eclipse_weight=3.0,
    eclipse_phase_half=0.12,
)


def main() -> None:
    """Load the VOTable, fit the contact-binary template, and write the figure."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    payload = load_tess_votable(VOTABLE_PATH)
    t_mjd_full = absolute_jd_to_mjd(payload["t"])
    mag = payload["mag"]
    sig = payload["sig"]
    period = payload["period"]
    epoch_jd = payload["epoch_jd"]
    title = payload["title"]
    timescale = payload["timescale"]

    pipeline = run_staged_fit(t_mjd_full, mag, sig, period, epoch_jd, FIT_CONFIG)
    adopted = pipeline.adopted
    single = pipeline.single_component

    yhat, f_template, theta = predicted_magnitude(
        pipeline.t_mjd,
        pipeline.mag,
        pipeline.sig,
        pipeline.model,
        adopted.p,
        adopted.ephem,
        pipeline.seg,
        pipeline.order,
    )
    t_jd_plot = np.asarray(Time(pipeline.t_mjd, format="mjd").jd, dtype=float)

    logger.info(
        "Final adopted rms=%.5f mag (rms/noise=%.2f)",
        adopted.rms,
        adopted.rms / pipeline.noise_floor,
    )

    plot_title = f"{title}  P={period:.6f} d  T0={epoch_jd:.6f} JD"
    plot_global_fit(
        t_jd_plot,
        pipeline.mag,
        pipeline.sig,
        yhat,
        f_template,
        theta,
        pipeline.model,
        single.p,
        adopted.p,
        pipeline.seg,
        plot_title,
        timescale=timescale,
        save_path=str(FIGURE_OUTPUT_PATH),
    )
    logger.info("Figure saved to %s", FIGURE_OUTPUT_PATH)

    m0_jd = float(np.asarray(Time(adopted.ephem["M0"], format="mjd").jd))
    extra = [
        f"template_profile: {pipeline.model.profile}",
        f"harmonics: {pipeline.model.harmonics}",
        f"ocon: {pipeline.model.ocon}",
        f"eclipse_weight: {FIT_CONFIG.eclipse_weight}",
        f"fitted_P0_days: {adopted.ephem['P0']}",
        f"fitted_M0_jd: {m0_jd:.10f}",
        "fitted_M0_J0: 0",
        "fit_time_system: MJD (ToM converted back to JD)",
        "two_component_primary: rejected (shape checks)",
    ]
    ascii_kw = dict(
        lightcurve=VOTABLE_PATH,
        period=period,
        t0_jd=epoch_jd,
        timescale=timescale,
    )
    t_mjd = pipeline.t_mjd
    mag_w = pipeline.mag
    sig_w = pipeline.sig
    model = pipeline.model

    timing_kw = dict(
        require_contact_walls=False,
        clip_outliers=False,
    )
    coverage_note = (
        "coverage: observations on both sides of mid-eclipse "
        "(min_each_side=3); no 90-10 percent contact wall_band; no O-C clip"
    )

    vm_p = time_both_walls(
        t_mjd, mag_w, sig_w, model, adopted, HALF_ORBIT_WINDOW,
        "primary", epoch_jd, period, **timing_kw,
    )
    if has_timings(vm_p):
        logger.info(
            "primary both-sides N=%s median formal sigma=%.1f s",
            len(vm_p["T"]),
            86400.0 * np.median(vm_p["sigma"]),
        )
    write_timing_ascii(
        RESULTS_DIR / f"{TIMING_STEM}_timing_primary.dat",
        vm_p,
        method="Mikulasek virtual minima, frozen adopted template",
        window=HALF_ORBIT_WINDOW,
        events="integer E from T0 (deeper minimum / phase ~0 of PARAM epoch)",
        extra_comments=extra + [
            coverage_note,
            "window_meaning: |phase-E| < 0.25",
        ],
        **ascii_kw,
    )

    vm_s = time_both_walls(
        t_mjd, mag_w, sig_w, model, adopted, HALF_ORBIT_WINDOW,
        "secondary", epoch_jd, period, **timing_kw,
    )
    if has_timings(vm_s):
        logger.info(
            "secondary both-sides N=%s median formal sigma=%.1f s",
            len(vm_s["T"]),
            86400.0 * np.median(vm_s["sigma"]),
        )
    write_timing_ascii(
        RESULTS_DIR / f"{TIMING_STEM}_timing_secondary.dat",
        vm_s,
        method="Mikulasek virtual minima, frozen adopted template",
        window=HALF_ORBIT_WINDOW,
        events="half-integer E from T0 (phase ~0.5 of PARAM epoch)",
        extra_comments=extra + [
            coverage_note,
            "window_meaning: |phase-E| < 0.25",
        ],
        **ascii_kw,
    )


if __name__ == "__main__":
    main()
