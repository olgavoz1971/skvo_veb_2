"""
mikulasek_eb.py -- phenomenological light-curve model of eclipsing binaries.

Independent re-implementation from the published description (NOT the author's code):
    Mikulasek, Z. 2015, A&A 584, A8  (doi:10.1051/0004-6361/201425244)

Equations used
    Eq. (13)  eclipse profile  A (1 + C phi^2/D^2) {1 - [1 - exp(1 - cosh(phi/D))]^G}
    Eq. (15)  proximity terms  H_k cos(2 pi k theta);  O'Connell term  S1 sin(2 pi theta)
    Eq. (17)  quadratic phase function  theta = v - Pdot v^2/2, v=(t-M0)/P0 ;
              Theta(E) = M0 + P0 E + 0.5 P0 Pdot E^2
    Eq. (9)   per-interval time shifts (O-C) of a fixed template -> "virtual minima"
    Table 2   alternative eclipse profiles (1-4 implemented; 4 = Andronov-type)

Conventions
    * light curves in magnitudes; eclipse depth A > 0 means fainter
    * E integer = primary minimum, E = n + 0.5 = secondary (circular orbit assumed)
    * use times relative to a reference (t = BJD - T_ref) to avoid float64 loss,
      and put M0 near the middle of the data to decorrelate M0 and P0.
Two timing modes
    fit_minimum / virtual_minima : template fixed (optionally scaled in A, D, G),
        free shift delta [d] + per-event polynomial baseline.  window=0.25 -> whole
        phase around the event; small window (e.g. 0.05-0.1) -> local-minimum mode.
    fit_global : all template + ephemeris parameters simultaneously.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
import numpy as np
from scipy.optimize import least_squares

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ profiles
def _one_minus_pow(u, G):
    """1 - (1-u)^G, accurate for tiny u; u in [0,1]."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return -np.expm1(G * np.log1p(-u))

def prof1(phi, D, G, C=0.0):          # Eq. (13) / Table 2 #1
    x = np.clip(phi / D, -60.0, 60.0)
    return (1.0 + C * x**2) * _one_minus_pow(np.exp(1.0 - np.cosh(x)), G)

def prof2(phi, D, G, C=0.0):          # Table 2 #2 (no C)
    return prof1(phi, D, G, 0.0)

def prof3(phi, D, G, C=0.0):          # Table 2 #3
    x = np.clip(phi / D, -60.0, 60.0)
    return _one_minus_pow(np.exp(-0.5 * x**2), G)

def prof4(phi, D, G, C=0.0):          # Table 2 #4: Re[(1-|x|^G)^(3/2)]
    base = 1.0 - np.abs(phi / D) ** G
    return np.where(base > 0.0, np.abs(base) ** 1.5, 0.0)

PROFILES = {1: prof1, 2: prof2, 3: prof3, 4: prof4}

# ------------------------------------------------------------------ model
class EBModel:
    """F(theta) = sum_k A_k prof(phi_k) + sum H_k cos(2 pi k theta) [+ S1 sin(2 pi theta)].

    Parameter dict keys: A1, A2, D1, G1, C1 (D2, G2, C2 optional; if absent they
    equal D1, G1, C1), H<k> for k in `harmonics`, S1 if `ocon`.
    OPTIONAL second component per eclipse k (EXTENSION, not in the paper): if the keys
    A<k>b, D<k>b, G<k>b are present, A<k>b * profile(phi; D<k>b, G<k>b, C=0) is added
    to eclipse k.  Lets a flat bottom and steep walls coexist; amplitudes may be negative.
    """
    def __init__(self, profile=1, harmonics=(2,), ocon=False):
        self.profile, self.harmonics, self.ocon = profile, tuple(harmonics), ocon

    def names(self, shared_shape=True):
        n = ["A1", "A2", "D1", "G1", "C1"]
        if not shared_shape:
            n += ["D2", "G2", "C2"]
        n += [f"H{k}" for k in self.harmonics]
        return n + (["S1"] if self.ocon else [])

    def __call__(self, theta, p):
        theta = np.asarray(theta, float)
        prof = PROFILES[self.profile]
        F = np.zeros_like(theta)
        for k in (1, 2):
            c = 0.5 * (k - 1)
            phi = (theta - c) - np.round(theta - c)
            F += p[f"A{k}"] * prof(phi, p.get(f"D{k}", p["D1"]),
                                   p.get(f"G{k}", p["G1"]), p.get(f"C{k}", p["C1"]))
            if f"A{k}b" in p:
                F += p[f"A{k}b"] * prof(phi, p[f"D{k}b"], p[f"G{k}b"], 0.0)
        for k in self.harmonics:
            F += p[f"H{k}"] * np.cos(2 * np.pi * k * theta)
        if self.ocon:
            F += p["S1"] * np.sin(2 * np.pi * theta)
        return F

