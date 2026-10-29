# Hints: data analysis with a skilled agent

Use this when fitting Mikulasek phenomenological templates and times of minima
together with a researcher, not when shipping a rigid one-star script.

The agent sees a light curve, a period, and an epoch. It does not guess the
stellar type or freeze last week's AA And knobs. It asks, configures the model
from the answers, then tests the choice on the data.

## Standing rules (do not ask)

- **T0 / epoch** is the common origin for eclipse numbers so timings from
  different codes and different stretches of the same star can be compared:
  `E = round(2*(JD - T0)/P)/2`. Periods change. In a given light curve T0 may
  sit at any phase. Do not require Min I at phase 0 or 1. Do not abort if the
  deepest eclipse in the data is far from T0. The model's M0 still comes from
  the data; T0 is for numbering, not for the template centre.
- Times in `*.dat` ToM files, printed M0, and plots are **absolute Julian Date,
  J0 = 0**, after volightcurve TIMESYS (`time_offset_to_absolute_jd`,
  `normalise_table_epoch_to_absolute_jd`). Period and epoch come from VOTable
  PARAMs.
- **Optimiser times are MJD**, converted with `astropy.time.Time` (JD of MJD 0
  is 2400000.5). Do not pass full JD into `fit_global` / `initial_guess` /
  virtual minima. Do not invent TESS BTJD (2457000). Convert M0 and ToMs back
  to JD for output. Why full JD breaks the fitter is below (standing
  mathematics, not a user-facing time-system question).
- Magnitudes: volightcurve PhotCal / `add_mag_column_from_flux`. No homemade
  unit rewrites.
- Fail fast on missing calibration, TIMESYS, period, or epoch. No silent
  defaults.
- Spike scripts may hard-code working values, but only as **named constants at
  the top of the file**, with a short comment. No magic numbers in the
  algorithm body.
- Discuss first. Implement only when the researcher asks to go coding.

## Questions before the model is configured

Ask these (or a subset, if some answers are already on the table). Map each
answer to `EBModel` and to the fit schedule.

1. **Science goal.** Template shape, or times of minima that must match other
   software? Shape work may add terms until residuals are honest. Timing work
   stays conservative: extra terms only if they change ToMs in a controlled way.

