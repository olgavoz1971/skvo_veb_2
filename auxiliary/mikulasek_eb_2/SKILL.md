---
name: mikulasek-eb-fitting
description: Fit phenomenological (Mikulášek-type) models to eclipsing-binary light curves, tune the fit, and measure precise times of minima (virtual minima, O-C) with the bundled mikulasek_eb.py, eb_tuning.py and compare_timings.py. Use this whenever the user works on an eclipsing binary (EB) light curve, TESS/ground photometry of an EB, fitting flat-bottomed or total eclipses, times of minima, eclipse timing, O-C diagrams, period or Pdot, or comparing timings with MAVKA or another method, even if they do not name the method or the files.
---

# Mikulášek-type EB fitting and minima timing

Goal: (1) an adequate global fit of the phase curve of an eclipsing binary, (2) precise,
honestly-quantified times of individual minima, (3) a documented comparison with other
timing methods (e.g. MAVKA). Work like a careful observer: every decision is based on a
number or a plot, every run is logged, and conclusions state what was and was not verified.

## 0. What you have

`scripts/mikulasek_eb.py` is an independent re-implementation of Mikulášek (2015, A&A 584, A8),
not the author's code. It is not validated against the paper's stars or against MAVKA.
Read `references/api.md` for signatures. Other scripts: `eb_tuning.py` (starting values,
multi-start, residuals, window scan, clipping), `compare_timings.py`,
`tess_workflow_example.py` (runnable on synthetic data; copy its structure).

Hard limits of the code. Say so to the user when relevant, never work around them silently:
- circular orbits only (secondary must sit at phase 0.5); eccentric systems are out of scope;
- no exposure-time supersampling (long cadence + narrow eclipses biases D wide; timings stay roughly unbiased);
- no eclipse-asymmetry parameter (an asymmetric minimum biases timings);
- `least_squares(method="lm")` is unbounded: always check D>0 and Γ>0 after a fit;
- the optional second eclipse component (section 4b) is my extension, not part of the paper's method; label it as such in every report.

## 1. Conventions (get these right first)

- y in **magnitudes** (fainter = larger), sigma in magnitudes. Eclipse depth A>0.
- Times relative to a reference: t = BJD − T_ref (TESS BTJD is already small). Float precision matters.
- Phase 0 = primary minimum, 0.5 = secondary. Eclipse number E: integer = primary, n+0.5 = secondary.
- `M0` near the **middle** of the data (decorrelates M0 and P0): `M0 += P*round((t.mean()-M0)/P)`.
- `seg`: integer id per point for baselines. TESS: one per orbit (split at gaps > ~0.5 d).
- `order` (baseline polynomial degree): 0–1 for global fits of already-detrended light curves, 1 per event in timings. Degree 2 per orbit only if PDCSAP trends remain. Too flexible baselines eat the eclipse shape.
- Before fitting remove NaNs, bad-quality points and flares. Clip outliers on **residuals** of a preliminary model (e.g. 5σ, out of eclipse first), never on raw magnitude inside eclipses.

## 2. Standard workflow

Run the stages in order. Do not free everything at once.

**Stage A – data and noise.** Estimate the white noise from OUT-OF-ECLIPSE points only:
`nf = noise_floor(t, mag, mask=out_of_eclipse_mask(t, ephem, fwhm))` (after a first ephemeris/FWHM from
`initial_guess`). The unmasked estimate is inflated by steep ingress/egress (2.9 vs true 2.0 mmag in my test).
All "rms/noise" judgements use this masked value; compare with the catalogue `sig` and report both.

**Stage B – starting values.** `g = initial_guess(t, mag, P)` returns M0, A1, A2 and the primary FWHM
(phase units). Verify the period first: if P is from a periodogram it may be P/2 (compare
odd/even eclipse depths) and the secondary must be near 0.5 in the fold. If not, stop and report (eccentric).

**Stage C – structure.** Pick `profile` and `harmonics` from the EB type (section 4). Start with profile 1.

**Stage D – staged global fit.**
1. free `A1, A2, D1, G1` + `M0, P0` with all `H*`, `S1`, `C1` = 0 (quick, locates the eclipses);
2. add `H*` (and `S1` if maxima differ), then `C1`;
3. if the two eclipses differ in shape, add `D2, G2, C2` to the parameter dict and free them.
Use `multistart_global` for stage 2 (Γ starts 1, 2, 4, 8 with D consistent with the FWHM). If the
starts disagree, take the lowest χ²; if they agree, the optimiser is not the problem.
Keep a term only if its amplitude exceeds ~3× its uncertainty AND χ² drops clearly.
Free `Pdot` only if the data span is long (many hundreds of epochs); otherwise it is degenerate with P0.