def phase(t, M0, P0, Pdot=0.0):
    v = (np.asarray(t, float) - M0) / P0
    return v - 0.5 * Pdot * v**2

def predicted_time(E, M0, P0, Pdot=0.0):
    return M0 + P0 * E + 0.5 * P0 * Pdot * E**2

# ------------------------------------------------- linear nuisance (Eq. 11)
class _Nuisance:
    """Per-segment polynomial baselines, eliminated by weighted linear LS
    (variable projection), so they never enter the nonlinear parameter vector."""
    def __init__(self, t, w, seg, order):
        seg = np.zeros(len(t), int) if seg is None else np.asarray(seg)
        self.blocks, self.npar = [], 0
        for s in np.unique(seg):
            idx = np.where(seg == s)[0]
            tt = t[idx]; sd = tt.std()
            x = (tt - tt.mean()) / (sd if sd > 0 else 1.0)
            V = np.vander(x, min(order, len(idx) - 1) + 1, increasing=True) * w[idx, None]
            self.blocks.append((idx, V)); self.npar += V.shape[1]

    def share(self, mask):
        """Number of baseline parameters attributable to the points selected by `mask`."""
        return sum(V.shape[1] * mask[idx].mean() for idx, V in self.blocks)

    def project(self, rw):
        out = rw.copy()
        for idx, V in self.blocks:
            c = np.linalg.lstsq(V, rw[idx], rcond=None)[0]
            out[idx] = rw[idx] - V @ c
        return out

# ------------------------------------------------------------------ results
@dataclass
class FitResult:
    p: dict; ephem: dict; err: dict
    chi2: float; dof: int; rchi2: float; rms: float
    names: list; cov: np.ndarray; success: bool
    resid: np.ndarray = None      # residuals [mag] after removing the baselines
    nuis: object = None           # baseline bookkeeping (used by fit_global_iterative)
    rank_deficient: bool = False  # True if the Jacobian is rank deficient (degenerate parameters)

class FitDidNotConverge(RuntimeError):
    """Raised when the Levenberg-Marquardt solver does not report convergence."""

@dataclass
class MinResult:
    E: float; T: float; sigma: float; delta: float; n: int
    rchi2: float; scales: dict = field(default_factory=dict)

def _check_solution(sol, what):
    """Fail fast on a non-converged solver result; report a rank-deficient Jacobian.

    Args:
        sol: ``scipy.optimize.OptimizeResult`` from ``least_squares``.
        what (str): Short description of the fit for the messages.

    Returns:
        bool: True if the Jacobian is rank deficient (some parameters are degenerate, so
        the pseudo-inverse covariance is not a proper covariance).

    Raises:
        FitDidNotConverge: If the solver reports no convergence.
    """
    if not sol.success:
        raise FitDidNotConverge(f"{what}: solver did not converge (status={sol.status}: {sol.message})")
    J = sol.jac
    rank = int(np.linalg.matrix_rank(J))
    deficient = rank < J.shape[1]
    if deficient:
        logger.warning("%s: Jacobian rank %d < %d parameters; covariance from pseudo-inverse "
                       "(degenerate parameters, errors unreliable)", what, rank, J.shape[1])
    return deficient

def _cov(sol, dof, rescale):
    J = sol.jac
    cov = np.linalg.pinv(J.T @ J)
    chi2 = 2.0 * sol.cost
    rchi2 = chi2 / max(dof, 1)
    return (cov * rchi2 if rescale else cov), chi2, rchi2

