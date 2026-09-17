# Lightcurve Extrema Modeller

Page path: `/gp`. Navbar name: **Extrema Modeller**. Title: Extrema modeller for O-C.

This page times individual minima or maxima on an uploaded light curve and
builds an O-C diagram against a trial ephemeris. It is a toolbox of three
independent timing methods plus one O-C step, not a wizard: you can time with
Gaussian Process, MAVKA, or a local parabola, keep the measurements you trust,
and only then plot O-C.

Work from the top. Accordion 1 holds the light curve and the interval list that
every timer reads. The Mag/Flux toggle there is the working photometry for
MAVKA and Parabola; Gaussian Process still fits **normalised instrumental
flux** internally.

In-app copy: page **About** is a short overview. Each accordion has its own
help (`?`). Per-control `?` popovers repeat the operational rules below.

**Not this page.** The [Lightcurve processor](lightcurve_processor.md)
(` /lc_processor `) smooths, detrends, and finds *rough* extrema. Its
running-parabola smooth and Find extrema drawer do **not** refine a ToM or
invent \(\sigma(\mathrm{JD})\). Interval `_int.dat` files from that page can
be loaded here. Compact rough-ToM files (`JD` + `nan`) can be uploaded as an
O-C source, but they carry no timing uncertainty.

---

## Contents