**Stage E – diagnose.** `residuals(...)` then `binned_residuals(...)`. Read section 3 to translate the pattern
into an action. Iterate D→E at most ~6 times; log each attempt (parameters, χ², rms, decision).

**Stage F – timings.** `window_scan(...)` (section 6), pick the window, clean timings, fit an ephemeris, report.

**Stage G – comparison.** Section 8.

## 3. Tuning playbook: symptom → check → action

First compute: rms of residuals vs `noise_floor`; reduced χ²; binned residuals around both eclipses and
out of eclipse; parameter errors from `r.err`; eclipse depth for scale.

| Symptom | Likely cause | Action |
|---|---|---|
| rms ≲ 1.5× (out-of-eclipse) noise, no structure | adequate | stop tuning |
| Residual ripple in eclipses: centre of the eclipse offset one way, shoulders (walls) the other, alternating sign | single-component ceiling for flat-bottomed/total eclipses (smooth function vs sharp contacts) | confirm rms/noise with the masked noise floor; if still > 1.5, try the two-component extension (section 4b); otherwise accept for timing. Do not add harmonics to fix it |
| D and Γ errors ≳ 10% and strongly correlated (`r.cov`) | degenerate valley, often with C1 | fix C1=0; refit; check multi-start; use profile 2 |
| Eclipse fitted too round/wide, Γ ≈ 1 while the data show a flat bottom | start in wrong basin or shapes shared by unlike eclipses or missing out-of-eclipse terms | multi-start; D from FWHM with `D_from_fwhm`; separate D2/G2; add H3/`S1` |
| χ² drops clearly when D2,G2,C2 are freed | the two eclipses differ (occultation vs transit, limb darkening) | keep separate shapes |
| One-sided residuals at maxima / wings of eclipses | missing harmonics or O'Connell effect | `harmonics=(1,2,3)`, `ocon=True` |
| Residuals oscillate with phase everywhere | too few harmonics, or spots changing in time | add harmonics (rarely beyond 3); otherwise use local timing windows |
| Residuals differ strongly between orbits/sectors | evolving spots/shape | fit per orbit or per sector; use local windows |
| Fit returns NaN, huge errors or D<0 / Γ<0 | unbounded optimiser ran away | restart from the best earlier solution; free fewer parameters; take abs(D) |
| rchi2 ≫ 1 but residuals look random | `sig` too small | rely on `rescale=True`; judge by rms vs noise floor |
| Secondary not at phase 0.5 | eccentric orbit | stop, report: out of scope |
| p0 has `H3` but nothing happens | `harmonics` does not include 3 | the model silently ignores unused keys: check |

Why Γ may stay near 1.2 on a total eclipse: a single Γ cannot give a flat centre and steep walls at the same time. Best Γ of profile 1 depends on (flat half-width)/(contact half-width) of the eclipse: 0.78 → Γ≈229 (rms 2.7 mmag); 0.58 → 10.8 (3.3); 0.39 → 2.3 (3.7); 0.19 → 1.2 (4.4) on a 0.39 mag deep synthetic occultation. A fit that sits at Γ≈1.2 with all multi-starts agreeing can therefore be the correct single-component answer for a short flat bottom (large radius ratio), not an optimiser failure.

Numbers I measured on synthetic total eclipses (use as orientation, not as law):
- A geometric flat bottom is represented by profile 1 with Γ ≈ 2–3, D ≈ FWHM/3, with a residual ripple of about ±7 mmag on a 0.39 mag deep eclipse (rms floor ≈ 1.2% of depth in an ideal case).
- From any Γ start (1–30) the fit converged to the same solution in ideal data; so repeated multi-start failures point to the data/model, not the optimiser.
- FWHM / D for profile 1 (C=0): Γ=1 → 2.24; Γ=2 → 2.9; Γ=3 → 3.2; Γ=5 → 3.6; Γ=10 → 3.9. Starting D = FWHM/2.2 is only right for Γ ≈ 1.

## 4. Recipes by EB type

