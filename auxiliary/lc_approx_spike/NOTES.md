# lc_approx spike — notes for EB extrema timing

**Purpose of this folder.** Experimental home for trying the MIT-licensed
[mpyat2/lc_approx](https://github.com/mpyat2/lc_approx.git) phenomenological
extrema approximators alongside our template-timing / O–C pipeline.  
**Not** production code yet: discuss results here before wiring into
`run_timing` or `auxiliary/oc`.

**Upstream.** https://github.com/mpyat2/lc_approx.git (MIT, © 2025 Maksym Yu. Pyatnytskyy).  
**Science reference.** Andrych, Andronov & Chinarova (2020), *MAVKA* / asymptotic
parabola methods — [J. Phys. Stud. 24, 1902](https://doi.org/10.30970/jps.24.1902),
[arXiv:1912.07677](https://arxiv.org/abs/1912.07677).

To experiment locally, clone upstream next to this folder (do not commit a full
vendor copy unless we decide to):

```bash
cd auxiliary
git clone https://github.com/mpyat2/lc_approx.git _vendor_lc_approx
```

---

## 1. What the upstream package actually is

Small Python toolkit (not a library install): CLI + a few pure functions.

| Piece | Role |
|-------|------|
| `ila_ap.py` | CLI: load LC, fit one method, write TOM + σ, HTML preview |
| `ila_code/ila.py` | Model functions + `scipy.optimize.curve_fit` + TOM from parameters |
| `ila_code/utils.py` | Argparse, plotting, curve evaluation |
| `split_lc.py` | Build per-cycle time windows from epoch + period + phase cuts |

**Input LC format.** Whitespace `time mag` (extra columns ignored). `#` comments OK.
Default plot inverts the Y axis (magnitude convention). Flux LCs need
`--non-inverseY` and care that the models assume a **minimum** (or peak) shaped like
a trough in the fitted y-values.

**Modes.**

1. **Single window** — whole file is one extremum.
2. **Batch** — `--ranges` file from `split_lc.py`: one fit per interval
   (`point1 time1 point2 time2`).

**Outputs.** Tab-separated `result.txt` with TOM, TOM uncertainty, magnitude,
C4/C5 (junction times), and for WSL eclipse duration; plus `result.html` previews.

---

## 2. Approximation methods (what we care about)

All fits use unconstrained `curve_fit` on time-centred data. Uncertainties come
from the parameter covariance via analytic Jacobians (delta method), not from
photometric σ columns (those are ignored today).

### AP — Asymptotic Parabola (default; highest priority for us)

- Core: parabola between junction times **C4** and **C5**.
- Outside: linear “asymptotes” matched in value (and with a linear tilt term **C3**).
- Extremum time (TOM):

  `t_ext = (C4 + C5)/2 − C3/(2 C2)`

  only accepted if that time lies **inside** `[C4, C5]`.

- Propagates σ(TOM) and σ(mag) from the full covariance.

**Why useful for EBs.** Classic MAVKA-style timing of a rounded minimum with
straight-ish flanks. Close in spirit to “parabola near the bottom”, but with
explicit wing matching and a covariance-based error bar.

### WSAP — Wall-Supported Asymptotic Parabola

- Parabola in `[C4, C5]` **without** the linear tilt in the core (`C3` goes into
  `|Δt|^1.5` wall terms outside).
- TOM is forced to the **midpoint** `(C4 + C5)/2` (symmetry assumed in the core).

**Why useful.** When the bottom is fairly symmetric but the wings are steeper /
cuspy; midpoint TOM is stabler than a free vertex if C2/C3 trade off badly.

### WSL — Wall-Supported Line (flat bottom)

- Flat magnitude **C1** between C4 and C5; walls `|x|^1.5` and `|x|^3.5` outside.
- TOM = midpoint of the flat segment; also reports **eclipse duration** `C5−C4`.

**Why useful.** Total / near-total eclipses with a flat floor (some EA systems).
Duration is a bonus diagnostic we do not currently export from template fits.

### A — Two straight lines (“broken linear”)

- Rising/falling linear slopes meeting at C4 (= TOM).
- Four parameters only.

**Why useful.** Rough / sparse nights; sanity check. Usually worse than AP for
well-sampled TESS/QLP eclipses.

Method `"0"` only plots data (no fit).

---

## 3. Mapping onto *our* two timing problems

We need precise extrema for:

| Our problem | What we do today | What lc_approx offers |
|-------------|------------------|------------------------|
| **A. Individual minima** (per night / per interval) | Template shift (CC / NLS / …) in calendar time against a GP shape | Direct phenomenological fit of the **local LC window** → TOM + σ |
| **B. Template ToM** (paint `tau_peak` on μ(τ)) | GP argmin, then KvW / bisector rectification (`rectify_template_tom`) | Fit AP/WSAP **on the GP mean grid** (or on the folded stack) as another ToM estimator |

### A — Individual minima (highest immediate value)

- Our interval files already define windows (like their `ranges`).
- Running AP/WSAP on each interval’s raw photometry gives an independent clock
  that does **not** depend on template shape or fold epoch.
- Natural comparison table: `t_max` from `nls` / `cc` / … vs AP TOM vs KvW-on-template.
- `split_lc.py` is optional; we already have intervals from the timing manifests.

**Caveats for our data.**

- Upstream assumes **magnitudes** by default; our FFI/QLP pieces are often **flux**.
  Either convert to mag for the spike, or fit `−flux` / invert carefully and keep
  `--non-inverseY` consistent.
- No use of tabulated photometric errors → σ(TOM) is fit-internal only; we should
  later weight by σ or compare to our `rms_slope` errors.
- Failures are common when C4/C5 leave the window or the extremum leaves the
  parabola (they warn and set NaNs) — good fail-fast behaviour for a spike.

### B — Template ToM (second track)

Apply the same AP/WSAP formulas to a dense sampling of the **GP mean** μ(τ)
inside a narrow window around the current `tau_peak` (or around phase 0 / 0.5).

That sits next to KvW / bisector as another “paint the mark” method:

| Estimator | Idea |
|-----------|------|
| GP argmin | Floor of μ |
| KvW | Symmetry of μ |
| Bisector | Midpoints of chords |
| **AP / WSAP on μ** | Phenomenological parabola (+ walls) on μ |

Product could later be another `rectify_template_tom.method` value (e.g. `ap`,
`wsap`) writing into `tom_rectified/` — **only after** spike experiments agree
with KvW on clean templates and beat argmin on flat-bottomed ones.

WSL-on-μ is less natural for a smooth GP eclipse unless the mean is truly flat.

---

## 4. What is useful vs what to ignore (for us)

### Useful (keep / reimplement cleanly)

1. **AP and WSAP model definitions + TOM formulas** in `ila_code/ila.py`
   (`f_AP`, `f_WSAP`, `method_result`).
2. **Jacobian-based σ(TOM)** — we lack a comparable analytic error for KvW today.
3. **Quality guards**: extremum must lie in `[C4, C5]`; parabola shorter than
   σ(TOM) → warn / reject.
4. **Batch-over-windows** pattern (ranges file) — mirrors our intervals.
5. **WSL duration** as an optional EB diagnostic on flat eclipses.
6. MIT license → we may reimplement or vendor with attribution.

### Useful but secondary

7. `split_lc.py` phase-window generator — only if we lack interval files.
8. HTML preview collage — nice for human review; our matplotlib interval panels
   already cover day-to-day work.

### Not useful / do not copy as-is

9. Heavy CLI / colorama / HTML embedding — fine for their tool, not for Dash.
10. Hard-coded `MAXFEV=100000` and silent “Fatal Error” wrapper — we prefer
    explicit exceptions and logging.
11. Ignoring photometric σ and flux units — must be fixed in any integration.
12. References to unimplemented `WSAPA` in `utils.generate_curve` — dead path.
13. Pure “plot only” method `0` — irrelevant.

---

## 5. Suggested spike experiments (this folder)

Order matters: prove value on individual minima before touching the orchestrator.

1. **One TESS/QLP interval** we already timed with NLS  
   - Export time, flux (or mag) ASCII.  
   - Run upstream `ila_ap.py --method=AP` and `WSAP`.  
   - Diff TOM vs our `t_max_*` and vs interval midpoint.

2. **Whole sector via our interval file**  
   - Thin wrapper: read `intervals/*.dat` + LC → call `ila.approx` / `method_result`.  
   - Write a CSV comparable to `timing.csv` (`method=ap` / `wsap`).

3. **AP on GP mean**  
   - Load `template.npz`, sample μ(τ) on a fine grid in ±0.1–0.2 phase of the
     painted peak, fit AP/WSAP in τ, convert TOM → new `tau_peak`.  
   - Compare to KvW / bisector on the same template (NSV 807 / NW Cam cases).

4. **Decision gate**  
   - If AP tracks NLS within ~σ and improves flat-bottom cases vs GP argmin →
     propose a production `utils/` module (Astropy/SciPy hierarchy respected) and
     optional `rectify_template_tom.method: ap`.  
   - If not, keep this folder as a reference implementation only.

---

## 6. Design constraints if we later integrate

Respect existing project rules:

- Maths live in `auxiliary/template_timing/` or shared `utils/` as **pure
  functions** returning data (TOM, σ, params) — not Plotly figures.
- Prefer **SciPy `curve_fit`** (already upstream) or Astropy modeling if we need
  units; do **not** hand-roll a parabola fitter.
- Fail fast: NaN TOM + explicit reason when the extremum leaves the parabolic
  segment (same as upstream warnings).
- British English in user-facing strings; keep algorithm ids `ap`, `wsap`, `wsl`, `a`.
- Attribute MIT upstream in the module docstring / NOTICE.

---

## 7. Quick reference — parameter meaning

| Symbol | AP / WSAP / WSL | A |
|--------|-----------------|---|
| C1 | Vertical level ( mag at vertex / flat ) | Mag at kink |
| C2 | Curvature (parabola) or wall scale | Slope left |
| C3 | Tilt (AP) or wall scale (WSAP/WSL) | Slope right |
| C4 | Left junction | TOM (kink) |
| C5 | Right junction | — |

TOM (AP): midpoint shifted by `−C3/(2 C2)`.  
TOM (WSAP, WSL): midpoint `(C4+C5)/2`.  
TOM (A): `C4`.

---

## 8. Folder layout (spike)

```text
auxiliary/lc_approx_spike/
  README.md          # short pointer
  NOTES.md           # this file
  scripts/           # thin experiment CLIs (add as we go)
  data/              # optional tiny excerpts / symlinks (gitignored if large)
```

Upstream clone (optional, local only): `auxiliary/_vendor_lc_approx/` or
`/tmp/lc_approx_review` as used for this review.

---

## 9. Step 1 implemented (this folder) — individual intervals

**Status.** First spike CLI is in place. Nothing outside
``auxiliary/lc_approx_spike`` was modified; LC/interval loading **imports**
helpers from ``template_timing`` / ``skvo_veb``.

### Layout

```text
lc_approx_spike/
  paths.py              # sys.path bootstrap
  io_spike.py           # VOTable + interval loaders (reuse project I/O)
  vendor/
    NOTICE              # MIT attribution
    ila_models.py       # AP / WSAP / WSL / A (adapted from lc_approx)
  scripts/
    run_interval_approx.py
  data/                 # your .vot + interval .dat files
  data/runs/            # CSV + PNG outputs from the spike
```

### Run

```bash
cd auxiliary/lc_approx_spike
../../.venv/bin/python scripts/run_interval_approx.py \
  --lc data/NWCam_sector_59_ffi_flat.vot \
  --intervals data/NWCam_59_prim.dat \
  --domain flux \
  --method AP \
  --max-intervals 3 \
  --save-plots
```

Same for ``--method WSAP`` (recommended first look on these flux FFI LCs).

### Early experimental findings (NW Cam 59 prim, first 3 intervals)

| Method | Formal σ(TOM) | Notes |
|--------|---------------|--------|
| **AP** | hundreds–thousands of seconds | Quality warning: parabolic core shorter than σ; TOM still returned |
| **WSAP** | ~45 s | Stable midpoint TOM; RMS ~0.014 in flux; no quality warning |

Interpretation (hypothesis for later steps): on **flux** dips, unconstrained AP
(C2/C3 trade-off) is poorly conditioned; **WSAP** (symmetric core) is the better
default for these TESS FFI windows. Interval 0 remains the truncated sector-start
window (large AP σ) — same pathology we already know from template fits.

NSV 489 sector 85 prim (first 3): AP similarly over-dispersed; try WSAP next.

### Interval / time convention in ``data/``

Your interval files use **absolute JD** in both columns (e.g. ``2459912…``).
The spike loader treats them as JD (same as ``intervals_time.scale: jd`` in
timing manifests). If you later drop MJD-only intervals here, extend
``io_spike.py`` with an explicit scale flag.

---

## 9b. Step 2 — multi-method batch (MAVKA-style)

**Status.** ``scripts/run_batch_approx.py`` fits **AP + WSAP + WSL** (optional
``A``) on each interval of the same LC, writes a long CSV and a wide comparison
table, and picks a **best** method per window = smallest formal σ(TOM) among
successful fits.

Defaults point at the current working pair:

- LC: ``data/NSV_807_sector_97_flatten.vot``
- Intervals: ``data/NSV_807_sector_97_prim.dat``

```bash
cd auxiliary/lc_approx_spike
../../.venv/bin/python scripts/run_batch_approx.py \
  --domain flux \
  --save-plots --plot-max 5
```

``--plot-max 0`` (default) = plot every fitted interval; use a small positive
cap for a quick sample. ``--show-plots`` opens a blocking window per plotted
interval (close each window to continue).

Outputs under ``data/runs/<lc>_<intervals>/``:

| File | Content |
|------|---------|
| ``approx_batch.csv`` | One row per ``(interval, method)`` |
| ``approx_compare.csv`` | One row per interval; columns per method + ``best_*`` + Δt vs AP |
| ``interval_XX_batch.png`` | Optional multi-panel (left / core / right coloured) |

``--max-intervals 0`` (default) = all intervals. ``--methods AP,WSAP,WSL,A`` to
include the broken-linear check.

### Early batch finding (NSV 807 sector 97 prim, 130 windows)

- **129 / 130** fitted (interval 32 skipped: only 1 LC point in the window).
- **Best method = WSAP for all 129** (min formal σ(TOM)).
- WSAP σ typically a few seconds; AP often much larger / quality warnings —
  same pattern as the earlier NW Cam flux windows.
- Sample multi-panel PNGs: ``interval_00``…``04_batch.png``.

---

## 9c. Step 3 — O-C from approx TOMs (Step 1 only)

**Status.** ``oc/run_oc_step1.py`` builds O-C vs cycle from ``approx_batch.csv``
(or ``approx_compare.csv``) for a chosen method, with optional ``--cycle-shift``
corrections (same rule as ``auxiliary/oc``). Formal σ(TOM) are drawn as error
bars and written to the O-C CSV.

```bash
cd auxiliary/lc_approx_spike/oc
../../../.venv/bin/python run_oc_step1.py \
  --tom-csv ../data/runs/NSV_807_sector_97_flatten_NSV_807_sector_97_prim/approx_batch.csv \
  --method WSAP \
  --t0 57711.3539 --p0 0.3389614 --time-scale mjd \
  --save-plot --show
```

Ephemeris defaults match ``auxiliary/oc/oc_configs/NSV807_sector97_ffi_main.yaml``.
No segment-period or parabolic tasks here — those stay in ``auxiliary/oc``.

---

## 10. Issues / improvements *outside* this folder (report only)

Observed while running the spike (no code changes made outside):

1. **VOTable ingest warning**  
   ``Invalid zp_flux_unit '---'`` from ``skvo_veb.volightcurve.lightcurve`` on
   both NW Cam and NSV 489 FFI flats. Harmless for flux-native curves so far,
   but noisy; worth a cleaner metadata parse upstream when convenient.

2. **Possible later product idea (not requested yet)**  
   Optional per-interval AP/WSAP column beside CC/NLS in ``template_timing``,
   or a ``timing.method: wsap`` experiment — only after we compare TOMs to
   ``fit_summary`` on the same intervals.

3. **Shared interval helper**  
   ``load_intervals_absolute`` lives in ``manifest_config`` and needs a
   ``TimeScaleConfig``. A tiny public ``load_intervals_jd(path)`` in
   ``template_timing`` would help spikes; we inlined the JD-only case here
   instead of touching that package.

