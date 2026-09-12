# Lightcurve processor

Page path: `/lc_processor`. Title: Lightcurve processor.

This page is a toolbox, not a wizard. A user who already has a detrended curve
can clean points or look at minima later without being forced through every
drawer. A user who only wants a trend can stop after Smooth.

Tools live in the left accordion (Light curve, Smooth, Detrend, Rough
extrema). Plots stay in the right column and stay visible when a drawer
is closed. Light curve starts open and is closeable.

| Plot | What it shows |
|------|----------------|
| 1 | Working photometry plus the last Apply-smooth overlay (LSQ knot lines, and teal diamonds after Find extrema). Cleaning (delete / unselect) always acts here. |
| 2 | Working residual: Apply detrend or Copy from plot 1, then optional Local tilt. Empty until seeded. |

Photometry is the **screen domain**: magnitude or flux, as chosen in Light
curve. Time crop affects the plots and the fit, not Export lightcurve.
Export lightcurve writes the full working series after deletes, stem
`{upload}_lc`.

Zoom / knot-shape behaviour is a separate note:
[lc_processor_zoom_shapes.md](lc_processor_zoom_shapes.md).

Maths live in `skvo_veb/utils/lc_processor/`. The page must not invent
photometry.

Status text uses one overlay on the plot column
(`lc-processor-plot-alert`). Drawers do not grow. A new message replaces
the previous one. Every alert is dismissable. Info and success use the
ready-made `dbc.Alert` `duration` (`STATUS_ALERT_DURATION_MS` in
`skvo_veb/pages/lightcurve_processor.py`). Warning and danger stay until
dismiss, a newer message, or a new file. A successful upload, domain
change, or delete clears the overlay. Plot redraw, zoom, and drawer
open/close do not.

---

## Smoothing

**Apply smooth** writes a trend \(T(t_i)\) at the observation times and draws
it as a red line on plot 1. It does **not** write a residual. That is a
later, explicit Apply detrend (magnitude subtracts \(T\); flux divides by
\(T\)).

Running parabola is a smoother, but its geometry is different enough that it
has its own section below. Everything here applies to the other methods, and
the shared gap widgets apply to all of them (including running parabola).

### Shared rules

- **Split on gaps** (default on) cuts the series wherever consecutive
  \(\Delta t\) exceeds **Break tolerance** (days; default 5). Each piece is
  fitted on its own. With the switch off, the whole crop is one segment.
  Leave the switch on for ground-based nights.
- The red overlay is straight segments between successive finite \(T(t_i)\).
  A `NaN` vertex is inserted at every gap-split boundary so night A is not
  joined to night B by a ruler across empty calendar time.
- A new upload, a domain change, a delete, a knot edit that invalidates the
  fit, or a new Apply smooth clears the previous overlay (and any residual).
- Empty required widgets fail. The fit does not invent defaults.

### Sliding median

Time window in days (default 2). At each \(t_i\), \(T\) is the median of
points inside \([t_i - W/2,\, t_i + W/2]\). This method does not use the
gap-split list for the window itself; the window is in calendar time, so a
large \(W\) can still see neighbouring nights. Prefer a window smaller than
the typical night gap, or use a point-window method with Split on.

### Sliding biweight

Point window (default 301). Astropy `biweight_location` in a centred window
that does not cross a gap-split. If a piece is shorter than the window,
\(T\) is the piece `nanmedian` (agreed exception).

### Savitzky–Golay

Point window (odd; even values are bumped) and polynomial order (default 5).
`scipy.signal.savgol_filter` on each gap-split piece. Short pieces use the
same `nanmedian` fill.

### Lightkurve flatten

Lightkurve's Savitzky–Golay flatten, still split on gaps. Same point window
and polynomial order as Savitzky–Golay. Short pieces use `nanmedian`.

### Smoothing spline

SciPy `UnivariateSpline` per piece. **Smoothing (relative)** (default 0.05)
sets \(s\) from the scatter when the explicit \(s\) box is empty.

### Least-squares spline

SciPy `LSQUnivariateSpline` on the current knot list. **Place knots** first
(Apply does not invent a grid). Grid mode is **Uniform** or **By occupancy**
(default occupancy). Knot tool: Off / Add knot / Delete knot. Knots are
layout lines, not a photometry trace.

### P-spline

Penalised spline: **Penalty lambda** (default \(10^4\)) and **Segments**
(default 40). Interior knots are equispaced from the segment count.

---

## Running parabola

