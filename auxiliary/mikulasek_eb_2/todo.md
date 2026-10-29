# Mikulasek EB package: work plan and progress

Scope: everything lives under `auxiliary/mikulasek_eb_2`. Nothing outside this folder is edited.
Reference: Mikulasek (2015), A&A 584, A8 (`docs/aa25244-14.pdf`); implementation notes in `docs/mikulasek_implementation_notes.md`.

## Goals

- (a) Successful AI-helped fit of a provided light curve.
- (b) A script that analyses a light curve by itself, chooses the model profile and the free-parameter set, and fits.
- Outputs of a run: the **model** and the **times of minima**, which may differ for primary and secondary. Timing code stays as it is for now; keep it in mind in every design decision.
- End state: a clean, tested, installable Python package.

## Decisions (developer, 29 Oct 2026)

1. TIC 450335412 is relabelled **EK Com**. No better-cadence EK Com data are available (10 min cadence stays).
2. Comparison with Table 1 uses shape parameters only (D, Gamma, C, A2/A1, harmonic ratios). Band and dilution differences accepted. Lambda extrapolation for AR Aur is a stated caveat. Every star gets a visual-inspection figure like the two existing ones.
3. All new code and changes stay inside `auxiliary/mikulasek_eb_2`.
4. Start with **paper defaults** (profile 1, paper parameter set). Two-component primary and eclipse weights are extensions, off by default. Intended pipeline: step 1 is light-curve analysis that results in the model profile choice for that star.
5. Silent-skip fix ordering: agent's call (see Phase 1).
6. Do not rewrite the timing part yet.
7. Rules: no code without an explicit request; discuss first. Fail fast, no silent fallbacks.

## Data

| Star | File | Cadence | Cycles | Notes |
|---|---|---|---|---|
| AA And (TIC 455790537) | `lc_discovery_TIC_455790537_SPOC_sector_16.vot` | 2 min | | Not in the paper. Already fitted (two-component adopted). |
| EK Com (TIC 450335412) | `EK_Com_sector_49.vot` (identical to `lc_discovery_TIC_450335412_...`) | 10 min | 89 | About 5.6 points per FWHM. |
| AR Aur (TIC 2236015) | `AR_Aur_sector_19.vot` | 2 min | 6 | Tmag about 6, possibly saturated. Paper has B and V only. |
| AV Del (TIC 383274804) | `AV_Del_sector_81.vot` | 3.3 min | 7 | Paper amplitudes depend on Lambda. |
| V477 Lyr (TIC 423311936) | `v477_Lyr_sector_26.vot` | 2 min | 53 | Noise about 29 mmag; dilution; strong reflection effect. |

## Phases

### Phase 0: housekeeping
- [x] Relabel EK Com: script `working_scripts/fit_ek_com_s49.py`, data `data/EK_Com_sector_49.vot`, results `results/ek_com_s49_*`. Rerun gave timings identical to the old TIC-labelled files; old script, duplicate VOTable and old results removed. Strict-cut files moved to `results/superseded_strict_cut/`.
- [x] Per-star manifest with Table 1 values: `references/stars_manifest.json` (transcribed from the PDF text; digits still to be checked against the PDF).
- [x] Record the current EK Com timing counts (primary 70, secondary 68) as the regression reference (stored in the manifest).
- [x] AR Aur period: the paper Table 1 value 4.13169 d is contradicted by the data (see the AR Aur forward-check entry); the VOTable value is right.
- [ ] Remove stray artefacts only after asking (`files (4).zip`, `.skill`).

### Phase 1: engine honesty (before new comparisons)
Reason for doing this first: the paper comparison must rest on an engine that does not drop events or accept failed fits silently. Counts may change; the reference counts above show by how much.
- [x] `virtual_minima`: no more silent `except`. Optional `rejected=` list gets one dict per skipped event (reason and detail); failed fits are logged at WARNING; coverage rejections at DEBUG. Output arrays unchanged. EK Com result: no fit failures, counts unchanged (70 and 68); the only final rejection is E=13.5 (one side uncovered).
- [ ] Surface the `rejected` table in `minima_timing.py` output (header or log summary).
- [x] Convergence enforced: `FitDidNotConverge` raised by `fit_global`, `fit_minimum`, `fit_global_shifts` (inside `virtual_minima` it becomes a logged `fit_failed` rejection). Rank-deficient Jacobian logged at WARNING and stored as `FitResult.rank_deficient`. No effect on AA And or EK Com (no failures, no rank warnings).
- [x] Gamma start 0.5 added to the default multistart (`eb_tuning.multistart_global`, `FitConfig`). AA And and EK Com converge to the same minimum; EK Com timings move by at most 0.014 s. Still to test on a star that truly has Gamma < 1 (AR Aur, AV Del, V477 Lyr) and the mid-eclipse spike behaviour.
- [ ] `initial_guess`: the pipeline already stops with an explicit error when the folded secondary is not a depression (A2 < 0), which is the honest behaviour. The real fix is to measure the secondary against the local continuum, not the global median; this is a feature-extraction task, moved to Phase 4.
- [ ] Docstrings (Google style), logging, units, no `print`.
- [x] Tests in `tests/` (11 passing, about 6 s): synthetic parameter and timing recovery, timing error calibration, gap rejection reporting, fail-fast behaviour (non-convergence, rank deficiency, failed event fits), EK Com regression (timing counts 70/68, adopted rms). Run: `cd auxiliary/mikulasek_eb_2 && ../../.venv/bin/python -m pytest tests`. AA And regression still to add.

