# Dash / Plotly: client mark, server delete, keep zoom

**Audience:** agents copying this pattern onto another Dash page that uses
Plotly `Scattergl` (WebGL) photometry.

**Reference implementations:**

- Lightcurve processor (`/lc_processor`): `skvo_veb/pages/lightcurve_processor.py`,
  `skvo_veb/assets/lc_processor_clientside.js` (`lcpSelect`)
- Lightcurve Discovery (`/lc_discovery`): `skvo_veb/pages/lightcurve_discovery.py`,
  `skvo_veb/assets/lc_discovery_clientside.js` (`lcdSelect`). Fold is an extra
  zoom tag (`phase`) because it changes the x-axis independently of MJD/date.

Shared helpers:

- Stamp: `skvo_veb/utils/lc_interaction.py` (`apply_zoom_store_to_figure`);
  processor wrapper `apply_processor_zoom_store`
- Row delete: `skvo_veb/utils/lc_interaction.py` (`delete_rows_by_perm_indices`)
- Processor product notes: [lightcurve_processor.md](lightcurve_processor.md)
- Knot-shape zoom (different problem): [lc_processor_zoom_shapes.md](lc_processor_zoom_shapes.md)

Hard-refresh the browser (Ctrl+Shift+R) after any JS change. Cached
`*_clientside.js` makes selection tests lie.

---

## When to use this

Use this split when **all** of the following are true:

1. The plot is **WebGL** (`go.Scattergl`). Do not switch to SVG to "make
   selection easier".
2. The user **unions** click / box / lasso marks. Orange must survive a
   second lasso until **Unselect** or **Delete**.
3. Marks are UI only. The light curve stays in the **server cache**, not in
   a `dcc.Store`.
4. **Delete** mutates the cached table and **rebuilds** the figure so traces
   and cache agree.
5. That rebuild **must** change Plotly `uirevision` (row count or time span),
   so zoom cannot ride `uirevision` and needs a **zoom store**.

Do **not** use this for time-window trim (store `{xmin, xmax}` only and crop
on the server). That is a different contract; see Discovery / TESS pages and
`docs/lightcurve_data_flow.md`.

Do **not** change `CurveDash` unless the page has no `perm_index`. The
processor leaves `CurveDash.selected` unused for live marks.

---

## Why native Plotly is not enough

Plotly box/lasso **replaces** `selectedpoints` unless Shift is held. A
server union into `CurveDash.selected` plus a figure rebuild with unchanged
`uirevision` does not win: Plotly restores the **last native** set.

A Dash `clientside_callback` that **outputs `figure`** (or a `Patch` of
`selectedpoints`) fights the same `uirevision` path on Scattergl.

Empty-space clicks fire `selectedData` with no points. That is **not**
Unselect.

WebGL events often drop `customdata` and keep `id` / `pointNumber`. Trace
`ids` must be `perm_index`. Overlay traces (trend, extrema) must **not**
carry photometry `ids`.

Delete changes `n` or JD span, so `plot_uirevision` **must** change. Zoom
is then lost unless the new figure already has explicit axis `range` and
`autorange=False`.

---

## Ownership split

```text
 Click / box / lasso
        │
        ▼
 Client: union perm_index into a small dcc.Store
 Client: Plotly.restyle selectedpoints on the LIVE graph
        │  (do not write dcc.Graph.figure)
        │
 Unselect  →  client: empty store + restyle []
        │
 Delete    →  server: drop those rows in the cache
        │             bump figure revision
        │             rebuild Scattergl (no leftover selectedpoints)
        │             stamp zoom store onto layout
        ▼
 Screen: remaining points, marks cleared, same viewport if the store had ranges
```

| Concern | Where | Shape |
|--------|--------|--------|
| Live orange set | Browser `dcc.Store` | list of `perm_index` ints |
| Paint orange | Client, live `.js-plotly-plot` | per-trace `selectedpoints` |
| Unselect | Client | empty list + restyle |
| Photometry rows | Server cache (`CurveDash`) | never in `dcc.Store` |
| Delete | Server | `delete_rows_by_perm_indices` |
| Viewport after delete | Browser zoom `dcc.Store` | axis ranges + coordinate tags |
| View-only replot (errors, crop) | Plotly `uirevision` | token **omits** the mark list |

