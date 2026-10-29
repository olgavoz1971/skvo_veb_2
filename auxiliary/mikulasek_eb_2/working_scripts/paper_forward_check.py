"""Forward check of the engine against Mikulasek (2015) Table 1.

Builds the published phenomenological model of a star from Table 1 and lays it
over the TESS light curve of the same star. Two variants are fitted, both with a
constant baseline per orbit segment:

- A, "paper values as published": every Table 1 parameter fixed; only the
  ephemeris zero point M0 is fitted (period from the VOTable).
- B, "paper shape, amplitudes refitted": the shape (D, Gamma, C1, C2) is fixed at
  the published values; eclipse depths, harmonic amplitudes, the O'Connell term
  and the ephemeris (M0, P0) are free. This absorbs the band difference
  (V against TESS red) and TESS dilution.

- C, "shape widths freed": as B, plus D and Gamma free (shared by both eclipses).
- D, "paper-style fit": as C, plus the per-eclipse C1 and C2 free. This is the
  full Table 1 parameter set of the star (shared D and Gamma, separate C).

A and B show how well the published shape describes the TESS light curve; C and
D show what the TESS data prefer when the same parameter set is freed. Figures
and a text summary go to ``results/``.

Run::

    cd auxiliary/mikulasek_eb_2
    ../../.venv/bin/python working_scripts/paper_forward_check.py EK_Com
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

_WORK = Path(__file__).resolve().parent
_ROOT = _WORK.parent
for _p in (_WORK, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from eb_tuning import initial_guess, noise_floor, out_of_eclipse_mask, residuals  # noqa: E402
from mikulasek_eb import EBModel, fit_global  # noqa: E402
from votable_loader import load_tess_votable  # noqa: E402
from workflow_helpers import (  # noqa: E402
    LINE_ADOPTED_COLOUR,
    LINE_ADOPTED_WIDTH,
    absolute_jd_to_mjd,
    predicted_magnitude,
    replicate_folded_points,
)

logger = logging.getLogger(__name__)

MANIFEST_PATH = _ROOT / "references" / "stars_manifest.json"
RESULTS_DIR = _ROOT / "results"

# TESS downlink gaps are longer than this (days); baselines split there. Shorter
# than one TESS orbit gap (0.9-1.0 d for AR Aur and V477 Lyr) and longer than any
# in-orbit gap in these data.
GAP_SPLIT_DAYS = 0.5
BASELINE_ORDER = 0

# Plot layout.
FOLD_PHASE_MIN = -0.25
FOLD_PHASE_MAX = 1.25
ZOOM_HALF_WIDTH = 0.15
CURVE_GRID_N = 3000
LINE_PAPER_COLOUR = "#1f77b4"
LINE_PAPER_WIDTH = 1.6
LINE_B_COLOUR = "0.35"
LINE_C_COLOUR = "#ff7f0e"
LINE_B_WIDTH = 1.4
LINE_C_WIDTH = 1.4
POINT_SIZE = 3
POINT_ALPHA = 0.35
FIGURE_DPI = 120
RESIDUAL_AXIS_MMAG = 40.0


def build_ek_com_template(paper: dict, tess_lambda: float) -> tuple[EBModel, dict, dict]:
    """Build the EK Com model of Table 1 (V band, one colour).

    Table 1 lists for EK Com: shared D and Gamma, separate C1 and C2, the
    cos(2 pi theta) and cos(4 pi theta) amplitudes and the sin(2 pi theta)
    O'Connell term (``A6``).

    Args:
        paper (dict): The ``paper`` block of the manifest entry for EK Com.
        tess_lambda (float): Lambda of the TESS band (unused: one-colour column).

    Returns:
        tuple[EBModel, dict, dict]: Model, published parameters and their
        published errors.
    """
    model = EBModel(profile=1, harmonics=(1, 2), ocon=True)
    params = dict(
        A1=paper["a11"][0],
        A2=paper["a21"][0],
        D1=paper["D"][0],
        G1=paper["Gamma"][0],
        C1=paper["C1"][0],
        C2=paper["C2"][0],
        H1=paper["a31_cos2pi"][0],
        H2=paper["a41_cos4pi"][0],
        S1=paper["A6_sin2pi"][0],
    )
    errors = dict(
        A1=paper["a11"][1], A2=paper["a21"][1], D1=paper["D"][1], G1=paper["Gamma"][1],
        C1=paper["C1"][1], C2=paper["C2"][1], H1=paper["a31_cos2pi"][1],
        H2=paper["a41_cos4pi"][1], S1=paper["A6_sin2pi"][1],
    )
    return model, params, errors


def build_v477_lyr_template(paper: dict, tess_lambda: float) -> tuple[EBModel, dict, dict]:
    """Build the V477 Lyr model of Table 1 (V band, one colour).

    Table 1: shared D, Gamma and a single C for both eclipses, harmonics
    cos(2 pi theta), cos(4 pi theta) and cos(6 pi theta), no O'Connell term
    (``np = 3``, ``nc = 0`` in Sect. 4.1.2). The single C is stored as ``C1``;
    the engine shares it with eclipse 2.

    Args:
        paper (dict): The ``paper`` block of the manifest entry for V477 Lyr.
        tess_lambda (float): Lambda of the TESS band (unused: one-colour column).

    Returns:
        tuple[EBModel, dict, dict]: Model, published parameters and their
        published errors.
    """
    model = EBModel(profile=1, harmonics=(1, 2, 3), ocon=False)
    params = dict(
        A1=paper["a11"][0],
        A2=paper["a21"][0],
        D1=paper["D"][0],
        G1=paper["Gamma"][0],
        C1=paper["C"][0],
        H1=paper["a31_cos2pi"][0],
        H2=paper["a41_cos4pi"][0],
        H3=paper["a51_cos6pi"][0],
    )
    errors = dict(
        A1=paper["a11"][1], A2=paper["a21"][1], D1=paper["D"][1], G1=paper["Gamma"][1],
        C1=paper["C"][1], H1=paper["a31_cos2pi"][1], H2=paper["a41_cos4pi"][1],
        H3=paper["a51_cos6pi"][1],
    )
    return model, params, errors


def _lambda_term(entry: list, slope: list, tess_lambda: float) -> tuple[float, float]:
    """Evaluate ``a_k1 + a_k2 * Lambda`` and its error without the correlation term.

    Args:
        entry (list): ``[a_k1, error]`` from Table 1.
        slope (list): ``[a_k2, error]`` from Table 1.
        tess_lambda (float): Lambda of the TESS band.

    Returns:
        tuple[float, float]: Value and uncorrelated error propagation.
    """
    value = entry[0] + slope[0] * tess_lambda
    error = float(np.hypot(entry[1], slope[1] * tess_lambda))
    return value, error


def build_av_del_template(paper: dict, tess_lambda: float) -> tuple[EBModel, dict, dict]:
    """Build the AV Del model of Table 1 evaluated at the TESS Lambda.

    Table 1: shared D, Gamma and a single C; eclipse depths ``a11 + a12 * Lambda``
    and ``a21 + a22 * Lambda``; the cos(4 pi theta) term ``a41 + a42 * Lambda``;
    the text sets ``A3 = 0`` (no cos(2 pi theta) term) and there is no O'Connell
    term. Lambda extrapolation: TESS red (745 nm, Lambda = -0.262) lies inside the
    BVRI range of the paper (I band is about 800 nm).

    Args:
        paper (dict): The ``paper`` block of the manifest entry for AV Del.
        tess_lambda (float): Lambda of the TESS band.

    Returns:
        tuple[EBModel, dict, dict]: Model, published parameters at the TESS
        Lambda and their errors (the correlation between ``a_k1`` and ``a_k2``
        is not in the paper, so the errors are an upper-level estimate).
    """
    model = EBModel(profile=1, harmonics=(2,), ocon=False)
    a1, e1 = _lambda_term(paper["a11"], paper["a12"], tess_lambda)
    a2, e2 = _lambda_term(paper["a21"], paper["a22"], tess_lambda)
    h2, eh2 = _lambda_term(paper["a41"], paper["a42"], tess_lambda)
    params = dict(A1=a1, A2=a2, D1=paper["D"][0], G1=paper["Gamma"][0],
                  C1=paper["C"][0], H2=h2)
    errors = dict(A1=e1, A2=e2, D1=paper["D"][1], G1=paper["Gamma"][1],
                  C1=paper["C"][1], H2=eh2)
    return model, params, errors


def build_ar_aur_template(paper: dict, tess_lambda: float) -> tuple[EBModel, dict, dict]:
    """Build the AR Aur model structure of Table 1 for a shape-only comparison.

    The paper gives AR Aur only in B and V (two columns, strongly Lambda
    dependent amplitudes); TESS red would need an extrapolation, so amplitudes are
    NOT compared. The V values serve only as starting values. Structure: shared D,
    Gamma and C, harmonics cos(2 pi theta) and cos(4 pi theta) (both about 2 mmag
    in the paper), no O'Connell term. The harmonic starting values are zero.

    Args:
        paper (dict): The ``paper`` block of the manifest entry for AR Aur.
        tess_lambda (float): Lambda of the TESS band (unused).

    Returns:
        tuple[EBModel, dict, dict]: Model, starting parameters (shape from the
        paper) and the published errors of the shape parameters.
    """
    model = EBModel(profile=1, harmonics=(1, 2), ocon=False)
    params = dict(
        A1=paper["a11_B_V"][1], A2=paper["a21_B_V"][1],
        D1=paper["D"][0], G1=paper["Gamma"][0], C1=paper["C"][0],
        H1=0.0, H2=0.0,
    )
    errors = dict(D1=paper["D"][1], G1=paper["Gamma"][1], C1=paper["C"][1])
    return model, params, errors


# Stars whose amplitudes are not compared (no TESS-band amplitudes in the paper);
# variant A (all paper values) is then skipped.
NO_AMPLITUDE_COMPARISON = {"AR_Aur"}
# Per-star builders; others are added as their Table 1 columns are mapped.
TEMPLATE_BUILDERS = {
    "EK_Com": build_ek_com_template,
    "V477_Lyr": build_v477_lyr_template,
    "AV_Del": build_av_del_template,
    "AR_Aur": build_ar_aur_template,
}

# Amplitude keys refitted in variant B (shape keys D1, G1, C1, C2 stay fixed).
AMPLITUDE_KEYS = {
    "EK_Com": ["A1", "A2", "H1", "H2", "S1"],
    "V477_Lyr": ["A1", "A2", "H1", "H2", "H3"],
    "AV_Del": ["A1", "A2", "H2"],
    "AR_Aur": ["A1", "A2", "H1", "H2"],
}
# Shape keys freed in variants C (width, kurtosis) and D (plus C1, C2).
WIDTH_KEYS = {"EK_Com": ["D1", "G1"], "V477_Lyr": ["D1", "G1"], "AV_Del": ["D1", "G1"], "AR_Aur": ["D1", "G1"]}
CURVATURE_KEYS = {"EK_Com": ["C1", "C2"], "V477_Lyr": ["C1"], "AV_Del": ["C1"], "AR_Aur": ["C1"]}


def load_star(star_key: str) -> tuple[dict, dict, float]:
    """Read the manifest entry of a star.

    Args:
        star_key (str): Key in ``stars_manifest.json`` (for example ``EK_Com``).

    Returns:
        tuple[dict, dict, float]: The star entry, its ``paper`` block and the
        TESS Lambda from the manifest.

    Raises:
        KeyError: If the star is unknown or has no Table 1 column.
    """
    manifest = json.loads(MANIFEST_PATH.read_text())
    entry = manifest["stars"][star_key]
    if not entry.get("paper"):
        raise KeyError(f"{star_key} has no Table 1 column in the manifest.")
    return entry, entry["paper"], float(manifest["tess_lambda"])


def baseline_segments(t_mjd: np.ndarray) -> np.ndarray:
    """Number the orbit segments by splitting at gaps longer than ``GAP_SPLIT_DAYS``.

    Args:
        t_mjd (ndarray): Sorted observation times (MJD).

    Returns:
        ndarray: Integer segment index per point.
    """
    return np.cumsum(np.r_[0, np.diff(t_mjd) > GAP_SPLIT_DAYS])


def fit_variants(t, mag, sig, model, params, star_key, seg, g, period):
    """Fit variants A to D of the published model (see the module docstring).

    Variant A (all paper values) is skipped for stars in
    ``NO_AMPLITUDE_COMPARISON``. In variants B to D both M0 and P0 are free (the
    period is fitted starting from the VOTable value).

    Args:
        t (ndarray): Times (MJD).
        mag (ndarray): Magnitudes.
        sig (ndarray): Magnitude uncertainties.
        model (EBModel): Published model structure.
        params (dict): Published parameters (or starting values).
        star_key (str): Manifest key (selects the free-parameter groups).
        seg (ndarray): Baseline segments.
        g (dict): ``initial_guess`` output (M0 start).
        period (float): Period (days) used as P0.

    Returns:
        dict[str, FitResult]: Fits keyed ``"A"`` (if run), ``"B"``, ``"C"``, ``"D"``.
    """
    amp = AMPLITUDE_KEYS[star_key]
    width = WIDTH_KEYS[star_key]
    curvature = CURVATURE_KEYS[star_key]
    free_ephem = ("M0", "P0")
    common = dict(seg=seg, order=BASELINE_ORDER)
    fits = {}
    ephem = dict(M0=g["M0"], P0=period)
    if star_key not in NO_AMPLITUDE_COMPARISON:
        fits["A"] = fit_global(
            t, mag, sig, model, params, [], ephem, free_ephem=("M0",), **common,
        )
        ephem = fits["A"].ephem
    previous = None
    for label, free in (("B", amp), ("C", amp + width), ("D", amp + width + curvature)):
        start = previous.p if previous is not None else dict(params)
        fits[label] = fit_global(
            t, mag, sig, model, start, free,
            previous.ephem if previous is not None else ephem,
            free_ephem=free_ephem, **common,
        )
        previous = fits[label]
    return fits


def plot_forward_check(t, mag, sig, model, fits, seg, title, save_path):
    """Draw folded data with all published-model variants and their residuals.

    Args:
        t (ndarray): Times (MJD).
        mag (ndarray): Magnitudes.
        sig (ndarray): Magnitude uncertainties.
        model (EBModel): Model structure.
        fits (dict): ``FitResult`` per variant label (``A`` to ``D``).
        seg (ndarray): Baseline segments.
        title (str): Figure title.
        save_path (Path): Output PNG path.
    """
    styles = {
        "A": ("A: paper values, M0 fitted", LINE_PAPER_COLOUR, LINE_PAPER_WIDTH, "--", 3),
        "B": ("B: paper shape, amplitudes free", LINE_B_COLOUR, LINE_B_WIDTH, "-", 4),
        "C": ("C: + D, Gamma free", LINE_C_COLOUR, LINE_C_WIDTH, "-", 5),
        "D": ("D: + C free", LINE_ADOPTED_COLOUR, LINE_ADOPTED_WIDTH, "-", 6),
    }
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    grid = np.linspace(FOLD_PHASE_MIN, FOLD_PHASE_MAX, CURVE_GRID_N)
    folded = {}
    for label, fit in fits.items():
        yhat, f_tpl, theta = predicted_magnitude(
            t, mag, sig, model, fit.p, fit.ephem, seg, BASELINE_ORDER
        )
        phi = theta - np.round(theta)
        folded[label] = replicate_folded_points(
            phi, mag - (yhat - f_tpl), mag - yhat,
            ph_min=FOLD_PHASE_MIN, ph_max=FOLD_PHASE_MAX,
        )
    phi_ref, mag_ref, _ = folded["D"]

    for ax in (axes[0, 0], axes[0, 1], axes[1, 0]):
        ax.scatter(phi_ref, mag_ref, s=POINT_SIZE, alpha=POINT_ALPHA, color="0.6",
                   zorder=1, label="TESS (baseline removed, fit D)")
        for label, fit in fits.items():
            text, colour, width, ls, z = styles[label]
            ax.plot(grid, model(grid, fit.p), color=colour, lw=width, ls=ls,
                    zorder=z, label=text)
        ax.invert_yaxis()
        ax.set_ylabel("Magnitude (template scale)")
    axes[0, 0].set_xlim(FOLD_PHASE_MIN, FOLD_PHASE_MAX)
    axes[0, 0].set_xlabel("Phase")
    axes[0, 0].set_title("Fold")
    axes[0, 0].legend(fontsize=8)
    axes[0, 1].set_xlim(-ZOOM_HALF_WIDTH, ZOOM_HALF_WIDTH)
    axes[0, 1].set_xlabel("Phase (primary)")
    axes[0, 1].set_title("Primary minimum")
    axes[1, 0].set_xlim(0.5 - ZOOM_HALF_WIDTH, 0.5 + ZOOM_HALF_WIDTH)
    axes[1, 0].set_xlabel("Phase (secondary)")
    axes[1, 0].set_title("Secondary minimum")

    ax = axes[1, 1]
    for label, colour, z in (("B", LINE_B_COLOUR, 1), ("D", LINE_ADOPTED_COLOUR, 2)):
        phi_l, _, res_l = folded[label]
        ax.scatter(phi_l, 1e3 * res_l, s=POINT_SIZE, alpha=POINT_ALPHA, color=colour,
                   zorder=z, label=f"residual {label}")
    ax.axhline(0.0, color="k", lw=1.0, zorder=5)
    ax.set_xlim(FOLD_PHASE_MIN, FOLD_PHASE_MAX)
    ax.set_ylim(-RESIDUAL_AXIS_MMAG, RESIDUAL_AXIS_MMAG)
    ax.set_xlabel("Phase")
    ax.set_ylabel("Residual (mmag)")
    ax.set_title("Residuals")
    ax.legend(fontsize=8)
    fig.suptitle(title, y=0.995)
    plt.tight_layout()
    fig.savefig(save_path, dpi=FIGURE_DPI, bbox_inches="tight")
    import matplotlib

    if matplotlib.get_backend().lower() != "agg":
        plt.show()
    else:
        plt.close(fig)


def run_forward_check(star_key: str) -> dict:
    """Run the forward check for one star and write the figure and summary.

    Args:
        star_key (str): Key in the manifest (must have a template builder).

    Returns:
        dict: Machine-readable summary: ``star``, ``n_points``, ``cadence_min``,
        ``rms_mmag`` per variant, ``fitted_period`` (value, error), ``paper_period``,
        ``shape`` (per parameter: TESS value and error, paper value and error,
        deviation in combined sigma) and ``a2_over_a1`` (TESS and paper).

    Raises:
        KeyError: If no template builder exists for the star.
    """
    if star_key not in TEMPLATE_BUILDERS:
        raise KeyError(f"No Table 1 template builder for {star_key}.")
    entry, paper, tess_lambda = load_star(star_key)
    model, params, perr = TEMPLATE_BUILDERS[star_key](paper, tess_lambda)

    payload = load_tess_votable(_ROOT / entry["votable"])
    t = absolute_jd_to_mjd(payload["t"])
    mag, sig, period = payload["mag"], payload["sig"], payload["period"]
    seg = baseline_segments(t)
    g = initial_guess(t, mag, period)
    logger.info("%s: N=%d, VOTable P=%.7f d, paper P=%.5f d", star_key, len(t), period,
                paper["period_d"])

    fits = fit_variants(t, mag, sig, model, params, star_key, seg, g, period)
    fit_d = fits["D"]
    oo_mask = out_of_eclipse_mask(t, fit_d.ephem, g["fwhm"])
    noise = noise_floor(t, mag, mask=oo_mask)
    lines = [
        f"star: {star_key}",
        f"VOTable period (start): {period:.7f} d; paper period: {paper['period_d']}",
        f"median catalogue sigma: {1e3 * float(np.median(sig)):.2f} mmag; "
        f"out-of-eclipse noise floor: {1e3 * noise:.2f} mmag "
        "(inflated by orbital modulation in contact systems; compare rms in mmag)",
    ]
    for label, fit in fits.items():
        lines.append(
            f"variant {label}: rms {1e3 * fit.rms:.2f} mmag, "
            f"chi2 {fit.chi2:.0f}, rchi2 {fit.rchi2:.1f}, free parameters {len(fit.names)}"
        )
    lines.append(
        f"fitted P0 (D): {fit_d.ephem['P0']:.8f} +- {fit_d.err['P0']:.8f} d "
        f"(VOTable {period:.7f}, paper {paper['period_d']})"
    )
    if star_key in NO_AMPLITUDE_COMPARISON:
        lines.append("amplitudes not compared (no TESS-band amplitudes in the paper)")
        pap_ratios = ", ".join(
            f"{band} {paper['a21_B_V'][i] / paper['a11_B_V'][i]:.3f}"
            for i, band in enumerate(("B", "V"))
        )
        lines.append(
            f"  A2/A1: TESS {fit_d.p['A2'] / fit_d.p['A1']:.3f}   paper {pap_ratios} "
            "(band dependent)"
        )
    else:
        lines.append(
            "amplitudes (fit D) against the paper (band differs; AV Del paper values are "
            f"evaluated at Lambda = {tess_lambda:+.3f}):"
        )
        for key in AMPLITUDE_KEYS[star_key]:
            lines.append(
                f"  {key}: TESS {fit_d.p[key]:+.4f} +- {fit_d.err[key]:.4f}"
                f"   paper {params[key]:+.4f} +- {perr[key]:.4f}"
            )
        lines.append(
            f"  A2/A1: TESS {fit_d.p['A2'] / fit_d.p['A1']:.3f}"
            f"   paper {params['A2'] / params['A1']:.3f}"
        )
    lines.append("shape parameters (fit D) against the paper:")
    for key in WIDTH_KEYS[star_key] + CURVATURE_KEYS[star_key]:
        lines.append(
            f"  {key}: TESS {fit_d.p[key]:+.4f} +- {fit_d.err[key]:.4f}"
            f"   paper {params[key]:+.4f} +- {perr[key]:.4f}"
        )
    for line in lines:
        logger.info(line)
    summary_path = RESULTS_DIR / f"paper_forward_{star_key.lower()}.txt"
    summary_path.write_text("\n".join(lines) + "\n")

    figure_path = RESULTS_DIR / f"paper_forward_{star_key.lower()}.png"
    shape_text = ", ".join(f"{k}={params[k]}" for k in ("D1", "G1", "C1", "C2") if k in params)
    title = f"{star_key}: Mikulasek (2015) Table 1 model on TESS (published shape {shape_text})"
    plot_forward_check(t, mag, sig, model, fits, seg, title, figure_path)
    logger.info("Figure saved to %s; summary %s", figure_path, summary_path)

    shape = {}
    for key in WIDTH_KEYS[star_key] + CURVATURE_KEYS[star_key]:
        combined = float(np.hypot(fit_d.err[key], perr[key]))
        shape[key] = dict(
            tess=float(fit_d.p[key]), tess_err=float(fit_d.err[key]),
            paper=float(params[key]), paper_err=float(perr[key]),
            deviation_sigma=float(abs(fit_d.p[key] - params[key]) / combined),
        )
    if star_key in NO_AMPLITUDE_COMPARISON:
        paper_ratio = paper["a21_B_V"][1] / paper["a11_B_V"][1]
    else:
        paper_ratio = params["A2"] / params["A1"]
    return dict(
        star=star_key,
        n_points=int(len(t)),
        cadence_min=entry["cadence_min"],
        rms_mmag={k: 1e3 * float(f.rms) for k, f in fits.items()},
        fitted_period=(float(fit_d.ephem["P0"]), float(fit_d.err["P0"])),
        paper_period=paper["period_d"],
        shape=shape,
        a2_over_a1=dict(tess=float(fit_d.p["A2"] / fit_d.p["A1"]), paper=float(paper_ratio)),
    )


def write_cross_star_summary(results: list[dict], path: Path) -> None:
    """Write a markdown comparison table of all stars against Table 1.

    Args:
        results (list[dict]): Outputs of ``run_forward_check``.
        path (Path): Output markdown file.
    """
    lines = [
        "# TESS fits against Mikulasek (2015) Table 1",
        "",
        "Fit D: paper parameter set freed, period fitted. Deviation = |TESS - paper| in "
        "combined sigma (TESS formal error rescaled by reduced chi2; paper error as "
        "published; paper amplitude errors ignore the a_k1, a_k2 correlation). "
        "Formal TESS errors understate systematic misfit.",
        "",
        "| Star | N | cadence (min) | rms A/B/C/D (mmag) | fitted P (d) | paper P (d) |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        rms = "/".join(f"{r['rms_mmag'][k]:.1f}" if k in r["rms_mmag"] else "-" for k in "ABCD")
        lines.append(
            f"| {r['star']} | {r['n_points']} | {r['cadence_min']} | {rms} | "
            f"{r['fitted_period'][0]:.6f}({r['fitted_period'][1]:.1e}) | {r['paper_period']} |"
        )
    lines += ["", "| Star | Parameter | TESS | Paper | Deviation (sigma) |", "|---|---|---|---|---|"]
    for r in results:
        for key, v in r["shape"].items():
            lines.append(
                f"| {r['star']} | {key} | {v['tess']:+.4f} ({v['tess_err']:.5f}) | "
                f"{v['paper']:+.4f} ({v['paper_err']:.4f}) | {v['deviation_sigma']:.1f} |"
            )
        ratio = r["a2_over_a1"]
        lines.append(
            f"| {r['star']} | A2/A1 | {ratio['tess']:.3f} | {ratio['paper']:.3f} | - |"
        )
    lines += [
        "",
        "Notes: AR Aur amplitudes are not compared (paper gives B and V only); its A2/A1 "
        "paper value is the V column. Paper period for AR Aur (4.13169 d) is contradicted "
        "by the data. EK Com has about 5.6 points per FWHM (10 min cadence). V477 Lyr is "
        "noise limited (29 mmag per point).",
    ]
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    """Run one star (``EK_Com``, ...) or ``all`` and write the cross-star summary."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    arg = sys.argv[1] if len(sys.argv) > 1 else "EK_Com"
    if arg == "all":
        results = [run_forward_check(key) for key in TEMPLATE_BUILDERS]
        summary = RESULTS_DIR / "paper_comparison_summary.md"
        write_cross_star_summary(results, summary)
        logger.info("Cross-star summary written to %s", summary)
    else:
        run_forward_check(arg)


if __name__ == "__main__":
    main()
