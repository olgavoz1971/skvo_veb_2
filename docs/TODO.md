# Project TODO

**Audience:** agents and developers. Do not start from chat history; this
file is the agreed backlog. Default remains think first; implement only
when the developer asks.

Open work lives here as tickets. Architecture, how-tos, and product notes
stay in the linked docs. Add a new ticket at the bottom of **Open** and
give it the next unused ID. When a ticket is done, move its row to
**Done** and leave the body until the developer asks to drop it.

---

## Open

| ID | Title | Status |
|----|-------|--------|
| 1 | Discovery shared fetch cache (per provider) | Open |
| 2 | TESS time-interval cleaning (client mark, server trim, keep zoom) | Open |

## Done

*(none)*

---

## Ticket 1 — Discovery shared fetch cache (per provider)

**Page:** Lightcurve Discovery (`/lc_discovery`).

**Related:** [caching_architecture.md](caching_architecture.md),
[mission_lightcurve_providers.md](mission_lightcurve_providers.md) (§4.4
`cache_key`), `skvo_veb/pages/lightcurve_discovery.py`
(`fetch_lc_discovery_lightcurve`), `skvo_veb/utils/lc_discovery_load.py`,
`skvo_veb/utils/lc_session_cache.py`.

### Goal

Discovery is meant to be a **two-cache** design. Today only the second layer
exists.

| Layer | Purpose | Shared across users? | Mutable? |
|-------|---------|----------------------|----------|
| **Archive fetch cache** (missing) | Immutable public download (VO light curve / archive payload) so a second Retrieve of the same product does not hit the archive | Yes | No (replace only on `force_refresh`) |
| **Session cache** (present) | Working `CurveDash` for this tab: fold, domain, select, delete, export | No (`user_tab_id`) | Yes |

Implement the missing **shared** layer so Retrieve is cheap when another
session (or the same user later) asks for the same catalogue product.

**Preferred shape: per provider.** One Discovery-wide blob store keyed only
by a hash is allowed as the *disk mechanism*, but ownership, directory, TTL,
and payload format should sit **with the mission adapter**. Archives are not
interchangeable (TAP VOTable vs Sky Patrol vs SSA `accref`). Gaia DR3 AIP
already has a private prefetch JSON store; do not flatten that into a single
anonymous directory without an explicit decision.

### Current state (do not re-derive)

- Fetch docstring: *no shared archive fetch cache (deferred)*.
- Pipeline: `provider.fetch_lightcurve(lc_key)` → `volc_to_curvedash` →
  `write_serialized_lc("lc_discovery", user_tab_id, ...)`.
- Session cache is `diskcache` under `USER_CACHE_DIR`, key
  `lc_discovery_{user_tab_id}_data`. Plot/select/delete mutate that copy.
- Browser `dcc.Store` holds catalogue UI and `user_tab_id`, not photometry.
- `MissionLightcurveProvider.cache_key(lc_key)` already returns a SHA-256 of
  the canonical `lc_key` document (`lc_providers/lc_key.py`). Unused by a
  shared fetch wrapper.
- `flask_caching` / `FileSystemCache` is **not** wired anywhere. `AGENTS.md`
  still requires that pattern for public archive data: thread-safe shared
  disk cache, deterministic keys, no raw global `dict`.
- Provider-local exceptions (not a Discovery-wide layer):
  - Gaia DR3 AIP: epoch-photometry JSON by `source_id`
    (`lc_providers/gaia_dr3_aip/prefetch_store.py`).
  - ASAS-SN Discovery path: no pickle cache (unlike the older ASAS-SN page
    note in `caching_architecture.md`).
  - Gaia ARI/VEB, OGLE, UPJS, personal: comments say no cache yet.
- `docs/caching_architecture.md` still claims the session cache is TESS-only.
  That is stale (Discovery and the processor both use `lc_session_cache`).
  Update it when this work lands.

### Locked constraints

1. **Do not put the light curve in `dcc.Store`.** Session cache stays the
   working copy.
2. **Do not cache the mutated `CurveDash` as the shared hit.** Shared cache
   is the **public fetch** (`VOLightCurve` or the archive bytes the provider
   already understands). After a hit, still `volc_to_curvedash` into a **new**
   session copy so user A’s deletes never appear for user B.
3. **Re-retrieve** (`force_refresh=True`) must bypass the shared cache and
   replace the stored fetch.
4. **Fail fast.** Corrupt cache files: surface the error; do not silently
   invent photometry. Healing (delete file and refetch) is allowed only if
   the developer agrees per provider, as TESS FITS already does.
5. **No Dash imports** in `lc_providers/` or the fetch wrapper.
6. **Math/VO reading** still goes through GAVO / Astropy / `pyvo` as in
   `AGENTS.md`. The cache only stores and returns bytes or an already-built
   `VOLightCurve`.
7. **British English** in any new user-facing string (e.g. cache miss is not
   a UI message unless Retrieve fails).

### Proposed implementation (when asked to code)

