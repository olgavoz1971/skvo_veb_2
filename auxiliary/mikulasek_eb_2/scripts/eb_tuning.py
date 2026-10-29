"""eb_tuning.py -- helpers for tuning mikulasek_eb fits (starting values, multi-start,
exact residuals, window scan, timing clean-up).  All times relative (t = BJD - T_ref),
y in magnitudes, sigma in magnitudes."""
import numpy as np
from mikulasek_eb import (EBModel, PROFILES, phase, fit_global, virtual_minima,
                          fit_ephemeris, _Nuisance)

def noise_floor(t, y, maxgap=None, mask=None):
    """Robust white-noise sigma [mag] from consecutive-point differences.
    mask: boolean array of usable points (use out_of_eclipse_mask: steep ingress/egress
    otherwise inflates the estimate, by ~30% in my test)."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    o = np.argsort(t); t, y = t[o], y[o]
    m = np.ones(len(t), bool) if mask is None else np.asarray(mask)[o]
    maxgap = 1.5*np.median(np.diff(t)) if maxgap is None else maxgap
    ok = (np.diff(t) < maxgap) & m[1:] & m[:-1]
    d = np.diff(y)[ok]
    return float(1.4826*np.median(np.abs(d - np.median(d)))/np.sqrt(2))

def out_of_eclipse_mask(t, ephem, fwhm, nfwhm=1.0):
    """True where the point is farther than nfwhm*FWHM (phase) from both eclipse centres."""
    ph = phase(t, ephem["M0"], ephem["P0"], ephem.get("Pdot", 0.0))
    d = np.abs(ph - np.round(2*ph)/2)
    return d > nfwhm*fwhm

def D_from_fwhm(fwhm, G):
    """Profile 1 with C=0: FWHM = 2 D arccosh(1 - ln(1 - 2^(-1/G)))."""
    return fwhm/(2*np.arccosh(1 - np.log(1 - 2**(-1/G))))

def initial_guess(t, mag, P, nb=200):
    """M0 (near mid-data), A1, A2, FWHM of primary [phase units] from the folded curve."""
    t = np.asarray(t); t0 = t[0]; ph = ((t - t0)/P) % 1
    b = np.minimum((ph*nb).astype(int), nb-1)
    c = np.array([np.median(mag[b == i]) if np.any(b == i) else np.nan for i in range(nb)])
    c = np.where(np.isnan(c), np.nanmedian(c), c)
    ip = int(np.argmax(c)); lev = np.median(c); A1 = c[ip]-lev; A2 = c[(ip+nb//2) % nb]-lev
    n = 1
    while n < nb//2 and c[(ip-n) % nb] > lev+A1/2: n += 1
    m = 1
    while m < nb//2 and c[(ip+m) % nb] > lev+A1/2: m += 1
    M0 = t0 + (ip+0.5)/nb*P; M0 += P*round((t.mean()-M0)/P)
    return dict(M0=M0, A1=float(A1), A2=float(A2), fwhm=(n+m-1)/nb)

def multistart_global(t, mag, sig, model, p0, free, e0, fwhm, starts=(0.5, 1, 2, 4, 8),
                      free_ephem=("M0", "P0"), seg=None, order=1):
    """Refit from several Gamma starts (D set consistently from the FWHM).
    The default includes Gamma < 1 (0.5): three of the four stars in Mikulasek (2015) Table 1
    have 0.62 <= Gamma <= 0.82.
    Returns (best FitResult, table).  Rejects non-finite or D<=0 / G<=0 solutions."""
    best, rows = None, []
    for G0 in starts:
        p = dict(p0, G1=G0, D1=D_from_fwhm(fwhm, G0))
        try:
            r = fit_global(t, mag, sig, model, p, free, e0, free_ephem, seg=seg, order=order)
        except Exception as ex:
            rows.append((G0, np.nan, np.nan, np.nan, str(ex)[:40])); continue
        ok = np.isfinite(r.chi2) and r.p["D1"] > 0 and r.p["G1"] > 0
        rows.append((G0, r.chi2, r.p["D1"], r.p["G1"], "ok" if ok else "rejected"))
        if ok and (best is None or r.chi2 < best.chi2): best = r
    return best, rows

def residuals(t, mag, sig, model, r, seg=None, order=1):
    """Exact residuals [mag] after removing the per-segment polynomial baselines."""
    t, mag, sig = (np.asarray(a, float) for a in (t, mag, sig)); w = 1/sig
    th = phase(t, r.ephem["M0"], r.ephem["P0"], r.ephem.get("Pdot", 0.0))
    return _Nuisance(t, w, seg, order).project(w*(mag - model(th, r.p)))/w, th

def binned_residuals(res, th, half=0.12, step=0.02):
    """Mean residual [mmag] in phase bins around eclipse 1 and 2 -> dict of arrays."""
    ph = th % 1; out = {}
    edges = np.arange(-half, half+1e-9, step)
    for name, c in (("primary", 0.0), ("secondary", 0.5)):
        d = (ph - c + 0.5) % 1 - 0.5
        out[name] = np.array([1e3*res[(d >= a) & (d < a+step)].mean() if np.any((d >= a) & (d < a+step)) else np.nan
                              for a in edges[:-1]])
    out["edges"] = edges
    return out

def clip_timings(vm, deg=1, nsig=4.0, max_iter=5):
    """Boolean mask of timings kept after iterative clipping about a polynomial ephemeris."""
    keep = np.ones(len(vm["T"]), bool)
    for _ in range(max_iter):
        c, _, _ = fit_ephemeris(vm["T"][keep], vm["sigma"][keep], vm["E"][keep], deg)
        allres = vm["T"] - np.polyval(c[::-1], vm["E"])
        mad = 1.4826*np.median(np.abs(allres[keep] - np.median(allres[keep])))
        new = np.abs(allres) < nsig*np.maximum(mad, vm["sigma"])
        if np.array_equal(new, keep): break
        keep = new
    return keep

def window_scan(t, mag, sig, model, r, windows=(0.25, 0.15, 0.10, 0.06), order=1, deg=1,
                free=(), max_sigma_factor=5.0, wall_band=None, min_wall=3):
    """Timings for several windows; prints N, median sigma, O-C rms (s), std(z).
    Choose the window with small O-C rms AND std(z) ~ 1, not the smallest formal sigma.
    If wall_band is given, every window is run twice: all events, and only events with both
    walls covered ("walls"); a big difference means partial events are biased."""
    variants = [("all", None)] + ([("walls", wall_band)] if wall_band is not None else [])
    rows, out = [], {}
    for lab, wb in variants:
        for w in windows:
            vm = virtual_minima(t, mag, sig, model, r.p, r.ephem, window=w, order=order, free=free,
                                wall_band=wb, min_wall=min_wall)
            good = vm["sigma"] < max_sigma_factor*np.median(vm["sigma"])
            vm = {k: v[good] for k, v in vm.items()}
            keep = clip_timings(vm, deg)
            v = {k: x[keep] for k, x in vm.items()}
            _, res, _ = fit_ephemeris(v["T"], v["sigma"], v["E"], deg)
            rows.append((lab, w, len(v["T"]), 86400*np.median(v["sigma"]), 86400*res.std(), (res/v["sigma"]).std()))
            out[(lab, w)] = v
    print("events  window  N   med.sigma[s]  O-C rms[s]  std(z)")
    for lab, w, n, sg, rr, z in rows: print(f"{lab:6s} {w:6.2f} {n:3d} {sg:12.1f} {rr:11.1f} {z:7.2f}")
    return out, rows

def wall_band(model, p, frac=(0.9, 0.1)):
    """Phase band of the eclipse walls: |phase offset| between where the eclipse profile has
    fallen to frac[0] and to frac[1] of its central value.  Returns {1: (lo, hi), 2: (lo, hi)}
    for use as virtual_minima(..., wall_band=...)."""
    out = {}
    g = np.linspace(0.0, 0.3, 6001)
    for k, c in ((1, 0.0), (2, 0.5)):
        q = dict(p); other = 2 if k == 1 else 1
        for key in list(q):
            if key.startswith("H") or key == "S1":
                q[key] = 0.0
        q[f"A{other}"] = 0.0
        if f"A{other}b" in q: q[f"A{other}b"] = 0.0
        F = model(c + g, q); F = F/F[0]
        i_lo = int(np.argmax(F < frac[0])); i_hi = int(np.argmax(F < frac[1])) if np.any(F < frac[1]) else len(g)-1
        out[k] = (float(g[i_lo]), float(g[i_hi]))
    return out

def refine_two_component(t, mag, sig, model, r, seg=None, order=1, eclipses=(1,),
                         frac=0.3, widths=(0.5, 1.5), gammas=(0.7, 6.0)):
    """EXTENSION (not in the paper): add a second profile component to the chosen eclipses,
    starting from single-component fit r.  Tries a small grid of starts (width factor x Gamma)
    for the new component and returns (best FitResult or None, rows).  Judge the result by
    rms/noise, error sizes and by timing stability (see SKILL.md), not by chi2 alone."""
    free_base = [n for n in r.names if n in r.p]
    free_eph = [n for n in r.names if n not in r.p]
    rows, best = [], None
    for wf in widths:
        for G2 in gammas:
            p = dict(r.p); newfree = []
            for k in eclipses:
                Dk = p.get(f"D{k}", p["D1"]); Gk = p.get(f"G{k}", p["G1"])
                for nm, v in ((f"D{k}", Dk), (f"G{k}", Gk)):
                    p.setdefault(nm, v)                      # make shape of this eclipse explicit
                Ak = p[f"A{k}"]
                p[f"A{k}"] = (1-frac)*Ak; p[f"A{k}b"] = frac*Ak
                p[f"D{k}b"] = wf*p[f"D{k}"]; p[f"G{k}b"] = G2
                newfree += [f"D{k}", f"G{k}", f"A{k}b", f"D{k}b", f"G{k}b"]
            free = list(dict.fromkeys(free_base + newfree))
            try:
                rr = fit_global(t, mag, sig, model, p, free, r.ephem, free_eph, seg=seg, order=order)
            except Exception as ex:
                rows.append((wf, G2, np.nan, np.nan, "error")); continue
            ok = (np.isfinite(rr.chi2) and all(rr.p[f"D{k}"] > 0 and rr.p[f"D{k}b"] > 0 and
                  rr.p[f"G{k}"] > 0 and rr.p[f"G{k}b"] > 0 for k in eclipses))
            rows.append((wf, G2, rr.chi2, 1e3*rr.rms, "ok" if ok else "rejected"))
            if ok and (best is None or rr.chi2 < best.chi2): best = rr
    return best, rows


def oc_diagnostics(v, deg=1, verbose=True):
    """What is behind the O-C scatter?  v = dict with E, T, sigma (e.g. one entry of window_scan).
    Reports rms of primary/secondary residuals, the excess over the formal sigma, the secondary-minus-
    primary offset (with s.e.), the correlation of each primary with the next secondary
    (negative = anticorrelated, the classic starspot signature), and lag-1 autocorrelation along E.
    sigma_extra [d] = extra white scatter to add in quadrature to the formal sigma."""
    E, T, s = (np.asarray(v[k], float) for k in ("E", "T", "sigma"))
    o = np.argsort(E); E, T, s = E[o], T[o], s[o]
    _, res, _ = fit_ephemeris(T, s, E, deg)
    k2 = np.round(2*E).astype(int); prim = (k2 % 2 == 0)
    rp, rs = res[prim], res[~prim]
    resc = res - np.where(prim, rp.mean(), rs.mean())      # remove the primary/secondary offset first
    out = dict(n_primary=int(prim.sum()), n_secondary=int((~prim).sum()),
               rms_primary=float(rp.std()), rms_secondary=float(rs.std()),
               median_sigma=float(np.median(s)),
               sigma_extra=float(np.sqrt(max(0.0, resc.var() - np.median(s)**2))))
    out["offset_sec_minus_prim"] = float(rs.mean() - rp.mean())
    out["offset_se"] = float(np.sqrt(rp.var(ddof=1)/len(rp) + rs.var(ddof=1)/len(rs)))
    d = dict(zip(k2, res))
    pr = [(d[k], d[k+1]) for k in sorted(d) if k % 2 == 0 and (k+1) in d]
    if len(pr) >= 5:
        a = np.array(pr); a = a - a.mean(axis=0)
        out["pair_corr"] = float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]); out["n_pairs"] = len(pr)
        out["rms_pair_mean"] = float(((a[:, 0] + a[:, 1])/2).std()); out["rms_pair_single"] = float(np.sqrt((a**2).mean()))
    ac = []
    for m in (prim, ~prim):                                  # lag-1 along consecutive eclipses of one kind
        x = resc[m] - resc[m].mean()
        if len(x) > 4: ac.append(np.sum(x[1:]*x[:-1])/np.sum(x**2))
    out["lag1_autocorr"] = float(np.mean(ac)) if ac else float("nan")
    if verbose:
        f = lambda x: 86400*x
        print(f"O-C rms [s]: primary {f(out['rms_primary']):.1f} (N={out['n_primary']}), secondary {f(out['rms_secondary']):.1f} (N={out['n_secondary']}); "
              f"median formal sigma {f(out['median_sigma']):.1f}; extra white scatter {f(out['sigma_extra']):.1f}")
        print(f"secondary - primary offset: {f(out['offset_sec_minus_prim']):+.1f} +- {f(out['offset_se']):.1f} s")
        if "pair_corr" in out:
            print(f"primary vs next-secondary O-C correlation r = {out['pair_corr']:+.2f} (N={out['n_pairs']}); "
                  f"rms of pair means {f(out['rms_pair_mean']):.1f} s vs single {f(out['rms_pair_single']):.1f} s;  lag-1 autocorr {out['lag1_autocorr']:+.2f}")
    return out
