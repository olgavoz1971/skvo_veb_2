# O-C analysis (`run_oc.py`)

## 1. What this is for

Take a list of timed extrema (minima or maxima), compute O-C against a trial ephemeris, and optionally refine that ephemeris.

Inputs may be:

- merged `timing.csv` from `auxiliary/template_timing/run_timing.py`
- compact `.dat` from the GP-for-O-C page
- a whitespace ASCII list

Which analyses run is set in YAML (`study.tasks`), not on the command line.

---

## 2. How to run

From `auxiliary/oc`:

```bash
python run_oc.py --config oc_configs/NSV807_sector30_spoc.yaml
python run_oc.py --config oc_configs/NSV807_sector30_spoc.yaml --no-show
```

| Argument | Required | Default | Meaning |
|----------|----------|---------|---------|
| `--config`, `-c` | yes | none | Path to the study YAML. |
| `--no-show` | no | off | Save figures; do not call `plt.show()`. |

There are no other CLI flags. Tasks, paths, and ephemeris all live in the YAML.

Outputs go to `study.output_dir`.

---

## 3. Configuration

A study file may include a shared profile. Paths that are not absolute are resolved **relative to the YAML file that contains them**.

```yaml
version: 1                 # present in files; not read by the loader
include: _defaults.yaml    # optional; merged first, then this file overlays it
```

`include` may chain. Circular includes raise an error.

Two independent time blocks exist. Both convert to **absolute JD** before any O-C maths.

| Block | Used for |
|-------|----------|
| `study.manifest_time` | Numbers **you type in this YAML**: `T0`, `cycle_shifts.at_time`, segment `t_min`/`t_max`, parabolic `fit_window`. |
| `study.inputs.extrema.file_time` | Numbers **inside the extrema file**. |

Time-block keys (same shape in both places):

| Key | Required | Default | Values |
|-----|----------|---------|--------|
| `scale` | yes | none | `jd`, `mjd`, `jd_offset` |
| `zero` | only if `scale` is `jd_offset` | omitted | additive zero (days). Forbidden for `jd` and `mjd`. |
| `shift` | no | `0.0` | Extra days after scale conversion. |

`run_timing` `timing.csv` stores extrema already as absolute JD. For that file use `file_time.scale: jd`.

---

### Root keys (outside `study`)

These come from `_defaults.yaml` unless you override them in the study file.

#### `plot`

Looked up as `study.plot` first, else root `plot`.

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `show` | no | `true` | Call `plt.show()` after plots. Overridden by `--no-show`. |
| `dpi` | no | `150` | PNG resolution for saved figures. |

#### `segment_period_fit` (algorithm defaults)

Read from the **root** mapping after include-merge, **not** from `study.segment_period_fit`.

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `max_iter` | no | `5` | Iteration limit for linear segment period correction. |
| `tol` | no | `1.0e-8` | Stop when `\|slope\|` of O-C vs JD is below this (days/day). |

#### `export`

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `write_provenance` | no | `true` | Write `# key: value` header lines on the O-C residual CSV. If `false`, that table is written by the legacy exporter (no `#` header). Other exports do not use this flag. |

---

### `study`

Required mapping. Missing `study` raises an error.

#### `study.label`

| | |
|-|-|
| Required | no |
| Default | YAML file stem |
| Type | string |
| Used in | log messages and CSV provenance `study:` line |

#### `study.manifest_time`

Required. See time-block keys above.

#### `study.ephemeris`

Required mapping (unless filled by `from_template_run.inherit_ephemeris_trial`).

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `T0` | yes | none | Trial epoch, in `manifest_time` units. |
| `P0` | yes | none | Trial period in days. |

O-C formula after optional cycle shifts:

`E = round((jd_ext - T0) / P0)`, then `O-C = jd_ext - (T0 + E * P0)` (days).

#### `study.cycle_shifts`

Optional list. Default: empty (no shifts).

Each entry:

| Key | Required | Meaning |
|-----|----------|---------|
| `at_time` | yes | Start of the shift, in `manifest_time` units. Converted to JD. |
| `delta_E` | yes | Integer added to `E` for every extremum with `jd_ext >= at_time`. Several entries accumulate. |

#### `study.tasks`