Think of three pieces. Prefer small wrappers over a new framework.

#### 1. Shared disk backend

- `flask_caching` with `FileSystemCache` (or the project’s existing
  `diskcache` **only if** the developer rejects Flask-Caching for this
  layer). Root under something like `CACHE_DIR/lc_providers/<mission_id>/`,
  not `USER_CACHE_DIR`.
- Key: `mission_id` + `provider.cache_key(lc_key)` (and fetch variant if
  `discovery_context` changes the product). Never use `user_tab_id` here.
- Thread-safe; no module-level `CACHE = {}`.

#### 2. Per-provider policy

Each adapter decides:

- Whether it participates (some TAP streams may stay uncached at first).
- What is stored (VOTable bytes, JSON epoch table, pickled `VOLightCurve`
  only if serialisation is already defined and versioned).
- TTL, if any (public photometry can be long-lived; say so in the provider
  `config.py`).
- How `force_refresh` deletes or overwrites **that** provider’s entry.

Do **not** require every provider to share one payload schema on day one.
Do require every participating provider to go through the same
get-or-fetch helper so Discovery itself does not grow `if mission_id`
branches.

#### 3. Discovery load path

In `lc_discovery_load.fetch_discovery_volightcurve` (or a new
`lc_providers/fetch_cache.py` called from there):

1. If not `force_refresh`, look up shared cache.
2. On miss, `provider.fetch_lightcurve(...)`, then write shared cache.
3. Always return `VOLightCurve` to `volc_to_curvedash` → session write.

The page callback stays a thin background job. It must not learn cache
paths.

#### Gaia AIP

Either wrap the existing prefetch store as that provider’s implementation of
the shared layer, or keep it and document it as the AIP backend so agents
do not add a second Gaia epoch cache.

### Out of scope

- Session-cache design (`lc_session_cache`) except documenting the split.
- Client-side Plotly selection (see
  [dash_plotly_select_delete_zoom.md](dash_plotly_select_delete_zoom.md)).
- Catalogue search result caching (cone/TAP tables) unless the developer
  expands this ticket. First target is **Retrieve lightcurve**.
- Changing `CurveDash`.
- Putting shared hits into the per-tab session key.

### Agent checklist

1. Confirm with the developer: Flask-Caching vs `diskcache`; cache
   `VOLightCurve` vs raw archive bytes; Gaia AIP fold-in vs leave as-is.
2. Add the wrapper under `lc_providers/` or `utils/` with no Dash.
3. Wire **one** provider end-to-end (prefer a slow public fetch: ASAS-SN or
   Gaia TAP, not a mock).
4. Tests: miss → fetch → hit; `force_refresh` refetches; two namespaces /
   two `lc_key`s do not collide; corrupt file fails visibly.
5. Second user / second `user_tab_id` gets a **fresh** session `CurveDash`
   from the same shared VO payload.
6. Update `caching_architecture.md` (Discovery uses session cache; fetch
   cache is per provider). Mark this ticket done when the work lands.
7. User-facing Retrieve behaviour unchanged except faster hits.

### Status

**Open.** Shared Discovery fetch cache is not implemented. Session cache is.
Do not treat Gaia AIP prefetch as completing this ticket.

---

## Ticket 2 — TESS time-interval cleaning (client mark, server trim, keep zoom)

**Page (primary):** TESS curve (`/tess_lc`), `skvo_veb/pages/lightcurve_tess_srv.py`.

**Related:** [dash_plotly_select_delete_zoom.md](dash_plotly_select_delete_zoom.md)
(processor + Discovery **split**, not their perm-index union),
[lightcurve_data_flow.md](lightcurve_data_flow.md) (§ trim and export window),
[caching_architecture.md](caching_architecture.md) (§ hybrid client–server),
`skvo_veb/utils/lc_interaction.py` (`trim_curvedash_from_selection_bounds`,
`apply_zoom_store_to_figure`), `store_tess_lc_srv_selection_bounds`.

### Goal

Give TESS archive cleaning the same **client mark / Unselect / server
mutate / rebuild / zoom store** ownership as Lightcurve Processor and
Discovery, while keeping TESS’s existing contract: the user selects a
**time interval**, not an arbitrary set of points.

**Trim selected** already deletes the boxed JD window (`lcd.cut`). That
action stays. What is missing is the processor/Discovery interaction
quality: the interval mark must survive empty-space clicks until
**Unselect**, the native box must not fight the stored window, and zoom
must survive the figure rebuild after trim.

### Keep (do not copy processor marks)

| Processor / Discovery | TESS (this ticket) |
|-----------------------|--------------------|
| Client store of `perm_index` ints | Client store of one interval `{xmin, xmax, time_axis_mode}` (plus fold tag if needed) |
| Click / lasso **union** of points | **One** horizontal time window (replace on a new box, as today) |
| `delete_rows_by_perm_indices` | `trim_curvedash_from_selection_bounds` → `lcd.cut` |
| Orange `selectedpoints` on individual markers | Interval highlight (box / span). Do **not** mark a sparse subset of points inside the window |

