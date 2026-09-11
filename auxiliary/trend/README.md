# Lightcurve processor

Standalone Dash page for smoothing, detrending, and (later) rough extremum
timing. Algorithms come from the ``plot_tcp_lc.py`` sandbox; that file is
**not** modified. Maths live in ``detrend_core.py``.

## Run

From ``auxiliary/trend``:

```bash
../../.venv/bin/python detrend_app.py
```

Then open ``http://127.0.0.1:8052`` (port **8052**, so it does not clash with
the main app on 8051). After changing ``assets/detrend_clientside.js``, hard-refresh
the browser so the clientside knot-delete handler reloads. After CSS changes,
hard-refresh as well (Ctrl+Shift+R).

## Layout

The left sidebar is three drawers (several may stay open). On load, only
**Light curve** is open; it can be closed.

| Drawer | What it holds |
|--------|----------------|
| Light curve | Domain, MJD / Date, error bars, time crop, P / Epoch, format, stem (``_lc``), **Export lightcurve** |
| Smooth | Method dropdown, method parameters, **Place knots**, gap split, **Apply smooth**, Knot tool last |
| Detrend | **Export detrended** (Apply detrend arrives in a later step) |

Cleaning (**Delete selected** / **Unselect**) stays on the strip above plot 1.
Both stay enabled. **Unselect** is secondary outline; **Delete selected** is
the same outline in caution orange. Hints live under ``?``.

The probe does **not** import GP pages, GP CSS, or ``skvo_veb.utils.gp``.
Shared light-curve helpers (``lc_config``, ``lc_bridge``, ``lc_figure``) are fine.

Working photometry lives in **one** ``CurveDash`` store (``detrend-store-lc``).
Knots are a separate store. The fit payload is an overlay only. Zoom is kept
by Plotly ``uirevision`` (Discovery contract); there is no zoom store.

## What it does

1. Load a light curve through the same volightcurve ingest as Discovery / TESS.
   The working object is a ``CurveDash`` (serialized in the page store).
2. In Smooth, choose **one** method from the dropdown and its parameters. Gap
   splitting defaults **on** with break tolerance **5 days**.
3. **Apply smooth**: plot 1 is raw + trend, plot 2 is the residual
   (mag subtract or flux divide). This single button still fills both plots;
   a separate Apply detrend is a later step. Points are coloured by the
   ``label`` column when it is present (``None`` / missing labels stay unmarked).
   The legend is shown only when more than one distinct label is present.
4. Export the working lightcurve from Light curve, or the detrended series
   from Detrend after Apply smooth (VOTable / ECSV / ``.dat`` / CSV). Format and
   stem live in Light curve. The stem **field** already includes ``_lc``
   (upload of ``tcp.vot`` fills ``tcp_lc``). The detrended file name is
   ``{base}_detrended``, not ``{base}_lc_detrended``.

Time crop widgets apply to **fitting and plots only**. Exports write the whole
working curve (after any deleted points). Cropping the export is not offered
yet.

## Plot tools

Default drag is pan. Lasso and box stay on the **figure toolbar**, as on
Discovery; there is no extra Pan / Select radio.

| Knot tool | Observed plot |
|-----------|----------------|
| Off | Click or lasso / box to mark points (orange). Residual plot is not used for selection. |
| Add knot | Click to place an LSQ knot; drag a green line to move it |
| Delete knot | Click near a green line (pointer hit-test, 2 % of the visible x-range) |

Switching the knot tool does **not** rebuild the figure, so Plotly keeps zoom.

**Place knots** is a filled primary button. It builds a grid without entering
Add knot / Delete knot.

**Delete selected** is outline caution orange. **Unselect** is secondary
outline. Both stay enabled. Clicking them shows Bootswatch's inset pressed
state (set via Bootstrap button variables, not a background override).

## Methods

| Method | Notes |
|--------|--------|
| Sliding median | Time window in days |
| Sliding biweight | Window in points; gap-aware |
| Savitzky-Golay | Window in points, polynomial order; gap-aware |
| Lightkurve flatten | Same family as SG, Lightkurve's own flatten |
| Smoothing spline | ``UnivariateSpline``; relative or explicit ``s`` |
| Least-squares spline | Explicit knots; **editable on plot 1** when Add / Delete knot is selected |
| P-spline | Penalty λ and segment count (knots shown, not dragged) |

## Least-squares knots

Green dotted lines on plot 1 are interior knots.

- **Place knots** builds ``n`` knots on the cropped time span (occupancy or uniform).
- Switch the knot tool to **Add knot** or **Delete knot** to edit them.
- P-spline lines stay display-only.

## Export

- **Export lightcurve**: working ``CurveDash`` after deletes, current photometric
  domain, Light curve P / Epoch. Time crop is ignored. Filename gains ``_lc``.
- **Export detrended**: same envelope, photometry replaced by the residual from
  the last Apply smooth (gated until a fit exists). Filename gains
  ``_detrended``.

Later products (not in this step) use further suffixes: ``_smooth``,
``_smoothed``, ``_int``, ``_rough_toms``.

## Files

| File | Role |
|------|------|
| ``detrend_app.py`` | Dash UI and callbacks |
| ``detrend_core.py`` | Trend / detrend maths |
| ``detrend_figures.py`` | Plotly figures |
| ``assets/detrend.css`` | Page tokens (GP-style) |
| ``assets/detrend_clientside.js`` | Delete-knot pointer hit-test |
| ``plot_tcp_lc.py`` | Original matplotlib sandbox (untouched) |
| ``TODO_lightcurve_processor.md`` | Refactoring plan |
