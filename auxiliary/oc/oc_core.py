"""O-C analysis tasks (plot residuals, segment period fit, parabolic ephemeris).

Methods
-------
``plot_oc_residuals``:
    Assign cycle ``E = round((jd_ext - T0)/P0)`` with optional ``cycle_shifts``,
    then ``O-C = jd_ext - (T0 + E*P0)`` (days).

``fit_segment_periods``:
    Within each JD segment, iteratively fit ``O-C`` vs calendar JD (Astropy
    ``Linear1D`` + 3σ outlier rejection), applying
    ``P <- P/(1-slope)`` and ``T0 <- T0 + mean(O-C)`` until ``|slope| < tol``.

``fit_parabolic_ephemeris``:
    Fit ``O-C(E)`` as a quadratic polynomial (Astropy ``Polynomial1D`` degree 2)
    inside ``fit_window``, build a piecewise ephemeris, and smart-fold the LC.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

_AUX = Path(__file__).resolve().parents[1]
_REPO = _AUX.parent
_TIMING = _AUX / "template_timing"
for _p in (_REPO, _AUX, _TIMING):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import plot_oc as _po
from lc_io import load_lightcurve_frame
from oc_config import OcStudyConfig
from oc_io import (
    ExtremaRecord,
    default_provenance,
    extrema_jd_array,
    load_extrema_file,
    write_csv_with_provenance,
)
from plot_style import apply_plot_style

logger = logging.getLogger(__name__)


def _export_path(cfg: OcStudyConfig, task: str, key: str, default: str) -> Path:
    task_exports = cfg.exports.get(task) or {}
    name = task_exports.get(key, default)
    return cfg.output_dir / name


def _records_as_plot_rows(records: list[ExtremaRecord]) -> list[dict]:
    """Adapt :class:`ExtremaRecord` list for legacy plot hover helpers."""
    rows: list[dict] = []
    for rec in records:
        rows.append(
            {
                "piece_id": rec.piece_id or "?",
                "interval": rec.interval_index if rec.interval_index is not None else "?",
                "sigma_t_max": rec.sigma_jd_ext,
            }
        )
    return rows


def run_plot_oc_residuals(
    cfg: OcStudyConfig,
    records: list[ExtremaRecord],
    *,
    E: np.ndarray,
    OC: np.ndarray,
    jd_ext: np.ndarray,
) -> None:
    """Plot and export calculated O-C residuals."""
    rows = _records_as_plot_rows(records)
    export_path = _export_path(cfg, "plot_oc_residuals", "oc_table", "oc_residuals.csv")
    fig_path = _export_path(cfg, "plot_oc_residuals", "figure", "oc_residuals.png")

    if cfg.write_provenance:
        prov = default_provenance(
            task="plot_oc_residuals",
            study_label=cfg.label,
            source_format=cfg.extrema_format,
            source_path=cfg.extrema_path,
            algorithm=(
                "O-C = jd_ext - (T0 + E*P0); "
                "E = round((jd_ext-T0)/P0) after cycle_shifts"
            ),
            extra={
                "ephemeris_T0_JD": f"{cfg.T0_jd:.5f}",
                "ephemeris_P0_d": f"{cfg.P0:.8f}",
                "cycle_shifts_applied": str(len(cfg.cycle_shifts)),
            },
        )
        csv_rows = [
            {
                "cycle_number": int(e),
                "OC": float(oc),
                **(
                    {"sigma_jd_ext": records[i].sigma_jd_ext}
                    if records[i].sigma_jd_ext is not None
                    else {}
                ),
            }
            for i, (e, oc) in enumerate(zip(E, OC, strict=True))
        ]
        fields = ["cycle_number", "OC"]
        if any(r.sigma_jd_ext is not None for r in records):
            fields.append("sigma_jd_ext")
        write_csv_with_provenance(
            export_path,
            provenance=prov,
            fieldnames=fields,
            rows=csv_rows,
        )
    else:
        _po.export_calculated_oc(export_path, rows, E, OC)

    apply_plot_style()
    fig, _ax = _po.plot_calculated_oc(
        E,
        OC,
        jd_ext,
        rows,
        T0=cfg.T0_jd,
        P0=cfg.P0,
        show=False,
    )
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=cfg.plot_dpi)
    plt.close(fig)
    logger.info("Wrote %s", fig_path)
    logger.info(
        "plot_oc_residuals: O-C range [%.5f, %.5f] d, RMS=%.5f d",
        float(np.min(OC)),
        float(np.max(OC)),
        float(np.sqrt(np.mean(OC**2))),
    )
    if cfg.show_plots:
        _po.plot_calculated_oc(
            E, OC, jd_ext, rows, T0=cfg.T0_jd, P0=cfg.P0, show=True
        )


def run_fit_segment_periods(
    cfg: OcStudyConfig,
    records: list[ExtremaRecord],
    *,
    E: np.ndarray,
    OC: np.ndarray,
    jd_ext: np.ndarray,
) -> None:
    """Linear O-C segment period correction (legacy ``correct_period_in_segment``)."""
    jd_ext_arr, sigma = extrema_jd_array(records)
    results: list[_po.LinearSegmentEphemeris] = []

    logger.info(
        "fit_segment_periods: %s segment(s), trial T0=%.5f P0=%.8f",
        len(cfg.segments),
        cfg.T0_jd,
        cfg.P0,
    )
    for seg in cfg.segments:
        mask = (jd_ext_arr >= seg.start_jd) & (jd_ext_arr <= seg.end_jd)
        n_in = int(np.count_nonzero(mask))
        if n_in < 2:
            logger.warning(
                "segment %r: skipping — only %s point(s) in JD [%.5f, %.5f]",
                seg.name,
                n_in,
                seg.start_jd,
                seg.end_jd,
            )
            continue
        fitted = _po.correct_period_in_segment(
            jd_ext_arr,
            E,
            OC,
            name=seg.name,
            jd_window=(seg.start_jd, seg.end_jd),
            T0=cfg.T0_jd,
            P0=cfg.P0,
            sigma=sigma,
            max_iter=cfg.segment_max_iter,
            tol=cfg.segment_tol,
        )
        logger.info("%s", fitted.describe())
        results.append(fitted)

    if not results:
        logger.warning("fit_segment_periods: no segments fitted")
        return

    export_path = _export_path(
        cfg, "fit_segment_periods", "segment_table", "segment_periods.csv"
    )
    _po.export_segment_periods(export_path, results)
    _po.plot_oc_segment_period_fits(
        E,
        OC,
        jd_ext,
        results,
        T0=cfg.T0_jd,
        P0=cfg.P0,
        show=cfg.show_plots,
    )


def _load_lc_mag_frame(path: Path, *, working_domain: str):
    """Load LC and expose ``mag``/``dmag`` columns for smart-fold export."""
    import pandas as pd

    df, meta = load_lightcurve_frame(path, working_domain=working_domain)
    out = df.rename(columns={"phot": "mag", "phot_err": "dmag"})
    return out, {"photcal": meta.get("photcal")}


def run_fit_parabolic_ephemeris(
    cfg: OcStudyConfig,
    records: list[ExtremaRecord],
    *,
    E: np.ndarray,
    OC: np.ndarray,
    jd_ext: np.ndarray,
) -> None:
    """Quadratic O-C ephemeris fit and piecewise LC fold."""
    assert cfg.parabolic_fit_start_jd is not None
    assert cfg.parabolic_fit_end_jd is not None
    assert cfg.lightcurve_path is not None
    assert cfg.photometry_domain is not None

    fit_window = (cfg.parabolic_fit_start_jd, cfg.parabolic_fit_end_jd)
    ephem, oc_model = _po.fit_oc_parabola(
        E,
        OC,
        jd_ext,
        jd_window=fit_window,
        T0=cfg.T0_jd,
        P0=cfg.P0,
    )
    logger.info("%s", ephem.describe())

    fit_mask = (jd_ext >= fit_window[0]) & (jd_ext <= fit_window[1])
    if not np.any(fit_mask):
        raise ValueError("no extrema inside parabolic_ephemeris.fit_window")

    fig_path = _export_path(
        cfg, "fit_parabolic_ephemeris", "figure", "oc_parabolic_fit.png"
    )
    _po.plot_oc_parabolic_fit(
        E,
        OC,
        jd_ext,
        fit_mask=fit_mask,
        oc_model=oc_model,
        T0=cfg.T0_jd,
        P0=cfg.P0,
        show=False,
    )
    apply_plot_style()
    fig = plt.gcf()
    fig.savefig(fig_path, dpi=cfg.plot_dpi)
    plt.close(fig)

    E_end_idx = int(np.argmax(jd_ext[fit_mask]))
    E_end = float(E[fit_mask][E_end_idx])
    piecewise = _po.PiecewiseEphemeris.from_quadratic(
        T0=cfg.T0_jd,
        P0=cfg.P0,
        quad=ephem,
        jd_window=fit_window,
        E_at_jd_end=E_end,
    )
    logger.info("%s", piecewise.describe())

    lc_df, lc_header = _load_lc_mag_frame(
        cfg.lightcurve_path,
        working_domain=cfg.photometry_domain,
    )
    folded_lc = _po.smart_fold_lightcurve(lc_df, piecewise)
    lc_export = _export_path(
        cfg, "fit_parabolic_ephemeris", "folded_lc", "lc_parabolic_folded.dat"
    )
    _po.export_smart_folded_lc(folded_lc, lc_export, header=lc_header)
    _po.plot_smart_folded_lc(folded_lc, show=cfg.show_plots)


def run_study(cfg: OcStudyConfig) -> None:
    """Execute all enabled tasks for one loaded study configuration."""
    records = load_extrema_file(
        cfg.extrema_path,
        fmt=cfg.extrema_format,
        file_time=cfg.extrema_file_time,
        exclude_rejected=cfg.exclude_rejected,
        timing_method=cfg.timing_method_filter,
        ascii_columns=cfg.ascii_columns,
    )
    jd_ext, _sigma = extrema_jd_array(records)
    E, OC = _po.compute_OC(
        jd_ext,
        cfg.P0,
        cfg.T0_jd,
        cycle_shifts=cfg.cycle_shifts or None,
    )

    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    if cfg.tasks["plot_oc_residuals"]:
        run_plot_oc_residuals(cfg, records, E=E, OC=OC, jd_ext=jd_ext)
    if cfg.tasks["fit_segment_periods"]:
        run_fit_segment_periods(cfg, records, E=E, OC=OC, jd_ext=jd_ext)
    if cfg.tasks["fit_parabolic_ephemeris"]:
        run_fit_parabolic_ephemeris(cfg, records, E=E, OC=OC, jd_ext=jd_ext)
