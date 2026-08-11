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

## The two steps (what the program does)

| Step | Name | Slow? | Output |
|------|------|-------|--------|
| **1** | Build GP **template** per piece | Yes (minutes per piece) | `template.npz`, `template_meta.json`, `template_gp.png` |
| **2** | **Fit** template in each interval | Faster | `fit_summary.csv`, optional `fits/interval_XX.png` |

At the end, everything is merged into **`timing.csv`** and **`overview_lc_maxima.png`** in the run folder.

---

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
| **`--show-plots`** | After each figure is saved, also open an **interactive** matplotlib window (`plt.show()`). You must **close each window** before the run continues. Without this flag, plots are **only saved to files** under `run_dir` (default behaviour). |

**Interactive pop-ups while you work on the machine:**

```bash
python run_timing.py --config manifests/manifest.yaml --show-plots
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

- **`timing.csv`** — merged maxima for the manifest **`timing.method`** (official)
- **`timing_cc.csv`**, **`timing_nls.csv`**, **`timing_nls_clean.csv`**, **`timing_nls_scale_clean.csv`** — same columns, one file per fit method
- **`overview_lc_maxima.png`** — LC with vertical lines at each official `t_max`
- **`pieces/<piece_id>/`** — template + per-piece **`fit_summary.csv`** (all four methods in one wide table, plus `sigma_t_max_*` when errors are enabled)
- **`pieces/<piece_id>/fits/`** — 4-panel debug plots (if `save_interval_plots: true`)

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
- **`peak_tau_hint`** — optional τ in days; when set, the class nearest this value wins and
  `peak_select` is ignored. Use it for double-humped light curves where only you can say which
  hump is "the" maximum.
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

**P** is the template's own `fold_period` (the axis the shape was stacked on), so the window
matches the τ axis exactly. Piece-level `local_period` still plays no part in Step 2.

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
- **`template_window`** — `{ t_min, t_max }` for Step 1 GP build (required in YAML; ignored when reusing a template).
- **`fit_window`** — truncated JD range where Step 2 loads the LC and fits intervals. Intervals in the file that **do not overlap** this window are **skipped** (logged). At least **one** interval must overlap or manifest load fails.
- **`intervals_path`** — file with interval start/end times
- **`local_period`** — optional; Step 1 fold period for this piece. If omitted, **`default_period`** is used. **Not used in Step 2 fitting.**
- **`local_lc_path`** — optional; detrended LC file for this piece only (relative to the manifest directory). If omitted, global **`lc_path`** is used for Step 1 and Step 2 on this piece. Useful for a pre-cut segment file (e.g. one epoch’s `.dat`) while other pieces use the full archive.
- **`local_epoch`** — optional; Step 1 fold epoch (truncated JD) for this piece. If omitted, **`template_fold.default_epoch`** is used. Use when you want phase 0 centred on a known maximum/minimum in that LC segment for a sharper template. **Not used in Step 2.** You are responsible for using a sensible template when reusing paths.

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

---

## Timing methods (which column wins)

All four methods are computed for every interval. **`timing.method`** selects the official row in **`timing.csv`** and the overview plot markers. Compare methods via **`timing_<method>.csv`** in `run_dir` or the wide **`fit_summary.csv`** per piece.

- **`nls_scale_clean`** — NLS + outlier cleaning + scale `s` (most flexible; default in examples)

Per-piece wide table: `pieces/<id>/fit_summary.csv` (all methods + `sigma_t_max_*` when errors enabled).

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
- **LC empty in window** — wrong `t_min`/`t_max` or wrong `lc_path`.

---

## Minimal workflow (copy-paste mindset)

1. Copy `examples/manifest_59857_only.yaml` or `manifests/manifest.yaml`.
2. Set `lc_path`, ephemeris, windows, interval files, `run_dir`.
3. `--dry-run`
4. Full run (add `--show-plots` for pop-ups, or `MPLBACKEND=Agg` for headless).
5. Open `run_dir/timing.csv` and `overview_lc_maxima.png`.
6. Next time: add `existing_template_dir` on pieces where the template is unchanged; rerun for new fits only.

---

## Example manifest location

- Working two-piece example: `manifests/manifest.yaml`
- Smaller examples: `examples/`

If in doubt, compare your YAML to those files line by line.
