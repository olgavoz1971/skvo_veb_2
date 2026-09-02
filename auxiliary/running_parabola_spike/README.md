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
| ``--min-peak-distance`` | Minimum separation between detected extrema on the smooth (days); default **0.3** |
| ``--fit-half-width`` | Half-width (days) of raw LC window for parabola ToM; default **window / 2** |
| ``--interval-delta-d`` | Half-width (days) for rough ToM interval file: ``[tom−δ, tom+δ]``; default **window / 2** |
| ``--out-intervals`` | Interval ``.dat`` from rough smooth minima (GP layout) |
| ``--demo-windows`` | Smoothed-point indices for step-1 parabola demo panels |
| ``--demo-tom`` | Parabola ToM hit indices for step-3 diagnostic fit panels |

After smoothing, extrema are found with ``scipy.signal.find_peaks`` (rough period =
median spacing between consecutive hits). Each rough extremum is refined by a
local parabola fit on **raw** points in ``|t - t_rough| <= fit_half_width``.
Overview plot marks refined ToM as large red spots.

Use ``--extremum max`` for brightness peaks (flux hills / mag valleys).

## Output ASCII

Smoothed curve (``--out``), double-space separated with ``#`` header:

``jd  smooth  curvature  rms``

- **smooth** — parabola value at window centre
- **curvature** — coefficient ``c`` in ``a + b·dt + c·dt²``
- **rms** — in-window residual RMS

Parabola ToM (``--out-tom``):

``tom_jd  sigma_t_d  rough_jd  n_points  rms  curvature  dt_ext``

Rough ToM intervals (``--out-intervals``), GP-compatible layout:

``# Interval_Start  Interval_End`` then rows ``tom−δ  tom+δ`` (δ = ``--interval-delta-d``).

- **tom_jd** — refined extremum time from the local parabola
- **sigma_t_d** — formal propagated uncertainty (days)
- **rough_jd** — anchor from smooth-minimum detection
- **dt_ext** — ``tom_jd - rough_jd``

Plots (optional): ``running_parabola_overview.png``, ``running_parabola_windows.png``,
``parabola_tom_windows.png`` (with ``--demo-tom``).

LC ingest uses the same bridge as ``lc_approx_spike`` / ``template_timing``.

Plot sizes and fonts: edit ``plot_style.py`` in this folder only (independent
of ``template_timing`` and other spikes).