---

## Identities (do not mix these)

| Name | Meaning |
|------|---------|
| `perm_index` | Stable row id on the cached table. Survives delete of *other* rows. |
| Trace `ids` / `customdata` | Same integers, on **photometry** Scattergl traces only. |
| `selectedpoints` | Trace-local indices (`0 .. n_trace-1`), rebuilt from the perm set every paint. |
| `pointIndex` / `pointNumber` | Last resort, and only with the live trace's `ids` array. Wrong across labelled traces and overlays. |

Map event → perm in this order: `point.id`, `customdata`, then
`plotDiv.data[curveNumber].ids[pointNumber]`.

---

## Stores (keep them tiny)

Add two page-local stores. Do not put the light curve in either.

**Mark store** (e.g. `store-<page>-selected-perm`):

- `data=[]` initially.
- List of ints. Normalise with `normalize_selected_perm_store` before delete.

**Zoom store** (e.g. `store-<page>-zoom`):

```text
{
  axis: "mjd" | "date",      # the x mapping when the snapshot was taken
  domain: "mag" | "flux",    # y units when the snapshot was taken
  x_autorange: true | false,
  y_autorange: true | false,
  x0, x1,                    # only when x_autorange is false
  y0, y1                     # only when y_autorange is false
}
```

Date-axis values: serialise `Date` to ISO strings in JS; Plotly accepts them
on a date axis. Do not convert them to MJD in the store.

Clear the zoom store when the **coordinates** change: new file, time-axis
mode, photometric domain. Crop may keep it (same plot units).

Clear the mark store on new file and after a successful delete.

---

## Client: mark and unselect

Put a namespace in that page's `assets/*_clientside.js` (processor:
`lcpSelect`). Register Dash `clientside_callback`s on the page module.

### Bind the live graph

On figure (and mark-store) updates, attach to
`#<graph-id> .js-plotly-plot` (the node with `.on`):

- `plotly_selected` and `plotly_click`
- skip if a competing tool owns the gesture (knot add/delete, extremum pick)
- ignore events with no `points` (empty-space deselect is not Unselect)
- union perms into the mark store
- `Plotly.restyle` `selectedpoints` on **every** trace: photometry traces
  get mapped indices; traces **without** `ids` get `[]`
- delay a second paint (0 / 50 ms) so it runs **after** Plotly's native
  replace
- **do not** assign `dcc.Graph.figure`

Re-paint from the mark store after a figure rebuild that did **not** delete
(error bars, crop) so orange comes back on the new traces.

### Dash `selectedData` / `clickData` backup

A clientside callback may also union into the mark store. Union onto both
the in-memory perm list **and** the store payload so a later Dash event
cannot shrink a live-binder union. Prefer `id` and live `ids`; do not
require `customdata`.

### Unselect

Clientside only: write `[]`, restyle empty. No cache write, no
`uirevision` bump, no figure rebuild.

### Lasso outline

Clearing `layout.selections` can relayout. If the user is already zoomed,
include the current `_fullLayout` ranges in that same `relayout` so axes
do not jump. Do not lock a full autorange view as an explicit range.

---

## Server: delete, then rebuild

Delete is the first moment the cache and the figure must both change.

1. Read the mark store (`State`), not `CurveDash.selected`.
2. Fail fast if the list is empty (`PreventUpdate`), if no rows match, or
   if the delete would remove every row (`PipeException`, no cache write).
3. `delete_rows_by_perm_indices` (keeps surviving `perm_index` values).
4. Write the cache. Clear derived blobs if they are now invalid.
5. Clear the mark store (`[]`).
6. Bump the figure revision so the plot callback rebuilds Scattergl
   **without** painting leftover `selectedpoints`.

The rebuilt figure is the synchronisation point. Do not try to splice
points out of the live GL traces on the client.

