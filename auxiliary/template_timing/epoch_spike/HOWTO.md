# Template epoch spike

A small experiment: take a GP template that already exists (`template.npz` + `template_meta.json`), compare better clocks than “the single lowest point”, and **write a new template folder** that `run_timing.py` can reuse.

It does **not** rebuild the GP. It does **not** change `run_timing.py`. It does **not** overwrite the source template. The new bundle is the same `μ(τ)` grid with a relabelled `tau_peak`.

---

## 1. What this is for

Eclipsing-binary minima can be **flat**. The folded GP mean is noisy there, so the stored `tau_peak` (the GP argmin) can sit almost anywhere along the trough. Different templates then get different painted marks. Step 2 still aligns the **shape**, but it reports

`t_max = tau_peak + delta_t`

so a random mark on the trough becomes a systematic shift between segments.

Forcing the GP itself to be symmetric is the wrong layer: spots and O’Connell are allowed in the wings. What we want is a **local** statement: “in the core of this eclipse, where is the symmetry axis?”

This spike compares three clocks on the **same** stored `μ(τ)`:

| Clock | Role |
|-------|------|
| GP argmin | What Step 1 already stored (`tau_peak`). Baseline, often the problem. |
| Kwee–van Woerden (KvW) | Candidate **replacement** epoch. |
| Bisector of chords | Independent check, plus a picture of asymmetry vs depth. |

If KvW and the bisector agree, and both disagree with GP argmin, the bug is the painted mark, not the GP shape.

---

## 2. The two methods (plain language)

Imagine a U-shaped eclipse drawn as a smooth curve. You must not ask “which pixel is the lowest?” on a flat bottom. You ask the walls.

### Kwee–van Woerden (the clock)

Pick a trial centre `τ0`. Look the same distance left and right. If the eclipse is even, the flux on the left equals the flux on the right. Sum the squared differences for many such pairs, and move `τ0` until that sum is smallest.

- Pairs run from one grid step out to `kvw.half_width_phase` (a **time** window, in units of the period).
- The search may only walk a shorter distance from the stored `tau_peak` (`kvw.search_half_width_phase`).
- Optional weights use the stored GP `sigma` so shaky walls count less.

A **narrow** window times near the trough. A **wide** window uses higher walls (and can be pulled by spots). This window is **not** the Step 2 fit mask: the fit mask is “how much shape we align”; KvW is “which part we believe is even”.

### Bisector of chords (the ladder)

At one flux level, find ingress and egress on `μ(τ)`. The midpoint is one bisector point. Repeat down a ladder of depths.

**Depth** is a fraction of **this template’s own dip**, not a fixed flux and not the GP kernel amplitude:

- depth 0 = out-of-eclipse continuum
- depth 1 = GP bottom (`min(μ)` for a minimum)
- `depth_min: 0.50` means halfway from continuum to that bottom

A perfectly even eclipse gives a **vertical** line (same time at every depth). A real one **tilts**. That tilt is a diagnostic (physical asymmetry), not a nuisance to hide.

The ladder is one method. The code then reads **two numbers** from it:

| Number | What it is | Use |
|--------|------------|-----|
| Weighted core mean | Inverse-variance mean of the accepted chords | Bisector **epoch** from the configured depth band |
| Linear extrapolation to the floor | Straight line through the ladder, evaluated at depth = 1 | “If the walls kept that trend, where would we be at bottom flux?” Diagnostic. Not the same as GP argmin’s **time**. |

KvW does **not** use the bisector knobs. The bisector does **not** use `kvw.half_width_phase`. The only coupling: chords use the KvW centre to tell ingress from egress.

---

## 3. Diagnostic plots

All written under `study.output_dir`.

**`template_marks.png`**  
The GP curve. Magenta = GP argmin. Green = KvW. Red = weighted bisector mean. Orange band = KvW pair window. Continuum and bottom are the flux anchors for depth. Purple (floor extrapolation) lives on the **ladder** plot, not here: it is a constructed time, not a point the GP picked.

**`bisector_ladder.png`**  
Depth vs bisector time. Blue points = chords. Green / red / purple = KvW, weighted mean, line to depth 1. If green cuts the deep, flat part of the blue points, the two methods agree.

**`kvw_cost.png`**  
How the KvW cost changes as you move the trial centre. A sharp well offset from magenta: the walls know a centre, the floor does not. A wide shallow valley: even KvW is still ill-posed (narrow the window or inspect the template).

**`branch_overlay.png`**  
Fold the eclipse about a centre and overplot left vs right. Left panel: about GP argmin. Right: about KvW. Branches on top of each other = that centre is a good local symmetry axis.

ASCII for xmgrace: `template_grid.dat` (`tau`, `mu`, `sigma`) and `bisector.dat`. Numbers: `epoch_summary.csv`.

The reusable template is a **separate** folder (see section 7), not mixed into these diagnostic files.

---

## 4. How to tweak (without mixing the two clocks)

