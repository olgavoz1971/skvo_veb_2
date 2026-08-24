# Template timing: simple HOWTO

This folder turns a **detrended light curve** plus **interval files** into a list of **maximum times** (`t_max`) and a picture of the LC with maxima marked.

You do **not** edit Python for a normal run. You edit one **YAML manifest** and run one command.

---

## What you need before you start

1. **One detrended LC file** (ASCII `.dat`, magnitudes already detrended).  
   Example: `data/R_detrended.dat`

2. **Step 1 fold defaults** (only when building templates):
   - `default_epoch` (default fold epoch; phase 0 anchor when a piece has no `local_epoch`)
   - `default_period` (used if a piece has no `local_period`)
   - optional `period_slope` (usually `0.0`)

3. **For each dense chunk of data** (“piece”):
   - **Template window** `[t_min, t_max]`: a segment with enough points to define the **shape** of one hump (Step 1, slow GP).
   - **Fit window**: usually the same as the template window; must cover all your intervals.
   - **Intervals file**: one row per hump you want timed (same format as elsewhere in the project, e.g. `data/intervals_59857.dat`).

4. A **manifest YAML** (see `manifests/manifest.yaml` or `examples/`).

Paths in the YAML are **relative to the manifest file**, not to where you run the command.

---

## The pipeline (what the program does)

| Step | Name | Slow? | Output |
|------|------|-------|--------|
| **1a** | Obtain **template** per piece (`template_engine: gp` or `mavka`) | Yes if building | `pieces/<id>/template.npz`, `template_meta.json`, diagnostic PNG |
| **1b** | Optional **ToM rectification** (`rectify_template_tom`; **GP only**) | Seconds | `pieces/<id>/tom_rectified/` (+ diagnostics under `tom_rectify/`) |
| **2** | **Fit** template in each interval / segment | Faster | `fit_summary.csv`, optional `fits/interval_XX.png` |

**Template engine (global).** Set top-level ``template_engine: gp`` (default) or
``mavka``. A run is never mixed. For ``mavka``, points inside the piece’s
**timing intervals** are folded with the **common** ``default_epoch`` /
``local_epoch`` (single phase copy). The phase window is then **shifted** so the
stacked extremum is contiguous near τ≈0 (circular mean phase of interval
midpoints) — secondary near phase 0.5 is fine without a second epoch or
``eclipse_phase``. This is **not** the GP multi-copy extended fold. AP/WSAP/WSL
are fit on that stack; ``tau_peak`` is the **MAVKA TOM** (not an argmin). Meta
stores ``fold_epoch`` as the τ-axis origin (ephemeris epoch + shift) and
``mavka.phase_window_shift`` / ``mavka.fold_epoch_ephemeris`` for provenance.
``mavka_template.method`` is ``best`` (smallest formal σ among ok fits
**without** quality warnings) or a fixed ``ap`` / ``wsap`` / ``wsl``.
``rectify_template_tom`` is skipped with a log line; ``derive_secondary`` is not
supported (rebuild secondary with its own intervals). Uncertainties on the
MAVKA μ grid are deferred (placeholder RMS). Prefer ``timing.error_model: none``
for now: ``rms_slope`` is undefined at a symmetric MAVKA TOM (zero template
slope).

MAVKA smoke test (short MJD cut)::

```bash
python run_timing.py --config manifests/manifest_NSV807_sector97_ffi_main_mavka_cut.yaml --template-only
```

Step 2 loads the template named by **`fit_template`** (`obtained` or `tom_rectified`). That choice is independent of whether Step 1b ran.

At the end of each active segment, official timing is written under **`pieces/<piece_id>/timing.csv`**. A merged **`run_dir/timing.csv`** is **not** updated automatically; use **`--export-only`** when you want the combined run file.

## Run it

From **`auxiliary/template_timing`** (adjust venv path if yours differs):

```bash
cd auxiliary/template_timing
../../.venv/bin/python run_timing.py --config manifests/manifest.yaml
```

### Command-line options

