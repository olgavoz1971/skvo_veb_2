"""TESS-style workflow on SYNTHETIC data (replace the block "fake input" by your own t, flux, ferr).
Run from the folder containing mikulasek_eb.py."""
import logging
import numpy as np
from mikulasek_eb import *

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

# ---- fake "TESS-like" input: 2 orbits, 2-min cadence, P = 1.2345 d ----
rng = np.random.default_rng(5)
mdl = EBModel(1, harmonics=(1, 2))
pt = dict(A1=0.40, A2=0.18, D1=0.022, G1=1.1, C1=-0.1, H1=0.004, H2=0.02)
et = dict(M0=2010.3, P0=1.2345, Pdot=0.0)
t = np.concatenate([np.arange(1999, 2012.5, 2/1440), np.arange(2013, 2026.5, 2/1440)])
mag_true = mdl(phase(t, **et), pt) + 0.003*np.sin(2*np.pi*t/9.0)       # slow trend
flux = 10**(-0.4*(mag_true + rng.normal(0, 0.003, len(t)))) * 1e5
ferr = np.full(len(t), 0.003/1.0857) * flux

# ---- 1. flux -> magnitudes ----
mag = -2.5*np.log10(flux/np.median(flux));  sig = 1.0857*ferr/flux
P = 1.2345                                   # known (approximate) period
seg = np.cumsum(np.r_[0, np.diff(t) > 0.5])  # one baseline per orbit/gap

# ---- 2. starting values from the folded curve ----
t0 = t[0]; ph = ((t - t0)/P) % 1
nb = 200; b = np.minimum((ph*nb).astype(int), nb-1)
curve = np.array([np.median(mag[b == i]) for i in range(nb)])
ip = int(np.argmax(curve))                           # faintest bin = primary minimum
M0 = t0 + (ip + 0.5)/nb*P
M0 += P*round((t.mean() - M0)/P)                     # put M0 near the middle of the data
level = np.median(curve);  A1 = curve[ip] - level
A2 = curve[(ip + nb//2) % nb] - level
D = (np.sum(curve > level + A1/2)/nb) / 2.2          # FWHM ~ 2.2 D  (for Gamma ~ 1)
logger.info(f"start: M0={M0:.4f} A1={A1:.3f} A2={A2:.3f} D={D:.4f}")

# ---- 3. staged global fit ----
model = EBModel(profile=1, harmonics=(1, 2))
p0 = dict(A1=A1, A2=A2, D1=D, G1=1.0, C1=0.0, H1=0.0, H2=0.0)
e0 = dict(M0=M0, P0=P, Pdot=0.0)
r1 = fit_global(t, mag, sig, model, p0, ["A1","A2","D1","G1"], e0, ("M0","P0"), seg=seg, order=2)
r2 = fit_global(t, mag, sig, model, r1.p, ["A1","A2","D1","G1","C1","H1","H2"], r1.ephem, ("M0","P0"), seg=seg, order=2)
for n in r2.names: logger.info(f"  {n:3s} = { {**r2.p, **r2.ephem}[n]:.6f} +- {r2.err[n]:.6f}")
logger.info(f"rms={r2.rms:.4f} mag  rchi2={r2.rchi2:.2f}")

# ---- 4. timings and O-C ----
vm = virtual_minima(t, mag, sig, model, r2.p, r2.ephem, window=0.25, order=1)
c, res, rms = fit_ephemeris(vm["T"], vm["sigma"], vm["E"], deg=1)
logger.info(f"{len(vm['T'])} minima, median sigma = {86400*np.median(vm['sigma']):.1f} s, O-C rms = {86400*res.std():.1f} s")
z = res/vm["sigma"]
logger.info("std(z)=%.2f ; sigma range [s]: %.1f - %.1f", z.std(), 86400*vm["sigma"].min(), 86400*vm["sigma"].max())
o = np.argsort(-abs(z))[:5]; logger.info("worst: %s", [(vm['E'][i], vm['n'][i], round(86400*res[i],1), round(86400*vm['sigma'][i],1)) for i in o])
logger.info("median |res| s: %.1f", 86400*np.median(abs(res)))
