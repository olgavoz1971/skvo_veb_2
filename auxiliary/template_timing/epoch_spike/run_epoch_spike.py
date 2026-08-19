"""CLI for the read-only template-epoch spike (bisector + Kwee-van Woerden)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_SPIKE = Path(__file__).resolve().parent
_TIMING = _SPIKE.parent
for _p in (_SPIKE, _TIMING):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from epoch_config import load_epoch_config
from epoch_core import run_epoch_estimators
from epoch_io import (
    default_provenance,
    days_to_seconds,
    load_template_dir,
    write_commented_table,
    write_corrected_template,
)
from epoch_plot import (
    plot_bisector_ladder,
    plot_branch_overlay,
    plot_kvw_cost,
    plot_template_marks,
)

logger = logging.getLogger(__name__)


def _write_exports(cfg, result) -> None:
    """Write ASCII tables and the summary CSV under ``cfg.output_dir``."""
    out = cfg.output_dir
    prov = default_provenance(study_label=cfg.label, template_dir=cfg.template_dir)
    tmpl = result.template

    grid_rows = [
        {
            "tau": float(tau),
            "mu": float(mu),
            "sigma": float(sig),
        }
        for tau, mu, sig in zip(tmpl.tau, tmpl.mu, tmpl.sigma, strict=True)
        if result.copy_lo <= tau <= result.copy_hi
    ]
    write_commented_table(
        out / "template_grid.dat",
        provenance=prov,
        fieldnames=["tau", "mu", "sigma"],
        rows=grid_rows,
    )

    bis_rows = [
        {
            "depth": row.depth,
            "flux": row.flux,
            "tau_left": row.tau_left,
            "tau_right": row.tau_right,
            "tau_bis": row.tau_bis,
            "sigma_tau_bis": row.sigma_tau_bis,
        }
        for row in result.bisector.levels
    ]
    write_commented_table(
        out / "bisector.dat",
        provenance=prov,
        fieldnames=[
            "depth",
            "flux",
            "tau_left",
            "tau_right",
            "tau_bis",
            "sigma_tau_bis",
        ],
        rows=bis_rows,
    )

    summary = {
        "label": cfg.label,
        "extrema_mode": tmpl.extrema_mode,
        "fold_period_d": tmpl.fold_period,
        "tau_gp_argmin_d": result.tau_gp_argmin,
        "tau_kvw_d": result.kvw.tau,
        "tau_kvw_parabola_d": result.kvw.tau_parabola,
        "tau_bisector_core_d": result.bisector.tau_core,
        "tau_bisector_extrap_floor_d": result.bisector.tau_extrap_floor,
        "delta_kvw_minus_argmin_s": result.delta_kvw_minus_argmin_s,
        "delta_bisector_minus_argmin_s": result.delta_bisector_minus_argmin_s,
        "sigma_kvw_s": days_to_seconds(result.kvw.sigma_tau),
        "sigma_bisector_core_s": days_to_seconds(result.bisector.sigma_tau_core),
        "bisector_slope_s_per_depth": days_to_seconds(
            result.bisector.slope_days_per_depth
        ),
        "kvw_cost_min": result.kvw.cost_min,
        "kvw_n_pairs": result.kvw.n_pairs,
        "n_bisector_levels": len(result.bisector.levels),
        "continuum": result.continuum,
        "bottom": result.bottom,
        "copy_lo_d": result.copy_lo,
        "copy_hi_d": result.copy_hi,
        "kvw_half_width_d": result.kvw_half_width_days,
        "kvw_search_half_width_d": result.kvw_search_half_width_days,
        "export_method": cfg.export_method,
        "export_template_dir": str(cfg.export_template_dir),
        "template_dir": str(cfg.template_dir),
    }
    write_commented_table(
        out / "epoch_summary.csv",
        provenance=prov,
        fieldnames=list(summary.keys()),
        rows=[summary],
    )


def main() -> None:
    """Run the template-epoch spike from a YAML study file."""
    parser = argparse.ArgumentParser(
        description="Bisector and Kwee-van Woerden spike; writes a relabelled template for run_timing"
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        required=True,
        help="Path to epoch_spike/configs/*.yaml",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save figures only; do not call plt.show()",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    cfg = load_epoch_config(args.config.resolve())
    if args.no_show:
        cfg.show_plots = False

    template = load_template_dir(cfg.template_dir)
    result = run_epoch_estimators(template, cfg)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    _write_exports(cfg, result)

    plot_kw = {"dpi": cfg.plot_dpi, "show": cfg.show_plots}
    plot_template_marks(result, cfg.output_dir / "template_marks.png", **plot_kw)
    plot_bisector_ladder(result, cfg.output_dir / "bisector_ladder.png", **plot_kw)
    plot_kvw_cost(result, cfg.output_dir / "kvw_cost.png", **plot_kw)
    plot_branch_overlay(result, cfg.output_dir / "branch_overlay.png", **plot_kw)

    tau_export = result.tau_for_method(cfg.export_method)
    write_corrected_template(
        template,
        tau_peak=tau_export,
        method=cfg.export_method,
        dest_dir=cfg.export_template_dir,
        study_label=cfg.label,
        copy_lo=result.copy_lo,
        copy_hi=result.copy_hi,
    )

    logger.info(
        "Epoch spike %r finished; KvW-argmin = %.3f s, bisector-argmin = %.3f s; "
        "corrected template (%s) in %s; diagnostics in %s",
        cfg.label,
        result.delta_kvw_minus_argmin_s,
        result.delta_bisector_minus_argmin_s,
        cfg.export_method,
        cfg.export_template_dir,
        cfg.output_dir,
    )


if __name__ == "__main__":
    main()