| Flag | What it does |
|------|----------------|
| **`--config PATH`** | Required. Your manifest YAML. |
| **`--dry-run`** | Only checks the manifest and paths. No GP, no fits, no plots written. |
| **`--show-plots`** | After each figure is saved, also open an **interactive** matplotlib window (`plt.show()`). You must **close each window** before the run continues. Without this flag, plots are **only saved to files** under `run_dir` (default behaviour). Not used for `--review-fits` windows (those always block until you press a key). |
| **`--review-fits`** | After each interval fit, open a **4-panel review** window. Press **`1`/`c`**, **`2`/`n`**, **`3`/`l`**, or **`4`/`s`** to accept that method as the official timing for **this interval only**. Press **`r`** to **reject** (the row is kept but written as a **`#`-commented line** in all timing CSVs and `fit_summary.csv`). **Enter** or **space** accepts the manifest default method. |
| **`--review-only`** | Skip Step 1 and refitting. Reload existing `pieces/<id>/fit_summary.csv`, run interactive review, then rewrite **that segment's** `pieces/<id>/timing.csv` only. Opens that segment's overview when review ends. |
| **`--export-only`** | **Explicit merge:** rebuild `run_dir/timing.csv` and run overview from all `pieces/*/fit_summary.csv`. Does not refit or re-review. |
| **`--template-only`** | Run Step **1a** and optional ToM rectification (**1b**); skip fitting. |
| **`--fit-only`** | Skip rebuild / rectify; fit using on-disk templates chosen by **`fit_template`** (`obtained` or `tom_rectified`). |

**Interactive pop-ups while you work on the machine:**

```bash
python run_timing.py --config manifests/manifest.yaml --show-plots
```

**Fit + review in one go:**

```bash
python run_timing.py --config manifests/manifest.yaml --review-fits
```

**Silent fit first, review later** (segment overview opens when review ends):

```bash
python run_timing.py --config manifests/manifest.yaml
python run_timing.py --config manifests/manifest.yaml --review-only
```

**Merge all segments into one run-level file** (only when you ask for it):

```bash
python run_timing.py --config manifests/manifest.yaml --export-only
```

**No GUI windows** (figures still saved to `run_dir`; good for SSH or batch):

```bash
MPLBACKEND=Agg python run_timing.py --config manifests/manifest.yaml
```

You can combine `--dry-run` with nothing else useful; do not expect plots from dry-run.

**Check the manifest only:**

```bash
python run_timing.py --config manifests/manifest.yaml --dry-run
```

---

## Where results go

Whatever you set under `global.output.run_dir`, for example:

`data/runs/two_intervals/`

Important files:

- **`pieces/<piece_id>/timing.csv`** — official maxima for **that segment only** (`timing_method` = your per-row review choice)
- **`pieces/<piece_id>/timing_<method>.csv`** — same segment, one file per fit method
- **`pieces/<piece_id>/fit_summary.csv`** — wide table (all methods + `selected_method`, `rejected`)
- **`pieces/<piece_id>/overview_lc_maxima.png`** — LC overview for that segment (when plots enabled)
- **`pieces/<piece_id>/fits/`** — four-panel interval plots (if `save_interval_plots: true`)
- **`timing.csv`** (under `run_dir`) — **merged** table; written only by **`--export-only`**
- **`overview_lc_maxima.png`** (under `run_dir`) — full-run overview; written only by **`--export-only`**

### The four-panel interval plot

Each interval fit produces one wide figure (`pieces/<id>/fits/interval_XX.png`, or the same layout in **`--review-fits`** / **`--review-only`** pop-ups):

| Panel | Method | Keys (review) |
|-------|--------|---------------|
| 1 | Cross-correlation (`cc`) | `1` or `c` |
| 2 | Nonlinear least squares (`nls`) | `2` or `n` |
| 3 | NLS + iterative outlier clean (`nls_clean`) | `3` or `l` |
| 4 | NLS + scale + outlier clean (`nls_scale_clean`) | `4` or `s` |

Each panel shows the LC points, the shifted template, and a magenta **`t_max`** line. Panel titles include RMS, point count, Δt, and scale.

**Caption / fonts:** titles and axis labels use the shared Step 2 style (`plot_style.py`, **`FONT_SIZE = 20`**). The figure caption (interval id and JD bounds) uses the same size. During review, the keyboard hint line under the caption is slightly smaller (`0.65 × FONT_SIZE`, matching legend text). Saved PNGs and review windows share this styling.