1. [Related documents](#related-documents)
2. [Layout and workflow](#layout-and-workflow)
3. [Time, photometry, and files](#time-photometry-and-files)
4. [Light curve and intervals](#light-curve-and-intervals)
5. [Shared timing UI](#shared-timing-ui)
6. [Gaussian Process](#gaussian-process)
7. [MAVKA](#mavka)
8. [Parabola](#parabola)
9. [O-C](#o-c)
10. [Compact ToM files](#compact-tom-files)
11. [What the three timers do not share](#what-the-three-timers-do-not-share)
12. [Scripts and spikes (not production)](#scripts-and-spikes-not-production)
13. [Code map](#code-map)

---

## Related documents

| Document | Role |
|----------|------|
| [dat_lightcurve_comments.md](dat_lightcurve_comments.md) | `.dat` `#` comments, column names, strict rows |
| [lightcurve_data_flow.md](lightcurve_data_flow.md) | VOLightCurve, CurveDash, upload ingest |
| [lightcurve_processor.md](lightcurve_processor.md) | Prep toolbox; `_int.dat` and rough ToMs |
| [gp_intervals_performance.md](gp_intervals_performance.md) | Why many intervals used to be slow (implemented findings 1–3) |
| [structure.md](structure.md) | Repository layout |

Ingest of user uploads uses the same path as the TESS light-curve page:
`ingest_volightcurve_file()` in `skvo_veb/utils/lc_bridge.py`.

---

## Layout and workflow

```text
Load light curve  (+ optional intervals file)
        |
        v
Accordion 1: Lightcurve and intervals
  fold, working range, add/mark/remove intervals, optional trend removal
        |
        +---> Accordion 2: Gaussian Process  --> Keep-marked ToMs
        +---> Accordion 3: MAVKA             --> Keep-marked ToMs
        +---> Accordion 4: Parabola          --> Keep-marked ToMs
        |
        v
Accordion 5: O-C
  source = GP / MAVKA / Parabola Keep-marked, or uploaded compact .dat
```

A data hub above the accordion loads the light curve and, separately, a
two-column interval list. Timing accordions do not ingest photometry
themselves; they read the stores filled in accordion 1.

Typical path:

1. Load a light curve. Set **P** and **Epoch** if you will fold or later copy
   them into O-C.
2. Load `_int.dat` from the processor, or mark intervals on the prep plot.
3. Run one timer, inspect live then review cards, uncheck poor fits.
4. In O-C, choose that source, set trial **P** and **Epoch**, Plot.
5. Apply cycle corrections if a cycle has slipped; optionally correct period
   on a zoomed window and Adopt ephemeris, then Plot again.

---

## Time, photometry, and files

### Time

Internal times are **absolute Julian Date**. Everything the researcher sees
on this page (plots, Epoch fields, O-C, failed-card popovers) is converted
**once** in `skvo_veb/components/extrema_modeller_appearance.py`. The origin
`PAGE_DISPLAY_EPOCH_JD` is the only switch; the caption is derived from it:

- `2400000.5` (`JD_TO_MJD`) → **MJD** (IAU definition)
- `0.0` → **JD**
- any other float → **JD-**origin (for example `2450000.0` → `JD-2450000`).
  Reduced JD `2400000.0` is **not** MJD.

Folding **Epoch** is labelled `Epoch (MJD)` (or `Epoch (JD)` / `Epoch (JD-2450000)`),
never `Epoch-2400000.5`. A **Date** axis remains available on the prep plot.

Set `PAGE_DISPLAY_EPOCH_JD` in that file to retitle the whole page.

Live and review **cards** (GP, MAVKA, Parabola) share the same module: change
`CARDS_PER_ROW`, `CARD_ROWS_PER_PAGE`, and `REVIEW_CARD_PLOT_HEIGHT` there.

O-C **Epoch** is independent of accordion 1 until you press **Take from
lightcurve**. Cycle-shift **At ≥** uses the same page display time.

### Photometry

Upload preserves the native domain (mag or flux). Accordion 1 **Magnitudes /
Flux** is a view toggle. MAVKA and Parabola fit whatever that toggle currently
shows. Gaussian Process converts to a **normalised instrumental flux** (not Jy
or e/s). Timing (JD) is the scientific product.

Working photometry lives in the server session cache (`lc_session_cache`,
namespace `gp_for_oc`) as VOLightCurve **transport JSON** — the same opaque
string formerly held in `dcc.Store`. The browser keeps `user_tab_id`, a
revision UUID, the light-curve filename, Mag/Flux view, the intervals list,
and the intervals filename chip in `SESSION_STORE`. Leaving `/gp` and
returning in the same tab replots from disk, refills P / Epoch from
transport `meta` (edits write through), and restores intervals, both
file-name chips, Mag/Flux, and the prep Show intervals registry / Show error
bars switches. The prep plot always draws interval stripes when intervals are
loaded; the registry switch only opens the Selected intervals panel and builds
its cards (defaults off). Marks, trend line, and the working-window Store
remain memory-only.

Default magnitude zero point when upload metadata lacks a complete PhotCal is
`DEFAULT_REFERENCE_MAG` in `skvo_veb/utils/lc_config.py` (paired with
`DEFAULT_ZP_FLUX_DIMENSIONLESS`). Prep and all three timers share that pair.

### Light-curve formats

VOTable (`.vot` / `.xml`), CSV, ECSV, and ASCII `.dat`. Same ingest as the
TESS page.

#### `.dat` comment headers

For **`.dat` only**, case-insensitive `#` comments may set:

| Pattern | Meaning |
|---------|---------|
| `JD0 = <value>` | Time origin added to the time column (default **0**). |
| `MAG0 = <value>` | Reference magnitude for mag-to-flux when converting for the GP. |
| `PERIOD = <value>` | Folding period in days (fills **P** after upload). |
| `EPOCH = <value>` | Reference epoch in the same units as the time column (fills **Epoch (MJD)** by default, combined with `JD0`). |
| `FILTER=` / `BAND=` | Filter or band label. |

A `#` line whose word count matches the column count (and is not `KEY=value`)
is treated as column names, e.g. `# jd mag mag_err`. Otherwise a legacy
three-column layout is assumed: time, magnitude, magnitude error.

Every data row must have a **fixed** field count. Ragged rows fail with a line
number. Columns named `label`, `sector`, or `flag` may be text; other columns
must be numeric. Use `NaN` for a missing magnitude error on that row.

Full rules: [dat_lightcurve_comments.md](dat_lightcurve_comments.md).

#### Other formats (brief)

- **VOTable**: preferred when TIMESYS, PhotDM, and PARAMs are already in the file.
- **CSV / ECSV**: headers and ECSV metadata. `.dat`-style `# JD0` comments do
  not apply.

### Interval files

Two whitespace-separated Julian Dates per line: start and stop. Blank lines
and `#` comments are skipped. This is the same layout as the processor
`_int.dat` export (`skvo_veb/utils/lc_intervals.py`).

---

## Light curve and intervals

Sidebar blocks: phase folding, view settings, export, and the interval
registry beside the prep plot.

### Folding

**Fold** uses accordion 1 **P** and **Epoch**. The folded plot uses an
**extended phase** axis (−0.5 to 1.5) so a Box Select can sit on one cycle
without wrapping.

**Quadratic O-C** folding is optional: coefficients *a*, *b*, *c* describe a
quadratic ephemeris for placing intervals on a changing period. Constant
period is the default.

### Working range

**Use visible range** (unfolded plot only) restricts later work to the zoomed
JD window. **Restore full light curve** clears it. If the zoom covers every
finite sample, the page stays in full-curve mode. Shared helper:
`skvo_veb/utils/lc_working_window.py`.

Export of the *current stored* light curve can honour that window (prep export
wrapper in `skvo_veb/utils/gp/working_window.py`). Reload the file to undo
trend removal.

### Adding intervals

The prep plot defaults to **zoom** (drag to zoom; **+** / **−** on the
toolbar). To add an interval, switch the toolbar to **Box Select**.

- **Unfolded:** Box Select a time range, then **Add interval**. Re-adding the
  same window is rejected.
- **Folded:** Box Select on the extended phase axis; width must not exceed one
  phase. Matching windows from all cycles are added, then you can unfold.

**TIPS** under the plot restates this. Do not use Plotly pan/zoom tools as a
substitute for Mark bands.

### Marking and removing

Enable **Mark bands**, then drag a box across green interval bands (or click
inside a strip). Touched bands turn red. Drag again to unmark. **Remove
marked** is the server round trip. **Clear marks** drops the selection
without deleting intervals.

Marking runs in the browser (band rectangles recolour in place). It is
unavailable while folded: one interval maps to several phase rectangles.
Existing marks are kept and reappear on unfold.

**Mark bands** and **Remove trend** cannot both be on (both use the pointer).

### Manual trend removal

Unfolded prep plot only. Switch on **Remove trend**, click once: a horizontal
dashed line appears at that level (about four-fifths of the visible width).
Drag the handles, then **Apply**. Mag view: subtract the line. Flux view:
divide by it. Uncertainties stay the same in mag and are scaled in flux.
Reload the light curve to undo. Implementation:
`skvo_veb/utils/gp/manual_detrend.py` (two-point line via
`lc_interaction.line_y_at_jd`).

### Error bars on the prep plot

**Show error bars** is display only. It does not change GP, MAVKA, or Parabola
noise handling. Drawing bars on a long series can slow pan/zoom.

### Registry and empty intervals

The registry lists start/end in the same time axis as the plot. You can
download the current interval list as `_int.dat`. **Remove empty** drops
windows that contain no photometry points.

---

## Shared timing UI

Gaussian Process, MAVKA, and Parabola share the same interaction pattern
(separate stores and caches; they do not share algorithms).

| Step | Behaviour |
|------|-----------|
| **Run** | Background callback. Fits one marked interval after another. |
| **Stop** | Cooperative: finish the current interval, then exit. |
| **Live grid** | Same page grid as Review (three columns, two rows). Progress: “N extrema from M ready”. |
| **Review** | Same six-card pages. **Keep result** on successes; failed cards cannot be kept. |
| **Select all / Unselect all** | Export inclusion only. |
| **Download** | Compact `.dat` of kept successes (JD and \(\sigma\) in days). Filename field and Download sit above Review. |
| **Max half-width** | Optional sidebar field on all three timers. A marked interval wider than twice the cap is trimmed to \(\pm\) that value around its midpoint; narrower intervals are unchanged. Trimmed successes show a **window capped** badge. |

Failed intervals become cards of the same size as successes: a compact
**FAILED ?** badge, the interval photometry, and Keep result stays off. Hover
or click the badge for the range in the page display time (MJD by default)
and the reason. They do not abort the batch.

Compact files from all three timers are readable by O-C
(`parse_compact_tom_contents`): `#` comments are metadata; each data line is
JD and \(\sigma(\mathrm{JD})\). Extra columns (GP `scale_limit`) are ignored
by the O-C parser.

---

## Gaussian Process

Accordion **Gaussian Process**. Code: `skvo_veb/utils/gp/`. Fits
scikit-learn `GaussianProcessRegressor` on each interval in **normalised
flux**.

Use it when the extremum is asymmetric, noisy, gappy, or poorly described by a
fixed polynomial.

Kernel: `ConstantKernel (Amplitude) × [Matern(ν = 2.5) or RBF]`.

### Controls

| Control | Meaning | Default (config) |
|---------|---------|------------------|
| Search extrema | Minima or maxima in the GP flux model | `max` (`EXTREMA_MODE`) |
| Guess sigma | Ignore tabulated errors; MAD scatter | off |
| Noise scale | Multiplier on guessed or tabulated errors | 1 |
| Length scale min / init / max | Smoothness in days | 0.01 / 0.1 / 1.0 |
| Signal amplitude min / init / max | Vertical headroom in normalised flux | \(10^{-4}\) / 1 / 20 |
| Kernel | Matern 2.5 or RBF | Matern |
| Max half-width | Optional cap (days); wide intervals trim to \(\pm\) the cap around the midpoint | empty (no cap) |
| Guess parameters | Fills length-scale bounds from the data | — |

**Noise scale** is a trust factor: `effective error = original × scale`. If the
fit chases points, increase it. If the mean is blunt and misses the extremum,
decrease it. Do not use it as a substitute for length-scale bounds.

**Length scale:** increase if the mean is too wiggly; decrease if it misses
structure. Init is roughly half a typical feature width.

On sparse extrema the optimiser can lock onto a scale that only fits those
few points. The page may import a scale learned from well-covered cycles of
the *same* light curve and narrow min/max around it. Quoted \(\sigma(t)\) is
then **noise-only, conditional on that imported shape**. If the fitted scale
sits at a bound, the compact file flags it (`scale_limit`).

**Amplitude:** too low clips a sharp peak; too high can swing unphysically.
Leave the defaults unless the mean cannot reach the feature.

Matern (\(\nu=2.5\)) is twice differentiable. RBF is infinitely smooth and
can be too stiff.

### Photometric uncertainties (Guess sigma)

Noise is decided **per interval** (`skvo_veb/utils/gp/noise_policy.py`).

When **Guess sigma** is **on**, tabulated errors are ignored and scatter is
estimated with a robust MAD (then multiplied by Noise scale).

When **Guess sigma** is **off**, the share of finite `flux_err` in that
interval (after mag-to-flux conversion) decides:

| Finite error fraction | Behaviour |
|-----------------------|-----------|
| None (all `NaN`, or no error column) | MAD guess for every point (same estimator as Guess sigma). |
| Below 70% | MAD guess for **every** point in the interval. |
| 70% or more | Tabulated errors: each missing row gets the **median** of the finite values, then all are multiplied by Noise scale. |

The 70% cut is `GP_MIN_FINITE_ERROR_FRACTION` in
`skvo_veb/utils/gp/config.py`. Prep **Show error bars** does not change this.

### How the ToM and \(\sigma(t)\) are computed

1. Fit the GP on the interval (normalised flux, `n_restarts_optimizer=3`).
2. Evaluate the **mean** on a fine time grid (`n_grid=2000`). The ToM is the
   time of the min or max of that mean.
3. Draw **300** posterior sample curves (`n_samples_uncert`). Find the extremum
   of each. \(\sigma(t)\) is the **standard deviation** of those sample ToMs.
4. If length scale sits at min/max (1% slack), set `scale_limit` 1 or 2;
   otherwise 0.

This is a posterior-sample spread, not a coefficient Jacobian. It does not
include extra uncertainty from an imported, bound-constrained length scale:
that is why `scale_limit` exists.

Orange points on the review figure are posterior-draw extrema; the magenta
line is the mean ToM; the blue band is GP \(\pm 1\sigma\) in flux, not
\(\sigma(t)\).

### Export

Compact only (`{lightcurve}_gp`): `# GP Minimum|Maximum Results`,
`# scale_limit: …`, `# max_half_width_d: none|<value>`, then
`JD  σ  scale_limit` (`0=ok`, `1=length_scale_min`, `2=length_scale_max`).

Literature in the accordion help: Pedregosa et al. (2011), scikit-learn;
Rasmussen & Williams (2006).

---

## MAVKA

Accordion **MAVKA**. Phenomenological piecewise models of the *observed*
eclipse shape, not a physical binary model. Code: `skvo_veb/utils/mavka/`.

Vendored models (`models.py`) come from
[mpyat2/lc_approx](https://github.com/mpyat2/lc_approx) (MIT). See
`skvo_veb/utils/mavka/NOTICE`. Science: Andrych, Andronov & Chinarova.

**Search maxima is not implemented** in this version. Search minima times a
trough in the current Mag/Flux view. Need at least **six** finite points.

**Max half-width** is optional and has the same meaning as for GP and
Parabola: a wide marked interval is trimmed to \(\pm\) the cap around its
midpoint; narrower intervals are unchanged. Trimmed cards show a
**window capped** badge.

### Methods

| Id | Shape | ToM |
|----|--------|-----|
| **AP** | Asymptotic parabola with a tilted core | Vertex, kept only if it lies between junctions C4 and C5 |
| **WSAP** (default) | Wall-supported asymptotic parabola; wings \(\propto |t|^{1.5}\) | Midpoint of C4 and C5 |
| **WSL** | Flat bottom, 1.5-power walls | Midpoint of the flat part |
| **A** | Two slopes meeting at C4 | Break point |

The 1.5 exponent on WSAP/WSL walls is the expected contact-law for two
circular disks (Andronov 2012; Andrych et al. 2018), not an arbitrary power.

Fits use `scipy.optimize.curve_fit` (`maxfev=100000`). **Photometric
uncertainties are not used.** \(\sigma(\mathrm{ToM})\) is the Jacobian of the
ToM formula through the parameter covariance. One method is fitted per run.

If the parabolic or flat core is shorter than \(\sigma(t)\), the card warns
to try another method. If the AP vertex leaves [C4, C5], that interval fails
the ToM cut.

### Export

Compact only (`{lightcurve}_{method}`, e.g. `NSV807_WSAP`):
`# MAVKA Minimum Results`, optional `# method:`,
`# max_half_width_d: none|<value>`, optional `# PERIOD` / `# EPOCH`, then
`JD  σ`.

**Cite** Andrych et al. (2020), *J. Phys. Stud.* 24, 1902
(DOI [10.30970/jps.24.1902](https://doi.org/10.30970/jps.24.1902);
arXiv:1912.07677). For WSAP/WSL also cite Andrych et al. (2018), arXiv:1712.05030,
and Andronov (2012). Acknowledge Pyatnytskyy `lc_approx` if you use this
implementation.

Further references are listed in the MAVKA accordion help (Marsakova &
Andronov 1996; Andronov & Tkachenko 2013).

---

## Parabola

Accordion **Parabola**. Local quadratic on the **raw points inside each marked
interval**. Not the processor running-parabola *smooth*, and not MAVKA’s
asymptotic parabola. Code: `skvo_veb/utils/parabola_tom/`. Algorithm family:
Astropy `Polynomial1D` degree 2 + `LinearLSQFitter(calc_uncertainties=True)`.

Use it when the extremum is rounded and well sampled, and you do not need GP
flexibility or MAVKA wings.

The interval **is** the fit window, unless **Max half-width** is set and that
interval is wider than twice the cap: then only \(\pm\) the cap around the
**midpoint** is used. Narrower intervals are not stretched. There is no
neighbour-to-neighbour shrink. Trimmed cards show a **window capped** badge.

Need at least **five** finite points. Search minima or maxima in the current
Mag/Flux view. Vertex must lie inside the fit window. Curvature must match:

| Domain | Search min (eclipse / faint) | Search max (bright) |
|--------|------------------------------|---------------------|
| Magnitude | \(c_2 < 0\) (local max of mag) | \(c_2 > 0\) |
| Flux | \(c_2 > 0\) (local min of flux) | \(c_2 < 0\) |

### Inverse-variance weights

Off by default. When on, each in-window point is weighted by \(1/\sigma^2\).
If the light curve has no errors, or any in-window point lacks a finite
positive error, **that card fails**. The fit is not silently unweighted.

### How \(\sigma(\mathrm{ToM})\) is calculated

Formal, linearised coefficient error; not a bootstrap or a GP posterior.

Time origin \(t_\mathrm{mid}\) (interval midpoint, after any half-width cap):

\[
y = c_0 + c_1\,\Delta t + c_2\,\Delta t^2,\qquad
\Delta t = t - t_\mathrm{mid}.
\]

ToM: \(t_\mathrm{ToM} = t_\mathrm{mid} - c_1/(2c_2)\).

Astropy returns \(\mathrm{Cov}(c_0,c_1,c_2) = (A^\top A)^{-1}\) scaled by the
residual sum of squares over \(N-3\). Then

\[
J = \bigl(0,\; -1/(2c_2),\; c_1/(2c_2^2)\bigr),\qquad
\sigma(t)=\sqrt{J\,\mathrm{Cov}\,J^\top}.
\]

Review cards show seconds; compact export and O-C keep days. Magenta band is
\(\pm\sigma(t)\).

Weights **off:** photometric bars unused; scale of \(\sigma(t)\) is scatter
about the parabola. Weights **on:** \(1/\sigma^2\) enters the least squares;
the same residual-scaled covariance is propagated.

If covariance is missing or the variance is not finite and positive, the
interval fails. No \(\sigma(t)\) is invented. The figure does not include
uncertainty from the window choice, the max-half-width cap, or the wrong
min/max setting.

### Export

Compact only (`{lightcurve}_parabola`): `# Parabola Minimum|Maximum Results`,
`# weights: on|off`, `# max_half_width_d: none|<value>`, optional `# PERIOD` /
`# EPOCH`, then `JD  σ`.

---

## O-C

Accordion **O-C**. Step 1 residuals against a trial linear ephemeris. Code:
`skvo_veb/utils/oc/`.

### ToM source

| Source | What is plotted |
|--------|-----------------|
| Gaussian Process | Keep-marked successes from the GP review store |
| MAVKA | Keep-marked successes from the MAVKA store |
| Parabola | Keep-marked successes from the Parabola store |
| Upload | Compact `.dat` (GP, MAVKA, or Parabola export; also processor rough ToMs with \(\sigma=\mathrm{nan}\)) |

Upload copies `#` comment lines into the O-C `.dat` after `# source`.

Trial **P** and **Epoch** are independent of accordion 1 until **Take from
lightcurve**.

### Cycle assignment

\[
E = \mathrm{round}\bigl((t_\mathrm{ext} - T_0)/P_0\bigr),\qquad
\mathrm{O{-}C} = t_\mathrm{ext} - (T_0 + E\,P_0).
\]

**Cycle corrections:** for every ToM with \(t_\mathrm{ext} \ge\) **At ≥**
(same page display time as Epoch), add integer \(\Delta E\) to \(E\). Several
rows accumulate. Click a point to fill **At ≥** from the observed time.

### Period correction

Zoom the diagram, **Use visible range** (or restore full O-C). **Correct
period** fits a straight line to O-C versus time in that window (Astropy
linear model; cycle numbers stay fixed after shifts) and overlays it. It
**proposes** a new P and Epoch; it does not rewrite the trial fields or
replot. **Adopt ephemeris** writes the proposal into P and Epoch; press
**Plot** yourself to rebuild.

The slope \(S\) must satisfy \(|S|<1\) so \(P/(1-S)\) is defined. Iterates up
to five times (`PERIOD_CORRECT_MAX_ITER`) until \(|S|\) is below
`PERIOD_CORRECT_TOL`.

The figure is O-C (days) versus cycle number \(E\), with a calculated page-time
axis on top (MJD by default). Error bars are \(\sigma(t)\) from the ToM file.

### Export

xmgrace `.dat`: `#` metadata, then
`cycle_number  OC  sigma_jd_ext  jd_ext` (double spaces). Stem follows the
timing source (`{lc}_gp_oc`, `{lc}_WSAP_oc`, `{lc}_parabola_oc`, or the
uploaded name + `_oc`).

This page does **not** run the full multi-task O-C study in
`auxiliary/oc/run_oc.py` (YAML segments, parabolic O-C, and so on). That CLI
is a separate research tool that can consume the same compact ToM `.dat`.

---

## Compact ToM files

All three timers and O-C upload share this shape:

```text
# ... comments ...
2458749.729000	0.000150
```

Whitespace-separated JD and \(\sigma\) in days. `#` lines are kept as
metadata on O-C upload. GP may add a third integer `scale_limit` column; O-C
still only requires two numbers.

Processor `{base}_rough_toms.dat` uses `JD  nan` on purpose
([lightcurve_processor.md](lightcurve_processor.md)).

---

## What the three timers do not share

Independent packages: `utils/gp`, `utils/mavka`, `utils/parabola_tom`. They
must not import each other’s algorithms. Shared glue is
`lc_bridge` / `lc_export` / `lc_intervals` / `lc_working_window` /
`unpack_json_for_gp_plot`.

| | GP | MAVKA | Parabola |
|--|----|-------|----------|
| Photometry fitted | Normalised flux | Current Mag/Flux view | Current Mag/Flux view |
| Tabulated \(\sigma\) | Per-interval policy + Noise scale | Ignored | Optional \(1/\sigma^2\) |
| \(\sigma(t)\) | Std of 300 posterior ToMs | Jacobian of piecewise ToM | Jacobian of \( -c_1/(2c_2) \) |
| Maxima | Yes | Not in this version | Yes |
| Min. points | 5 | 6 | 5 |
| Max half-width | Optional | Optional | Optional |

---

## Scripts and spikes (not production)

`auxiliary/` is **not** imported by the running app. Spikes informed the
page; production copies live under `skvo_veb/utils/`.

| Spike | What it explored | Production counterpart |
|-------|------------------|------------------------|
| `auxiliary/lc_approx_spike/` | MAVKA batch ToMs, compact `.dat`, Step 1 O-C | `utils/mavka/`, `utils/oc/` |
| `auxiliary/lc_approx_spike/oc/` | Cycle shifts, xmgrace O-C | O-C accordion |
| `auxiliary/oc/` | Broader YAML O-C study (`run_oc.py`) | Not on this page; can read compact ToMs |
| `auxiliary/running_parabola_spike/parabola_tom.py` | Local quadratic ToM (step 3) | `utils/parabola_tom/` (interval = window; optional max half-width; no neighbour cap) |
| `auxiliary/running_parabola_spike/running_parabola.py` | Sliding smooth | Lightcurve processor Smooth, **not** this accordion |
| `auxiliary/template_timing/` | Template ToM CLI | Not on this page |
| `auxiliary/gp_presentation/` | GP outreach figures (`samples.png`) | GP accordion help image |

If a spike and the page disagree, the page and `skvo_veb/utils/` win.

---

## Code map

| Area | Location |
|------|----------|
| Page graphics (display time, card grid, colours) | `skvo_veb/components/extrema_modeller_appearance.py` |
| About / accordion help | Same file: `PAGE_ABOUT_MARKDOWN`, `LC_INTERVALS_HELP_MARKDOWN`, `GP_HELP_MARKDOWN`, `MAVKA_HELP_MARKDOWN`, `PARABOLA_HELP_MARKDOWN` |
| GP science | `skvo_veb/utils/gp/` (`pipeline.py`, `noise_policy.py`, `config.py`, `export.py`, …) |
| MAVKA science | `skvo_veb/utils/mavka/` (`models.py`, `NOTICE`, `pipeline.py`, `export.py`) |
| Parabola science | `skvo_veb/utils/parabola_tom/` |
| O-C science | `skvo_veb/utils/oc/` (`compute.py`, `period_correct.py`, `tom_io.py`, `export.py`) |
| Intervals / working JD window | `skvo_veb/utils/lc_intervals.py`, `lc_working_window.py` |
| Upload ingest | `skvo_veb/utils/lc_bridge.py`, sibling ``volightcurve`` |
| CSS | `skvo_veb/assets/gp_for_oc.css` |

Register: `dash.register_page(..., path='/gp', order=9)` (after Lightcurve Processor).
