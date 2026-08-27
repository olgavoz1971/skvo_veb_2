# Interval handling performance on the Lightcurve Extrema Modeller

Scope: `skvo_veb/pages/gp_for_oc.py` and the interval-related helpers in
`skvo_veb/utils/gp/`. This note records why the page degrades badly as the
interval count grows, with measured numbers, and sets out how to correct it.

Reference workload used throughout: an uploaded light curve of **20 000 rows**
(0.86 MB transport JSON) with **300 intervals**, compared against the same file
with **5 intervals**.

## Status

Findings 1 to 3 are **implemented**. Findings 4 to 6 are **not started**.

Measured effect of the implemented work at 300 intervals:

| Operation | Before | After | Gain |
|---|---|---|---|
| Prep plot bands, unfolded | 9.76 s | 0.046 s | 212x |
| Prep plot bands, folded (900 copies) | 206.53 s | 0.134 s | 1541x |
| GP run preparation before first fit | 21.08 s | 0.310 s | 68x |
| Remove empty intervals | 21.24 s | 0.159 s | 134x |
| Prep figure payload | 1.50 MB | 0.64 MB | 0.86 MB smaller |

None of this changes what is computed, only how often the light curve is decoded
and how figures are assembled.

## Summary

The page slows down super-linearly in the number of intervals. Two independent
causes dominate, and both are quadratic or multiplicative in the interval count:

1. **Prep plot band drawing is O(n^2)** because bands are added to the figure one
   Plotly call at a time. 300 intervals cost 9.8 s per replot in the unfolded
   view and about 206 s in the folded view. This is server-side figure
   construction, but the user perceives it as the plot hanging.
2. **The whole light curve is decoded once per interval** during GP preparation.
   300 intervals cost 21 s of overhead before the first fit starts, which is why
   fitting "one interval at a time" still gets slower with more intervals.

Three secondary problems inflate the client side: the figure payload carries a
redundant copy of the entire light curve, a purely cosmetic band recolour makes
a full server round trip, and every prep figure update fans out into three extra
clientside callbacks that each receive the full figure and do not use it.

## How the measurements were taken

Synthetic light curve of 20 000 rows packed through
`skvo_veb.utils.gp.ingest.pack_uploaded_lightcurve`, 300 intervals of 0.05 d
spread over the time span, timed with `time.perf_counter` on the development
machine. Figure payload sizes are `len(json.dumps(fig.to_plotly_json()))`.

## Finding 1: quadratic band drawing in `update_prep_graph`

`plotly.graph_objects` re-validates the entire existing shapes tuple on every
`add_shape` or `add_vrect` call, so building n bands in a loop is O(n^2). Both
branches of `update_prep_graph` do exactly that: `fig.add_shape` per interval in
the unfolded branch, and `fig.add_vrect` per phase copy in the folded branch
(the extended fold produces roughly three copies per interval).

Measured cost of building the bands alone:

| Intervals | `add_shape` loop | One batched assignment | Speedup |
|---|---|---|---|
| 5 | 0.01 s | 0.001 s | 7x |
| 25 | 0.07 s | 0.003 s | 20x |
| 50 | 0.27 s | 0.006 s | 42x |
| 100 | 1.02 s | 0.013 s | 77x |
| 200 | 4.27 s | 0.026 s | 163x |
| 300 | **9.76 s** | 0.037 s | 261x |

Folded view, 900 calls (300 intervals x 3 phase copies):

| Method | Time |
|---|---|
| `add_vrect` loop (current) | **206.53 s** |
| `add_shape` loop | 99.65 s |
| `update_layout(shapes=[...])` batched | 0.114 s |

This is the signature the developer observed: going from 5 to 300 intervals is
60 times more intervals but roughly 1000 times more time.

`update_prep_graph` re-runs on every interval add, interval delete, mark toggle,
time-axis switch, view-mode switch, error-bar toggle, folding toggle and
working-window change, so this cost is paid constantly, not only on load.

**Correction (implemented).** Accumulate plain dicts in a Python list and assign
once. `prep_interval_band_shape` in
`skvo_veb/utils/gp/prep_interval_bands.py` builds one band dict, and
`update_prep_graph` collects them into `band_shapes` and finishes with a single
`fig.update_layout(shapes=band_shapes)` shared by both branches. Measured after:
0.046 s for 300 unfolded bands and 0.134 s for 900 folded copies.

```python
shapes = []
for index, interval in enumerate(intervals_data):
    ...
    shapes.append({"type": "rect", "x0": x0, "x1": x1, "y0": 0, "y1": 1,
                   "yref": "paper", "layer": "below",
                   "name": interval_shape_name(index), **band_style})
fig.update_layout(shapes=shapes)
```