Andronov-style sliding **centred parabola** on unfolded Julian Date. The
native product is not \(T\) at the observations. It is a sample at each
successful **window centre**.

On each centre \(t_c\) the filter fits

\[
y = a + b\,(t - t_c) + c\,(t - t_c)^2
\]

with Astropy `Polynomial1D` and `LinearLSQFitter`. The stored smooth is
\(a\): the parabola **at \(t_c\)**. Optional inverse-variance weights use
the error column.

| Widget | Meaning | Default |
|--------|---------|---------|
| Window | Full window width (days) | \(P/2\) when period is set; otherwise 0.05 |
| Step | Shift between centres (days) | one quarter of the window |
| Minimum points | In-window samples required to fit | 5 |
| Weight by errors | Off unless you trust the errors | off |

Gap widgets are the same as the other smoothers. **Split on gaps must be
on** for ground-based data. With it off, a 0.25 d window can sit in the
daytime gap, grab one night from one side, and the quadratic runs away
(\(a \sim -1\) or worse while the photometry is near 0).

### When a centre is kept

A centre is used only if:

1. the window contains at least **Minimum points**, and
2. there is at least one sample **strictly before** \(t_c\) and one
   **strictly after** (two-sided). A one-sided window is not a fit; \(a\)
   at an empty or edge centre is a quadratic extrapolation, not a smooth.

Centres are placed so the *full* window lies inside the piece
(\([t_{\min}+W/2,\, t_{\max}-W/2]\)). A night shorter than the window
therefore has **no** native centres. That is not a reason to discard the
night (see mapping below).

### Mapping to observation times

Plot 1 and Apply detrend need \(T(t_i)\). The mapping is:

1. Linear interpolation of neighbouring centres **only when**
   \(t_{c,k+1} - t_{c,k} \le W\). A hole larger than the window stays
   empty. A single surviving centre is **not** painted onto the whole
   night.
2. Any \(t_i\) still empty is evaluated as a parabola **centred on that
   observation**, with the same minimum-points and two-sided rules.
3. Otherwise \(T(t_i)\) is non-finite (`NaN`). We do not invent 0 or 1,
   and we do not interpolate from the previous night.

So a dense burst shorter than \(W\) still gets local \(T\) in the interior;
dusk and dawn one-sided points stay `NaN`. A 1-point gap-split fragment
stays `NaN`. The red line breaks there and at every gap-split boundary.

### What this is for

The overlay is the honest filter: Rough extrema uses only finite \(T\)
and ignores rejected pieces.

Detrend must still keep every point. How holes are filled is the next
section; it is not part of this smoother.

Native centre-grid export (`{stem}_smoothed.dat`: `jd`, `smooth`,
`curvature`, `rms`) is not on the page yet.

---

## Detrend

Plot 2 is the working residual. It stays empty until you seed it.

**Apply detrend** writes the residual of the last Apply-smooth overlay.
It is not run when you apply a smooth. Arithmetic uses the **screen
domain** of that overlay:

- magnitude: residual \(= y - T\)
- flux: residual \(= y / T\) (finite \(T\) must be strictly positive)

**Copy from plot 1** writes the cropped, cleaned series from plot 1
onto plot 2 with no overlay required. Use this when the loaded file is
already detrended, or to skip a global detrend. Either seed button
replaces whatever is already on plot 2.

The residual follows the same time crop as the last seed. A new smooth,
a domain change, a delete, or a knot edit that invalidates the fit
clears it.

**Local tilt** is a second-pass rewrite of plot 2 only, using the same
working-range pattern as GP Remove trend. Zoom plot 2 and press **Use
visible range**. Switch on **Place tilt line**, click once, drag the
handles, then **Apply local tilt**. The line is the model; the working
range is the locality (the whole seeded series if no range is set).
**Restore full plot 2** shows every seeded point again. Magnitudes
subtract the line; flux divides by it. You can apply more than once.
Reload the light curve to undo. Plot 1 is not changed.

The dashed 0 / 1 guide on plot 2 is a *normalised* reference. After
Copy from plot 1 of a raw series it is only a visual guide.

**Export detrended** is a light-curve export: same format list as Export
lightcurve, plus its own stem field. The stem starts from the uploaded
name (the shared entry point, the Light curve ``_lc`` field) and already
ends in ``_detrended``, not ``_lc_detrended``. It writes the current
plot 2 (seed plus any local tilts). Ephemeris (P / Epoch) still comes
from Light curve.