# ------------------------------------------------------------- global fit
def fit_global(t, y, sigma, model, p0, free, ephem0, free_ephem=("M0", "P0"),
               seg=None, order=0, rescale=True):
    """Simultaneous fit of template parameters `free` and ephemeris `free_ephem`
    (subset of M0, P0, Pdot) to all data; segments `seg` (e.g. night id) each get
    a polynomial baseline of degree `order`.  rescale=True multiplies the covariance
    by reduced chi2 (paper, Sect. 5.2: weights from residual scatter)."""
    t, y, sigma = (np.asarray(a, float) for a in (t, y, sigma))
    w = 1.0 / sigma
    nui = _Nuisance(t, w, seg, order)
    free, fe = list(free), list(free_ephem)
    names = free + fe

    def unpack(x):
        p, e = dict(p0), dict(ephem0)
        for n, v in zip(names, x):
            (p if n in free else e)[n] = v
        return p, e

    def resid(x):
        p, e = unpack(x)
        F = model(phase(t, e["M0"], e["P0"], e.get("Pdot", 0.0)), p)
        return nui.project(w * (y - F))

    x0 = [p0[n] for n in free] + [ephem0[n] for n in fe]
    sol = least_squares(resid, x0, method="lm", x_scale="jac")
    deficient = _check_solution(sol, "fit_global")
    dof = len(t) - nui.npar - len(x0)
    cov, chi2, rchi2 = _cov(sol, dof, rescale)
    p, e = unpack(sol.x)
    err = dict(zip(names, np.sqrt(np.diag(cov))))
    rms = float(np.sqrt(np.mean((sol.fun / w) ** 2)))
    return FitResult(p, e, err, chi2, dof, rchi2, rms, names, cov, sol.success,
                     resid=sol.fun / w, nuis=nui, rank_deficient=deficient)

# ------------------------------------------- single event / virtual minima
def fit_minimum(t, y, sigma, model, p, ephem, E, window=0.1, order=1,
                free=(), scan=0.1, rescale=True):
    """Time of one eclipse (number E) from points with |theta - E| < window.
    Model: y = poly_order(t) + F(theta_c(t) - delta/P_loc)   [Eq. (9)]
    Free: delta [d] and optional multiplicative scales of this eclipse's depth 'A',
    width 'D', kurtosis 'G' (use for local-window fits when the shape varies).
    scan: first scan delta over +-scan phase units to avoid local minima (0 = off)."""
    t, y, sigma = (np.asarray(a, float) for a in (t, y, sigma))
    M0, P0, Pdot = ephem["M0"], ephem["P0"], ephem.get("Pdot", 0.0)
    th = phase(t, M0, P0, Pdot)
    sel = np.abs(th - E) < window
    ts, ys, ths = t[sel], y[sel], th[sel]
    w = 1.0 / sigma[sel]
    Pl = P0 * (1.0 + Pdot * E)
    k = 1 if abs(E - round(E)) < 1e-6 else 2
    base = dict(p)
    for kk in (1, 2):
        for nm in "DGC":
            base.setdefault(f"{nm}{kk}", p[f"{nm}1"])
    scales = list(free)
    nui = _Nuisance(ts, w, None, order)

    def build(x):
        q = dict(base)
        for nm, sc in zip(scales, x[1:]):
            for key in (f"{nm}{k}", f"{nm}{k}b"):
                if key in q:
                    q[key] = q[key] * sc
        return q

    def resid(x):
        return nui.project(w * (ys - model(ths - x[0] / Pl, build(x))))

    d0 = 0.0
    if scan > 0:
        grid = np.linspace(-scan, scan, 61) * Pl
        c = [np.sum(resid(np.r_[g, np.ones(len(scales))]) ** 2) for g in grid]
        d0 = grid[int(np.argmin(c))]
    x0 = np.r_[d0, np.ones(len(scales))]
    sol = least_squares(resid, x0, method="lm", x_scale="jac")
    _check_solution(sol, f"fit_minimum E={E}")
    dof = int(sel.sum()) - nui.npar - len(x0)
    cov, chi2, rchi2 = _cov(sol, dof, rescale)
    delta = float(sol.x[0])
    return MinResult(E, predicted_time(E, M0, P0, Pdot) + delta,
                     float(np.sqrt(cov[0, 0])), delta, int(sel.sum()), rchi2,
                     dict(zip(scales, sol.x[1:])))

