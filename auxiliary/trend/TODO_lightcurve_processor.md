# Lightcurve processor probe -- refactoring TODO

Context for the next session. Do not re-derive this from chat.
Standalone Dash on port 8052: `cd auxiliary/trend && ../../.venv/bin/python detrend_app.py`.
Default: think first; this file is the agreed plan. **Do not modify `plot_tcp_lc.py`.**

Page title (user): **Lightcurve processor**. Matches `lightcurve_discovery` naming.
Keep Python/CSS ids as `detrend-*` until the page is registered in the main app.

Out of scope forever in this probe: parabola-refined ToM / rectifying extrema
(`parabola_tom.dat`). That belongs to the extrema modeller.

---

## Locked decisions (2026-09-11)

### 1. Gap split lives in the Smooth drawer

You were right. Gap split is **not** light-curve ingest.

Used only by smoothing / knot placement in `detrend_core.py`:

- `contiguous_segment_bounds` / `resolve_break_tolerance`
- every `apply_detrend_method` family (median, biweight, SG, Lightkurve flatten,
  smoothing spline, LSQ, P-spline)
- LSQ **Place knots** occupancy grid (`interior_knots_by_occupancy`)

Not used by: upload, working CurveDash, plot of raw points, select/delete,
ephemeris, LC export, residual arithmetic (residual is subtract/divide after
`T(t)` exists).

Move **Split on gaps** + **Break tolerance** into the Smooth drawer.
Running parabola later reuses the same widgets (`min-gap` is that switch, not a
second control).

### 2. Detrend is a separate Apply + LC export

Do **not** auto-freeze the residual when Smooth is applied.

- **Apply smooth**: writes the overlay on plot 1 (and the fit store). Plot 2
  stays empty until detrend is applied.
- **Apply detrend**: residual = mag subtract or flux divide from the last
  smooth; fills plot 2; enables residual download.
- **Download detrended**: export that residual as a light curve (`replace_series`
  plus local ephemeris apply), same formats as the working LC.

Today one button (`detrend-apply`, label "Apply smooth") does fit + residual.
Split that only in **step 2**. Step 1 only moves widgets.

### 3. Rough extrema: two GP-compatible downloads

Both land in the browser Downloads folder. Content must parse on the GP O-C page.

| Product | Filename suffix | Body |
|---------|-----------------|------|
| Intervals | `_int.dat` | GP `format_intervals_download`: `# Interval_Start  Interval_End` then `[t-δ, t+δ]` |
| Timing | `_rough_toms.dat` | Compact ToM: two columns `JD  σ(JD)` so `parse_compact_tom_contents` accepts it |

Do **not** use `_gp` for rough times. GP's own export is `{stem}_gp.dat`; the
Downloads folder would collide. O-C upload is content-based; the suffix need
not be `_gp`.

σ(JD): rough times have no uncertainty. **Do not invent a dummy sigma.** Write
`nan` as the second column (the O-C parser already stores non-finite σ as NaN).
Do **not** write GP `scale_limit`. Header comments: `# Rough {Minimum|Maximum} times`
plus `# JD_Minimum` / `# JD_Maximum` and `# JD_Std`.

δ is an extrema-drawer parameter; intervals are computed at export (and for
optional plot bands), not stored as a second table.

### 4. Shared stem + automatic suffixes

One stem field (from the upload name, editable), typically in the Light curve
drawer. The **field itself** holds `{upload}_lc` (do not leave a bare stem and
hope the download callback adds it). Every other product adds its own suffix
from that shared field. Users cannot tell files apart in Downloads otherwise.

Do **not** import `skvo_veb.utils.gp` or GP page CSS. Copy tiny helpers locally
(`_stem_from_upload_filename`, `_export_download_name`, `_apply_export_ephemeris`).