Required mapping. At least one task must be `true`. Unknown names are ignored.

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `plot_oc_residuals` | no | `false` | Compute O-C, write table, save PNG. |
| `fit_segment_periods` | no | `false` | Linear O-C-vs-JD period correction per named JD window. Writes `segment_periods.csv`. Plot is interactive only (not saved). |
| `fit_parabolic_ephemeris` | no | `false` | Quadratic O-C fit in a JD window, piecewise ephemeris, smart-fold of the light curve. |

Also required when the matching task is `true`:

| Task | Extra YAML required |
|------|---------------------|
| `fit_segment_periods` | `study.segment_period_fit.segments` (non-empty) |
| `fit_parabolic_ephemeris` | `study.parabolic_ephemeris.fit_window` and `study.inputs.lightcurve` |

#### `study.from_template_run`

Optional. Fills **missing** fields from a template-timing manifest. An explicit value in this study file always wins.

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `manifest` | yes (if this block is present) | none | Path to a `run_timing` manifest YAML. |
| `timing` | no | `run_merged` | How to find extrema. Only `run_merged` is implemented: `{manifest.run_dir}/timing.csv`. Any other value raises. |
| `inherit_ephemeris_trial` | no | `false` | If `T0` is missing, copy `default_epoch` from the timing manifest and, if `manifest_time` is also missing, set it to `{scale: jd, shift: 0.0}`. If `P0` is missing, copy `default_period`. |
| `inherit_lightcurve` | no | `false` | If light-curve `path` / `photometry_domain` are missing, copy them from the timing manifest. |

If `inputs.extrema.path` is missing, this block also sets:

- `path` to `{run_dir}/timing.csv`
- `format` to `template_timing_csv` (if unset)
- `file_time` to `{scale: jd, shift: 0.0}` (if unset)

If `study.output_dir` is missing, it becomes `{run_dir}/oc`.

#### `study.inputs`

Required mapping.

##### `study.inputs.extrema`

Required mapping.

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `path` | yes (unless filled by `from_template_run`) | none | Extrema file. Must exist. |
| `format` | no | `template_timing_csv` | `template_timing_csv`, `gp_extrema_dat`, or `ascii_columns`. |
| `file_time` | no | `{scale: jd, shift: 0.0}` | Time scale of numbers **in the file**. |
| `exclude_rejected` | no | `true` | `template_timing_csv` only: drop rows whose `rejected` is `1` / `true` / `yes`. |
| `timing_method` | no | omitted (keep all) | `template_timing_csv` only: keep rows whose `timing_method` equals this string. |
| `columns` | no | see below | `ascii_columns` only. |

`template_timing_csv` columns:

| File column | Used as |
|-------------|---------|
| `t_max` | extremum epoch (required) |
| `sigma_t_max` | uncertainty (optional) |
| `t_start`, `t_end` | interval bounds (optional metadata) |
| `piece_id`, `interval`, `timing_method`, `rejected` | metadata / filters |

`#` lines in that CSV are skipped.

`gp_extrema_dat`: whitespace file. Column 0 = epoch, column 1 = uncertainty if present. Header line matching `GP Minimum Results` or `GP Maximum Results` sets extrema kind to `min` or `max`.

`ascii_columns` (`columns` mapping):

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `time` | no | `0` | Column index of the epoch. |
| `sigma` | no | omitted | Column index of the uncertainty. |

Lines starting with `#` are skipped. Remaining columns are ignored.

##### `study.inputs.lightcurve`

Required only when `fit_parabolic_ephemeris` is `true`. Optional otherwise.

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `path` | yes (if this block is present) | none | Light-curve file. Must exist. |
| `photometry_domain` | no | `mag` | `mag` or `flux`. Must match how the file is to be used. |

#### `study.output_dir`

| | |
|-|-|
| Required | no |
| Default | `{extrema_file_parent}/oc`, or `{run_dir}/oc` when `from_template_run` is used |
| Type | directory path (created if needed) |

#### `study.segment_period_fit`

Used for **windows** only. Algorithm `max_iter` / `tol` are root keys (see above).

Required when `fit_segment_periods` is `true`.

```yaml
segment_period_fit:
  segments:
    - name: main          # required string
      t_min: 60934.70     # required; manifest_time units
      t_max: 60940.40     # required; manifest_time units
```

A segment with fewer than 2 extrema in that JD window is skipped with a warning.

Method: iteratively fit O-C vs calendar JD (Astropy `Linear1D`, 3σ rejection), then `P <- P / (1 - slope)` and `T0 <- T0 + mean(O-C)` until `|slope| < tol`.

#### `study.parabolic_ephemeris`