def virtual_minima(t, y, sigma, model, p, ephem, window=0.25, order=1, free=(),
                   min_points=10, min_each_side=3, wall_band=None, min_wall=3,
                   rejected=None, **kw):
    """Fit every eclipse covered by the data (window <= 0.25 so events never overlap).
    Events lacking points on both sides of the predicted centre are skipped.
    rejected: optional list; every skipped event is appended as a dict
    {"E": float, "reason": "too_few_points" | "one_side_uncovered" | "walls_uncovered" |
    "fit_failed", "detail": str}.  Rejections are always logged; a failed fit is logged at
    WARNING level with the exception text and is never dropped silently.
    wall_band: (lo, hi) in |phase offset|, or {1: (lo, hi), 2: (lo, hi)} per eclipse; if
    given, an event also needs >= min_wall points on BOTH walls (ingress and egress) --
    partially covered events rest on one wall and are biased by any wall-shape mismatch.
    (see eb_tuning.wall_band).
    Call separately for each instrument/filter. Returns dict of arrays."""
    window = min(window, 0.25)
    t = np.asarray(t, float)
    th = phase(t, ephem["M0"], ephem["P0"], ephem.get("Pdot", 0.0))
    En = np.round(2 * th) / 2
    near = np.abs(th - En) < window
    rows = []
    for E in np.unique(En[near]):
        d = th[near & (En == E)] - E
        reason = None
        if len(d) < min_points:
            reason = "too_few_points"
        elif (d < 0).sum() < min_each_side or (d > 0).sum() < min_each_side:
            reason = "one_side_uncovered"
        elif wall_band is not None:
            lo, hi = wall_band[1 if abs(E - round(E)) < 1e-6 else 2] if isinstance(wall_band, dict) else wall_band
            if ((d > -hi) & (d < -lo)).sum() < min_wall or ((d > lo) & (d < hi)).sum() < min_wall:
                reason = "walls_uncovered"
        if reason is not None:
            logger.debug("event E=%s rejected: %s (n=%d, before=%d, after=%d)", E, reason,
                        len(d), int((d < 0).sum()), int((d > 0).sum()))
            if rejected is not None:
                rejected.append(dict(E=float(E), reason=reason, detail=f"n={len(d)}"))
            continue
        try:
            rows.append(fit_minimum(t, y, sigma, model, p, ephem, E, window, order, free, **kw))
        except Exception as ex:
            logger.warning("event E=%s fit failed: %s: %s", E, type(ex).__name__, ex)
            if rejected is not None:
                rejected.append(dict(E=float(E), reason="fit_failed", detail=f"{type(ex).__name__}: {ex}"))
    return {k: np.array([getattr(r, k) for r in rows])
            for k in ("E", "T", "sigma", "delta", "n", "rchi2")}

# ------------------------------------------------------- O-C helper
def fit_ephemeris(T, sigma, E, deg=2):
    """Weighted polynomial ephemeris T(E); returns coefficients, residuals, weighted rms."""
    T, sigma, E = (np.asarray(a, float) for a in (T, sigma, E))
    V = np.vander(E, deg + 1, increasing=True); w = 1 / sigma
    c = np.linalg.lstsq(V * w[:, None], T * w, rcond=None)[0]
    res = T - V @ c
    return c, res, float(np.sqrt(np.sum((res * w) ** 2) / np.sum(w**2)))


# =====================================================================================
# Section 5.1 of the paper: uncertainties, correlations, simultaneous solution
# =====================================================================================
def correlation_matrix(r):
    """(names, correlation matrix) of the fitted parameters of a FitResult."""
    sd = np.sqrt(np.diag(r.cov))
    return list(r.names), r.cov / np.outer(sd, sd)