Do **not** port `lcpSelect` / `lcdSelect` point union onto TESS.

### Current state (do not re-derive)

- Clientside callback copies `selectedData.range.x` into
  `store_tess_lc_srv_selection_bounds` (~16 bytes). Requires Plotly
  **box** `range.x`; a lasso payload has `points` and often **no**
  `range`.
- **Trim selected** reads that store, mutates the **server** user cache,
  bumps the plot UUID, and clears `selectedData`. Light curve is not in
  `dcc.Store`.
- No **Unselect** control. Empty-space clicks / native deselect can drop
  the Plotly outline even if the bounds store still holds a window (or
  the reverse).
- No zoom store. Trim changes n / JD span so `uirevision` must change;
  the viewport is lost unless ranges are stamped on the new figure
  (same reason as processor delete).
- Fold is forbidden for trim (`require_time_view_for_trim`). Time-axis
  change already clears bounds.
- **TESS cutout** (`/tess`) uses the same `{xmin, xmax}` capture but
  holds the working curve in `store_tess_cutout_lightcurve`. That is a
  different architecture; do not “fix” it by copying processor perm
  marks, and do not enlarge that store.

### Locked constraints

1. **Time interval only.** Store display `xmin` / `xmax` (and the axis
   mode they were drawn in). Never a list of `perm_index`. Never union
   disjoint gaps unless the developer asks.
2. **Do not put the light curve in `dcc.Store`.** `/tess_lc` stays on the
   server user cache (`user_tab_id`).
3. **Do not change `CurveDash`** for live marks. Do not write the
   interval into `CurveDash.selected`.
4. **Fail fast** if Trim is clicked with no usable bounds. Do not invent
   a window from zoom or from `relayoutData`.
5. **Unselect** is a button (or an explicit control). Empty-space
   Plotly deselect is **not** Unselect; it must not wipe the stored
   interval.
6. After trim, rebuild the figure and **stamp zoom** with
   `apply_zoom_store_to_figure` when axis / domain / extra tags match.
   Invalidate the zoom store when the time axis (or fold) changes.
7. British English UI. Scattergl stays; do not switch to SVG.
8. Reuse `trim_curvedash_from_selection_bounds`. Do not reimplement
   JD conversion or `cut` in the page.

### Proposed implementation (when asked to code)

Copy the *split* from the processor/Discovery pattern doc, substituting
the interval store for the perm store.

1. Keep (or replace the inline JS with a small `assets/` namespace)
   bounds capture from box `range.x`. If lasso is offered, derive the
   interval from the **x-span of the event**, not from point ids — still
   one `[xmin, xmax]`. Confirm with the developer whether lasso is in
   scope; today’s code is box-only.
2. Add **Unselect**: clear the bounds store and the live Plotly
   selection outline (`relayout` `selections: []`), without a server
   trim and without rebuilding photometry.
3. Add a zoom store + `relayoutData` capture + invalidate on time-axis
   (and fold). Plot callback takes zoom as **State** and stamps after
   trim rebuild. Fold extra tag only if TESS trim is ever allowed in
   phase view (today it is not).
4. **Trim selected** stays the server action: bounds store →
   `trim_curvedash_from_selection_bounds` → cache write → revision bump
   → clear bounds. Fail if the cut would empty the curve (same spirit as
   Discovery delete).
5. New Retrieve / re-retrieve: clear bounds and zoom stores.
6. Tests: bounds parse; missing bounds fail visibly; trim removes the
   JD interior and keeps survivors; zoom stamp skips mismatched axis;
   no photometry in the bounds store.
7. When this lands, update
   [dash_plotly_select_delete_zoom.md](dash_plotly_select_delete_zoom.md):
   TESS is the **interval** variant of the same split, not a
   counter-example to ignore.

### Out of scope

- Ticket 1 (Discovery shared fetch cache).
- Point-wise union / click-to-mark as on processor and Discovery.
- Changing `CurveDash`.
- Catalogue / MAST search cache.
- **TESS cutout** (`/tess`) unless the developer expands this ticket.
  Cutout still serialises the working curve in the browser; do not
  treat that as the `/tess_lc` pattern.

### Agent checklist

1. Confirm: box only vs lasso-as-x-span; Unselect label; whether Trim
   copy stays “Trim selected”.
2. Interval store + Unselect on the live graph; no `figure` output from
   the mark callback.
3. Zoom store stamped on post-trim rebuild.
4. Server trim still uses `trim_curvedash_from_selection_bounds` only.
5. Manual: box A, click empty space (interval stays), Unselect, box
   again, zoom, Trim selected → gap gone, viewport kept.
6. Update the pattern doc and [lightcurve_data_flow.md](lightcurve_data_flow.md)
   trim section.

### Status

**Open.** `/tess_lc` already trims by stored `{xmin, xmax}` on the
server. It does not yet have Unselect-as-interval, live outline
ownership, or zoom restore after trim.