Press **`r`** to reject an interval; **Enter** or **space** accepts the manifest default method.

### Step 2 (fitting) vs Step 1 (template)

**Step 2** uses **only** LC time and interval bounds. Template **μ(days from peak)**; **y(t) ≈ s·μ(t − t_max) + b**; **no fold epoch, period, or cycles**.

**Step 1** uses **`global.template_fold`** (**`default_epoch`**, **`default_period`**) and per-piece **`local_epoch`** / **`local_period`** when set. Template meta records **`fold_epoch`** and **`fold_period`** (values actually used to stack that μ shape) plus manifest defaults at build time.

| Setting | Role |
|--------|------|
| **`template_fold.default_epoch`** | Default fold epoch when a piece has no **`local_epoch`** (Step 1 only). Sets where phase 0 falls so peak/minimum selection near τ = 0 is meaningful. |
| **`pieces[].local_epoch`** | Fold epoch for that piece’s Step 1 build; overrides **`default_epoch`**. Ignored in Step 2. |
| **`template_fold.default_period`** | Fallback fold P when a piece has no **`local_period`** (Step 1 only). |
| **`pieces[].local_period`** | Fold P for that piece’s Step 1 build; overrides **`default_period`**. Ignored in Step 2. |
| **`template_meta.json` → `fold_epoch`, `fold_period`** | Labels on the artefact: fold origin and P used when stacking. Not read for fitting. |

---

## Manifest cheat sheet

### Global (once per run)

- **`lc_path`** — default detrended LC for every piece (Step 1 template window + Step 2 fits)
- **`template_fold`** — **`default_epoch`**, **`default_period`** (Step 1 only; legacy `ephemeris` / `t_ref` / `p0` still load with warnings)
- **`timing.method`** — which fit defines `t_max` in `timing.csv`:
  - `cc`, `nls`, `nls_clean`, **`nls_scale_clean`** (usual choice)
- **`timing.error_model`** — `rms_slope` or `none`
- **`plots.save_interval_plots`** — `true` / `false` (default on in examples)
- **`plots.save_overview`** — whole-LC plot with maxima

### `gp_template_defaults` (Step 1 peak / GP; overridable per piece via `gp_template:`)

**How `tau_peak` is chosen.** The GP grid is padded beyond the folded data so the mean stays
smooth at the ends; that pad is **never** searched. Candidates are local extrema of the GP mean
inside the folded data range, inset by an edge margin, ranked by **topographic prominence**
relative to the peak-to-peak amplitude *inside that range*. Because the extended fold stacks
`φ` and `φ+1`, every extremum appears twice one period apart, so candidates are grouped into
**phase classes** (`τ/P` mod 1). The dominant class wins, and within it the **best-centred copy**
is used: the one with the widest symmetric span of folded data around it (ties go to the copy
nearer τ = 0, the one you target with `local_epoch`). Since the extended fold covers exactly 2 P,
one copy always sits at least half a period from both ends, so **any** Step 2 window up to a full
cycle is backed by real photometry. If nothing survives the cuts, the run **stops** with the full
candidate list in the error message — there is no fallback to the grid extremum.

- **`extrema_mode`** — `max` or `min`; everything below is applied to that kind of extremum
- **`peak_edge_margin_frac_period`** — candidate search window is inset from each end of the
  folded data range by this fraction of **P** (default `0.05`). Raise it if the GP turns up at
  the ends and invents an extremum there.
- **`peak_min_prominence_frac`** — minimum prominence as a fraction of the in-range peak-to-peak
  amplitude (default `0.25`). This is real prominence — how far you must descend before you can
  reach anything higher — not raw height, so a low secondary hump is rejected even if it sits
  well above the baseline.
- **`peak_min_separation_frac_period`** — minimum spacing between candidates as a fraction of
  **P** (default `0.15`); merges ripples on one lobe
- **`peak_duplicate_phase_tol`** — phase tolerance for treating two candidates as copies of the
  same extremum (default `0.05`)
- **`peak_select`** — `dominant` (most prominent class, default) or `nearest_phase0`
- **`peak_phase_hint`** — optional phase in `[0, 1)`; when set, the class nearest
  `peak_phase_hint · P` wins and `peak_select` is ignored. Prefer this over the
  legacy absolute-day `peak_tau_hint`.