A `vrect` is just a shape with `yref="paper"`, so the folded branch collapses
into the same batched assignment. The helper returns dicts rather than figures,
which keeps the utils layer free of Plotly figures as required. The former
`add_vrect` kwargs `line_width` and `line_color` map onto `line: {width, color}`
in a raw shape dict.

Folded bands stay anonymous (no shape `name`), matching the previous behaviour,
because mark mode is disabled while the curve is folded. Unfolded bands keep
their `gp-int-<index>` names for clientside styling.

## Finding 2: the light curve is decoded once per interval

`get_gp_flux_fragment(json_str, jd_min, jd_max)` takes the **serialised** light
curve, so each call performs a full `json.loads` of the 0.86 MB packet, builds
the full 20 000-row arrays, converts magnitudes to flux through Astropy units,
and only then slices out the requested window. Returning about 35 rows costs
20.8 ms.

Three call sites loop over intervals doing this:

| Call site | Trigger | 5 intervals | 300 intervals |
|---|---|---|---|
| `run_gp` work-items loop | **Run GP** | 0.40 s | **21.08 s** |
| `empty_interval_indices` | **Remove empty** | 0.4 s | **21.24 s** |
| `update_GP_scale` | **Guess parameters** | short-circuits on the first populated interval | worst case the same |

The 21 s in `run_gp` is spent **before any fitting begins**. The GP fits
themselves are genuinely per-interval and are not the problem.

**Correction (implemented).** Decoding is split from slicing in
`skvo_veb/utils/gp/flux.py`:

- `decode_gp_flux_arrays(json_str)` parses the transport packet once and returns
  `jd`, `flux` and `flux_err` arrays in the original row order.
- `slice_gp_flux_arrays(arrays, jd_min, jd_max)` masks those arrays to one closed
  interval and drops non-finite `jd` or `flux`.
- `get_gp_flux_fragment` remains as a thin wrapper over the two, so single-call
  users elsewhere are unaffected.
- `run_gp`, `empty_interval_indices` and `update_GP_scale` decode once and slice
  in the loop.

Measured after: GP run preparation for 300 intervals fell from 21.08 s to
0.310 s, and **Remove empty** from 21.24 s to 0.159 s.

Two deliberate choices:

- Slicing keeps boolean masking rather than `numpy.searchsorted`. Masking 20 000
  rows costs microseconds, so it captures essentially the whole gain, and unlike
  `searchsorted` it does not require sorting the light curve, so **row order is
  preserved exactly** and the fits see the same data in the same order as before.
- The former branch that delegated flux-native transports with a complete
  photcal pair to `lc_bridge.get_flux_fragment` has been removed as redundant:
  both flux paths unpack in the flux domain and apply the same closed-bound mask.
  `test_flux_native_with_photcal_pair_matches_bridge_fragment` pins that
  equivalence.

## Finding 3: `uirevision` carries the entire light curve JSON

```python
uirevision=(
    f"{lc_json_string}_{view_mode}_{folding_on}_{axis_mode}_"
    f"{show_prep_errorbars}_{working_window_store}_{fold_ephemeris_mode}_"
    f"{oc_a}_{oc_b}_{oc_c}"
),
```

The full transport JSON string is interpolated into the revision token.

| Figure payload | Size |
|---|---|
| With a short revision token | 0.50 MB |
| With `lc_json_string` in the token (current) | 1.35 MB |

That is 0.86 MB of dead weight per figure update. It is sent to the browser,
held in the `dcc.Graph` figure prop, compared by Plotly on every react, and
carried into every clientside callback that takes the figure as `Input` or
`State`.

**Correction (implemented).** `transport_revision_token` in
`skvo_veb/utils/gp/plot_data.py` returns a 16-character SHA-1 prefix of the
transport string, and `update_prep_graph` uses that in place of the string
itself. The digest is a change detector, not an integrity check. Hashing 0.86 MB
costs about 0.36 ms, against 0.86 MB saved on every figure update. Reset
semantics are unchanged: the token still changes exactly when the light curve
changes, so zoom resets on a new upload and survives interval edits.

## Finding 4: marking a band makes a full server round trip

Current chain for one double-click on a band:

1. JS click listener detects the double-click and sets
   `store-gp-prep-dblclick-pending`.
2. Clientside `toggleIntervalMarkFromDblClick` computes the new marked list.
3. `store-gp-intervals-marked` is an **`Input` to the server callback**
   `update_prep_graph`.
4. The server rebuilds the whole figure, including the 9.8 s shape loop from
   Finding 1, and sends 1.35 MB back.