### Deeper toward the minimum

These are **two** knobs, not one.

| Method | What to change | Direction |
|--------|----------------|-----------|
| Bisector | `bisector.depth_min` and `depth_max` | **Higher** (e.g. 0.50–0.90) uses chords closer to the bottom. Never set `depth_max` to 1.0 (that is the noisy floor). |
| KvW | `kvw.half_width_phase` | **Smaller** uses pairs closer to the centre (nearer the trough). Larger goes **up** the wings. |

`kvw.search_half_width_phase` must stay **strictly smaller** than `half_width_phase`. It is only “how far may the minimiser walk from the stored mark?”

### If the ladder tilts a lot in the shallow part

Raise `bisector.depth_min` so the epoch average does not include contacts. Keep the shallow chords for the picture if you like, or drop them.

### If KvW fails (“too few pairs”, “parabola is not a minimum”)

Widen `kvw.half_width_phase` a little, or check that the template is not a mess. Do not silently lower `n_pairs_min` to hide a bad window.

### If a depth has no ingress/egress pair

That level is skipped and logged. If fewer than `min_accepted_levels` survive, the run **stops**. That is intentional.

---

## 5. YAML layout

Two files:

```text
configs/
  _defaults.yaml     # knobs (included)
  your_study.yaml    # which template, where to write
```

Paths that are not absolute are relative to **the YAML file that contains them**.

### Study file (required)

```yaml
version: 1                 # not read by the loader
include: _defaults.yaml

study:
  label: "A name for logs and CSV headers"
  template_dir: ../../data/runs/.../template   # source; never overwritten
  output_dir: ../../data/runs/.../epoch_spike  # plots and CSV

export_template:
  method: kvw    # kvw | bisector_core | bisector_extrap
  # output_dir: ../../data/runs/.../template_kvw   # optional; see below
```

Example: `configs/NSV807_ffi_template_30.yaml`.

You may override any default in the study file (same keys). A leftover top-level `core:` section is an error; those keys belong under `kvw`.

### Defaults (`_defaults.yaml`)

**`plot`**

| Key | Meaning |
|-----|---------|
| `show` | Open matplotlib windows. `--no-show` forces this off. |
| `dpi` | PNG resolution. |

**`bisector`** (depth band only)

| Key | Meaning |
|-----|---------|
| `depth_min` / `depth_max` | Chord band; must satisfy `0 < min < max < 1`. |
| `n_levels` | Equally spaced depths in that band, inclusive. |
| `min_accepted_levels` | Fail if fewer chords succeed. |

**`kvw`** (time window only)

| Key | Meaning |
|-----|---------|
| `half_width_phase` | Maximum pair lag, in phase. Orange band on `template_marks.png`. |
| `search_half_width_phase` | Search half-width around stored `tau_peak`. Must be smaller than `half_width_phase`. |
| `n_pairs_min` | Minimum number of left/right pairs at a trial centre. |
| `weight_by_sigma` | Weight pairs by GP `sigma` (`true`) or raw squares (`false`). |

**`export_template`**

| Key | Meaning |
|-----|---------|
| `method` | Required. Which clock becomes the new `tau_peak`: `kvw`, `bisector_core`, or `bisector_extrap`. |
| `output_dir` | Optional. New folder for `template.npz` + `template_meta.json`. Default: `{study.output_dir}/template_{method}`. Must not be the source `template_dir`. |

`extrema_mode` and the period come from `template_meta.json`, not from this YAML.

---

## 6. How to run

From this folder:

```bash
cd auxiliary/template_timing/epoch_spike
python run_epoch_spike.py --config configs/NSV807_ffi_template_30.yaml
python run_epoch_spike.py --config configs/NSV807_ffi_template_30.yaml --no-show
```

| Argument | Required | Meaning |
|----------|----------|---------|
| `--config`, `-c` | yes | Study YAML. |
| `--no-show` | no | Save figures only; do not call `plt.show()`. |

To try another template, copy the study YAML, point `template_dir` at that piece folder, and set a new `output_dir`.

After a run, look first at `epoch_summary.csv` columns `delta_kvw_minus_argmin_s` and `delta_bisector_minus_argmin_s` (seconds), then at the four PNGs.

---

## 7. Reuse the corrected template in `run_timing.py`

The GP curve is copied. Only the painted extremum time changes. Point a piece at the **new** folder:

```yaml
pieces:
  - piece_id: "1"
    existing_template_dir: ../data/runs/NSV_807_97_ffi_main_template_30/epoch_spike/template_kvw
```

(Adjust the path so it is relative to **that timing manifest**.) Then run `run_timing.py` as usual. Step 1 GP is skipped. Step 2 uses `t_max = tau_peak_new + delta_t`.

Change `export_template.method` and re-run the spike to emit `template_bisector_core` or `template_bisector_extrap` (or set `export_template.output_dir` yourself). Inspect the diagnostics **before** you trust the new mark in a science run.
