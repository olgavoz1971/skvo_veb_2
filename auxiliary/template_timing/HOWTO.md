# Template timing: simple HOWTO

This folder turns a **detrended light curve** plus **interval files** into a list of **maximum times** (`t_max`) and a picture of the LC with maxima marked.

You do **not** edit Python for a normal run. You edit one **YAML manifest** and run one command.

---

## What you need before you start

1. **One detrended LC file** (ASCII `.dat`, magnitudes already detrended).  
   Example: `data/R_detrended.dat`

2. **Ephemeris you trust** for the whole project:
   - `t_ref` (reference time, truncated JD)
   - `p0` (period in days)
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

- **`timing.csv`** — the main result: `t_max`, `sigma_t_max`, piece, interval, method, etc.  
  **`t_max`** is mapped from the fit in fold-time **within each interval** (no global cycle number). Assign cycles later for O–C if you need them.
- **`overview_lc_maxima.png`** — LC with vertical lines at each `t_max`
- **`pieces/<piece_id>/`** — template + per-piece `fit_summary.csv`
- **`pieces/<piece_id>/fits/`** — 4-panel debug plots (if `save_interval_plots: true`)

---

## Manifest cheat sheet

### Global (once per run)

- **`lc_path`** — your detrended LC
- **`mag0`** — `10` or `null` to read from the file header
- **`ephemeris`** — `t_ref`, `p0`, `period_slope`
- **`timing.method`** — which fit defines `t_max` in `timing.csv`:
  - `cc`, `nls`, `nls_clean`, **`nls_scale_clean`** (usual choice)
- **`timing.error_model`** — `rms_slope` or `none`
- **`plots.save_interval_plots`** — `true` / `false` (default on in examples)
- **`plots.save_overview`** — whole-LC plot with maxima

### Each entry under `pieces:`

- **`piece_id`** — short label (e.g. `"59857"`)
- **`template_window`** / **`fit_window`** — `{ t_min, t_max }`
- **`intervals_path`** — file with interval start/end times
- **`local_period`** — optional; if omitted, folding uses global `p0`. If this piece needs a different fold period, set it here.

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

Fold period must match the source (same `local_period` / same effective `p0`).

**Use only one** of `existing_template_dir` and `reuse_template_from` per piece.

---

## Timing methods (which column wins)

All four methods are computed internally; **`timing.method`** picks the official `t_max` in `timing.csv`.

- **`nls_scale_clean`** — NLS + outlier cleaning + scale `s` (most flexible; default in examples)

Per-piece details stay in `pieces/<id>/fit_summary.csv`.

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

- **Interval outside fit window** — widen `fit_window` or fix the intervals file.
- **`existing_template_dir` not found or missing npz/meta** — check the path relative to the manifest.
- **Fold period mismatch** — `local_period` / global `p0` must match the template you load.
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