5. The new figure retriggers three clientside callbacks that take
   `Input("prep-graph", "figure")`, each of which calls `Plotly.relayout` for
   dragmode, forcing a relayout of all 300 SVG rectangles.

The cheap path already exists in the codebase and is **never called**:
`_relayoutMarkedIntervalShapes` in `skvo_veb/assets/clientside_callbacks.js`
ends in `Plotly.relayout(plotDiv, { shapes: updated })`, which is exactly the
right operation. It is dead code.

**Correction.** See the design section below.

## Finding 5: clientside callbacks receive the figure and do not use it

| Function | Figure argument | Figure output |
|---|---|---|
| `applyIntervalMarkMode` | unused | declared, always `no_update` |
| `clearIntervalMarks` | unused | declared, always `no_update` |
| `applyTrendMode` | unused | declared, always `no_update` |
| `toggleIntervalMarkFromDblClick` | only `!figure` | declared, always `no_update` |
| `bindPrepGraphIntervalMarkClick` | only `!figure` | n/a |
| `bindPrepGraphTrend` | only `!figure` | n/a |
| `restoreTrendPreviewFromStore` | only `!figure` | declared, always `no_update` |

Three of these use `Input("prep-graph", "figure")`, so each figure update fans
out into three further clientside passes plus three `Plotly.relayout` calls.

**Correction.** Drop the unused `State("prep-graph", "figure")` arguments. The
`!figure` guards are only asking "has the graph been rendered yet", which
`_prepPlotlyGraphDiv()` already answers directly. For the two `bind*`
callbacks, trigger the rebinding from a small counter or a lightweight store
that the prep callback bumps, rather than from the figure itself. Also remove
the six `Output("prep-graph", "figure", allow_duplicate=True)` declarations that
never write a figure, so the renderer stops treating the graph as a possible
target of these callbacks.

## Finding 6: the registry rebuilds every card

`render_registry` re-renders all cards whenever the interval store, time axis or
working window changes. Each card is a `dbc.Card` containing a `CardBody`, two
nested `Div`s, two `html.B`, a `Span`, a `Button` and an `html.I`, so about nine
React components per interval, roughly 2700 for 300 intervals. `delete_interval`
then tracks 300 pattern-matched `n_clicks` inputs and identifies rows by
positional index.

**Correction.** Replace the hand-rolled card list with a single
`dash_ag_grid.AgGrid`, which the project conventions already prefer over
bespoke tables. The grid virtualises rows, so 300 intervals cost the same as 5,
and row deletion moves from 300 pattern-matched inputs to one `cellClicked` or
selection event. This is independent of the other corrections and can be done
last.

## Proposed design for marking intervals clientside

The developer's proposal is to keep marking entirely in the browser using
ready-made Plotly behaviour, and to defer the expensive point-versus-interval
work until the user presses a **Remove** button. That is the right shape for
this interaction, with one clarification about which work is actually expensive.

### Which work is heavy, and which is not

Removing marked intervals is **not** heavy on the server: it is list filtering
in `intervals_without_marked_indices`, which is microseconds. The expensive
point-versus-interval scan is `empty_interval_indices`, used by the separate
**Remove empty** button, and the equivalent scan inside `run_gp`. Both are
addressed by Finding 2. So the deferral principle is correct, but after
Finding 2 lands there is no large batch cost left to defer for **Remove
marked**; the win there comes purely from not rebuilding the figure on every
click.

### Recommended approach: clientside recolour with indexed relayout

Minimal change, keeps the existing interaction (double-click a photometry point
inside a band):

1. Keep the existing hit test. `store-gp-interval-pick-bands` is small (three
   numbers per interval, about 15 kB for 300 intervals) and the JS hit test in
   `_hitIntervalIndex` is already correct.
2. On toggle, recolour clientside instead of returning to the server. Plotly
   accepts indexed attribute strings, so a single band can be restyled without
   touching the other 299:

   ```javascript
   Plotly.relayout(plotDiv, {
       'shapes[7].fillcolor': 'rgba(220, 53, 69, 0.35)',
       'shapes[7].opacity': 0.35,
       'shapes[7].line.color': '#dc3545',
       'shapes[7].line.width': 2,
   });
   ```

   This is strictly cheaper than the existing dead `_relayoutMarkedIntervalShapes`,
   which replaces the whole shapes array. Keep the array-replacement variant only
   for **Clear marks**, where many bands change at once.
3. Remove `store-gp-intervals-marked` from the `Input` list of
   `update_prep_graph`. The marked state then no longer triggers a server
   replot. The server still needs the marked set when it does rebuild the figure
   for another reason, so it should stay as a `State`.