---

## Zoom after a real rebuild

### Two mechanisms (do not confuse them)

| Situation | Keep zoom with |
|-----------|----------------|
| View-only replot, same rows and time span (`uirevision` unchanged) | Plotly `uirevision` only. Do **not** put the mark list in the token. |
| Rebuild that **must** change `uirevision` (delete, new file) | Stamp layout from the zoom store. |

`uirevision` cannot mean both "this is a new series" and "keep the old
window".

### Capture

Clientside on `relayoutData`. Ignore payloads with no `xaxis*` / `yaxis*`
keys (shape-only relayouts). Prefer a snapshot of `_fullLayout` when the
graph exists; otherwise merge range / autorange keys into the previous
store.

Treat `autorange === true` (and magnitude `autorange === "reversed"` while
still autoranging) as "no explicit window". Do not invent limits.

### Apply (layout, not GL)

In the **Python** figure builder, after traces and default `autorange`,
call a helper like `apply_zoom_store_to_figure` (processor:
`apply_processor_zoom_store`):

- skip if the store is empty
- skip if `axis` or `domain` does not match this figure
- skip if extra coordinate tags (Discovery `phase`) do not match
- skip axes flagged autorange
- otherwise `update_xaxes` / `update_yaxes` with `range=[lo, hi]` and
  `autorange=False`

Scattergl does not need a special zoom API. Axes are cartesian **layout**.
The new figure JSON must already contain the window before Dash replaces
the graph.

Pass the zoom store into the plot callback as **State** (do not make it an
Input: a store write must not rebuild photometry).

After a shallow Dash/page refresh, a clientside-only store can look empty
to a server `State` until the next full load or a server round-trip. If
delete rezooms after a soft refresh, hard-reload the page before rewriting
the pattern.

---

## Port checklist (another page)

Copy the *split*, not the processor widget ids.

1. Photometry traces: `ids` and `customdata` = `perm_index`. Overlays have
   neither photometry `ids` nor selectable markers that share that id space.
2. Two stores: perm list, zoom snapshot. Light curve stays in the cache.
3. Clientside namespace: live bind + paint; `selectedData`/`clickData`
   union; Unselect; `relayoutData` zoom capture; invalidate zoom when
   coordinates change.
4. Skip mark intercept when another plot tool owns the click.
5. Ignore empty `points`. Unselect is a button (or an explicit control).
6. Delete: server, perm store, fail-fast, revision bump, clear perm store.
7. Plot rebuild: do not paint from `CurveDash.selected`. Stamp zoom if the
   snapshot matches.
8. Upload / new data: clear both stores.
9. `uirevision` omits the mark list; it **does** include n / time span so
   delete is a new series.
10. British English UI; no photometry in `dcc.Store`; no silent fallbacks
    for missing perms.

---

## What not to do

- Do not union into `CurveDash.selected` on every click.
- Do not put the light curve in `dcc.Store`.
- Do not output `figure` or a `Patch` of `selectedpoints` from a mark
  callback.
- Do not put the perm list into `uirevision`.
- Do not treat Plotly empty-deselect as Unselect.
- Do not map `pointIndex` through a single dataframe order on a labelled
  multi-trace plot.
- Do not paint trend / extrema traces as selected photometry.
- Do not invent axis limits when the zoom store is missing; leave autorange.
- Do not rebuild Scattergl to move a knot line or other overlay shape
  (see [lc_processor_zoom_shapes.md](lc_processor_zoom_shapes.md)).
- Do not switch Scattergl to SVG for this problem.

---

## Manual test (port acceptance)

Hard-refresh. Load data.

1. Lasso A, then lasso B: orange is the **union**.
2. Click empty space: orange stays.
3. Unselect: orange gone; zoom unchanged; no server delete.
4. Mark again, zoom, Delete selected: those rows gone, remaining traces
   match the cache, **viewport kept**.
5. Load a new file: marks and zoom store cleared; autorange.
6. With a competing tool on, clicks do not add photometry marks.