| Product | Download name |
|---------|----------------|
| Working light curve | `{stem}_lc.{ext}` (stem field already ends in `_lc`) |
| Smooth at observation times | `{stem}_smooth.{ext}` |
| Running-parabola native table (later) | `{stem}_smoothed.dat` |
| Detrended light curve | `{base}_detrended.{ext}` (`_lc` stripped first) |
| Rough intervals | `{stem}_int.dat` |
| Rough timing (O-C upload) | `{stem}_rough_toms.dat` |

Local helpers: `_lc_export_stem`, `_detrended_export_stem`, `_export_download_name`.
Add `_smooth` / `_rough_toms` the same way (do not duplicate `_int` /
`_detrended` / `_smooth` / `_rough_toms` / `_smoothed`).

### 5. Two plots, cleaning always on

- Plot 1: working photometry + overlays (smooth, LSQ knots, later extrema).
  Select / delete / unselect stay in the **strip above plot 1**, always.
- Plot 2: residual only, after Apply detrend. Empty before that.
- Figure toolbar: pan / zoom / lasso / box. No extra Pan radio.

### 6. Server later

No user LC in process globals. Probe may keep `dcc.Store` for now. Heavy blobs
(`working_lc`, `smooth_payload`, residual CurveDash) should go through get/set
wrappers so production can swap in Discovery's session cache. Extrema list and
UI flags stay in Store (tiny).

### 7. Stores and zoom (locked 2026-09-11)

The figure is a disposable view of stores. Do **not** keep zoom in a Store
or paste `relayoutData` back onto the next figure.

| Store | What it is |
|-------|------------|
| `detrend-store-lc` | The working light curve: one `CurveDash.serialize()` (times, photometry, errors, labels, `selected`, metadata) |
| `detrend-store-knots` | Isolated knot times (not photometry) |
| `detrend-store-result` | Derived fit overlay only. Must **not** replace plotted times / `y` / labels |
| `detrend-store-knot-pick` | Tiny JS hit event |
| `detrend-store-clientside` | Tiny knot-tool flag |

Dropped: `detrend-store-xrange`, `detrend-store-raw-relayout`,
`detrend-store-det-relayout`, `datarevision`, `selectionrevision`, point
`ids` / `uid`, SHA1 of the full serialize (that includes `selected` and
would rezoom on every click).

Zoom: Plotly `uirevision` only, Discovery-style token (filename, name,
domain, MJD/Date, row count, JD span). Same series → zoom stays. New file,
domain, or time-axis mode → autorange. Delete changes the extent, so Plotly
autoranges and drops stale orange marks (same as Discovery trim).

---

## Target drawers (`dbc.Accordion`, `always_open=True`)

Light curve item starts open and **is closeable**. Only Light curve is open on load.

**Light curve** (starts open; **is closeable**)

- Domain, show error bars, time crop (fit/plot only), P / Epoch
- Export: format + shared stem + **Export lightcurve** (`{stem}_lc.{ext}`)
- Not here: gap split, knot tool, method, Apply

**Smooth**

- Gap split + break tolerance
- Method radio + method params (including LSQ Place knots)
- Knot tool radio: Off / Add knot / Delete knot (or on the plot strip when
  method is LSQ; disable otherwise)
- Primary: **Apply smooth**
- Export (later): `{stem}_smooth.{ext}`; RP native `{stem}_smoothed.dat`

**Detrend**

- Primary: **Apply detrend** (step 2; gated on a smooth)
- Export: **Export detrended** as `{stem}_detrended.{ext}`

**Rough extrema** (step 4; widgets disabled until a smooth exists)

- Min/max, min peak distance, interval half-width δ
- **Find extrema**; manual add/delete when this drawer owns the plot tool
- Export: **Export intervals** (`_int.dat`), **Export times** (`_rough_toms.dat`)

Plot-tool conflict: cleaning always on. Extra modes are mutually exclusive.
When Smooth is open and method is LSQ: knot add/delete. When Rough extrema is
open: add/delete extremum. If both open, one plot-tool radio on the strip with
unavailable options disabled.

---

## Build order