4. **Remove marked** keeps its single server round trip, which is the one place
   the user expects to wait.

Note that shape indices must line up with `intervals_data` indices. Today the
band loop skips intervals outside the working window, so shape index and
interval index diverge as soon as a working range is active. The shape `name`
(`gp-int-<i>`) already carries the true interval index, so the clientside code
should look the band up by name and use its array position for the relayout
path. Alternatively, emit a band for every interval and hide out-of-window ones
with `visible: False`, which keeps the two indices identical.

### Native Plotly features worth using

Confirmed against the Dash documentation on image annotations:

- **`layout.activeshape`** styles the shape currently selected by clicking, with
  no custom JS at all. Useful, but it highlights only one shape at a time, so it
  cannot express "mark twenty bands, then remove them all". It is a cursor, not
  a selection set. Not a replacement for the marked store.
- **`eraseshape` modebar button** natively deletes the active shape in the
  browser. This enables an alternative flow with almost no custom JS: click a
  band, press erase, the band disappears immediately, and one **Apply**
  button reads the surviving shapes from `relayoutData` and rewrites the store.
  It matches the "wait once at the end" requirement well. Two cautions: making
  shapes clickable requires them to be editable, which also makes them
  draggable unless `config.edits.shapePosition` is kept off, and the shapes
  array also holds the trend-preview shape, so any sync must filter by the
  `gp-int-` name prefix.
- **`dragmode="drawrect"` with `newshape`** lets the user draw new rectangles
  entirely clientside and reports them through `relayoutData`. This is a
  candidate for a future, faster way of *creating* intervals, replacing the
  current select-points-then-press-Add flow. Out of scope for this work.
- **`dash.Patch`** supports indexed assignment, `append`, `extend`, `insert`,
  `clear`, `remove` and `del` on figure sub-properties, including lists such as
  `layout.shapes`. Where a server round trip is genuinely wanted, returning
  `Patch()` with a targeted shape assignment sends a tiny payload instead of the
  whole figure. Worth keeping in mind for any remaining server-driven band
  restyle.

### Longer-term option: bands as traces rather than shapes

Shapes render as SVG even when the data trace is `Scattergl`, so 300 bands means
300 SVG rectangles that Plotly re-lays-out on every zoom, pan and dragmode
change. Drawing all unmarked bands as one filled trace and all marked bands as a
second filled trace would reduce that to two traces, remove the O(n^2) figure
construction entirely, and make toggling a band a cheap `Plotly.restyle` that
moves one rectangle between the two traces. The trade-off is that clicks inside
a filled polygon are not reported by Plotly, so the hit test would still be
driven by clicks on photometry points. This is a larger change and should only
be considered if the batched-shapes fix from Finding 1 proves insufficient.

## Order of work

1. **Finding 1**, batched shape assignment. **Done.**
2. **Finding 2**, decode once and slice. **Done.**
3. **Finding 3**, short `uirevision` token. **Done.**
4. **Finding 4**, clientside marking, plus **Finding 5**, dropping the unused
   figure arguments. Not started. Best done together because they touch the same
   callbacks.
5. **Finding 6**, registry on `AgGrid`. Not started. Independent, largest UI
   change.

Steps 1 to 3 were behaviour-preserving and are covered by timing plus the tests
listed below. Steps 4 and 5 change the callback graph and the registry markup,
so they warrant manual checking of the mark, clear, remove and trend-removal
flows in the browser.

### Tests covering the implemented work

- `skvo_veb/tests/test_gp_flux_slicing.py`: decode and slice contract, closed
  bounds, row-order preservation, wrapper equivalence, decode-once equivalence,
  magnitude-native conversion, bridge equivalence, revision token behaviour.
- `skvo_veb/tests/test_gp_empty_intervals.py`: emptiness detection on the new
  path, closed-bound edges, and a guard that the light curve is decoded once per
  call rather than once per interval.
- `skvo_veb/tests/test_gp_prep_interval_bands.py`: band shape geometry, style
  agreement with `prep_interval_band_shape_style`, anonymous folded bands, and
  pass-through of date-axis string bounds.

Note that seven tests fail in `test_lc_providers_gaia.py`,
`test_lc_providers_gaia_dr3_aip.py`, `test_lc_discovery_search.py` and
`test_lc_tabular_export.py`. These fail identically on a clean tree and are
unrelated to interval handling.

## Out of scope

- Keep-result defaults, badge colours and the accordion help Markdown are not
  touched by any of the above.
- The GP fitting mathematics is unchanged. Findings 1 to 3 alter only when and
  how often data is decoded and figures are built, not what is computed.