### Strict rule: do not drop points

Every point in that series must appear in the residual, except rows the
user has already deleted. The red overlay may still show `NaN` where the
filter refused. Detrend fills those holes **before** subtract or divide.
It does not turn a one-sided parabola back on, and it does not take \(T\)
from the previous night.

Work is per **gap-split piece** (the same break tolerance as the last
smooth).

1. **The piece already has some finite \(T\).** Fill each hole from the
   **nearest finite \(T\) in that piece**. If the hole has finite \(T\) on
   both sides and those two samples are at most one running-parabola
   window apart, use a linear interpolant of \(T\) instead. That is the
   trusted trend held (or interpolated) to dusk and dawn.
2. **The piece has no finite \(T\).** Isolated point, or a night the
   filter never spoke. Then \(T = \mathrm{nanmedian}(y)\) on that piece.
   The residual is a zero-point, not a shape. A one-point night becomes
   \(\Delta\mathrm{mag}=0\) or flux ratio \(1\).

Apply detrend reports how many samples used nearest \(T\), a local
interpolant, or the piece median. Flux still fails if a filled \(T\) is
finite and not strictly positive.

---

## Rough extrema

**Find extrema** runs on the last Apply-smooth overlay, not on the
photometry and not on the detrend-filled \(T\). The algorithm is the
running-parabola spike: ``scipy.signal.find_peaks`` on a domain-aware
sign flip.

- Magnitude **minimum**: peaks of \(T\) (fainter = larger mag).
- Flux **minimum**: peaks of \(-T\).
- Maximum is the opposite flip.

Only **finite** overlay samples are used. Gap-split pieces are searched
separately, and a non-finite hole inside a piece starts a new run, so
two nights are never treated as neighbouring samples. The peak-distance
in samples is \(\lfloor\) min. peak distance / median \(\Delta t\,\rfloor\)
of that run. A run shorter than **Min. points in segment** (default 5;
floor 3) is skipped; the rest of the series is still searched.

This drawer does **not** refine a time of minimum with a parabola. That
stays with MAVKA / GP. \(\sigma(\mathrm{JD})\) is not invented.

| Widget | Meaning | Default |
|--------|---------|---------|
| Extremum | Minimum or maximum in the working domain | minimum |
| Extremum tool | Off, add, or delete a mark by clicking plot 1. Exclusive with the knot tool. | Off |
| Min. peak distance | Smallest allowed gap between hits (days) | \(0.7P\) when period is set; otherwise 0.3 |
| Min. points in segment | Finite overlay samples required in a run | 5 (not period-scaled; floor 3) |
| Interval half-width \(\delta\) | Export-only: window is \([t-\delta,\, t+\delta]\) | \(P/3\) when period is set; otherwise 0.025 |

Find extrema is gated on a matching overlay and **replaces** the mark
list. Add and delete use a plot-area pointer pick (Plotly ``p2d``), not
``clickData``, so a click does not need to hit photometry or the overlay.
Add extremum stores that click time as the ToM; Delete extremum removes
the nearest mark.
Both product files are written in time order. A new smooth, a domain
change, a delete, or a knot edit that invalidates the fit clears the
marks.
Closing the drawer does not hide plot 1. Zoom is kept by Plotly
``uirevision`` (the token does not include the mark list).

Orange diamonds sit on the overlay at each hit (symbol and colour:
``EXTREMA_MARKER`` in ``skvo_veb/utils/lc_processor/figures.py``).
Interval width is an export parameter: you can change \(\delta\) and
export again without finding again.

All scientific defaults (constants and period-scaled formulae) live in
``skvo_veb/utils/lc_processor/config.py``, grouped by algorithm.
Changing the Light curve period field rewrites the period-scaled knobs
(window, step, peak distance, and δ). Those Input values are rounded to
``DISPLAY_DECIMALS`` places.

| Product | Stem | Body |
|---------|------|------|
| Intervals | `{base}_int.dat` | ``#`` metadata (source file, smooth method and applied knobs), then GP layout `# Interval_Start  Interval_End` and \([t-\delta,\, t+\delta]\) |
| Times | `{base}_rough_toms.dat` | Same ``#`` metadata, then compact ToM: `# Rough {Minimum\|Maximum} times`, `JD  nan` |

Both stems start from the Light curve `_lc` field (the `_lc` suffix is
stripped first). The timing file is accepted by
`parse_compact_tom_contents`; \(\sigma\) is `nan` on purpose.