Keep all existing behaviour until the step that explicitly changes it.
Hard-refresh after JS/CSS. Port 8052. Sample: `auxiliary/trend/data/tcp.vot`
and the labelled J0247 VOTable.

### Step 1 -- rearrange existing functionality (done 2026-09-11)

Accordion shell. Widgets moved; Apply still fills both plots; no RP or extrema.

- Title / `app.title`: Lightcurve processor
- Accordion: Light curve | Smooth | Detrend (Light curve starts open and is closeable)
- Light curve: domain, MJD / Date, errors, crop, ephemeris, format, stem with `_lc`, Export lightcurve
- Smooth: method, params, Place knots (filled primary), gaps, Apply smooth, Knot tool last
- Detrend: **Export detrended** only (still gated on current apply)
- Plot toolbar: both buttons always enabled; Delete selected outline
  caution orange; Unselect secondary outline; hints under `?`
- Plots: GP height ``clamp(20rem, 55vh, 40rem)``, Open Sans 12 / black ``#000``,
  no figure titles, GP-tight margins
- CSS: accordion tokens on `.detrend-page`; local `?` and caution button; no GP imports
- README: page name + drawer map; behaviour unchanged aside from labels/homes
- Timing suffix locked: `_rough_toms`

### Step 2 -- split Smooth vs Detrend apply

- Apply smooth: overlay + fit store; clear residual store; plot 2 empty
- Apply detrend: residual store from last smooth; plot 2; enable download
- Invalidate residual (and later extrema) when points are deleted or smooth
  is re-applied
- Detrend download uses the residual store, not a live recompute from an
  un-applied preview

### Step 3 -- running parabola as a Smooth method

- Overlay + residual at **observation times** `T(t_i)`
- Native centre-grid table is Smooth-drawer export only (`_smoothed.dat`)
- Reuse gap widgets; lock interpolate-vs-evaluate-at-`t_i` before coding

### Step 4 -- Rough extrema drawer

- `find_peaks` on the smooth; store `{id, jd, kind, origin: auto|manual}`
- New Apply smooth: drop auto hits; keep manual; say so in the drawer
- Delete photometry: clear smooth, residual, auto extrema
- Manual add/delete on plot 1 (knot-style hit-test)
- Two downloads with suffixes above
- Optional interval bands from the same list + δ

---

## Files (step 1)

| Path | Change |
|------|--------|
| `auxiliary/trend/detrend_app.py` | Accordion layout, title, widget homes |
| `auxiliary/trend/assets/detrend.css` | Accordion / drawer tokens |
| `auxiliary/trend/README.md` | Name + drawer map |
| `detrend_figures.py`, `detrend_core.py`, JS | Unchanged in step 1 |
| `plot_tcp_lc.py` | Do not touch |
| Component ids | Keep `detrend-*` in step 1 |

Callback ids stay. Only the Python parent of the same components moves.

---

## UI rules that apply to this probe

From `.cursor/rules/dash-page-ui.mdc`:

- Page class owns sizes; no new `style=` except visibility / data-driven colour
- Sentence case, British English
- One primary per drawer; plot-strip cleaning buttons stay enabled.
  Unselect is secondary outline. Delete selected is outline caution orange
  (``detrend-btn-caution-outline``) so the pressed ``:active`` look still
  uses Bootstrap inset shadow.
- Actions live with the object they change (clean on the plot, export in the
  drawer that owns the product)
- Flex-gap blocks, not mixed `mb-*`
- Long copy in `?` modals (can wait until after the accordion lands)

---

## Current apply/export ids (do not lose)

- `detrend-apply` -- today's fit + residual
- `detrend-download-lc-btn` / `detrend-download-lc`
- `detrend-download-btn` / `detrend-download`
- `detrend-export-format`, `detrend-export-stem`
- Fit payload: `detrend-store-result` (overlay; do not overwrite the LC)
- Working LC: `detrend-store-lc` (`CurveDash.serialize()`)
- Knots: `detrend-store-knots`