### Phase 2: paper validation
- [x] Forward check, EK Com: `working_scripts/paper_forward_check.py EK_Com` -> `results/paper_forward_ek_com.png` and `.txt`. Result: published shape (D 0.052, Gamma 1.7, C1 0.10, C2 -0.14) reproduces the TESS fold well; with paper amplitudes the depths are too large (V band, no dilution), with amplitudes refitted rms is 8.5 mmag, residuals up to about 20 mmag on the primary walls and 8 mmag out of eclipse. A2/A1 = 0.868 (paper 0.873). Refitted A1, A2, H2 are 0.93, 0.92, 0.85 of the paper values; paper H1 (0.023) and O'Connell (0.032) are not reproduced (TESS 0.0002 and 0.0037), as expected for a spotted star decades apart.
- [x] EK Com, shape freed (variants C and D in the same script): rms 8.5 (B) -> 7.5 (D, free) -> 6.2 mmag with D, Gamma, C1, C2 free. TESS D = 0.0498(3) (paper 0.052(3)), Gamma = 1.23(4) (paper 1.7(4)), C1 = 0.20(3) (paper 0.10(17)), C2 = 0.07(2) (paper -0.14(9)); formal errors are rescaled by rchi2 27 and understate the systematic misfit. Largest tension: C2 (about 2.3 sigma), same sign ordering C1 > C2 as the paper. Residual structure of about 20 mmag on the primary walls stays in all variants: single-Gamma shape ceiling plus 10-min smearing and spots, not a parameter choice.
- [x] V477 Lyr (`paper_forward_check.py V477_Lyr`, harmonics 1 to 3, no O'Connell, single shared C): TESS D = 0.0217(4) (paper 0.0219(5)), C = -0.337(16) (paper -0.342(20)), Gamma = 1.28(6) (paper 0.79(4), clear difference). Amplitudes: A1 0.42 (paper 1.56), A2 0.053 (0.078), H1 0.201 (0.321), H2 -0.024 (-0.035). Variants B, C, D all give rms 34 mmag, which is the per-point noise (sigma 29 mmag), so the data cannot separate the shape variants well. Quick check (ad hoc, not saved): diluting the paper model by third light to the TESS depth shifts D to 0.015 and flips the sign of C, which the TESS fit does not show, so plain dilution does not explain the amplitude drop. Hypothesis, untested: band effect (hot nucleus plus cool companion, so the primary is much shallower in TESS red; the paper has strong Lambda dependence of the amplitudes) and a possible band dependence of Gamma.
- [x] AV Del (`paper_forward_check.py AV_Del`; model evaluated at Lambda = -0.262: A1 = 0.8465, A2 = 0.1723, H2 = 0.0615; no cos 2 pi theta, no O'Connell, as in the paper). Variant A (all paper values, only M0 fitted) already gives rms 13.6 mmag. With the paper parameter set freed (variant D, rms 7.2 mmag): D = 0.0413(2) (paper 0.0396(7)), Gamma = 0.870(5) (0.82(5)), C = -0.2435(43) (-0.24(7)), A1 = 0.8715 (0.8465), A2 = 0.1740 (0.1723), A2/A1 = 0.200 (0.204), H2 = 0.0495 (0.0615). Best agreement of the four stars; confirms the Lambda mapping and the engine. Remaining residual: smooth out-of-eclipse asymmetry of about 15 mmag (positive near phase 0.2 to 0.3, negative near 0.6 to 0.7), which the paper model has no term for (A3 = 0, no sine); an odd harmonic or an O'Connell term would absorb it. Variants C and D coincide (C is not significant). Fitted P0 = 3.85334(4) d against VOTable 3.85343 d.
- [x] AR Aur (`paper_forward_check.py AR_Aur`, shape only; amplitudes not compared; P held at the paper value 4.13169 d as requested). Result with the paper period: D = 0.0173(1) (paper 0.0168(3)), Gamma = 0.618(4) (0.619(10)), C = -0.270(5) (-0.25(2)); A2/A1 = 0.878 (paper 0.797 in B, 0.828 in V, band dependent). But rms is 8.6 mmag with large in-eclipse residuals: the paper period smears the eclipses. Diagnostic (ad hoc, not saved): with the VOTable period rms is 1.69 mmag and D = 0.0175, Gamma = 0.604, C = -0.281; a free fit starting from the paper period converges to P = 4.134649(5) d. The paper table period is almost certainly a typo. Shape parameters agree with the paper within about 2 sigma either way; Gamma < 1 is recovered (0.60 to 0.62) from the multistart.
- [x] AR Aur reference run now uses the data period (free P from the VOTable value): rms 1.7 mmag, D = 0.0175, Gamma = 0.6035(8), C = -0.2807(10), P = 4.134649(5) d.
- [x] Paper-pure fits of all four stars (variants B to D of `paper_forward_check.py`; harmonics and O'Connell as in Table 1, shared D, Gamma, C, separate C1 and C2 for EK Com).
- [x] Comparison table: `results/paper_comparison_summary.md` (D, Gamma, C, A2/A1, rms, fitted period against Table 1; written by `paper_forward_check.py all`).
- [x] One figure per star: `results/paper_forward_<star>.png` (fold, primary, secondary, residuals; paper model and fit variants).
- [x] Implementation notes updated (`docs/mikulasek_implementation_notes.md`): paper remedy C1 != C2, new section 7 with the validation, paper period erratum candidate.

### Phase 3: package structure
- [ ] Standalone installable package inside this folder (model, fit, timing, diagnostics, I/O, optional plotting).
- [ ] Extensions (two-component, eclipse weights) in a separate module, off by default.
- [ ] Remove `sys.path` hacks; one place for configuration (`FitConfig` or successor).
- [ ] Timing module wrapped as is; per-eclipse-type (primary, secondary) outputs preserved.

### Phase 4: automatic profile selection
- [ ] Light-curve analysis features from the fold (depths, widths, flatness, out-of-eclipse curvature, reflection effect, secondary phase check).
- [ ] Hypothesis tree: detached, contact, semi-detached, reflection, eccentric flag.
- [ ] Model choice by an explicit criterion (BIC or similar on honest uncertainties), not ad hoc thresholds.
- [ ] Output: `FitConfig` plus evidence plus an "ask a human" flag.
- [ ] Validation: develop on some stars, test on the others; ground truth is Table 1 and the developer's judgement.
- [ ] AI-helped mode: the agent proposes a config from diagnostics; the script validates and records it.

## Progress log

- 2026-10-29: Review done. Found that TIC 450335412 is EK Com; paper D and Gamma agree with our fit. Decisions recorded above. This file created.
- 2026-10-29: Phase 0 done except the AR Aur period check. Phase 1: `virtual_minima` rejection reporting done; EK Com timings unchanged. Next in Phase 1: enforce `success` and singular covariance, Gamma < 1 starts, `initial_guess` for a bright secondary.
- 2026-10-29: Phase 1: convergence enforcement and Gamma 0.5 start done. AA And and EK Com fits unchanged; EK Com timings 70/68, changes below 0.014 s. Remaining in Phase 1: surface rejections in timing output, docstrings/logging/units in the engine, unit tests.
- 2026-10-29: Phase 1 tests added and passing (11). Remaining in Phase 1: surface rejections in timing output, docstrings/logging/units in the engine, AA And regression test.
- 2026-10-29: Phase 2 started. EK Com forward check done (see above). Note: rms/noise from the out-of-eclipse mask is misleading for contact binaries (noise floor 22 mmag against catalogue sigma 1 mmag); compare rms in mmag instead.
- 2026-10-29: EK Com paper-style fit done (variants A to D). Published D, Gamma, C1 agree within errors; C2 differs by about 2.3 sigma. Wall residuals of about 20 mmag remain. Next: map the other three Table 1 columns (AV Del with Lambda, V477 Lyr, AR Aur).
- 2026-10-29: V477 Lyr paper-style fit done. D and C agree with the paper, Gamma does not (1.28 against 0.79), amplitudes are 0.27 (A1) to 0.63 (H1) of the paper values. Noise-limited (29 mmag per point). Gap split for the forward-check script changed to 0.5 d (EK Com unchanged). Next: AV Del with Lambda, then AR Aur.
- 2026-10-29: AV Del paper-style fit done: shape parameters and amplitudes (at Lambda) agree with Table 1 within a few percent. Builders refactored (builder returns model, published parameters and published errors; one summary code path). Next: AR Aur (needs a decision on the B/V extrapolation and the period check).
- 2026-10-29: AR Aur shape-only check done with the paper period as requested. Shape agrees with Table 1; the paper period is a typo (data prefer 4.134649 d, rms 1.7 against 8.6 mmag). All four paper stars now have a forward check and a paper-style fit. Phase 2 remaining: summary table across stars, notes update, Phase 2 decision on next step.
- 2026-10-29: Phase 2 finished. AR Aur reference run uses the data period. Cross-star summary `results/paper_comparison_summary.md`, implementation notes section 7, regression test `tests/test_paper_comparison.py` (21 tests passing, about 11 s). Open from the validation: V477 Lyr Gamma (1.28 against 0.79, untested band hypothesis), EK Com C2 (2.2 sigma), Table 1 AR Aur period erratum candidate, amplitude comparison for AR Aur skipped by decision. Next: Phase 1 leftovers (rejection table in timing output, engine docstrings/logging/units, AA And regression test), then Phase 3.
