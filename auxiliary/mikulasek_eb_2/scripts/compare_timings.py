#!/usr/bin/env python3
"""Compare two lists of eclipse timings (e.g. this method vs MAVKA) on the same data.

usage: compare_timings.py ours.csv mavka.csv --P 0.5 --M0 2459000.123 [--tol 0.02] [--deg 2] [--png out.png]
CSV: first columns  time[, sigma]   (comma/space/semicolon separated, '#' comments ok).
Unknown 'truth' => the meaningful precision test is the scatter about a smooth
ephemeris fitted to each method's timings (same events), plus the paired difference."""
import argparse, numpy as np
from mikulasek_eb import fit_ephemeris

def load(fn):
    a = np.atleast_2d(np.genfromtxt(fn, delimiter=None if ',' not in open(fn).read() else ',', comments='#'))
    return a[:, 0], (a[:, 1] if a.shape[1] > 1 else np.full(len(a), np.nan))

ap = argparse.ArgumentParser()
ap.add_argument("ours"); ap.add_argument("mavka")
ap.add_argument("--P", type=float, required=True); ap.add_argument("--M0", type=float, required=True)
ap.add_argument("--tol", type=float, default=0.02, help="match tolerance [d]")
ap.add_argument("--deg", type=int, default=2); ap.add_argument("--png")
a = ap.parse_args()

T1, s1 = load(a.ours); T2, s2 = load(a.mavka)
idx = [(i, int(np.argmin(abs(T2 - t)))) for i, t in enumerate(T1)]
idx = [(i, j) for i, j in idx if abs(T2[j] - T1[i]) < a.tol]
i, j = map(np.array, zip(*idx))
T1, s1, T2, s2 = T1[i], s1[i], T2[j], s2[j]
E = np.round((T1 - a.M0) / a.P * 2) / 2
d = T1 - T2
print(f"matched events: {len(d)}")
print(f"ours - MAVKA : mean {86400*d.mean():+.1f} s  (s.e. {86400*d.std(ddof=1)/np.sqrt(len(d)):.1f}),  rms {86400*d.std(ddof=1):.1f} s")
if np.isfinite(s1).all() and np.isfinite(s2).all():
    z = d / np.hypot(s1, s2)
    print(f"median sigma : ours {86400*np.median(s1):.1f} s, MAVKA {86400*np.median(s2):.1f} s;  std(diff/combined sigma) = {z.std(ddof=1):.2f}")
res = {}
for name, T, s in (("ours", T1, s1), ("MAVKA", T2, s2)):
    sg = s if np.isfinite(s).all() else np.ones_like(T)
    c, r, w = fit_ephemeris(T, sg, E, a.deg); res[name] = r
    print(f"O-C scatter about degree-{a.deg} ephemeris, {name}: rms {86400*r.std(ddof=a.deg+1):.1f} s")
if a.png:
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    f, ax = plt.subplots(2, 1, figsize=(7, 6), sharex=True)
    for k, (n, r) in enumerate(res.items()): ax[0].plot(E, 86400*r, "o", ms=3, label=n)
    ax[0].set_ylabel("O-C residual [s]"); ax[0].legend()
    ax[1].plot(E, 86400*d, "k.", ms=4); ax[1].axhline(0, c="grey"); ax[1].set_ylabel("ours - MAVKA [s]"); ax[1].set_xlabel("epoch")
    f.savefig(a.png, dpi=130, bbox_inches="tight")
