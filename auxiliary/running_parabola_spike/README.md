# running parabola spike

Experimental **sliding centred-parabola** smooth on **unfolded** calendar time
(Andronov-style local quadratic filter). Output is a smoothed LC for rough
extremum hunting; precise timing stays with MAVKA / template timing.

## Run

Edit constants in ``scripts/run_running_parabola.py`` or use CLI flags.

```bash
cd auxiliary/running_parabola_spike
../../.venv/bin/python scripts/run_running_parabola.py --show
../../.venv/bin/python scripts/run_running_parabola.py \
  --lc ../lc_approx_spike/data/NSV_807_sector_97_flatten.vot \
  --out-dir data/runs/nsv807 \
  --domain flux --window 0.05 --step 0.0001 --weights \
  --save-plots --demo-windows 0 80 160
```

## Parameters

| Setting | Meaning |
|---------|---------|
| ``--domain`` | Working photometry domain: ``mag`` or ``flux`` |
| ``--extremum`` | Search for ``min`` or ``max`` in the working domain; default **min** |
| ``--window`` | Full window width in days |
| ``--step`` | Centre step (days); default **window / 4** |
| ``--weights`` / ``--no-weights`` | Inverse-variance weighting from ``phot_err`` |
| ``--t-min`` / ``--t-max`` | Optional JD crop |
| ``--min-gap`` | Split into independent segments where consecutive Δt exceeds this many days; default **do not split** |
| ``--min-peak-distance`` | Minimum separation between detected extrema on the smooth (days); default **0.3** |
| ``--fit-half-width`` | Half-width (days) of raw LC window for parabola ToM; default **window / 2** |
| ``--interval-delta-d`` | Half-width (days) for rough ToM interval file: ``[tom−δ, tom+δ]``; default **window / 2** |
| ``--out-dir`` | Directory for every product (created if missing); file names use the light-curve stem |
| ``--demo-windows`` | Smoothed-point indices for step-1 parabola demo panels |
| ``--demo-tom`` | Parabola ToM hit indices for step-3 diagnostic fit panels |

After smoothing, extrema are found with ``scipy.signal.find_peaks`` (rough period =
median spacing between consecutive hits). Each rough extremum is refined by a
local parabola fit on **raw** points in ``|t - t_rough| <= fit_half_width``.
Overview plot marks rough extrema (blue) and parabola ToM (green).

With ``--min-gap D``, the cropped LC is split wherever consecutive points are
more than ``D`` days apart. Smooth, extremum search, and parabola ToM then run
**independently on each segment** (windows never mix points across a gap).
Products are still one concatenated table per file; the overview line is not
drawn across gaps. Omit the flag (or leave ``MIN_GAP_D = None``) for a single
segment. A segment too short for the window is skipped with a warning; the run
fails only if every segment fails.

Use ``--extremum max`` for brightness peaks (flux hills / mag valleys).

## Output

All products go in ``--out-dir`` (default ``data/runs``). Names are
``{lightcurve_stem}_{suffix}``, where the stem is the input file base name
(not the path). Example: ``NSV_807_sector_97_flatten.vot`` yields
``NSV_807_sector_97_flatten_smoothed.dat``, and so on.

ASCII tables are space-separated with a ``#`` comment header (run settings,
``min_gap_d``, ``n_segments``). Segment results are concatenated in time order.
Plots are written only with ``--save-plots`` (and the matching demo flags).

LC ingest uses the same bridge as ``lc_approx_spike`` / ``template_timing``.
Plot sizes and fonts: edit ``plot_style.py`` in this folder only.

### ``smoothed.dat``

Sliding centred-parabola **smooth** of the unfolded light curve. This is the
filter output used for rough extremum hunting, not a ToM table.

**Columns:** ``jd  smooth  curvature  rms``

- ``jd``: window centre (absolute JD)
- ``smooth``: parabola value at the centre (photometry in the working domain)
- ``curvature``: quadratic coefficient ``c`` in ``a + b*(t - jd) + c*(t - jd)^2``
- ``rms``: residual RMS of in-window points to that parabola

**How:** for each centre (step ``--step``, full width ``--window``) a quadratic
is fitted to points with ``|t - centre| <= window/2``. Centres with fewer than
``--min-points`` samples are skipped. Independent per gap-split segment; rows
from skipped (too short) segments are omitted.

### ``rough_tom_intervals.dat``

Coarse search windows around extrema found **on the smooth**, in GP interval
``.dat`` layout. Use this as a first guess for template timing / GP, not as
precise ToM.

Written only if at least one smooth extremum is found.

**Columns:** ``Interval_Start  Interval_End``

Each row is ``[t_rough - d, t_rough + d]`` with ``d = --interval-delta-d``
(default ``window/2``). ``t_rough`` is a ``jd`` from the smoothed series at a
``find_peaks`` hit (``--extremum min`` or ``max``, minimum separation
``--min-peak-distance``).

**How:** ``scipy.signal.find_peaks`` on the concatenated-per-segment smooth,
then a symmetric interval about every hit. Failed / skipped segments contribute
no rows.

### ``parabola_tom.dat``

**Refined** times of extremum from a local parabola on **raw** points, one row
per successful fit. This is the spike's ToM product; ``rough_jd`` is the
smooth-peak anchor that started the fit.

Always written (the table may have zero data rows if every refinement failed).

**Columns:** ``tom_jd  sigma_t_d  rough_jd  n_points  rms  curvature  dt_ext``

- ``tom_jd``: parabola extremum time (absolute JD)
- ``sigma_t_d``: formal uncertainty on ``tom_jd`` from coefficient covariance (days)
- ``rough_jd``: anchor time from the smooth-extremum detector
- ``n_points``: raw LC points used in the fit
- ``rms``: residual RMS in the fit window
- ``curvature``: quadratic coefficient ``c2`` of the centred parabola
- ``dt_ext``: ``tom_jd - rough_jd`` (days)

**How:** around each ``rough_jd``, fit ``y = c0 + c1*dt + c2*dt^2`` on raw
points in ``|t - rough_jd| <= --fit-half-width`` (capped so neighbouring
anchors do not share points). Rejected if too few points, wrong curvature
sign for ``--extremum`` / ``--domain``, or the vertex lies outside the window.
Independent per segment; only successful hits are listed.

### ``overview.png``

Diagnostic plot of the cropped raw LC, the running-parabola smooth (broken at
segment gaps), rough extrema (blue), and parabola ToM (green).

**How:** ``--save-plots`` and/or ``--show``. Title includes a rough period from
the median spacing of parabola ToMs (or of smooth extrema if ToM is unavailable).

### ``windows.png``

Per-panel check of **step-1** sliding-parabola fits. One panel per index in
``--demo-windows`` (indices into ``smoothed.dat`` rows).

**How:** redraw the in-window raw points, the fitted parabola, and the centre
mark. Requires ``--demo-windows`` plus ``--save-plots`` and/or ``--show``.

### ``tom_windows.png``

Per-panel check of **step-3** parabola ToM fits. One panel per index in
``--demo-tom`` (indices into ``parabola_tom.dat`` rows).

**How:** redraw the raw points in the effective fit window, the parabola, the
rough anchor, and the refined ToM. Requires ``--demo-tom`` plus ``--save-plots``
and/or ``--show``.