2. **Eclipse geometry.** Total / flat-bottomed primary, partial / V-shaped, or
   unknown from this curve? Profile 1 (Table 2 #1) for total/flat; consider
   profile 3 or 4 for partial/V-shaped. A two-component primary is a candidate
   only for a stubborn flat bottom, and it is an extension, not Mikulasek 2015.

3. **Contact vs detached.** Strong ellipsoidal variation between eclipses?
   Start contact-like with cosine harmonic 2; add 1 and 3 only if out-of-eclipse
   residuals demand it. Detached: keep proximity terms minimal.

4. **O'Connell.** Unequal maxima expected or visible? If yes, `ocon=True` (S1).
   If no, leave it off until residuals show a one-sided maximum.

5. **Secondary and period.** Is there a clear second eclipse half a cycle from
   the *data* primary? Could P be P/2? May the orbit be eccentric (secondary
   not at phase 0.5 from M0)? The present engine assumes a circular orbit and
   a secondary at 0.5. Eccentricity is out of scope until the researcher says
   otherwise.

6. **Shared vs separate eclipse shapes.** Same D, Gamma, C for both minima, or
   independent D2, G2, C2? Default: share, then unlock separate shapes only if
   chi-squared falls clearly (about 1% or more in the current spike rule).

7. **Time baseline.** One polynomial for the whole series, or split on gaps?
   If split, what gap in days is a real interruption (not an orbit)? Put that
   length in a named constant (for example `GAP_SPLIT_DAYS`). Degree of the
   per-segment polynomial belongs next to it (`FIT_BASELINE_ORDER`).

Do not ask a T0-convention question. That is already a standing rule.

## How the agent should use the light curve

- Fold only to **start** (M0, depths, FWHM) and to **inspect** residuals.
- Optimise on the **unfolded time series**. Phase is internal:
  `theta = (t - M0)/P0`.
- Add parameters in stages. Do not free the full template at once.
- Judge a template by rms versus out-of-eclipse noise and by binned eclipse
  residuals, not by chi-squared alone.
- After the template is frozen, times of minima are local shifts with a phase
  window. Number those events from **T0**, not from fitted M0, when the product
  must be compared with other software.

## What "configured" means

A session is configured when these are explicit (constants or a short written
choice, not buried literals):

- `MODEL_PROFILE`, `MODEL_HARMONICS`, `MODEL_OCON`
- shared vs separate eclipse shape
- whether a two-component primary is allowed
- `GAP_SPLIT_DAYS` and `FIT_BASELINE_ORDER` (or "no split")
- timing windows and both-walls policy
- output times: JD, J0 = 0, `*.dat`

If a choice came from an older star (for example AA And: profile 1, harmonics
1-2-3, O'Connell on), label it as a **working hypothesis for this spike**, then
confirm or replace it with the answers above.

## Why full JD breaks Levenberg-Marquardt (do not ask the user this)

The researcher already knows JD versus MJD. The agent must know that **this
engine's LM step is numerically wrong on full JD**, even when the cadence is
high and the scientific times in the files are correctly JD.

`fit_global` calls SciPy `least_squares(method="lm")` **without an analytic
Jacobian**. SciPy then approximates `J_{ij} = dr_i / dx_j` by a two-point
finite difference. The absolute step is

`h_j = sqrt(eps) * max(1, |x_j|)`

with `eps ~ 2.2e-16`, so `sqrt(eps) ~ 1.5e-8`. Phase is `theta = (t - M0) / P0`.
A step `h` in M0 is a time shift of `h` days for every point.

| Time system of M0 | typical \|M0\| | finite-difference `h` on M0 |
|---|---|---|
| Julian Date | 2.46e6 | ~0.037 d ~ **53 minutes** |
| MJD | 5.9e4 | ~8.8e-4 d ~ **76 seconds** |
| invented BTJD (2457000) | ~1.7e3 | ~2.5e-5 d ~ **2 seconds** |

Ingress/egress of a close binary is minutes, not an hour. On full JD the
numerical `dF/dM0` averages the eclipse over a shift comparable to the whole
minimum, so the M0 column of J is garbage. LM then cannot move M0, D, or Gamma
consistently; the fitted minimum looks rounded or offset. Cadence does not
rescue this: 2-min sampling still sees a 53-minute difference step.

IEEE float64 on JD itself is adequate for millisecond ToMs (ulp at 2.46e6 d is
~5e-10 d). The failure is the **relative finite-difference step growing with
\|M0\|**, not subtraction `t - M0`. `x_scale="jac"` cannot repair a Jacobian
that was already estimated with a step larger than the eclipse.

Use **MJD** (`astropy.time`) for every call that goes into LM. Do not invent
BTJD as the fit axis. Place M0 near mid-span **in MJD** (`initial_guess`
already does `M0 += P * round((t.mean() - M0) / P)`). Report JD, J0 = 0.

## Two light curves of the same star (high cadence teaches, low cadence is timed)

When two reductions of the **same object** exist, one well sampled through
contacts and one coarser, treat them as teacher and student. This is not a
named-pipeline recipe and not a one-star story.

- **Teacher:** the higher-cadence series. Fit the phenomenological template
  (depths, D, Gamma, harmonics, optional two-component eclipse) so contacts
  are resolved. Catalogue weights; no extra eclipse weight unless the
  researcher asked for that experiment. Show this fit **first**, on its own
  figure. If the teacher is wrong, nothing transferred downstream can help.
- **Student:** the series that is the scientific target (often the longer
  baseline or the only public cadence for that season). Freeze the taught
  shape (D, Gamma, C, H, S1, extra components). Fine-tune what the coarser
  sampling can still constrain, typically A1, A2, M0, P0. Measure times of
  minima **on the student**, with E from T0.
- Keep the two time series separate. Do not splice high-cadence points into
  the low-cadence fit to "improve" contacts.
- This engine has **no exposure-time supersampling**. A total eclipse can look
  rounded on long cadence because each point averages the ingress; D is then
  biased wide. Timings remain roughly unbiased if the template walls are taken
  from the teacher. A rounded single-Gamma fit on the student is often cadence,
  not a wrong profile family.
- Transfer M0 by an integer number of periods into the student's span, in
  **MJD**. T0 still numbers E in JD.
- Configure `EBModel` from the questions above on the **teacher** residuals.
  Do not copy harmonic / O'Connell knobs from a previous low-cadence script
  onto the teacher without looking at the high-cadence fit.

## Extra weight on minima (suggest; never a silent default)

Equal catalogue `sigma` lets out-of-eclipse points dominate chi-squared when
eclipses are a small fraction of the series. Proximity harmonics then win and
the walls stay rounded. That is a modelling choice, not a hidden default.

**The agent must not apply extra eclipse weights unless the researcher agrees.**
Raise it in the configuration discussion when the science goal is a precise
minimum shape on a **single** (usually coarser) curve, and the unweighted fit
leaves contact ripple while harmonics look adequate out of eclipse.

A worked custom solution lives in `aa_and_shape_fit.py` (named constants
`ECLIPSE_WEIGHT`, `ECLIPSE_PHASE_HALF`):

1. Fit the whole curve with catalogue `sigma` (locate eclipses, harmonics, M0,
   P0).
2. Freeze M0, P0, and the proximity terms (H and S1).
3. In both eclipse windows (`|phase| < half` of 0 and of 0.5), set
   `sigma_eff = sigma / weight` so those points count as `weight^2` in
   chi-squared (`weight = 3` means they count ninefold). Refit **eclipse
   shape only** (A, D, Gamma, C, and any two-component keys).
4. Judge walls on **unweighted** residuals and binned contact ripple. The
   weighted chi-squared is not a catalogue goodness-of-fit.

Do not use this on a high-cadence **teacher** whose job is an honest global
shape. Do not mix it into ingest or into another script "to be safe".

## Cadence and two-component eclipses

A single Gamma cannot be both a flat floor and steep walls. The two-component
primary (`A1b, D1b, G1b`) is an extension, not Mikulasek 2015. Label it. Adopt
it only if rms, binned contact ripple, and parameter errors improve without a
degenerate A and Ab pair.

## Ingest and what not to touch

- Work inside `auxiliary/mikulasek_eb` unless the researcher asks otherwise.
  Do not edit volightcurve to paper over PhotCal problems.
- Flux columns may already be in the PhotCal zero-point unit (`electron / s`
  versus an `UnrecognizedUnit` of the same name). Do not force
  `add_mag_column_from_flux` when the numbers are already there. Catch unit
  conversion errors as **warnings** in the local loader; fail fast only when
  period, epoch, TIMESYS, or PhotCal metadata are actually missing.
- One VOTable, one loader policy. A script that must not call
  `add_mag_column_from_flux` should have its own loader, not a silent change
  to `tess_workflow_votable_jk.py`.
