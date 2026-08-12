# Model-free, period-change-aware folding

This note describes the basic ideas behind **model-free smart folding** as implemented in this repository for offline analysis. The core library lives in `auxiliary/smart_folding/model_free_folding.py`; the scratch workflow and diagnostic plots are in `auxiliary/template_timing/plot_oc.py` (Step 3).

The method is complementary to **Step 2 parametric folding**, which fits a parabolic O-C law and builds a piecewise ephemeris. Model-free folding does **not** assume a functional form for O-C or period evolution. It derives a local period curve directly from observed maximum times and corrected cycle numbers.

---

## 1. Problem statement

Classical phase folding assumes a **constant period** `P0` and a reference epoch `T0`:

```text
phase = fractional part of  (JD - T0) / P0
```

When the period changes with time, this produces a blurred or distorted folded light curve.

The usual remedy is to fit an **ephemeris** (often quadratic in cycle number) to O-C residuals and fold using the fitted law. That works well when the O-C shape is smooth and well modelled, but it commits to a parametric form.

**Model-free folding** instead asks:

1. Given trustworthy **cycle assignments** `E` for each observed maximum, what was the **local period** as a function of time?
2. How do we assign **phase** to every light-curve point when `P` varies?

---

## 2. Separation of concerns

The workflow deliberately splits two hard problems:

| Step | Question | Output |
|------|----------|--------|
| **Cycle assignment** | Which integer cycle does each maximum belong to? | `(JD_obs, E)` pairs |
| **Period law** | How does period change between those maxima? | `P(t)` sampled in time |

In `plot_oc.py`, **Step 1** handles cycle assignment:

- Start from trial `(T0, P0)`.
- Compute naive cycle numbers and apply manual **cycle shifts** at known JD boundaries (`CYCLE_SHIFTS`).
- Export O-C diagnostics and the timing handoff table.

Step 3 **does not** re-fit O-C. It trusts the `(JD_obs, E)` pairs from Step 1.

If cycle numbers are wrong, model-free folding cannot fix that; it will propagate the error into `P(t)` and the final fold.

---

## 3. Input data

### Required

For each observed extremum (maximum or minimum):

- **`JD_obs`**: observed time of the extremum (full Julian Date in the workflow).
- **`E`**: corrected cycle number (integer or half-integer, depending on convention).

These are exported as `oc_timing_pairs_*.csv`:

```text
jd_obs,cycle_number[,timing_sigma]
```

### Optional

- **Timing uncertainty** per maximum (`timing_sigma` / `sigma_t_max`), used for weighted sliding-window fits.
- **Known JD gaps**: intervals with no trustworthy timing or no continuous cycle coverage (see Section 6).

### Light curve

The full detrended LC (`.dat` file) is folded **after** a working `P(t)` curve is built from the maxima alone.

---

## 4. Local period from timing pairs

### 4.1 Pairwise estimate (exploratory)

For any two maxima `i` and `j` with cycle separation `ΔE = E_j - E_i`:

```text
P_local(i, j) = (JD_obs_j - JD_obs_i) / (E_j - E_i)
```

This is the average period implied by that pair. It is plotted at the **midpoint time**:

```text
t_mid = (JD_obs_i + JD_obs_j) / 2
```

Important: the horizontal axis is **not** the JD of a single maximum. Each point represents **one pair**, placed at the time halfway between its two maxima.

**Interpretation:**

- **Small |ΔE|** (e.g. 1 cycle): very local, but **noisy** because timing errors dominate a small numerator.
- **Large |ΔE|**: more stable period estimate, but **worse time resolution** (average over a longer baseline).

The pairwise plot is a **cloud** of many competing estimates. It is useful for spotting trends and inconsistencies, not as the final period law.

### 4.2 Sliding-window estimate (working curve)

Instead of all pairs, take **consecutive** maxima in time order (e.g. 5 in a row) and fit a straight line:

```text
JD_obs = T0_local + P_local * E
```

The **slope** `P_local` is the period in that window; the **intercept** is a local epoch. The fit is repeated as the window slides one maximum at a time.

This is the curve used for folding. It is smoother than the pairwise cloud and provides an uncertainty on `P` when enough points are in the window.

Implementation uses Astropy `Polynomial1D(degree=1)` with optional inverse-variance weights from timing sigmas.

---

## 5. Folding when period varies

Once we have samples `P(t)` at window centre times, we need phase at arbitrary LC timestamps.

### Primary method: numerical integration

When period changes, cycle count must accumulate as:

```text
dE/dt = 1 / P(t)
```

So:

```text
E(t) = E_anchor + integral from t_anchor to t of  dt' / P(t')
```

Steps in code:

1. Interpolate `P(t)` linearly between sliding-window samples (constant extrapolation at edges).
2. Build a fine time grid and integrate `1/P(t)` (trapezoidal rule).
3. Anchor at one well-chosen maximum `(t_anchor, E_anchor)`.
4. **Phase** = fractional part of `E(t)`.

This is physically correct for a slowly varying period and is preferred over naively applying a different local `(T0, P)` at each LC point.

### Alternative (not used in Step 3 default)

**Nearest-window fold**: assign each LC point to the closest sliding window and use that window's linear ephemeris. Simpler but can produce discontinuities at window boundaries.

---

## 6. Continuity rules

Not every pair or window is meaningful. Pairs that span missing cycles or known observing gaps give **false** average periods.

Both pairwise and sliding-window logic share `TimingContinuityRules`:

| Rule | Default | Meaning |
|------|---------|---------|
| `min_cycle_gap` | 1 | Minimum \|ΔE\| for a pair |
| `max_cycle_gap` | 30 | Maximum \|ΔE\| for a pair or window span |
| `max_neighbour_dE` | 1 | Between **consecutive sorted maxima**, require ΔE ≤ 1 (no skipped cycles in the chain) |
| `known_jd_gaps` | `[]` | List of `(jd_lo, jd_hi)`; reject pairs/windows that **straddle** any gap |