Required when `fit_parabolic_ephemeris` is `true`.

```yaml
parabolic_ephemeris:
  fit_window:
    t_min: 60938.0        # required; manifest_time units
    t_max: 60940.0        # required; manifest_time units
```

No extrema inside the window raises an error.

Method: fit `O-C(E)` as Astropy `Polynomial1D` degree 2 inside the window; build a piecewise ephemeris; smart-fold the light curve (regimes: before / parabolic / after).

#### `study.exports`

Optional. Filenames only (always written under `output_dir`). Missing keys use the defaults below.

**`plot_oc_residuals`**

| Key | Default |
|-----|---------|
| `oc_table` | `oc_residuals.csv` |
| `figure` | `oc_residuals.png` |

CSV columns: `cycle_number`, `OC`, and `sigma_jd_ext` when any row has an uncertainty.

**`fit_segment_periods`**

| Key | Default |
|-----|---------|
| `segment_table` | `segment_periods.csv` |

**`fit_parabolic_ephemeris`**

| Key | Default |
|-----|---------|
| `figure` | `oc_parabolic_fit.png` |
| `folded_lc` | `lc_parabolic_folded.dat` |

The folded-LC plot is shown when `plot.show` is true; it is not saved as a PNG.

---

## 4. Examples

Run from `auxiliary/oc`. Paths below are relative to the study YAML directory.

### From a template-timing manifest

This is the shipped study `oc_configs/NSV807_sector30_spoc.yaml`. Extrema path is not given: `from_template_run` fills `{run_dir}/timing.csv`.

```yaml
version: 1
include: _defaults.yaml

study:
  label: "NSV 807 sector 30 SPOC template timing"

  manifest_time:
    scale: mjd

  ephemeris:
    T0: 57711.3539
    P0: 0.3389614

  cycle_shifts: []

  tasks:
    plot_oc_residuals: true
    fit_segment_periods: false
    fit_parabolic_ephemeris: false

  from_template_run:
    manifest: ../../template_timing/manifests/manifest_NSV807_sector30_spoc.yaml
    timing: run_merged
    inherit_ephemeris_trial: false

  inputs:
    extrema:
      format: template_timing_csv
      file_time:
        scale: jd
        shift: 0.0
      exclude_rejected: true

  output_dir: ../data/runs/NSV_807_30_SPOC_main/oc

  exports:
    plot_oc_residuals:
      oc_table: oc.csv
      figure: oc.png
```

To take `T0` / `P0` from the timing manifest instead, omit them under `ephemeris` and set `inherit_ephemeris_trial: true`. If `manifest_time` is also omitted, it becomes `jd`.

### From a GP compact `.dat`

File shape written by the GP-for-O-C compact export (`skvo_veb/utils/gp/results_export.py`):

```text
# GP Minimum Results
# JD_Minimum	JD_Std
2460973.677563	0.000181
```

(`Maximum` / `JD_Maximum` for maxima.) Column 0 is JD, column 1 is the uncertainty. Set `file_time` to how those numbers are stored (`jd` for this export).

```yaml
version: 1
include: _defaults.yaml

study:
  label: "GP extrema"

  manifest_time:
    scale: jd

  ephemeris:
    T0: 2460973.0
    P0: 0.3389614

  tasks:
    plot_oc_residuals: true
    fit_segment_periods: false
    fit_parabolic_ephemeris: false

  inputs:
    extrema:
      path: ../data/gp_minima.dat
      format: gp_extrema_dat
      file_time:
        scale: jd
        shift: 0.0

  output_dir: ../data/gp_oc
```

### From ASCII columns

Whitespace-separated rows. `#` lines ignored. Default: epoch in column 0. Here column 1 is the uncertainty; extra columns are ignored.

```text
# epoch_mjd  sigma_d  note
60973.677563  0.000181  night1
60974.016500  0.000220  night2
```

```yaml
version: 1
include: _defaults.yaml

study:
  label: "ASCII extrema"

  manifest_time:
    scale: mjd

  ephemeris:
    T0: 60935.21
    P0: 0.3389614

  tasks:
    plot_oc_residuals: true
    fit_segment_periods: false
    fit_parabolic_ephemeris: false

  inputs:
    extrema:
      path: ../data/extrema.txt
      format: ascii_columns
      file_time:
        scale: mjd
        shift: 0.0
      columns:
        time: 0
        sigma: 1

  output_dir: ../data/ascii_oc
```
