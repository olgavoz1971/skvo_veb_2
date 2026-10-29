# API reference (mikulasek_eb.py, eb_tuning.py)

## EBModel(profile=1, harmonics=(2,), ocon=False)
Callable `model(theta, p) -> mag`. Parameter dict keys: `A1 A2 D1 G1 C1` (+ optional `D2 G2 C2`; absent means equal to D1,G1,C1), `H<k>` for every k in `harmonics` (term cos(2πkϑ)), `S1` if `ocon` (sin 2πϑ). All keys needed by the model must be present in the dict, free or not. `model.names(shared_shape=True)` lists them.
Profiles: 1 = A(1+Cx²){1−[1−exp(1−cosh x)]^Γ}; 2 = same without C; 3 = A{1−[1−exp(−x²/2)]^Γ}; 4 = A·Re[(1−|x|^Γ)^{3/2}] (x = φ/D). Γ<1 cusp, Γ=1 rounded, Γ>1 flatter bottom.

## Phase and times
`phase(t, M0, P0, Pdot=0)`; `predicted_time(E, M0, P0, Pdot=0) = M0 + P0 E + 0.5 P0 Pdot E²`.

## fit_global(t, y, sigma, model, p0, free, ephem0, free_ephem=("M0","P0"), seg=None, order=0, rescale=True) -> FitResult
`free`: template keys to vary; `free_ephem`: subset of M0, P0, Pdot. Per-segment polynomial baselines (degree `order`) are solved linearly. FitResult: `p`, `ephem`, `err` (dict incl. ephemeris), `chi2`, `dof`, `rchi2`, `rms` (mag, after baselines), `names`, `cov` (order = `names`), `success`. `rescale` multiplies the covariance by rchi2.

## fit_minimum(t, y, sigma, model, p, ephem, E, window=0.1, order=1, free=(), scan=0.1, rescale=True) -> MinResult
Points with |ϑ−E| < window. Free: delta [d] (+ multiplicative scales of A, D, G of that eclipse named in `free`). `scan` = initial shift grid half-width in phase. MinResult: `E, T, sigma, delta, n, rchi2, scales`.

## virtual_minima(t, y, sigma, model, p, ephem, window=0.25, order=1, free=(), min_points=10, min_each_side=3) -> dict of arrays (E, T, sigma, delta, n, rchi2)
All eclipses with enough points on both sides. Call per instrument/filter. window is capped at 0.25.

## fit_ephemeris(T, sigma, E, deg=2) -> (coefficients, residuals, weighted rms)
Weighted polynomial T(E).

## eb_tuning.py
`noise_floor(t, y)`, `D_from_fwhm(fwhm, G)`, `initial_guess(t, mag, P)`, `multistart_global(...)` -> (best, rows), `residuals(t, mag, sig, model, r, seg, order)` -> (res, theta), `binned_residuals(res, theta)`, `clip_timings(vm, deg, nsig)`, `window_scan(...)` -> (timings per window, summary rows).

## compare_timings.py
`python compare_timings.py ours.csv other.csv --P P --M0 M0 [--tol 0.02] [--deg 2] [--png out.png]`