- **`length_scale_init_frac_period` / `_min_` / `_max_`** — GP Matérn/RBF length
  scale as a **fraction of P** (defaults `0.02` / `0.01` / `0.03`). Change **P**
  only when moving EB → Mira; do not retune absolute days. Legacy
  `length_scale_init` / `_min` / `_max` (days) still load with a deprecation warning.

`template_meta.json` records the whole decision under `peak_selection`: the search window, the
in-range amplitude, the symmetric photometric support of the chosen copy, every candidate with its
τ, μ, prominence and phase, the rejection reason for those that were dropped, and a plain-language
`reason` for the winner. `template_gp.png` marks accepted candidates with green triangles, rejected
ones with grey crosses, and greys out the pad and edge margin.

The Step 2 fit window is **not** set here and is **not** a property of the template — see below.

### `fit_defaults` (Step 2; overridable per piece via `fit:`)

**Which part of the cycle is fitted.** You declare it; nothing is inferred from the GP. The window
is always symmetric about the timed extremum and is re-resolved from the manifest on **every run**,
so you can switch between a full cycle and a narrow flank without rebuilding any template.

- **`fit_mask_mode`**
  - **`whole_period`** (default) — one full cycle: `t − t_max` in `[−P/2, +P/2]`
  - **`frac_period`** — `t − t_max` in `[−h·P, +h·P]` with `h` = `fit_mask_half_width_phase`
- **`fit_mask_half_width_phase`** — half width **in phase units**, used only by `frac_period`.
  Must be in `(0, 0.5]`; e.g. `0.3` means ±0.3 P around the peak. Values above `0.5` are
  **rejected** at manifest load rather than clamped — use `whole_period` for a full cycle.
- **`delta_t_max_phase`** — half-width of the allowed peak shift from the interval
  **midpoint**, as a **fraction of P** (default `0.05`). Resolved to days as
  `delta_t_max_phase · fold_period`. This is what stops a truncated first cycle
  from latching on the search edge when the eclipse is far from the window centre.
- **`delta_t_margin_phase`** — small phase pad used when the interval is shorter
  than `2 · delta_t_max` (default `0.01`). Legacy `delta_tau_max` /
  `delta_tau_margin` (absolute days) still load with a deprecation warning.

**Rule of thumb:** anything that means “how far in the cycle” is **phase** (or
`*_frac_period`). Only epoch, LC windows, and **period** stay in days.

**P** for masks and ``delta_t`` limits is the template's own ``fold_period``
(the axis the shape was stacked on). Piece-level ``local_period`` still plays no
part in Step 2 fitting.

Example, whole cycle everywhere except one piece that wants only the flank:

```yaml
fit_defaults:
  fit_mask_mode: whole_period

pieces:
  - piece_id: "59878"
    fit:
      fit_mask_mode: frac_period
      fit_mask_half_width_phase: 0.3
```

**Edges.** The template is defined only where folded photometry exists; the GP pad is
extrapolation and is treated as undefined, so nothing is ever fitted against invented shape. If a
window somehow reaches past that support, the run logs a warning naming the piece and the bounds,
and the affected points drop out of every fit. An interval shorter than the window is simply used
in full — the window is intersected with the interval, which is normal for a short night.

The resolved window is logged per piece (`fit mask whole_period: +/-0.500 in phase = ...`), drawn
as the orange band on `template_gp.png`, and snapshotted in `template_meta.json` under
`fit_mask_at_build` for provenance only.

**Rebuild note.** Templates written before this change lack `tau_data_min` / `tau_data_max`, so a
piece pointing at such a run directory with `existing_template_dir` **fails fast** with an
instruction to rebuild; the photometric support of the fold cannot be recovered afterwards.

### Each entry under `pieces:`

