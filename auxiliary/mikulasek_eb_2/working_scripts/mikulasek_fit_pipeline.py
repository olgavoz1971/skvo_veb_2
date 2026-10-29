"""Staged Mikulasek global fit with optional two-component primary extension."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from astropy.time import Time

from eb_tuning import (
    binned_residuals,
    D_from_fwhm,
    initial_guess,
    multistart_global,
    noise_floor,
    out_of_eclipse_mask,
    refine_two_component,
    residuals,
    wall_band,
)
from mikulasek_eb import EBModel, fit_global, phase, virtual_minima
from workflow_helpers import (
    complete_template,
    out_of_eclipse_phase_mask,
    report_fit,
    two_component_degenerate,
)

logger = logging.getLogger(__name__)

# Folded depth ratio below which we warn that P might be P/2.
PRIMARY_A2_OVER_A1_MIN_RATIO = 1.2

# Cadence warning: fewer than this many samples per FWHM (FFI / long cadence).
MIN_POINTS_PER_FWHM = 8.0

# Two-component acceptance (shape): fractional rms improvement.
MIN_RMS_GAIN_FRAC = 0.25

# Two-component acceptance: agreeing refine_two_component starts at best chi2.
MIN_AGREEING_TWO_COMP_STARTS = 2

# Two-component acceptance: max relative error on A1, D1, G1, A1b, D1b, G1b.
MAX_TWO_COMP_REL_ERR = 0.5

# Eclipse index for the optional second profile component (extension, not Mikulasek 2015).
TWO_COMP_ECLIPSES = (1,)

# Virtual-minima check when choosing two-component (same as aa_and_timing_oc).
HALF_ORBIT_WINDOW = 0.25
TIMING_BASELINE_ORDER = 1

# Median |delta T| / combined sigma must be at most this for timing_ok.
TIMING_AGREEMENT_SIGMA_MAX = 1.0


@dataclass
class FitConfig:
    """Star-specific phenomenological and baseline choices.

    Attributes:
        profile (int): Mikulasek Table 2 profile index.
        harmonics (tuple[int, ...]): Cosine harmonic orders (H_k).
        ocon (bool): If True, include O'Connell sine S1.
        baseline_order (int): Per-segment polynomial degree.
        gap_split_days (float | None): Split baselines on gaps longer than this
            (days). None means one baseline for the whole series.
        gamma_starts (tuple): Multi-start Gamma values.
        separate_shape_chi2_frac (float): Unlock D2/G2 if chi2 drops by more.
        clip_nsig (float): Out-of-eclipse MAD clip threshold.
        allow_two_component (bool): Whether to try A1b/D1b/G1b after a poor
            single-component rms/noise.
        rms_noise_two_comp_threshold (float): Try two-component above this
            rms/noise ratio.
        eclipse_weight (float): Extra least-squares weight in both eclipse
            windows (``sigma_eff = sigma / weight``). 1.0 means catalogue
            sigma only. Must be agreed by the researcher; not a silent default.
        eclipse_phase_half (float): Phase half-width around 0 and 0.5 for
            that extra weight (cycles).
    """

    profile: int
    harmonics: tuple[int, ...]
    ocon: bool
    baseline_order: int
    gap_split_days: float | None
    gamma_starts: tuple = (0.5, 1, 2, 4, 8)
    separate_shape_chi2_frac: float = 0.01
    clip_nsig: float = 5.0
    allow_two_component: bool = True
    rms_noise_two_comp_threshold: float = 1.5
    eclipse_weight: float = 1.0
    eclipse_phase_half: float = 0.12


@dataclass
class FitPipelineResult:
    """Outputs of the staged fit pipeline.

    Attributes:
        model (EBModel): Phenomenological model instance.
        adopted: Final ``FitResult`` (single- or two-component).
        single_component: Last valid single-component ``FitResult``.
        seg (ndarray | None): Baseline segment indices (None = one segment).
        order (int): Baseline polynomial degree.
        t_mjd (ndarray): Times used in the fit (MJD).
        mag (ndarray): Magnitudes (possibly clipped).
        sig (ndarray): Uncertainties (catalogue).
        noise_floor (float): Out-of-eclipse noise (mag).
        initial_guess (dict): Folded start (M0, A1, A2, fwhm).
    """

    model: EBModel
    adopted: object
    single_component: object
    seg: np.ndarray | None
    order: int
    t_mjd: np.ndarray
    mag: np.ndarray
    sig: np.ndarray
    noise_floor: float
    initial_guess: dict


def eclipse_reweighted_sigma(
    t: np.ndarray,
    sig: np.ndarray,
    ephem: dict,
    weight: float,
    half: float,
) -> np.ndarray:
    """Scale catalogue sigma down in both eclipse windows (higher chi-squared weight).

    Args:
        t (ndarray): Times in the optimiser system (MJD in this project).
        sig (ndarray): Catalogue magnitude uncertainties.
        ephem (dict): Ephemeris (M0, P0, optional Pdot).
        weight (float): Factor >= 1. Points in eclipse count as weight squared.
        half (float): Phase half-width around 0 and 0.5 (cycles).

    Returns:
        ndarray: Effective sigma for the shape-only refit.

    Raises:
        ValueError: If ``weight`` is not finite and at least 1.
    """
    if not np.isfinite(weight) or weight < 1.0:
        raise ValueError(f"eclipse_weight must be >= 1, got {weight!r}.")
    th = phase(t, ephem["M0"], ephem["P0"], ephem.get("Pdot", 0.0))
    ph = th - np.round(th)
    d2 = (ph - 0.5) - np.round(ph - 0.5)
    in_ecl = (np.abs(ph) < half) | (np.abs(d2) < half)
    sig_w = np.asarray(sig, dtype=float).copy()
    sig_w[in_ecl] = sig_w[in_ecl] / weight
    logger.info(
        "eclipse weight=%g on %s/%s points with |phase|<%g of 0 or 0.5",
        weight,
        int(np.count_nonzero(in_ecl)),
        len(t),
        half,
    )
    return sig_w


def _shape_free_names(r, model: EBModel) -> list[str]:
    """Eclipse-shape keys, excluding frozen harmonics and ephemeris.

    Args:
        r: Fit result whose ``names`` list is the last free set.
        model (EBModel): Template (harmonics / O'Connell).

    Returns:
        list[str]: Names to free in the weighted shape refit.
    """
    frozen = set(_harmonic_free_names(model)) | {"S1", "M0", "P0", "Pdot"}
    return [n for n in r.names if n not in frozen]


def _harmonic_free_names(model: EBModel) -> list[str]:
    """Return H* and S1 names to free for this model.

    Args:
        model (EBModel): Configured model.

    Returns:
        list[str]: Parameter names.
    """
    names = [f"H{k}" for k in model.harmonics]
    if model.ocon:
        names.append("S1")
    return names


def _mjd_to_jd(t_mjd: float) -> float:
    """Convert one MJD value to absolute Julian Date.

    Args:
        t_mjd (float): Modified Julian Date.

    Returns:
        float: Julian Date (J0 = 0).
    """
    return float(Time(t_mjd, format="mjd").jd)


def _fold_phase_from_t0(t_jd: float, t0_jd: float, period: float) -> float:
    """Phase of one JD relative to folding epoch T0.

    Args:
        t_jd (float): Absolute Julian Date.
        t0_jd (float): TABLE PARAM epoch (absolute JD).
        period (float): Orbital period (days).

    Returns:
        float: Phase in [0, 1).
    """
    return float(np.mod((t_jd - t0_jd) / period, 1.0))


def _two_component_timing_ok(
    t_mjd: np.ndarray,
    mag: np.ndarray,
    sig: np.ndarray,
    model: EBModel,
    r_single,
    r_two,
) -> tuple[bool, str]:
    """Compare both-walls virtual minima for single- vs two-component templates.

    Args:
        t_mjd (ndarray): Times in MJD.
        mag (ndarray): Magnitudes.
        sig (ndarray): Uncertainties.
        model (EBModel): Phenomenological model.
        r_single: Single-component ``FitResult``.
        r_two: Two-component ``FitResult``.

    Returns:
        tuple[bool, str]: ``timing_ok`` and a log line for check 4.
    """
    wb = wall_band(model, r_two.p)
    vm_s = virtual_minima(
        t_mjd,
        mag,
        sig,
        model,
        r_single.p,
        r_single.ephem,
        window=HALF_ORBIT_WINDOW,
        order=TIMING_BASELINE_ORDER,
        wall_band=wb,
    )
    vm_t = virtual_minima(
        t_mjd,
        mag,
        sig,
        model,
        r_two.p,
        r_two.ephem,
        window=HALF_ORBIT_WINDOW,
        order=TIMING_BASELINE_ORDER,
        wall_band=wb,
    )
    common = np.intersect1d(vm_s["E"], vm_t["E"])
    if len(common) == 0:
        return False, "check4 no common both-walls events"
    ds = np.array([vm_s["T"][vm_s["E"] == e][0] for e in common])
    dt = np.array([vm_t["T"][vm_t["E"] == e][0] for e in common])
    comb = np.sqrt(
        np.array(
            [
                vm_s["sigma"][vm_s["E"] == e][0] ** 2 + vm_t["sigma"][vm_t["E"] == e][0] ** 2
                for e in common
            ]
        )
    )
    d_t = dt - ds
    med_ratio = float(np.median(np.abs(d_t) / comb))
    msg = (
        f"check4 both-walls N={len(common)} "
        f"median dt={86400.0 * np.median(d_t):.1f} s "
        f"rms dt={86400.0 * d_t.std():.1f} s "
        f"median |dt|/comb.sigma={med_ratio:.2f}"
    )
    timing_ok = med_ratio <= TIMING_AGREEMENT_SIGMA_MAX
    return timing_ok, msg


def run_staged_fit(
    t_mjd: np.ndarray,
    mag: np.ndarray,
    sig: np.ndarray,
    period_days: float,
    epoch_jd: float,
    config: FitConfig,
) -> FitPipelineResult:
    """Run staged global fit and optional two-component primary extension.

    Catalogue sigma only. Adoption of two-component follows ``aa_and_timing_oc``
    shape checks 1-3 and virtual-minima check 4 when ``config.allow_two_component``.

    Args:
        t_mjd (ndarray): Observation times in MJD.
        mag (ndarray): Magnitudes.
        sig (ndarray): Catalogue magnitude uncertainties.
        period_days (float): VOTable PARAM period (days).
        epoch_jd (float): VOTable PARAM epoch as absolute JD (T0 for E).
        config (FitConfig): Star-specific model and baseline choices.

    Returns:
        FitPipelineResult: Adopted and diagnostic fit products.

    Raises:
        RuntimeError: If multi-start finds no valid solution.
        ValueError: If the folded secondary is not an eclipse.
    """
    order = config.baseline_order
    if config.gap_split_days is None:
        seg = None
    else:
        seg = np.cumsum(np.r_[0, np.diff(t_mjd) > config.gap_split_days])
    g = initial_guess(t_mjd, mag, period_days)
    m0_jd = _mjd_to_jd(float(g["M0"]))
    phi_pri = _fold_phase_from_t0(m0_jd, epoch_jd, period_days)
    logger.info(
        "T0=%.10f JD; deepest eclipse M0=%.10f JD; phase vs T0=%.4f",
        epoch_jd,
        m0_jd,
        phi_pri,
    )
    e0 = dict(M0=g["M0"], P0=period_days, Pdot=0.0)
    oo_mask = out_of_eclipse_mask(t_mjd, e0, g["fwhm"])
    nf = noise_floor(t_mjd, mag, mask=oo_mask)
    nf_raw = noise_floor(t_mjd, mag)
    med_sig = float(np.median(sig))
    logger.info(
        "noise floor OOE=%.5f mag unmasked=%.5f median catalogue sig=%.5f",
        nf,
        nf_raw,
        med_sig,
    )
    cadence_d = float(np.median(np.diff(np.sort(t_mjd))))
    fwhm_d = g["fwhm"] * period_days
    nseg = 1 if seg is None else int(np.max(seg) + 1)
    logger.info(
        "start M0=%.6f MJD A1=%.4f A2=%.4f FWHM=%.4f phase (%.4f d) "
        "points/FWHM=%.1f cadence=%.0f s  baseline nseg=%s order=%s "
        "profile=%s harmonics=%s ocon=%s",
        g["M0"],
        g["A1"],
        g["A2"],
        g["fwhm"],
        fwhm_d,
        fwhm_d / cadence_d,
        86400.0 * cadence_d,
        nseg,
        order,
        config.profile,
        config.harmonics,
        config.ocon,
    )
    if fwhm_d / cadence_d < MIN_POINTS_PER_FWHM:
        logger.warning(
            "Fewer than %.0f points per FWHM; contacts may be exposure-smeared "
            "and D biased wide (no supersampling in this engine).",
            MIN_POINTS_PER_FWHM,
        )
    if g["A2"] < 0:
        raise ValueError(f"Folded secondary depth A2={g['A2']:.4f} mag is not an eclipse.")
    if g["A1"] < PRIMARY_A2_OVER_A1_MIN_RATIO * g["A2"]:
        logger.warning(
            "A1 is not much deeper than A2; period may be P/2. Continuing with given P."
        )

    model = EBModel(profile=config.profile, harmonics=config.harmonics, ocon=config.ocon)
    hnames = _harmonic_free_names(model)
    p0 = complete_template(
        dict(A1=g["A1"], A2=g["A2"], D1=D_from_fwhm(g["fwhm"], 1.0), G1=1.0),
        model,
    )
    free_ephem = ("M0", "P0")

    r1 = fit_global(
        t_mjd,
        mag,
        sig,
        model,
        p0,
        ["A1", "A2", "D1", "G1"],
        e0,
        free_ephem,
        seg=seg,
        order=order,
    )
    report_fit("1 locate eclipses", r1, nf)

    r2, rows = multistart_global(
        t_mjd,
        mag,
        sig,
        model,
        complete_template(r1.p, model),
        ["A1", "A2", "D1", "G1"] + hnames,
        r1.ephem,
        g["fwhm"],
        starts=config.gamma_starts,
        free_ephem=free_ephem,
        seg=seg,
        order=order,
    )
    for g0, chi2, d1, g1, st in rows:
        logger.info("  G0=%s chi2=%s D1=%s G1=%s %s", g0, chi2, d1, g1, st)
    if r2 is None:
        raise RuntimeError("Multi-start returned no valid (D>0, G>0) solution.")
    report_fit("2 best multi-start", r2, nf)

    r3 = fit_global(
        t_mjd,
        mag,
        sig,
        model,
        complete_template(r2.p, model),
        ["A1", "A2", "D1", "G1", "C1"] + hnames,
        r2.ephem,
        free_ephem,
        seg=seg,
        order=order,
    )
    report_fit("3 add C1", r3, nf)
    d_rel = r3.err["D1"] / abs(r3.p["D1"])
    g_rel = r3.err["G1"] / abs(r3.p["G1"])
    c1_weak = abs(r3.p["C1"]) < 3.0 * r3.err["C1"]
    if c1_weak or d_rel > 0.10 or g_rel > 0.10:
        logger.info("Fix C1=C2=0 (weak C1 or large D/G errors).")
        p_fix = complete_template(r2.p, model)
        p_fix["C1"] = 0.0
        p_fix["C2"] = 0.0
        r = fit_global(
            t_mjd,
            mag,
            sig,
            model,
            p_fix,
            ["A1", "A2", "D1", "G1"] + hnames,
            r2.ephem,
            free_ephem,
            seg=seg,
            order=order,
        )
        report_fit("3b C1=C2=0", r, nf)
        free_shape = ["A1", "A2", "D1", "G1", "D2", "G2"] + hnames
    else:
        r = r3
        free_shape = ["A1", "A2", "D1", "G1", "C1", "D2", "G2", "C2"] + hnames

    r4 = fit_global(
        t_mjd,
        mag,
        sig,
        model,
        complete_template(r.p, model),
        free_shape,
        r.ephem,
        free_ephem,
        seg=seg,
        order=order,
    )
    report_fit("4 separate eclipse shapes", r4, nf)
    if r.chi2 > 0 and (r.chi2 - r4.chi2) / r.chi2 < config.separate_shape_chi2_frac:
        logger.info(
            "Keeping shared eclipse shape (< %.0f%% chi2 drop).",
            100 * config.separate_shape_chi2_frac,
        )
    else:
        r = r4
        logger.info("Keeping separate D2, G2.")

    res, th = residuals(t_mjd, mag, sig, model, r, seg=seg, order=order)
    oo = out_of_eclipse_phase_mask(th)
    mad = (
        1.4826 * np.median(np.abs(res[oo] - np.median(res[oo])))
        if np.any(oo)
        else float(np.median(np.abs(res)))
    )
    keep = np.ones(len(t_mjd), dtype=bool)
    keep[oo] = np.abs(res[oo]) < config.clip_nsig * max(mad, 1e-8)
    n_clip = int((~keep).sum())
    logger.info(
        "%s-sigma clip out of eclipse: dropped %s points mad=%.2f mmag",
        config.clip_nsig,
        n_clip,
        1e3 * mad,
    )
    t_work, mag_work, sig_work = t_mjd, mag, sig
    seg_work = seg
    if n_clip:
        free_tpl = [n for n in r.names if n not in ("M0", "P0", "Pdot")]
        seg_clip = None if seg is None else seg[keep]
        r5 = fit_global(
            t_mjd[keep],
            mag[keep],
            sig[keep],
            model,
            complete_template(r.p, model),
            free_tpl,
            r.ephem,
            free_ephem,
            seg=seg_clip,
            order=order,
        )
        report_fit("5 after clip", r5, nf)
        if r5.chi2 < r.chi2:
            r = r5
            t_work, mag_work, sig_work = t_mjd[keep], mag[keep], sig[keep]
            seg_work = seg_clip

    res, th = residuals(t_work, mag_work, sig_work, model, r, seg=seg_work, order=order)
    b = binned_residuals(res, th)
    logger.info(
        "single-component binned primary (mmag): %s",
        np.array2string(b["primary"], precision=2),
    )
    logger.info(
        "single-component binned secondary (mmag): %s",
        np.array2string(b["secondary"], precision=2),
    )
    oo_mask = out_of_eclipse_mask(t_work, r.ephem, g["fwhm"])
    nf = noise_floor(t_work, mag_work, mask=oo_mask)
    ratio = r.rms / nf
    logger.info("single-component rms/noise=%.2f G1=%.3f", ratio, r.p["G1"])
    r_single = r

    if config.allow_two_component and ratio > config.rms_noise_two_comp_threshold:
        logger.info(
            "Two-component primary (extension, not Mikulasek 2015); rms/noise > %.1f",
            config.rms_noise_two_comp_threshold,
        )
        r_two, tc_rows = refine_two_component(
            t_work,
            mag_work,
            sig_work,
            model,
            r_single,
            seg=seg_work,
            order=order,
            eclipses=TWO_COMP_ECLIPSES,
        )
        for wf, g2, chi2, rms_mmag, st in tc_rows:
            logger.info(
                "  start wf=%s Gb=%s chi2=%s rms=%s mmag %s",
                wf,
                g2,
                chi2,
                rms_mmag,
                st,
            )
        if r_two is None:
            logger.info("No valid two-component start; keeping single-component.")
        else:
            report_fit("6 two-component primary", r_two, nf)
            ok_chi = [row[2] for row in tc_rows if row[4] == "ok" and np.isfinite(row[2])]
            n_agree = int(
                np.sum(np.abs(np.asarray(ok_chi) - r_two.chi2) / r_two.chi2 < 0.01)
            )
            rms_gain = 1.0 - r_two.rms / r_single.rms
            keys = ("A1", "D1", "G1", "A1b", "D1b", "G1b")
            rel = {k: r_two.err[k] / abs(r_two.p[k]) for k in keys if k in r_two.err}
            deg = two_component_degenerate(r_two.p, 1, r_single.p["A1"])
            pos = all(r_two.p[k] > 0 for k in ("D1", "G1", "D1b", "G1b"))
            rel_ok = all(v < MAX_TWO_COMP_REL_ERR for v in rel.values()) if rel else False
            check123 = (
                rms_gain >= MIN_RMS_GAIN_FRAC
                and n_agree >= MIN_AGREEING_TWO_COMP_STARTS
                and pos
                and rel_ok
                and not deg
            )
            timing_ok, timing_msg = _two_component_timing_ok(
                t_work, mag_work, sig_work, model, r_single, r_two
            )
            logger.info("  %s", timing_msg)
            res2, th2 = residuals(
                t_work, mag_work, sig_work, model, r_two, seg=seg_work, order=order
            )
            b2 = binned_residuals(res2, th2)
            logger.info(
                "  binned primary [two-comp] (mmag): %s",
                np.array2string(b2["primary"], precision=2),
            )
            logger.info(
                "  rms gain=%.1f%% agree_starts=%s check123=%s timing_ok=%s",
                100 * rms_gain,
                n_agree,
                check123,
                timing_ok,
            )
            if check123:
                r = r_two
                logger.info("Two-component adopted for template.")
                if not timing_ok:
                    logger.warning(
                        "Shape checks passed but virtual-minima timings disagree; "
                        "see check4 line above."
                    )
            else:
                logger.info("Two-component rejected; keeping single-component.")
    elif not config.allow_two_component:
        logger.info("Skipping two-component: not allowed in this star's FitConfig.")
    else:
        logger.info(
            "Skipping two-component: rms/noise %.2f <= %.1f.",
            ratio,
            config.rms_noise_two_comp_threshold,
        )

    r_catalogue = r
    if config.eclipse_weight > 1.0:
        logger.info(
            "Eclipse-weighted shape refit: freeze M0, P0 and harmonics; "
            "weight=%g (chi2 is not catalogue goodness-of-fit).",
            config.eclipse_weight,
        )
        sig_w = eclipse_reweighted_sigma(
            t_work,
            sig_work,
            r.ephem,
            config.eclipse_weight,
            config.eclipse_phase_half,
        )
        free_ecl = _shape_free_names(r, model)
        if not free_ecl:
            raise RuntimeError("No eclipse parameters left to free in the weighted refit.")
        r_w = fit_global(
            t_work,
            mag_work,
            sig_w,
            model,
            complete_template(r.p, model),
            free_ecl,
            r.ephem,
            (),
            seg=seg_work,
            order=order,
        )
        report_fit("weighted eclipse shape (H and ephemeris frozen)", r_w, nf)
        res_w, th_w = residuals(
            t_work, mag_work, sig_work, model, r_w, seg=seg_work, order=order
        )
        b_w = binned_residuals(res_w, th_w)
        logger.info(
            "unweighted binned primary after weight (mmag): %s",
            np.array2string(b_w["primary"], precision=2),
        )
        logger.info(
            "unweighted binned secondary after weight (mmag): %s",
            np.array2string(b_w["secondary"], precision=2),
        )
        r = r_w

    return FitPipelineResult(
        model=model,
        adopted=r,
        single_component=r_catalogue if config.eclipse_weight > 1.0 else r_single,
        seg=seg_work,
        order=order,
        t_mjd=t_work,
        mag=mag_work,
        sig=sig_work,
        noise_floor=nf,
        initial_guess=g,
    )