def strong_correlations(r, thr=0.9):
    """List of (name_i, name_j, corr) with |corr| >= thr (degeneracy warnings)."""
    names, c = correlation_matrix(r)
    return [(names[i], names[j], float(c[i, j])) for i in range(len(names))
            for j in range(i) if abs(c[i, j]) >= thr]

def curve_band(model, r, theta, rel_step=1e-5):
    """Template F(theta) and its 1-sigma uncertainty from the FULL parameter covariance
    (general law of uncertainty propagation, paper Sect. 5.1)."""
    theta = np.asarray(theta, float)
    pn = [n for n in r.names if n in r.p]; ii = [r.names.index(n) for n in pn]
    C = r.cov[np.ix_(ii, ii)]
    J = np.empty((len(theta), len(pn)))
    for k, n in enumerate(pn):
        h = rel_step * max(abs(r.p[n]), 1e-3)
        pp, pm = dict(r.p), dict(r.p); pp[n] += h; pm[n] -= h
        J[:, k] = (model(theta, pp) - model(theta, pm)) / (2*h)
    var = np.einsum("ij,jk,ik->i", J, C, J)
    return model(theta, r.p), np.sqrt(np.maximum(var, 0.0))

def ephemeris_at_epoch(r, t=None, Ec=None):
    """Re-express the fitted ephemeris at a reference epoch Ec chosen to make M0' and P0'
    uncorrelated (paper Sect. 5.1: 'orthogonalize at least in the ephemeris parameters').
    T(E) = M0' + P0' (E-Ec) + 0.5 P0' Pdot (E-Ec)^2.  Ec = integer epoch of minimal |corr|
    within the data range (from t) if not given."""
    eph = r.ephem; M0, P0, Pd = eph["M0"], eph["P0"], eph.get("Pdot", 0.0)
    fe = [n for n in ("M0", "P0", "Pdot") if n in r.names]
    ii = [r.names.index(n) for n in fe]; C = r.cov[np.ix_(ii, ii)]
    def stats(E):
        dM = {"M0": 1.0, "P0": E + 0.5*Pd*E**2, "Pdot": 0.5*P0*E**2}
        dP = {"M0": 0.0, "P0": 1.0 + Pd*E, "Pdot": P0*E}
        J = np.array([[dM[n] for n in fe], [dP[n] for n in fe]]); S = J @ C @ J.T
        return S, S[0, 1] / np.sqrt(S[0, 0]*S[1, 1])
    if Ec is None:
        if t is not None:
            E = (np.asarray(t, float) - M0) / P0; grid = np.arange(np.floor(E.min()), np.ceil(E.max()) + 1)
        else:
            grid = np.arange(-1000.0, 1001.0)
        Ec = float(grid[int(np.argmin([abs(stats(e)[1]) for e in grid]))])
    S, corr = stats(Ec)
    return dict(Ec=Ec, M0=M0 + P0*Ec + 0.5*P0*Pd*Ec**2, M0_err=float(np.sqrt(S[0, 0])),
                P0=P0*(1 + Pd*Ec), P0_err=float(np.sqrt(S[1, 1])), Pdot=Pd,
                corr_M0_P0_before=float(stats(0.0)[1]), corr_M0_P0_after=float(corr))