Always start with profile 1; use 2 if C is consistent with zero or data are noisy/sparse (one parameter fewer).
Profile 4 is the Andronov-type function; use it for like-for-like comparison with MAVKA-style fits (do not assume MAVKA's exact implementation). 3 is an alternative tail shape. From the paper, one test star (AR Aur primary) gave scatter 3.4/3.9/5.5/6.9 mmag for profiles 1/2/3/4: indicative only.

| Type | harmonics | ocon | notes |
|---|---|---|---|
| Detached, narrow eclipses | `()` or `(2,)` | no | D ≈ 0.01–0.03; baseline order 1 |
| Detached/semi-detached with reflection/ellipsoidal | `(1,2)` | if maxima differ | |
| Contact (W UMa) | `(2,3)` (XY Boo style) | if spotted | wide eclipses D ≈ 0.05; maybe `(1,2,3)` |
| Total / flat-bottomed (e.g. AA And) | `(1,2,3)` | yes | multi-start, `D_from_fwhm`, separate shapes; accept ripple ceiling |
| Very shallow secondary | as above | | do not over-interpret its shape; shared shape is often best; timings of the secondary have larger σ |
| Eccentric | not supported | | stop |

## 4b. Optional two-component eclipse profile (extension, not in the paper)

Adds A·profile(D,Γ) + Ab·profile(Db,Gb) per eclipse (keys `A<k>b, D<k>b, G<k>b`), so a flat bottom and steep walls can coexist.
Use ONLY after the single-component fit is tuned and the residual ripple remains (rms/noise > 1.5 with the masked noise).
`best, rows = refine_two_component(t, mag, sig, model, r_single, seg=seg, order=..., eclipses=(1,2))` tries 4 starts.
Accept the second component only if ALL hold (my heuristics):
1. rms/noise improves clearly (≥ ~25%) and residual ripple shrinks;
2. the best starts agree on χ² (at least two starts at the same minimum);
3. new parameters are finite, D>0, Γ>0, relative errors < ~50%; no degenerate pair (A and Ab of opposite sign, each larger than the total depth);
4. timings from both templates (both-walls events, same window) agree within combined errors; if they do not, report the difference instead of choosing silently.
Always report both fits. In a synthetic test (short flat bottom, 2 mmag noise, data gaps) the single component gave rms 2.2× noise and the second component 1.2×; this is a simulation, not proof for real data.

## 5. Cadence rules

Points per FWHM = FWHM_days / cadence, with FWHM_days ≈ (FWHM in phase) × P.
- ≥ 20: excellent; whole-phase and local timings both fine.
- 8–20: fine for the global fit; local timings possible but check σ.
- < 8 (e.g. 10–30 min FFI on narrow eclipses): use folded data for the template; individual timings mostly rely on the template (whole phase). Report that D is biased wide because exposure smearing is not modelled.

## 6. Timings

Two modes (same function, `window` differs):
- **whole phase** (`window=0.25`): template fixed, shift + baseline per eclipse; most precise for stable shape.
- **local** (`window≈0.06–0.15`): robust against shape changes, spots, O'Connell variability; less precise.

`free=("A","D")` lets depth/width float per eclipse. Use only when depth/width demonstrably vary, with `window ≥ 0.1`; in short windows it gave occasional wild solutions in my tests.

Procedure:
1. `out, rows = window_scan(...)`: reports N, median σ, O–C rms and std(z) for windows 0.25, 0.15, 0.10, 0.06.
2. Choose the window with the **smallest O–C rms**, looking at std(z) only as a calibration check. Never choose by smallest formal σ, and never by std(z) ≈ 1 alone: narrow windows reach std(z) ≈ 1 because σ explodes, not because the timing is good (AA And: window 0.06 had std(z) 0.87 and O–C rms 115 s). A rising O–C rms towards narrow windows is expected (fewer points on the walls) and says nothing about template adequacy. If a narrow window gives a clearly SMALLER rms than the whole phase, the shape varies: prefer local.
3. Require coverage of BOTH walls: `wb = wall_band(model, r.p)` then `window_scan(..., wall_band=wb)` runs each window with all events and with both-walls events only. Partially covered events rest on one wall and are biased by any wall-shape mismatch. In a synthetic test with data gaps, removing 3 of 53 events cut the scatter about the true times from 16.5 s to 4.5 s (window 0.25) and from 88 s to 4.5 s (window 0.15). A real-data sign of the same problem: O–C rms that grows sharply for narrower windows while std(z) stays ≈ 1 (big-σ outliers hide in z). Report all/walls side by side. Also remove events with huge-σ events at orbit edges dominate an unweighted rms (in a test σ ranged from 3.5 to 644 s). `window_scan` also cuts σ > 5× median and clips at 4σ about the ephemeris; report how many were removed and why.
4. `fit_ephemeris(T, sigma, E, deg)` with deg=1 (linear) or 2 (quadratic); inspect O–C for structure. Genuine O–C variation (e.g. light-time effect) inflates scatter; that is not a failure of the method.
5. Error calibration: with `rescale=True`, σ is scaled by √(rchi2). When the model misfits (flat bottoms), this makes σ conservative, so std(z) < 1 is expected and acceptable (I saw 0.5–0.6 on idealised synthetic data). std(z) > 1.3 means σ underestimated: check shape variability, baselines, and timing outliers.
6. Primary and secondary timings may be systematically offset (asymmetry, spots, light-travel delay in unequal-mass close binaries). Report them separately and the offset.
7. **Understand the scatter** with `oc_diagnostics(v)`. It reports primary/secondary O–C rms, the extra scatter beyond the formal σ (`sigma_extra`), the secondary−primary offset ± s.e., the correlation of each primary with the next secondary and the lag-1 autocorrelation. Interpretation (heuristics): O–C rms ≫ formal σ and std(z) ≫ 1 with a good template means correlated noise (spots, SAP systematics) that the single-event fit cannot see; a negative primary–secondary correlation points to starspots (anticorrelated shifts have been reported for Kepler EBs), so average neighbouring primary+secondary O–C or treat it as a systematic; a positive correlation or positive lag-1 points to common-mode trends (systematics, real period variation). In that case quote the EMPIRICAL uncertainty (≈ O–C rms, or formal σ ⊕ `sigma_extra`), not the formal σ.
8. **Check that the wall filter did anything.** If the "all" and "walls" rows of `window_scan` are identical, either there are no partial events (fine, say so) or `wall_band` was not passed; confirm which before concluding.
9. A better template does not automatically give better timings. In AA And the two-component template flattened the primary (ripple ±12 → ±1.4 mmag) but timings from the single and two-component templates differed by only 1 s rms against 16 s O–C scatter, so the scatter is not a shape problem there. Compare the two timing sets (acceptance check 4 of section 4b) and say honestly which of the two improvements (shape vs timing) was achieved.

## 7. Acceptance and stop rules

Declare the fit "adequate for timing" when: parameters finite with D>0, Γ>0; multi-start consistent; residual rms within ~1.5× the out-of-eclipse noise, or the remaining structure is the single-component ceiling and the two-component test (4b) either was done or was judged unnecessary; timings from both-walls events are stable between windows 0.25/0.15; and `oc_diagnostics` has been run and its verdict (white vs correlated scatter) is reported together with the uncertainty actually quoted. Declare "not adequate" and say why otherwise. Heuristic thresholds (mine, not from the paper): adjust them if the user disagrees.

Budget: at most ~6 tuning iterations per star unless the user asks for more. Stop earlier when χ² improves by < 1% for a new term. Report, don't loop.

## 8. Comparison with MAVKA (or any other timing list)

1. Same data, same eclipses (same filter/orbit, same selection). Ask the user for the MAVKA settings and the interval used per minimum.
2. Export ours as CSV `time[,sigma]` (relative to the same reference) and run
   `python compare_timings.py ours.csv mavka.csv --P <P> --M0 <M0> --deg 1 --png cmp.png`.
3. Interpret: paired mean difference and its s.e. (systematic offset between methods); rms of the difference; each method's O–C scatter about a smooth ephemeris (precision proxy, since the truth is unknown); std(diff/combined σ) (error calibration). Differences between methods cannot tell which is right; only scatter and consistency can.
4. Check whether differences correlate with phase coverage, depth or night; report outliers individually.

## 9. Reporting

Give: star, data and cadence, period, profile and harmonics chosen and why, final parameters ± errors, rms vs noise floor, residual plot description, the window chosen with the scan table, number of timings, O–C rms, error calibration, MAVKA comparison, and an explicit list of caveats (the hard limits in section 0 that apply). Save: parameter JSON, timing CSV (E, T, σ, n, rchi2), figures (folded fit + residuals, O–C), and the run log. Ask the user only when the choice needs domain knowledge (period alias, eccentric orbit, which minima to include).

## 10. Do not

- free all parameters at once, or add harmonics beyond 3 without evidence;
- free A, D in windows < 0.1;
- time partially covered eclipses without reporting them separately;
- judge rms/noise with an in-eclipse-contaminated noise estimate;
- adopt the two-component profile without the four acceptance checks of 4b;
- trust formal σ from a fit with obvious structured residuals without checking std(z);
- invent paper details: the code follows the equations as transcribed from the paper; if something is unclear, say so;
- present the comparison with MAVKA as validation of accuracy when it only shows consistency.
