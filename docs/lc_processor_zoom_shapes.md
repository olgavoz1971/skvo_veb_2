# Lightcurve processor: zoom reset when editing knots

Status: diagnosis only. No code change is implied by this note.

Symptom: after a zoom on plot 1, the first Add-knot or Delete-knot action
jumps the viewport back to the full series. Later knot edits in the same
session often keep the view. Photometry looks unchanged, so it feels like a
replot. It is almost always **axis autorange**, not a new scatter of the
points.

Locked product rule (from the processor plan): zoom is Plotly `uirevision`
only. There is no dedicated zoom store.

## Verdict

This is a **Plotly / Dash contract**, and our knot path **triggers** it.

It is not a random Plotly bug. `uirevision` was never a complete guarantee
once `layout.shapes` or `dcc.Graph.config.editable` changes. Sending a new
figure, a Dash `Patch` of shapes, or `Plotly.relayout({shapes: [...]})` all
hit the same Plotly path.

The last two processor fixes failed because they still changed `layout.shapes`
while the Dash-owned figure still said `autorange: true`.

## Two copies of the figure

After the user zooms there are two different layouts:

| Copy | Where | Axis state |
|---|---|---|
| Live Plotly graph | Browser `_fullLayout` | Zoomed `range`, `autorange` false |
| Dash `figure` property | React / server last write | `autorange` true (magnitude: `"reversed"`), no `range` |

User zoom is **not** written back into the Python figure. Every later layout
update that Plotly treats as a real layout change can re-apply the Dash copy
and autorange.

`uirevision` is supposed to keep UI state (zoom, pan, selection) when the
token is unchanged. It does that for many trace-only updates. It does **not**
reliably do that when `layout.shapes` changes.

## Why the first knot after zoom is special

Classic pattern, already seen on this project:

1. Plot has no knot lines, or Dash still thinks it has none.
2. User zooms. Only `_fullLayout` has the window.
3. First Add/Delete installs or replaces `layout.shapes`.
4. Plotly re-applies autorange from the Dash figure. Viewport jumps.
5. Later knot edits only extend or replace an **already present** shapes
   list. Plotly then often keeps the (new) UI state, so the jump seems to
   "go away".

The same jump can happen if shapes already exist and the **whole** `shapes`
array is replaced in one `relayout`, because Dash's layout still claims
autorange.

What the user sees as "replotting" is the axes expanding. The `Scattergl`
trace need not be rebuilt for that to happen.

## What we tried, and why it did not help

### 1. Knot tool is not a figure Input

Correct and still needed. Switching Off / Add / Delete must not rebuild
photometry. That was a real extra trigger, not the remaining one.

### 2. Dash `Patch` of `layout.shapes` only

Still a write to `dcc.Graph.figure`. Dash merges the patch into the
**stored** figure (unzoomed, `autorange` on). Plotly then draws that. First
Add after zoom resets; later edits can look fine because `uirevision` has
something to hold onto.

### 3. Clientside `Plotly.relayout({shapes: next})`

Does not write the Dash `figure` property. Still changes `layout.shapes` on
the live graph. Plotly.js then consults `gd.layout` (Dash-owned, autorange
on) and re-autoranges. Same visual result.

So "do not write `figure` from Python" is necessary and not sufficient.

## Current triggers in the processor

Files: `skvo_veb/pages/lightcurve_processor.py`,
`skvo_veb/assets/lc_processor_clientside.js`,
`skvo_veb/utils/lc_processor/figures.py`.

1. **Shapes replace.** Knot list → `store-lc-processor-knot-shapes` →
   `lcpKnot.applyShapes` → `Plotly.relayout(plotDiv, {shapes: next})`.
2. **Config editable.** Add mode sets `config.editable` and
   `edits.shapePosition`. Some Dash versions `Plotly.react` the stored
   (unzoomed) figure when `config` changes. That would jump on the **tool
   switch**, before any click.
3. **`relayoutData` as Input** on `edit_knots_on_plot`. A shapes relayout
   emits `plotly_relayout`. The callback should `PreventUpdate` unless the
   payload looks like a knot drag, but it is another shapes-related layout
   pass.
4. **Full figure rebuilds that are intentional.** Upload, crop, domain,
   time axis, error bars, delete points, Apply smooth (revision bump). Those
   are allowed to redraw. If an overlay exists, a knot edit also bumps
   revision and **does** rebuild the figure; that is a separate, honest
   replot.