- **`piece_id`** — short label (e.g. `"59857"`)
- **`skip`** — optional; if **`true`**, this piece is listed but Step 1 and Step 2 are not run (no output under `pieces/<id>/`, no rows in `timing.csv`). Intervals file is not checked. Another piece cannot `reuse_template_from` a skipped piece.
- **`timing_mode`** — optional; default **`per_interval`**. Set to **`segment_anchor`** for sparse segments where you want **one** Step 2 timing point over the whole **`fit_window`** (no **`intervals_path`**). See [Segment-anchor timing](#segment-anchor-timing-sparse-segments) below.
- **`anchor_epoch`** — optional; used only when **`timing_mode: segment_anchor`**. Which cycle the ensemble ToM is written on: **`window_centre`** (default), **`window_start`**, or **`window_end`**. The fit itself is in fold space (all cycles); this only chooses **E** for `t_max = T0 + E P + tau_peak + delta_t`. Step 1 still uses **`local_epoch`** / **`default_epoch`** for building the template. Quadratic **`fold_ephemeris`** is not allowed with **`segment_anchor`**.
- **`template_window`** — `{ t_min, t_max }` for Step 1 GP build. Required for **`per_interval`**; for **`segment_anchor`**, defaults to **`fit_window`** if omitted. Ignored when reusing a template (`existing_template_dir` / `reuse_template_from`) or when **`derive_secondary`** is set. Set **both** to **`null`** to use the full time span of the piece LC file (`local_lc_path` or global **`lc_path`**); bounds are read from the file at manifest load (logged as absolute JD).
- **`fit_window`** — time range where Step 2 loads the LC (manifest time scale, or **`null`/`null`** for full LC as above). For **`per_interval`**, intervals in the file that **do not overlap** this window are **skipped** (logged); at least **one** interval must overlap or manifest load fails. For **`segment_anchor`**, every point in the window is folded and used in the ensemble fit (interval index **`0`** in outputs).
- **`intervals_path`** — file with interval start/end times; **required** for **`per_interval`**, **not used** for **`segment_anchor`** (may be omitted).
- **`local_period`** — optional; Step 1 fold period for this piece. If omitted, **`default_period`** is used. **Not used in Step 2 fitting.**
- **`local_lc_path`** — optional; detrended LC file for this piece only (relative to the manifest directory). If omitted, global **`lc_path`** is used for Step 1 and Step 2 on this piece. Useful for a pre-cut segment file (e.g. one epoch’s `.dat`) while other pieces use the full archive.
- **`local_epoch`** — optional; Step 1 fold epoch (truncated JD) for this piece. If omitted, **`template_fold.default_epoch`** is used. Use when you want phase 0 centred on a known maximum/minimum in that LC segment for a sharper template. **Not used in Step 2.** You are responsible for using a sensible template when reusing paths.

**Full LC window** (optional convenience; Step 1 on an entire sector is slow and often worse than a dense hump slice):

```yaml
fit_window:
  t_min: null
  t_max: null
```

Both keys must be **`null`** together; one null and one number is rejected. Extent comes from **`local_lc_path`** when set, otherwise global **`lc_path`**.

### Segment-anchor timing (sparse segments)

Use **`timing_mode: segment_anchor`** when a piece spans **several cycles** but you only want **one** O-C point for the whole segment (e.g. early sparse ground data), not one point per observing night.

```yaml
  - piece_id: "early_sparse"
    timing_mode: segment_anchor
    anchor_epoch: window_centre   # reporting cycle for the ensemble ToM (not the fold epoch)
    existing_template_dir: ../data/runs/ground_R/pieces/early
    fit_window:
      t_min: 59853.0
      t_max: 59858.203804
    local_epoch: 59866.380310805   # Step 1 fold only
    local_period: 0.05937839
```

**Step 1 (template):** unchanged — fold with **`local_epoch`** / **`default_epoch`**, build or reuse GP template. Omit **`existing_template_dir`** to rebuild; **`template_window`** defaults to **`fit_window`** when omitted.

**Step 2 (ensemble ToM):** fold **all** points in **`fit_window`** with the template’s constant period and epoch, then run the four methods in **tau** (the stacked segment). The fitted shift ``delta_t`` is one number for the whole stack. Calendar time is that shift placed on the cycle nearest **`anchor_epoch`**:

`t_max = T0 + E P + tau_peak + delta_t`  (`t_anchor` is the unshifted peak on that cycle; `t_max = t_anchor + delta_t`).

Piece **`local_period`** must match the template **`fold_period`**. Quadratic **`fold_ephemeris`** is not supported. Outputs use **`interval: 0`**, plot **`fits/segment_anchor.png`**, and **`timing_mode`** / **`anchor_epoch`** / **`cycle_index`** in **`fit_summary.csv`**.

**Review plot (`segment_anchor.png`):** two rows, both in fold time. **Top:** folded segment vs **unshifted** template (shape check). **Bottom:** the four methods on the **same stacked points** (orange mask); `n` is the ensemble, not one cycle. Step 1 fold quality is also in **`template_gp.png`**.

**When not to use it:** single-cycle or single-hump segments — keep **`per_interval`** (default).

---

## Skip Step 1 when you already have a template (save time)

You already ran Step 1 once and have `template.npz` + `template_meta.json`. **Do not rebuild** unless the LC slice or GP settings changed.

### Same piece, files from an old run

```yaml
existing_template_dir: ../data/runs/two_intervals/pieces/59857
```

- **`existing_template_dir`** — folder with `template.npz` + `template_meta.json`. Step 1 GP is skipped.
- If that path is **the same** as this run’s output `pieces/59857/` (same `run_dir` as last time), files are not copied again; Step 2 runs only.

**Tip:** To force a **new** GP template, remove `existing_template_dir` for that piece (or point to a different `run_dir`).

### Another piece in the *same* manifest (same run)

List the **source piece first**, then:

```yaml
reuse_template_from: "59857"
```

**Use only one** of `existing_template_dir` and `reuse_template_from` per piece.

The orchestrator does **not** check that a loaded template’s **`fold_period`** meta matches the piece; that is your responsibility.

### Secondary eclipse from the same template (no GP rebuild)

After the **primary** template exists, a secondary-eclipse piece can reuse that grid and paint the other accepted minimum class (~0.5 phase). The GP is **not** rebuilt. Interval `.dat` files stay in calendar time; do not shift them by 0.5 phase.

```yaml
existing_template_dir: ../data/runs/NSV_807_30_SPOC_main/pieces/1
derive_secondary:
  method: other_min_class   # only method implemented
  phase_offset: 0.5
  phase_tolerance: 0.15
```

- **`existing_template_dir`** — primary template folder (`template.npz` + `template_meta.json`). **Never overwritten.**
- **`derive_secondary`** — writes a **new** bundle into **this** run’s `pieces/<id>/` with the same `tau` / `mu` / `sigma` and a relabelled `tau_peak`. Step 2 then fits that copy against the secondary interval file.
- **`method: other_min_class`** — among **accepted** `peak_selection.candidates`, take the class nearest `(primary_phase + phase_offset) mod 1`. Fail if none lies within **`phase_tolerance`** (no silent 0.5 shift, no windowed argmin fallback).
- **`run_dir`** must differ from the primary run, otherwise the write would clobber the source.
- Prefer pointing **`existing_template_dir`** at the primary’s **`tom_rectified/`** when that folder exists (whatever **`method`** produced it). Fall back to the primary `pieces/<id>/` only if ToM was never rectified.
- Order when both apply: **`derive_secondary` → `rectify_template_tom`** on the derived secondary bundle.

Do **not** set `peak_phase_hint` / `peak_tau_hint` for this path; the painted mark is chosen from the stored candidate table.

### ToM rectification (optional Step 1b)

After Step 1a, you can relabel **`tau_peak`** with KvW or a bisector estimate **without rebuilding the GP**. The source Step 1a artefacts are never overwritten.

**Two independent knobs:**

| Key | Role |
|-----|------|
| **`rectify_template_tom.enabled`** | Whether to **run/update** Step 1b into `tom_rectified/` |
| **`fit_template`** | Which folder Step 2 **loads**: `obtained` (1a / GP-argmin or derived) or `tom_rectified` |

```yaml
fit_template: tom_rectified   # or obtained; default is obtained

rectify_template_tom_defaults:
  include: epoch_spike/configs/_defaults.yaml   # shared scientific profile
  enabled: false
  method: kvw   # kvw | bisector_core | bisector_extrap

pieces:
  - piece_id: "1"
    fit_template: tom_rectified   # optional per-piece override
    rectify_template_tom:
      enabled: true
      # method: bisector_core   # optional override
```

- **`method`** — algorithm that paints the new template ToM (stored in meta; **not** part of the folder name).
- Product path is always **`pieces/<id>/tom_rectified/`**.
- Diagnostics (marks, ladder, KvW cost) go under **`pieces/<id>/tom_rectify/`**.
- Re-fit intervals on the GP-argmin template after a rectified product exists: set **`fit_template: obtained`** (and optionally `rectify_template_tom.enabled: false` if you do not want to refresh 1b). Leftover `tom_rectified/` is ignored when `fit_template` is `obtained`.
- Re-fit on the rectified mark without re-running KvW: **`fit_template: tom_rectified`** and **`enabled: false`** (folder must already exist; otherwise the run fails fast).
- Works the same for **`per_interval`** and **`segment_anchor`**.

Standalone experiments can still use `epoch_spike/run_epoch_spike.py`; for production timing runs prefer this manifest block.

---

## Timing methods (which column wins)

All four methods are computed for every interval. Compare methods via **`timing_<method>.csv`** in `run_dir` or the wide **`fit_summary.csv`** per piece.

**Official timing per segment:** `pieces/<id>/timing.csv` — one row per accepted interval; **`timing_method`** is your selected method for that row. Without review, every row uses the manifest default **`timing.method`** (stored as **`selected_method`** in `fit_summary.csv`).

**Run-level `timing.csv`:** optional merged copy; create it only with **`--export-only`**.

**Rejected intervals:** press **`r`** during review. The row stays in the segment files but is prefixed with **`#`** (skipped by downstream loaders such as `plot_oc.py`). Cycle / interval index remains traceable. On **`--review-only`**, commented rows are **not shown again**; if you change nothing, `fit_summary.csv` is rewritten **verbatim** (same commented rows, same order). Segment **`timing.csv`** is **always refreshed** from the summary after review (so method changes and stale exports stay in sync).

- **`nls_scale_clean`** — NLS + outlier cleaning + scale `s` (most flexible; default in examples)

Per-piece wide table: `pieces/<id>/fit_summary.csv` (all methods + `selected_method`, `rejected`, and `sigma_t_max_*` when errors enabled).

---

## Old sniff scripts (optional)

Still usable for experiments; constants are hardcoded in the file:

- `build_template.py` — Step 1 only
- `fit_template_sniff.py` — Step 2 only

For real work, prefer **`run_timing.py` + manifest**.

---

## When something fails

The program is meant to **stop with an error** instead of guessing.

Common fixes:

- **No interval overlaps fit window** — widen `fit_window`, or add intervals that intersect it; extras outside the window are skipped, not errors.
- **`existing_template_dir` not found or missing npz/meta** — check the path relative to the manifest.
- **`derive_secondary` cannot find the other class** — inspect `peak_selection.candidates` on the primary template; do not lower prominence silently. Rebuild the primary if the secondary was rejected.
- **One interval has too few points in the fit mask** — that cycle is marked **rejected** (`#` in the CSV) and the run continues. Check `fit_fail_reason` on the summary row.
- **LC empty in window** — wrong `t_min`/`t_max` or wrong `lc_path`.

---

## Minimal workflow (copy-paste mindset)

1. Copy `examples/manifest_59857_only.yaml` or `manifests/manifest.yaml`.
2. Set `lc_path`, ephemeris, windows, interval files, `run_dir`.
3. `--dry-run`
4. Full run (add `--show-plots` for pop-ups, or `MPLBACKEND=Agg` for headless).
5. Open `pieces/<id>/timing.csv` and `pieces/<id>/overview_lc_maxima.png` for each segment you ran.
6. Next time: add `existing_template_dir` on pieces where the template is unchanged; rerun for new fits only (`skip: true` on finished segments).

**Incremental segment runs:** set `skip: true` on finished pieces; only the active segment's `pieces/<id>/timing.csv` is written. Other segments are never touched.

**Merged run file:** when all segments are ready, run **`--export-only`** to build `run_dir/timing.csv`.

---

## Example manifest location

- Working two-piece example: `manifests/manifest.yaml`
- Smaller examples: `examples/`

If in doubt, compare your YAML to those files line by line.