def fit_global_iterative(t, y, sigma, model, p0, free, ephem0, free_ephem=("M0", "P0"), seg=None,
                         order=0, subsets=None, n_iter=8, tol=0.01, rescale=False):
    """Paper Sect. 5.2 principle 2: if the uncertainties are not known, estimate them iteratively
    from the scatter of the residuals of appropriate data subsets (default: the baseline segments).
    Per subset s the sigmas are multiplied by sqrt(chi2_s / dof_s) until all factors are within tol
    of 1.  Returns (FitResult, sigma array, history).  Beware: a systematic model misfit that is
    concentrated in a part of a subset is absorbed into that subset's sigma."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    sig = np.asarray(sigma, float).copy()
    sub = np.zeros(len(t), int) if (subsets is None and seg is None) else np.asarray(seg if subsets is None else subsets)
    p, e, hist = dict(p0), dict(ephem0), []
    for it in range(n_iter):
        r = fit_global(t, y, sig, model, p, free, e, free_ephem, seg=seg, order=order, rescale=rescale)
        chi = (r.resid / sig)**2; fac = {}
        for u in np.unique(sub):
            m = sub == u; dof = max(m.sum() - r.nuis.share(m), 1.0)
            fac[u] = float(np.sqrt(chi[m].sum() / dof))
        f_pt = np.array([fac[u] for u in sub]); hist.append(fac)
        sig = sig * f_pt; p, e = r.p, r.ephem
        if max(abs(f - 1) for f in fac.values()) < tol: break
    r = fit_global(t, y, sig, model, p, free, e, free_ephem, seg=seg, order=order, rescale=rescale)
    return r, sig, hist

@dataclass
class ShiftFit:
    p: dict; p_err: dict
    E: np.ndarray; T: np.ndarray; sigma: np.ndarray; delta: np.ndarray
    cov_T: np.ndarray                 # full covariance matrix of the timings (days^2)
    sigma_fixed_template: np.ndarray  # same events, template held fixed (virtual_minima)
    names: list; cov: np.ndarray
    chi2: float; dof: int; rchi2: float; rms: float; n_unassigned: int

def fit_global_shifts(t, y, sigma, model, p0, free, ephem, seg=None, order=1, window=0.25,
                      min_points=10, min_each_side=3, wall_band=None, min_wall=3, rescale=True):
    """SIMULTANEOUS solution of the template parameters `free` and one time shift per eclipse
    (paper Eq. 9 + Sect. 5.2 principle 1 + Sect. 5.1 error propagation).  The ephemeris is held
    fixed (shifts are O-C relative to it; M0, P0 are degenerate with a mean/linear shift).
    The timing uncertainties are the diagonal of the joint covariance, so they include the
    template uncertainty and its correlation with the shifts; `cov_T` is the full matrix.
    Points not belonging to any accepted event (outside `window`, or in rejected events) get
    zero shift.  Events are those accepted by virtual_minima with the same criteria."""
    t, y, sigma = (np.asarray(a, float) for a in (t, y, sigma))
    w = 1.0 / sigma
    M0, P0, Pd = ephem["M0"], ephem["P0"], ephem.get("Pdot", 0.0)
    th_c = phase(t, M0, P0, Pd); En = np.round(2*th_c) / 2
    window = min(window, 0.25)
    vm = virtual_minima(t, y, sigma, model, p0, ephem, window=window, order=order,
                        min_points=min_points, min_each_side=min_each_side,
                        wall_band=wall_band, min_wall=min_wall)
    ev = vm["E"]; K = len(ev)
    pos = {float(e): i for i, e in enumerate(ev)}
    idx = np.array([pos.get(float(e), -1) if abs(th - e) < window else -1 for th, e in zip(th_c, En)])
    asg = idx >= 0; Pl = P0 * (1.0 + Pd * En)
    nui = _Nuisance(t, w, seg, order)
    free = list(free); nf = len(free)

    def resid(x):
        p = dict(p0)
        for n, v in zip(free, x[:nf]): p[n] = v
        th = th_c.copy(); th[asg] -= x[nf:][idx[asg]] / Pl[asg]
        return nui.project(w * (y - model(th, p)))

    x0 = np.r_[[p0[n] for n in free], vm["delta"]]
    sol = least_squares(resid, x0, method="lm", x_scale="jac")
    _check_solution(sol, "fit_global_shifts")
    dof = len(t) - nui.npar - len(x0)
    cov, chi2, rchi2 = _cov(sol, dof, rescale)
    p = dict(p0)
    for n, v in zip(free, sol.x[:nf]): p[n] = v
    d = sol.x[nf:]; cT = cov[nf:, nf:]
    T = np.array([predicted_time(e, M0, P0, Pd) for e in ev]) + d
    return ShiftFit(p, dict(zip(free, np.sqrt(np.diag(cov)[:nf]))), ev, T, np.sqrt(np.diag(cT)), d, cT,
                    vm["sigma"], list(free) + [f"d[{e}]" for e in ev], cov, chi2, dof, rchi2,
                    float(np.sqrt(np.mean((sol.fun / w)**2))), int((~asg).sum()))