Figure construction always sets `yaxis.autorange` to `True` or `"reversed"`
and does not stamp a zoomed `range`. See `_apply_y_axis_direction` in
`figures.py`.

## Precedent in this repository

The GP prep plot had the same first-shape jump: first **Add interval**
dropped zoom with an unchanged `uirevision`; later adds kept it.

The established workaround is already in
`skvo_veb/utils/lc_interaction.py`:

- `apply_plot_relayout_ranges_to_figure`
- reads the graph's last `relayoutData`
- writes explicit `xaxis.range` / `yaxis.range` and `autorange=False`

That is **not** a zoom store. It is Plotly's own last relayout event, used
only at the moment a figure (or shapes relayout) is applied.

## Suggestions

Do not invent a session zoom store. Do not keep trying "don't write
`figure`" as the whole fix. The viewport must travel **with** the shapes
update.

### Preferred: stamp ranges from `relayoutData` (GP pattern)

On any server rebuild that must change shapes (or that we cannot avoid),
take `State("lc-processor-graph-working", "relayoutData")` and call
`apply_plot_relayout_ranges_to_figure` before returning the figure.

Pros: already reviewed in this codebase; works when a full rebuild is
unavoidable (Apply smooth, delete points, overlay clear).
Cons: `relayoutData` is the last event, not a guaranteed snapshot. A
double-click autorange payload must be respected (empty / autorange true).
Date-axis values must stay in the form Plotly sent.

This can coexist with "knots are not a figure Input". Use it for the
rebuilds we still do, not as an excuse to rebuild on every click.

### Preferred for knot-only edits: clientside relayout with ranges

In `lcpKnot.applyShapes`, read `_fullLayout.xaxis.range` and
`yaxis.range` and send them in the **same** `Plotly.relayout` as `shapes`:

```text
{shapes: next, 'xaxis.range': [...], 'yaxis.range': [...],
 'xaxis.autorange': false, 'yaxis.autorange': false}
```

For magnitude, keep the reversed direction; do not send `autorange: true`.

Pros: knot clicks never write `figure`; zoom cannot lose to stale
autorange.
Cons: must handle date vs MJD range types; must not fight a user double-click
reset if that arrives as autorange.

### Also stop the config remount if the jump happens on tool switch

Keep Add/Delete off the figure callback. Prefer not to toggle
`config.editable` if Dash remounts the graph. Clientside
`shapes[i].editable` (already in `_setShapesEditable`) is enough for
dragging, once lines exist.

Confirm with a hard-refresh: zoom, then only switch Off → Add, no click.
If the view jumps there, `config` is a trigger of its own.

### Confirm which trigger before coding

| Test | If it jumps | Meaning |
|---|---|---|
| Zoom, switch to Add, no click | Config / editable remount | Do not write `config.editable` |
| Place knots, zoom, Add one more | Shapes replace, not empty→first | Relayout must include ranges |
| Zoom on empty knots, first Add | Classic first-shape case | Same as GP intervals |
| Zoom, Add, then Add again | First only | `uirevision` after shapes exist |
| Zoom with a smooth overlay, then Add | Revision bump + full rebuild | Stamp `relayoutData` on that rebuild |

Hard-refresh after any JS/CSS change. Cached `lc_processor_clientside.js`
makes these tests lie.

## What not to do

- Do not treat this as "Plotly is broken, wait for a library upgrade".
- Do not add a dedicated zoom `dcc.Store` unless the product rule changes.
- Do not rebuild photometry (`Scattergl`) to move a green line.
- Do not send a shapes-only `Patch` or shapes-only `relayout` and expect
  `uirevision` to save the window.
- Do not silently invent axis limits when `relayoutData` is missing. If there
  is no last relayout, leave autorange (unzoomed) and fail visibly only if
  a required widget is empty, not because zoom state is absent.

## Bottom line

Plotly keeps user zoom in the live graph. We keep `autorange: true` on the
Dash figure. Changing `layout.shapes` (or `config.editable`) makes Plotly
trust the Dash figure again. That is the jump.

The fix is to send the live ranges in the same update as the shapes, the
way the GP page already does with `relayoutData`. Until that happens, the
processor will keep rezooming in these cases.