A pair `(i, j)` is accepted only if:

- `min_cycle_gap ≤ |E_j - E_i| ≤ max_cycle_gap`
- every neighbour step from `i` to `j` has ΔE ≤ `max_neighbour_dE`
- the JD interval does not cross a known gap

A sliding window of `N` maxima is accepted only if the same rules hold for its first and last member (and thus for the whole chain inside the window).

Configure gaps in `plot_oc.py`:

```python
MF_KNOWN_JD_GAPS = [
    (JD0 + 59856.0, JD0 + 59856.5),
]
```

---

## 7. Workflow in `plot_oc.py`

```text
Step 1   Load timings → compute (JD_obs, E, O-C) → export + plot O-C
Step 2   Parabolic O-C fit → piecewise ephemeris fold (parametric; optional)
Step 3   Model-free P(t) → diagnostics → fold LC
```

### Step 3 outputs

| File | Content |
|------|---------|
| `oc_timing_pairs_*.csv` | `jd_obs`, `cycle_number`, optional sigma |
| `*_model_free_folded.dat` | LC with `cycle_E`, `phase`, `period_local`, `tau_days`, diagnostic `fold_regime` |

The `fold_regime` column (BEFORE / PARABOLIC / AFTER) is **diagnostic only**: it marks which JD region each LC point came from, using the same boundaries as Step 2's `JD_OBS_FOR_FIT`. It does not change the model-free fold maths.

### Step 3 diagnostic plots

1. **Pairwise P(t) cloud** — all allowed pairs; colour ≈ \|ΔE\|.
2. **Sliding-window P(t)** — working period curve with error bars.
3. **Window fit gallery** — subsampled panels: 5 points + fitted line in `E` vs `JD_obs`.
4. **Overlaid window fits** — subsampled faint lines on one `E` vs `JD_obs` plot.
5. **Membership track** — Gantt chart of which maxima each window includes.
6. **Phase at maxima** — sanity check: recovered phase at input timings should cluster.
7. **Folded LC** — final model-free phase plot with regime colours.

---

## 8. Comparison with Step 2 (parametric)

| Aspect | Step 2 (parabolic / piecewise) | Step 3 (model-free) |
|--------|-------------------------------|---------------------|
| O-C model | Quadratic (or piecewise) | None |
| Period law | Analytic from fit coefficients | Empirical `P(t)` from data |
| Strength | Compact ephemeris for prediction/export | Flexible when O-C shape is awkward |
| Weakness | Wrong model → wrong fold | Needs good `(JD, E)` and continuous segments |
| Folding | Regime-based analytic inversion | Integration of `1/P(t)` |

Both can be run on the same Step 1 output and compared visually.

---

## 9. Configuration reference (`plot_oc.py`)

```python
MF_MIN_CYCLE_GAP = 1.0       # minimum |ΔE| for pairs
MF_MAX_CYCLE_GAP = 30.0      # maximum |ΔE| for pairs / windows
MF_MAX_NEIGHBOUR_DE = 1.0      # max ΔE between consecutive sorted maxima
MF_KNOWN_JD_GAPS = []        # [(jd_lo, jd_hi), ...]
MF_SLIDING_WINDOW = 5        # maxima per window fit
MF_ANCHOR_INDEX = 0          # which maximum anchors E(t) integration
MF_GALLERY_MAX_WINDOWS = 12  # subsample for gallery panels
MF_OVERLAY_MAX_WINDOWS = 24  # subsample for overlay plot
```

---

## 10. Practical guidance

1. **Invest effort in Step 1** — cycle shifts and O-C review are the foundation.
2. **Use the pairwise plot** to see whether a period trend exists and whether scatter is dominated by short baselines.
3. **Trust the sliding-window plot** for the shape of `P(t)` used in folding.
4. **When P(t) jumps**, inspect the window gallery and membership track: usually a gap, an outlier time, or a window crossing a cycle-shift boundary.
5. **Check phase at maxima** before trusting the folded LC; large scatter means the fold is not self-consistent.
6. **Declare known JD gaps** explicitly rather than letting bad pairs pollute `P(t)`.
7. **Compare with Step 2** when a smooth parabolic model is plausible; large disagreement is scientifically informative.

---

## 11. Code map

```text
auxiliary/
├── dec/
│   └── model_free_folding.md          ← this document
├── smart_folding/
│   └── model_free_folding.py          ← core algorithms
└── template_timing/
    └── plot_oc.py                     ← Steps 1–3 workflow and plots
```

Key functions in `model_free_folding.py`:

- `local_period_pairs` — exploratory pairwise P estimates
- `sliding_local_period` — working P(t) with continuity filtering
- `fold_interpolated` — phase via integration of `1/P(t)`
- `TimingContinuityRules` — shared gap and ΔE filters

---

## 12. Limitations (explicit)

- **No silent repair** of bad timings or cycle labels; invalid windows are skipped, not patched.
- **Edge extrapolation**: outside the JD range covered by valid sliding windows, `P(t)` is held constant at the nearest edge value; a warning is logged if the LC extends beyond that range.
- **Sparse timing**: few continuous segments yield few windows and a coarse `P(t)` sampling.
- **Not a publication ephemeris** by itself: for a compact `(T0, P0, Q)` law suitable for long-term prediction, Step 2 (or a dedicated fit) remains the usual path.

---

*Document version: aligned with the Step 3 implementation in `plot_oc.py` and `model_free_folding.py` as of the model-free folding development branch in `auxiliary/`.*
