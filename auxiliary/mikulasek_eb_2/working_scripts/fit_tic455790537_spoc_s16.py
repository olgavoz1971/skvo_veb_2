"""Fit TIC 455790537 SPOC sector 16 (2-min) with the Mikulasek phenomenological model.

Period and folding epoch (T0) come from the VOTable TABLE PARAMs. The optimiser
uses MJD; plots and logs use absolute Julian Date (J0 = 0). Figures go to
``results/``.

Run::

    cd auxiliary/mikulasek_eb_2
    .venv/bin/python working_scripts/fit_tic455790537_spoc_s16.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from astropy.time import Time
import numpy as np

_WORK = Path(__file__).resolve().parent
_ROOT = _WORK.parent
_ENGINE = _ROOT / "scripts"
for _p in (_WORK, _ENGINE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mikulasek_fit_pipeline import FitConfig, run_staged_fit  # noqa: E402
from votable_loader import load_tess_votable  # noqa: E402
from workflow_helpers import (  # noqa: E402
    absolute_jd_to_mjd,
    plot_global_fit,
    predicted_magnitude,
)

logger = logging.getLogger(__name__)

# Input VOTable (under ``data/``).
VOTABLE_PATH = _ROOT / "data" / "lc_discovery_TIC_455790537_SPOC_sector_16.vot"
# VOTABLE_PATH = _ROOT / "data" / "lc_discovery_TIC_455790537_TESS_SPOC_sector_16.vot"

# Diagnostic figure (under ``results/``).
FIGURE_OUTPUT_PATH = _ROOT / "results" / "fit_tic455790537_spoc_s16.png"

# Working hypothesis for this 2-min SPOC teacher (AA And-like total primary).
FIT_CONFIG = FitConfig(
    profile=1,
    harmonics=(1, 2, 3),
    ocon=True,
    baseline_order=0,
    gap_split_days=None,
    allow_two_component=True,
)


def main() -> None:
    """Load the VOTable, fit the model, and write the diagnostic figure."""
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


if __name__ == "__main__":
    main()
