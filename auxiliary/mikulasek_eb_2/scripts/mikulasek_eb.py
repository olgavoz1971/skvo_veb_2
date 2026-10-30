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
Units (the numerical core uses plain floats on purpose; the boundary adds the units)
    times t, M0, P0 and all timing errors: days (the pipeline passes MJD; the ToM files are
    written in JD, TDB); phase, D, theta: cycles; Gamma, C, Pdot: dimensionless; A, H, S1,
    y, sigma, rms: magnitudes.  astropy.units is applied where the data enter (volightcurve
    reader, time scale conversions), not inside the least-squares residual functions.

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
    """Compute 1 - (1 - u)^G without cancellation for tiny u.

    Args:
        u (ndarray): Values in [0, 1].
        G (float): Exponent (Gamma, dimensionless).

    Returns:
        ndarray: 1 - (1 - u)^G.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        return -np.expm1(G * np.log1p(-u))

def prof1(phi, D, G, C=0.0):          # Eq. (13) / Table 2 #1
    """Normalised eclipse profile: Eq. (13) / Table 2 profile 1 with curvature term C.

    Args:
        phi (ndarray): Phase offset from the eclipse centre (cycles).
        D (float): Width parameter (cycles).
        G (float): Kurtosis Gamma (dimensionless).
        C (float): Curvature of the bottom (dimensionless).

    Returns:
        ndarray: Profile, 1 at the centre and 0 far from it (multiply by A in mag).
    """
    x = np.clip(phi / D, -60.0, 60.0)
    return (1.0 + C * x**2) * _one_minus_pow(np.exp(1.0 - np.cosh(x)), G)

def prof2(phi, D, G, C=0.0):          # Table 2 #2 (no C)
    """Normalised eclipse profile: Table 2 profile 2 (the curvature C is ignored).

    Args:
        phi (ndarray): Phase offset from the eclipse centre (cycles).
        D (float): Width parameter (cycles).
        G (float): Kurtosis Gamma (dimensionless).
        C (float): Curvature of the bottom (dimensionless).

    Returns:
        ndarray: Profile, 1 at the centre and 0 far from it (multiply by A in mag).
    """
    return prof1(phi, D, G, 0.0)

def prof3(phi, D, G, C=0.0):          # Table 2 #3
    """Normalised eclipse profile: Table 2 profile 3 (Gaussian-based; the curvature C is ignored).

    Args:
        phi (ndarray): Phase offset from the eclipse centre (cycles).
        D (float): Width parameter (cycles).
        G (float): Kurtosis Gamma (dimensionless).
        C (float): Curvature of the bottom (dimensionless).

    Returns:
        ndarray: Profile, 1 at the centre and 0 far from it (multiply by A in mag).
    """
    x = np.clip(phi / D, -60.0, 60.0)
    return _one_minus_pow(np.exp(-0.5 * x**2), G)

def prof4(phi, D, G, C=0.0):          # Table 2 #4: Re[(1-|x|^G)^(3/2)]
    """Normalised eclipse profile: Table 2 profile 4, Re[(1 - |x|^G)^(3/2)] (Andronov type; C is ignored).

    Args:
        phi (ndarray): Phase offset from the eclipse centre (cycles).
        D (float): Width parameter (cycles).
        G (float): Kurtosis Gamma (dimensionless).
        C (float): Curvature of the bottom (dimensionless).

    Returns:
        ndarray: Profile, 1 at the centre and 0 far from it (multiply by A in mag).
    """
    base = 1.0 - np.abs(phi / D) ** G
    return np.where(base > 0.0, np.abs(base) ** 1.5, 0.0)

PROFILES = {1: prof1, 2: prof2, 3: prof3, 4: prof4}

# ------------------------------------------------------------------ model
class EBModel:
    """Phenomenological eclipsing-binary light curve in magnitudes (Mikulasek 2015).

    F(theta) = sum_k A_k prof(phi_k) + sum H_k cos(2 pi k theta) [+ S1 sin(2 pi theta)].

    Parameter dict keys: A1, A2 (mag), D1, G1, C1 (D2, G2, C2 optional; if absent they
    equal D1, G1, C1), H<k> (mag) for k in ``harmonics``, S1 (mag) if ``ocon``.

    Optional second component per eclipse k (EXTENSION, not in the paper): if the keys
    A<k>b, D<k>b, G<k>b are present, A<k>b * profile(phi; D<k>b, G<k>b, C=0) is added
    to eclipse k. This lets a flat bottom and steep walls coexist; amplitudes may be negative.

    Attributes:
        profile (int): Table 2 profile number (1 to 4).
        harmonics (tuple): Orders k of the cosine terms.
        ocon (bool): Whether the O'Connell sine term S1 is included.
    """
    def __init__(self, profile=1, harmonics=(2,), ocon=False):
        """Store the model configuration.

        Args:
            profile (int): Table 2 profile number (1 to 4).
            harmonics (tuple of int): Orders of the cosine terms H_k.
            ocon (bool): Include the O'Connell sine term S1.
        """
        self.profile, self.harmonics, self.ocon = profile, tuple(harmonics), ocon

    def names(self, shared_shape=True):
        """Names of the template parameters that can be fitted.

        Args:
            shared_shape (bool): If True the two eclipses share D, G, C; otherwise D2, G2, C2
                are listed as well.

        Returns:
            list of str: Parameter names.
        """
        n = ["A1", "A2", "D1", "G1", "C1"]
        if not shared_shape:
            n += ["D2", "G2", "C2"]
        n += [f"H{k}" for k in self.harmonics]
        return n + (["S1"] if self.ocon else [])

    def __call__(self, theta, p):
        """Evaluate the model.

        Args:
            theta (ndarray): Phase (cycles), primary at integer values.
            p (dict): Parameters (A in mag, D in cycles, see class docstring).

        Returns:
            ndarray: Magnitude relative to the out-of-eclipse level.
        """
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
    """Quadratic phase function theta(t), Eq. (17).

    Args:
        t (ndarray): Times (days; MJD in the pipeline).
        M0 (float): Reference primary minimum (same time system, days).
        P0 (float): Period at M0 (days).
        Pdot (float): Dimensionless period derivative dP/dt.

    Returns:
        ndarray: Phase in cycles.
    """
    v = (np.asarray(t, float) - M0) / P0
    return v - 0.5 * Pdot * v**2

def predicted_time(E, M0, P0, Pdot=0.0):
    """Predicted time of eclipse number E from the quadratic ephemeris.

    Args:
        E (float or ndarray): Eclipse number (integer primary, n + 0.5 secondary).
        M0 (float): Reference primary minimum (days).
        P0 (float): Period at M0 (days).
        Pdot (float): Dimensionless period derivative.

    Returns:
        float or ndarray: Time of minimum (days, same system as M0).
    """
    return M0 + P0 * E + 0.5 * P0 * Pdot * E**2

# ------------------------------------------------- linear nuisance (Eq. 11)
class _Nuisance:
    """Per-segment polynomial baselines eliminated by weighted linear least squares.

    This is variable projection: the baselines never enter the nonlinear parameter vector.
    """
    def __init__(self, t, w, seg, order):
        """Build the weighted Vandermonde blocks.

        Args:
            t (ndarray): Times (days).
            w (ndarray): Weights, 1/sigma (1/mag).
            seg (ndarray or None): Segment id per point; None means one segment.
            order (int): Polynomial degree per segment (reduced if a segment is too short).
        """
        seg = np.zeros(len(t), int) if seg is None else np.asarray(seg)
        self.blocks, self.npar = [], 0
        for s in np.unique(seg):
            idx = np.where(seg == s)[0]
            tt = t[idx]; sd = tt.std()
            x = (tt - tt.mean()) / (sd if sd > 0 else 1.0)
            V = np.vander(x, min(order, len(idx) - 1) + 1, increasing=True) * w[idx, None]
            self.blocks.append((idx, V)); self.npar += V.shape[1]

    def share(self, mask):
        """Number of baseline parameters attributable to a subset of points.

        Args:
            mask (ndarray): Boolean selection of points.

        Returns:
            float: Fractional parameter count.
        """
        return sum(V.shape[1] * mask[idx].mean() for idx, V in self.blocks)

    def project(self, rw):
        """Remove the best-fit baselines from weighted residuals.

        Args:
            rw (ndarray): Weighted residuals (dimensionless).

        Returns:
            ndarray: Weighted residuals orthogonal to the baselines.
        """
        out = rw.copy()
        for idx, V in self.blocks:
            c = np.linalg.lstsq(V, rw[idx], rcond=None)[0]
            out[idx] = rw[idx] - V @ c
        return out

# ------------------------------------------------------------------ results
@dataclass
class FitResult:
    """Outcome of ``fit_global``.

    Attributes:
        p (dict): Fitted template parameters (mag, cycles).
        ephem (dict): Fitted ephemeris (M0, P0 in days, Pdot dimensionless).
        err (dict): 1-sigma errors of every fitted parameter.
        chi2, dof, rchi2 (float, int, float): Chi-square, degrees of freedom, reduced chi-square.
        rms (float): Rms residual (mag).
        names (list): Fitted parameter names in covariance order.
        cov (ndarray): Covariance matrix (rescaled by rchi2 if requested).
        success (bool): Solver success flag.
        resid (ndarray): Residuals (mag) after removing the baselines.
        nuis: Baseline bookkeeping used by ``fit_global_iterative``.
        rank_deficient (bool): True if the Jacobian is rank deficient (degenerate parameters).
    """
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
    """Outcome of ``fit_minimum``.

    Attributes:
        E (float): Eclipse number.
        T (float): Time of minimum (days).
        sigma (float): Formal 1-sigma error of T (days).
        delta (float): Shift relative to the ephemeris prediction (days).
        n (int): Number of points used.
        rchi2 (float): Reduced chi-square of the event fit.
        scales (dict): Fitted multiplicative shape scales (A, D, G), if requested.
    """
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
    """Covariance matrix from a least-squares solution.

    Args:
        sol: ``scipy.optimize.OptimizeResult`` with ``jac`` and ``cost``.
        dof (int): Degrees of freedom.
        rescale (bool): Multiply the covariance by the reduced chi-square.

    Returns:
        tuple: (cov, chi2, rchi2).
    """
    J = sol.jac
    cov = np.linalg.pinv(J.T @ J)
    chi2 = 2.0 * sol.cost
    rchi2 = chi2 / max(dof, 1)
    return (cov * rchi2 if rescale else cov), chi2, rchi2

# ------------------------------------------------------------- global fit
def fit_global(t, y, sigma, model, p0, free, ephem0, free_ephem=("M0", "P0"),
               seg=None, order=0, rescale=True):
    """Simultaneous fit of template parameters and ephemeris to all data.

    Segments ``seg`` (for example night or orbit id) each get a polynomial baseline of
    degree ``order``. With ``rescale=True`` the covariance is multiplied by the reduced
    chi-square (paper, Sect. 5.2: weights from residual scatter).

    Args:
        t (ndarray): Times (days).
        y (ndarray): Magnitudes (mag).
        sigma (ndarray): Magnitude errors (mag).
        model (EBModel): Model to fit.
        p0 (dict): Starting template parameters.
        free (list of str): Names of the template parameters to fit.
        ephem0 (dict): Starting ephemeris (M0, P0 in days; optional Pdot).
        free_ephem (tuple of str): Subset of M0, P0, Pdot to fit.
        seg (ndarray or None): Segment id per point.
        order (int): Baseline polynomial degree per segment.
        rescale (bool): Rescale the covariance by the reduced chi-square.

    Returns:
        FitResult: Fitted parameters, errors and diagnostics.

    Raises:
        FitDidNotConverge: If the solver does not converge.
    """
    t, y, sigma = (np.asarray(a, float) for a in (t, y, sigma))
    w = 1.0 / sigma
    nui = _Nuisance(t, w, seg, order)
    free, fe = list(free), list(free_ephem)
    names = free + fe

    def unpack(x):
        """Split the solver vector into template and ephemeris dicts.

        Args:
            x (ndarray): Parameter vector in the order ``free + free_ephem``.

        Returns:
            tuple: (template dict, ephemeris dict).
        """
        p, e = dict(p0), dict(ephem0)
        for n, v in zip(names, x):
            (p if n in free else e)[n] = v
        return p, e

    def resid(x):
        """Weighted, baseline-projected residuals for the solver.

        Args:
            x (ndarray): Parameter vector.

        Returns:
            ndarray: Residuals (dimensionless).
        """
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

    Model: y = poly_order(t) + F(theta_c(t) - delta/P_loc), Eq. (9). Free: the shift delta
    and optional multiplicative scales of this eclipse's depth 'A', width 'D', kurtosis 'G'
    (use for local-window fits when the shape varies).

    Args:
        t (ndarray): Times (days).
        y (ndarray): Magnitudes (mag).
        sigma (ndarray): Magnitude errors (mag).
        model (EBModel): Template model.
        p (dict): Template parameters held fixed (except the scales).
        ephem (dict): Ephemeris (M0, P0 in days; optional Pdot).
        E (float): Eclipse number.
        window (float): Half-width of the fitted phase window (cycles, at most 0.25).
        order (int): Per-event baseline polynomial degree.
        free (tuple of str): Shape scales to fit, subset of "A", "D", "G".
        scan (float): First scan the shift over +-scan cycles to avoid local minima (0 = off).
        rescale (bool): Rescale the covariance by the reduced chi-square.

    Returns:
        MinResult: Time of minimum with its formal error.

    Raises:
        FitDidNotConverge: If the solver does not converge.
    """
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
        """Template parameters with the fitted shape scales applied.

        Args:
            x (ndarray): Solver vector, shift first then the scales.

        Returns:
            dict: Scaled template parameters.
        """
        q = dict(base)
        for nm, sc in zip(scales, x[1:]):
            for key in (f"{nm}{k}", f"{nm}{k}b"):
                if key in q:
                    q[key] = q[key] * sc
        return q

    def resid(x):
        """Weighted, baseline-projected residuals of the event fit.

        Args:
            x (ndarray): Solver vector.

        Returns:
            ndarray: Residuals (dimensionless).
        """
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

    Events lacking enough points, or points on both sides of the predicted centre, are
    skipped and recorded, never dropped silently. If ``wall_band`` is given an event also
    needs at least ``min_wall`` points on both walls, because partially covered events rest
    on one wall and are biased by any wall-shape mismatch (see ``eb_tuning.wall_band``).
    Call separately for each instrument or filter.

    Args:
        t (ndarray): Times (days).
        y (ndarray): Magnitudes (mag).
        sigma (ndarray): Magnitude errors (mag).
        model (EBModel): Template model.
        p (dict): Template parameters.
        ephem (dict): Ephemeris (M0, P0 in days; optional Pdot).
        window (float): Half-width of the phase window (cycles, capped at 0.25).
        order (int): Per-event baseline polynomial degree.
        free (tuple of str): Shape scales to fit per event.
        min_points (int): Minimum points in the window.
        min_each_side (int): Minimum points on each side of the centre.
        wall_band (tuple or dict or None): (lo, hi) in |phase offset|, or per eclipse
            {1: (lo, hi), 2: (lo, hi)}.
        min_wall (int): Minimum points on each wall when ``wall_band`` is given.
        rejected (list or None): Receives one dict per skipped event:
            ``{"E": float, "reason": "too_few_points" | "one_side_uncovered" |
            "walls_uncovered" | "fit_failed", "detail": str}``.
        **kw: Passed to ``fit_minimum`` (``scan``, ``rescale``).

    Returns:
        dict: Arrays E, T (days), sigma (days), delta (days), n, rchi2.
    """
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
    """Weighted polynomial ephemeris T(E).

    Args:
        T (ndarray): Times of minima (days).
        sigma (ndarray): Errors of T (days).
        E (ndarray): Eclipse numbers.
        deg (int): Polynomial degree.

    Returns:
        tuple: (coefficients in increasing order, residuals in days, weighted rms in days).
    """
    T, sigma, E = (np.asarray(a, float) for a in (T, sigma, E))
    V = np.vander(E, deg + 1, increasing=True); w = 1 / sigma
    c = np.linalg.lstsq(V * w[:, None], T * w, rcond=None)[0]
    res = T - V @ c
    return c, res, float(np.sqrt(np.sum((res * w) ** 2) / np.sum(w**2)))


# =====================================================================================
# Section 5.1 of the paper: uncertainties, correlations, simultaneous solution
# =====================================================================================
def correlation_matrix(r):
    """Correlation matrix of the fitted parameters.

    Args:
        r (FitResult): Fit result.

    Returns:
        tuple: (names, correlation matrix).
    """
    sd = np.sqrt(np.diag(r.cov))
    return list(r.names), r.cov / np.outer(sd, sd)

def strong_correlations(r, thr=0.9):
    """List parameter pairs whose correlation is strong (degeneracy warnings).

    Args:
        r (FitResult): Fit result.
        thr (float): Absolute correlation threshold.

    Returns:
        list: Tuples (name_i, name_j, correlation) with |correlation| >= thr.
    """
    names, c = correlation_matrix(r)
    return [(names[i], names[j], float(c[i, j])) for i in range(len(names))
            for j in range(i) if abs(c[i, j]) >= thr]

def curve_band(model, r, theta, rel_step=1e-5):
    """Template and its 1-sigma band from the full parameter covariance.

    Uses the general law of uncertainty propagation (paper Sect. 5.1).

    Args:
        model (EBModel): Template model.
        r (FitResult): Fit result with covariance.
        theta (ndarray): Phases (cycles).
        rel_step (float): Relative step for the numerical derivatives.

    Returns:
        tuple: (F(theta) in mag, 1-sigma uncertainty in mag).
    """
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
    """Re-express the fitted ephemeris at an epoch where M0' and P0' are uncorrelated.

    T(E) = M0' + P0' (E - Ec) + 0.5 P0' Pdot (E - Ec)^2 (paper Sect. 5.1).

    Args:
        r (FitResult): Fit result with covariance.
        t (ndarray or None): Observation times (days) defining the search range for Ec.
        Ec (float or None): Epoch to use; if None, the integer epoch of minimal
            correlation within the data range.

    Returns:
        dict: Ec, M0, M0_err, P0, P0_err (days), Pdot and the correlation before and after.
    """
    eph = r.ephem; M0, P0, Pd = eph["M0"], eph["P0"], eph.get("Pdot", 0.0)
    fe = [n for n in ("M0", "P0", "Pdot") if n in r.names]
    ii = [r.names.index(n) for n in fe]; C = r.cov[np.ix_(ii, ii)]
    def stats(E):
        """Covariance and correlation of (M0', P0') at epoch E.

        Args:
            E (float): Epoch.

        Returns:
            tuple: (2x2 covariance, correlation coefficient).
        """
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
    """Iteratively estimate unknown uncertainties from subset residuals (paper Sect. 5.2, principle 2).

    Per subset the sigmas are multiplied by sqrt(chi2_s / dof_s) until all factors are within
    ``tol`` of 1. A systematic model misfit concentrated in part of a subset is absorbed into
    that subset's sigma.

    Args:
        t (ndarray): Times (days).
        y (ndarray): Magnitudes (mag).
        sigma (ndarray): Starting magnitude errors (mag).
        model (EBModel): Model to fit.
        p0 (dict): Starting template parameters.
        free (list of str): Template parameters to fit.
        ephem0 (dict): Starting ephemeris.
        free_ephem (tuple of str): Ephemeris parameters to fit.
        seg (ndarray or None): Baseline segment id per point.
        order (int): Baseline polynomial degree.
        subsets (ndarray or None): Subset id per point; defaults to ``seg``.
        n_iter (int): Maximum iterations.
        tol (float): Convergence tolerance on the scale factors.
        rescale (bool): Rescale the covariance in the fits.

    Returns:
        tuple: (FitResult, rescaled sigma array in mag, history of factors per iteration).
    """
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
    """Outcome of ``fit_global_shifts``.

    Attributes:
        p, p_err (dict): Template parameters and errors.
        E, T, sigma, delta (ndarray): Eclipse numbers, times, joint-fit errors and shifts (days).
        cov_T (ndarray): Full covariance of the timings (days^2).
        sigma_fixed_template (ndarray): Errors of the same events with the template fixed (days).
        names, cov: Parameter names and joint covariance.
        chi2, dof, rchi2, rms: Fit statistics (rms in mag).
        n_unassigned (int): Points outside every accepted event.
    """
    p: dict; p_err: dict
    E: np.ndarray; T: np.ndarray; sigma: np.ndarray; delta: np.ndarray
    cov_T: np.ndarray                 # full covariance matrix of the timings (days^2)
    sigma_fixed_template: np.ndarray  # same events, template held fixed (virtual_minima)
    names: list; cov: np.ndarray
    chi2: float; dof: int; rchi2: float; rms: float; n_unassigned: int

def fit_global_shifts(t, y, sigma, model, p0, free, ephem, seg=None, order=1, window=0.25,
                      min_points=10, min_each_side=3, wall_band=None, min_wall=3, rescale=True):
    """Simultaneous solution of template parameters and one time shift per eclipse.

    Implements Eq. (9) with Sect. 5.2 principle 1 and Sect. 5.1 error propagation. The
    ephemeris is held fixed (shifts are O-C relative to it; M0, P0 are degenerate with a mean
    or linear shift). The timing errors are the diagonal of the joint covariance, so they
    include the template uncertainty and its correlation with the shifts; ``cov_T`` is the
    full matrix. Points outside accepted events get zero shift. Events are those accepted by
    ``virtual_minima`` with the same criteria.

    Args:
        t (ndarray): Times (days).
        y (ndarray): Magnitudes (mag).
        sigma (ndarray): Magnitude errors (mag).
        model (EBModel): Template model.
        p0 (dict): Starting template parameters.
        free (list of str): Template parameters to fit.
        ephem (dict): Fixed ephemeris (M0, P0 in days; optional Pdot).
        seg (ndarray or None): Baseline segment id per point.
        order (int): Baseline polynomial degree.
        window (float): Half-width of the phase window (cycles, capped at 0.25).
        min_points (int): Minimum points per event.
        min_each_side (int): Minimum points on each side of the centre.
        wall_band (tuple or dict or None): Wall coverage requirement, see ``virtual_minima``.
        min_wall (int): Minimum points per wall.
        rescale (bool): Rescale the covariance by the reduced chi-square.

    Returns:
        ShiftFit: Template, shifts and joint covariance.

    Raises:
        FitDidNotConverge: If the solver does not converge.
    """
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
        """Weighted, baseline-projected residuals with per-event shifts applied.

        Args:
            x (ndarray): Template parameters followed by the shifts (days).

        Returns:
            ndarray: Residuals (dimensionless).
        """
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
