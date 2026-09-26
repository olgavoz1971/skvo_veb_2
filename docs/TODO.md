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
| 7 | Photcal coherence, domain-switch policy, and shared calibration UI | Open (Phase 1 done; Phase 2 next) |
| 9 | Extract ``volightcurve`` as a sibling editable Python package | Open (Phase 5 done; Phase 6 optional) |
| 10 | Extract lightcurve discovery toolkit as a sibling package | Open (editable install done; app still on nested providers) |
| 11 | Rough extrema drawer: move intervals (and related state) to client ``dcc.Store`` | Open |
| 12 | volightcurve: photometric calibration validation for domain conversion | Open |
| 13 | volightcurve: §8 product validation on ingest (structure + cells) | Open |
| 14 | volightcurve: preserve VO column names; UCD-aware export; label/sector ingest | Open |

## Done

| ID | Title | Status |
|----|-------|--------|
| 8 | volightcurve owns lightcurve file I/O; preserve metadata on all formats | Done (Phases 0–3) |
| 6 | Professional busy feedback for long lightcurve uploads (GP + Processor) | Done (unified icons + ? detail) |
| 5 | Spinners for background-callback long operations | Done (Phases 0–1; Phase 2 waived) |
| 3 | Unify server session LC (common base, then page-by-page) | Done (phases 0–4; ASAS-SN + cutout out of scope) |
| 4 | Unified dismissable / timed status alerts (all LC pages) | Done (Phases 0–3; ASAS-SN out of scope) |

---

## Ticket 1 — Discovery shared fetch cache (per provider)

**Page:** Lightcurve Discovery (`/lc_discovery`).

**Related:** [caching_architecture.md](caching_architecture.md),
[mission_lightcurve_providers.md](discovery/mission_lightcurve_providers.md) (§4.4
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
- `docs/caching_architecture.md` §1.A now documents `lc_session_cache`
  (namespaced keys; Discovery, processor, ASAS-SN, and TESS). Ticket 3
  is the session-cache resume work; this ticket is the **archive fetch**
  layer only.

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

---

## Ticket 3 — Unify server session LC (common base, then page-by-page)

**Audience:** agents. Do not start from chat history; this ticket is the
agreed plan. Think first; implement only when the developer asks, and
**one phase at a time**. Goal 1 (haystack on the server) is the reason
for the cache. Goal 2 here means only the **TESS-archive in-tab resume**
(refresh / leave the page / come back in the **same** tab). It does
**not** mean recover after closing the tab or sharing work across tabs.

**UX reference:** TESS curve (`/tess_lc`),
`skvo_veb/pages/lightcurve_tess_srv.py`. That page already feels right
when returning to the tool. Other pages that already keep `CurveDash` on
disk must be promoted to **that resume behaviour**, not the other way
around.

**Disk reference:** `skvo_veb/utils/lc_session_cache.py` (namespaced
keys, one helper). TESS archive uses this module with namespace
`tess_lc_srv` (Phase 1). Discovery resume is Phase 2.

**Related:** [caching_architecture.md](caching_architecture.md) (§1.A is
stale: session cache is not TESS-only),
[lightcurve_data_flow.md](lightcurve_data_flow.md), ticket 1 (shared
**archive** fetch — different layer), ticket 2 (TESS interval cleaning —
do not block this ticket).

---

### What “TESS version” means (the contract)

Dash Pages remount layout when you leave a route. The working curve
survives on disk; the figure and tabs do not, unless the page **rehydrates
from the handle**.

TESS archive does this:

1. Browser stores (all `SESSION_STORE`): `user_tab_id`, plot revision
   UUID, search result, selection bounds, metadata, periodogram result.
2. On remount, Stores hydrate from `sessionStorage`.
3. `restore_lc_srv_tabs`: if `user_tab_id` is set **and** the disk
   entry exists → enable the graph tab and switch to it.
4. `restore_lc_srv_search_table`: rebuild the sector grid from the
   search Store.
5. `plot_tess_curve`: `prevent_initial_call='initial_duplicate'` so the
   persisted revision UUID triggers a rebuild from **server** cache.

That is the behaviour to copy. The photometry still never lives in
`dcc.Store`.

**Gaps today (do not re-derive):**

| Page | Disk | Resume |
|------|------|--------|
| `/tess_lc` | `lc_session_cache` `tess_lc_srv_*` | Reference: restore tabs + table + replot |
| Discovery | `lc_session_cache` `lc_discovery_*` | Phase 2 + chrome promote: restore tabs from cache hit; restore catalogue chrome from session stores; restore P / epoch / mag / fold from cached `CurveDash`; plot from revision. Cache hit admits the Light curve tab without fresh AgGrid `rowData`. |
| Processor | `lc_session_cache` `lc_processor_*` | Phase 3 + chrome promote: UUID + revision on `SESSION_STORE`; restore P / epoch / domain from cached `CurveDash`; `store-lc-processor-ui` holds tool chrome (method, crop, stems, filename chip, time axis, error bars). Plot + action gating take revision and `user_tab_id` as Inputs. Marks / zoom / knots / plot-2 window stay memory-only. |
| Extrema modeller `/gp` | `lc_session_cache` `gp_for_oc_*` (VOLightCurve transport JSON, not CurveDash) | Phase 4 + chrome promote: UUID + revision on `SESSION_STORE`; restore P / Epoch from transport `meta` (write-through); intervals + LC/intervals filenames + Mag/Flux view in session stores. Prep plot + runners read server blob. Marks / trend / working-window stay memory-only. |
| `/tess` cutout | Working LC in `dcc.Store` | Out of scope for this ticket. |
| Legacy ASAS-SN | `lc_session_cache` `asassn_*` | Out of scope for this ticket (Discovery is the long-term ASAS-SN UI). |

---

### Proposed approach

Two layers. Implement the **base** first. Switch pages **one by one**.
Do not migrate five pages in one change.

```text
 Browser (per tab, SESSION_STORE)
   user_tab_id + revision token + page UI (search, switches, …)
           │
           ▼
 Pages (thin): restore-if-cached, mutate, bump revision, plot
           │
           ▼
 lc_session_cache (only USER_CACHE_DIR accessor)
   {namespace}_{user_tab_id}_data      → CurveDash JSON
   {namespace}_{user_tab_id}_{blob}    → optional extras (processor)
```

#### Layer A — common disk base (no Dash)

Canonical module: `lc_session_cache.py`.

- **One** `diskcache.Cache` on `USER_CACHE_DIR`. TESS must stop
  constructing a second instance.
- Keep **namespace** in the key. Isolation between pages is required.
- Keep 24 h sliding expiry on read/write.
- Public API stays small: `generate_user_tab_id`, `has_cached_lc`,
  `read_serialized_lc`, `write_serialized_lc`, plus existing
  `*_page_blob` for processor extras.
- **No Dash imports** in this module. Restore callbacks stay in pages.
- Fail fast if `USER_CACHE_DIR` is missing or the entry expired
  (existing `PipeException` text is fine).

Do **not** invent a generic “session controller” that owns figures.
Pages still own callbacks.

#### Layer B — common resume checklist (pages, TESS as template)

Every Goal 1 page, after the disk switch, must:

1. Persist **both** `user_tab_id` and the **plot revision** with
   `SESSION_STORE`.
2. Persist the other Stores needed to rebuild the chrome (catalogue /
   search table, not the LC).
3. On layout remount: if `has_cached_lc(namespace, user_tab_id)`,
   restore the working view (enable plot tab / switch to it / equivalent)
   **from the cache**, not from “did the search grid already render”.
4. Plot callback must run from the persisted revision (`initial_duplicate`
   or an equivalent restore Input) and read the server blob only.
5. New Retrieve / upload still generates a UUID only when missing, then
   overwrites the namespaced blob.

Page-specific tools (Discovery client marks, processor blobs, TESS
periodogram) stay in that page. Only the **handle + disk + restore
ritual** is standardised.

---

### Phases (do in this order)

**Phase 0 — Base (no user-facing change).**  
Tests and docs for `lc_session_cache` as the sole API. Confirm
processor blobs stay. Update [caching_architecture.md](caching_architecture.md)
§1.A: Discovery, processor, ASAS-SN already use it; TESS is the fork.
No page migration yet.

**Phase 1 — Switch `/tess_lc` onto the base.**  
Replace page-local `user_cache` / `extract_data_from_user_cache` /
`write_user_data_to_cache` / `generate_user_tab_id` with
`lc_session_cache` and namespace `tess_lc_srv`. **Must not regress**
restore tabs, restore search table, or replot. (Sandbox: no dual-read
of old unprefixed keys.) This page is the UX gold standard; treat a
resume regression as a failed phase.

**Phase 2 — Discovery resume.**  
Keep `lc_session_cache`. Add TESS-like restore: cache hit → enable
Light curve tab, select it, plot from revision. Do not require a
fresh catalogue `rowData` to admit that a working curve exists.
Do not put the LC in a Store. Ticket 1 (shared fetch) stays separate.

**Phase 3 — Processor resume.**  
Put the revision Store on `SESSION_STORE`. Restore the working plots
from cache + blobs after in-tab navigation. Do not move mark/zoom
Stores to session unless resume actually needs them (marks are UI;
losing orange after a route change is acceptable unless the developer
says otherwise).

**Phase 4 — Extrema modeller (`/gp`) session LC.**  
Move the working photometry out of `store-lc-data` onto
`lc_session_cache` (namespace `gp_for_oc`). Persist `user_tab_id` +
revision with `SESSION_STORE`; plot and runners read the server blob.
Keep intervals, marks, trend line, and working-window Stores memory-only
unless resume explicitly needs them. The cached payload stays the existing
VOLightCurve **transport JSON** (not CurveDash) so GP helpers need no
format rewrite. TESS cutout and legacy ASAS-SN are **out of scope**.

**Phase 5 — TESS cutouts page (`/tess`)**  
---

### Locked constraints

1. Photometry stays on the server. `dcc.Store` holds ids, revision,
   search/catalogue UI, and small marks/zoom only.
2. Do not share one `user_tab_id` across pages. Namespace (or a
   per-page UUID Store) keeps Discovery from clobbering TESS.
3. Do not implement close-tab recovery (`localStorage`, login) in
   this ticket.
4. Do not merge ticket 1 (archive fetch cache) into session keys.
5. Do not rewrite CurveDash.
6. British English for any new user-facing strings.
7. One phase per implementation request. After each page switch:
   retrieve/upload, leave the app section, return in the same tab,
   working curve and plot still there without fetching again.

### Out of scope

- Ticket 1 shared Discovery fetch cache.
- Ticket 2 TESS interval mark/trim/zoom (can land before or after
  phase 1; do not couple).
- Legacy ASAS-SN resume (Discovery supersedes `/asassn`).
- TESS cutout (`/tess`) working-LC move to session cache.
- GP/MAVKA/parabola run-control diskcaches.
- Changing the 24 h TTL unless the developer asks.
- Converting GP transport JSON to CurveDash inside the session cache.

### Agent checklist

1. Phase 0: tests for namespace keys, sliding expire, missing env /
   missing key fail visibly.
2. Phase 1: TESS uses only `lc_session_cache`; manual resume matches
   today’s `/tess_lc`.
3. Phases 2–3: each page has an explicit restore path equivalent to
   `restore_lc_srv_tabs` + replot from disk.
4. Phase 4: `/gp` no longer puts photometry in `dcc.Store`; remount
   replots from `gp_for_oc` cache + revision.
5. `caching_architecture.md` matches reality.
6. No second `diskcache.Cache(USER_CACHE_DIR)` in a page module.

### Status

**Phase 1 done (sandbox; no legacy-key dual-write).** `/tess_lc` uses
`lc_session_cache` with namespace `tess_lc_srv` only. Manual resume
check passed.

**Phase 2 done.** Discovery restores the Light curve tab from a session
cache hit (not from catalogue `rowData`) and rehydrates Search chrome
from `store_lc_discovery_catalog`. Manual check: retrieve, leave the
page, return in the same tab, plot still there without fetching again.

**Phase 2 chrome promote.** Discovery also restores period, epoch,
magnitude switch, and fold switch from the cached `CurveDash`
(`restore_lc_discovery_curve_controls`). No parallel ephemeris store;
edits already write through on fold / mag.

**Phase 3 done.** Processor puts `store-lc-processor-lc-revision` on
`SESSION_STORE` and plots / gates from both revision and `user_tab_id`
as Inputs so remount rebuilds plot 1 (+ smooth / extrema blobs) and
plot 2 (detrend blob) from disk. Marks, zoom, knots, and plot-2 window
remain memory-only.

**Phase 3 chrome promote.** Processor restores domain / period / epoch
from the cached `CurveDash` and tool chrome from
`store-lc-processor-ui` (method, crop, stems, filename chip, time axis,
error bars). Sidebar P / Epoch write through to the cached curve.
No `CurveDash` class changes.

**Phase 4 done.** Extrema modeller (`/gp`) stores working photometry in
`lc_session_cache` (`gp_for_oc`) as transport JSON; `user_tab_id` + revision
use `SESSION_STORE`. Legacy ASAS-SN and TESS cutout remain out of scope.

**Phase 4 chrome promote.** `/gp` restores P / Epoch from transport `meta`
(sidebar edits write through), Mag/Flux from `store-gp-view-mode`, intervals
from `store-intervals-data`, and both upload filename chips from session
stores. Still transport JSON on disk — no CurveDash migration. Marks,
trend line, and working window stay memory-only.

---

## Ticket 4 — Unified dismissable / timed status alerts (all LC pages)

**Audience:** agents. Think first; implement only when asked, **one phase
at a time**. Reference behaviour is Lightcurve Processor — do not invent a
second alert design.

**Reference:** `skvo_veb/components/message.py` (`status_alert`,
`STATUS_ALERT_DURATION_MS`), Processor overlay `lc-processor-plot-alert`,
[lightcurve_processor.md](lightcurve_processor.md) (status text rules).

**Related outdated helpers:** same module’s legacy `warning_alert` /
`info_alert` (no dismiss, no duration). Migrated pages use `status_alert`
instead; legacy helpers may remain for unmigrated callers outside this ticket.

### Goal

User-facing status and error text across LC pages should match Processor:

| Severity | Dismiss (×) | Auto-clear |
|----------|-------------|------------|
| `info` / `success` | Yes | Yes (`duration`, ~4 s) |
| `warning` / `danger` | Yes | No — stay until dismiss, a newer message, or a deliberate clear (e.g. new upload) |

A new message replaces the previous one in the same slot. Plot redraw,
zoom, and accordion open/close must **not** clear alerts by accident.

### Current state (do not re-derive)

| Page | What exists today | Gap |
|------|-------------------|-----|
| **Processor** `/lc_processor` | One plot-column overlay; uses shared `status_alert` | Phase 0 done |
| **GP** `/gp` | Zone `*-feedback` slots use shared `status_alert` (prep, trend, export, interval add, O-C, run errors) | Phase 1 done |
| **Discovery** `/lc_discovery` | Search / fetch / plot alerts use shared `status_alert`; children-only (no show/hide style) | Phase 2 done |
| **TESS** `/tess_lc` | Tools / search / download / plot alerts use shared `status_alert`; children-only | Phase 3 done |

`components/message.py` is the shared factory. Legacy `warning_alert` /
`info_alert` are not part of this ticket’s remaining work.

### Proposed approach

**Do not** invent per-page alert widgets. **Do** promote Processor’s rules
into one shared builder, then migrate callers.

```text
 skvo_veb/components/message.py   (or status_alert.py)
   status_alert(text, color) → dbc.Alert
     dismissable=True always
     duration only for info/success
           │
           ▼
 Pages: return that component into a fixed feedback slot
   Prefer one plot-column overlay (Processor model) where the layout allows
   GP may keep a few zone slots (prep / O-C) but each slot uses the same builder
```

#### Phase 0 — Shared helper

- Extend `components/message.py` (preferred: one module) with
  `status_alert(message, color)` matching Processor semantics
  (`STATUS_ALERT_DURATION_MS`, timed colours = info/success).
- Keep `warning_alert` / `info_alert` as thin wrappers **or** deprecate them
  after callers move (no silent behaviour change mid-migration).
- Processor may switch `_status_alert` to call the shared helper (behaviour
  unchanged).

#### Phase 1 — Extrema modeller `/gp`

- Replace raw `dbc.Alert(...)` feedback with `status_alert`.
- Decide slots: keep existing zone feedback ids for now; do not merge every
  GP message into one overlay in this phase unless trivial.
- Clear feedback on successful upload / successful primary action where
  Processor would; leave plot redraw alone.

#### Phase 2 — Discovery

- Route search / fetch / plot alerts through `status_alert`.
- Prefer setting `children` only; drop the old show/hide `style` dance where
  `None`/empty children is enough (or a single visible overlay like Processor).

#### Phase 3 — TESS archive `/tess_lc`

- Same as Discovery for tools / search / download / plot alert divs.

### Out of scope

- Legacy ASAS-SN (`/asassn`) — not migrated under this ticket.
- Redesigning accordion help / About modals.
- Toast libraries or non-Bootstrap notification stacks.
- Changing scientific fail-fast text (still show the real error; only the
  chrome around it changes).

### Acceptance

1. Info/success alerts dismiss with × and auto-clear after the shared duration.
2. Warning/danger dismiss with × and do not auto-clear.
3. Processor behaviour unchanged (or only refactored onto the shared helper).
4. GP, Discovery, and TESS no longer depend on undismissable `message.warning_alert`
   for new/edited call sites in the migrated phase.
5. Manual check: trigger an info and a warning on each migrated page; confirm
  timer vs sticky and that a newer message replaces the old one.

### Status

**Done.** Phases 0–3 complete: shared `status_alert` in
`skvo_veb/components/message.py`; Processor, Extrema modeller (`/gp`),
Discovery (`/lc_discovery`), and TESS (`/tess_lc`) use it with children-only
alert slots. Legacy ASAS-SN left out of scope.

---

## Ticket 5 — Spinners for background-callback long operations

**Audience:** agents. Think first; implement only when asked, **one phase
at a time**. **Every phase must start with a discussion** of where and how
spinners attach on that page (slots, Outputs inside the wrap, coexistence
with existing progress UI) before any code. Reference behaviour is TESS —
do not invent a second loading design.

**Reference:** `skvo_veb/pages/lightcurve_tess_srv.py` and
`skvo_veb/pages/tess_cutout.py` — `dbc.Spinner` wrapping stable layout
slots (tools alert, search results + alert, download result + alert).
Spinners appear when a **background** callback updates an Output inside
the wrap; layout does not jump; `running=` still disables action buttons
and enables Cancel.

**Related:** Discovery search status strip
(`lc_discovery_search_status`, [lc_discovery_messages.md](lc_discovery_messages.md));
GP/MAVKA/Parabola live `progress=` / `set_progress` review cards on `/gp`.

### Goal

Long operations implemented as **background callbacks** should show a
classical spinner in a reserved slot, matching TESS:

- No full-page overlay that covers the whole UI.
- No widgets jumping when the spinner appears or clears.
- Existing progress text / live cards stay; spinner complements them.

First approach scope: **background callbacks only**. Ordinary
(non-background) callbacks are out of scope until a later ticket.

### Current state (do not re-derive)

| Page | Background jobs | Spinner today | Other progress UI |
|------|-----------------|---------------|-------------------|
| **TESS** `/tess_lc` | Search, retrieve, purge/re-retrieve, periodogram | Shared `wrap_with_spinner` (Phase 0) | Button disable + Cancel via `running=` |
| **TESS cutout** `/tess_cutout` | Search, retrieve sector | Shared `wrap_with_spinner` (Phase 0) | Same |
| **Discovery** `/lc_discovery` | Catalogue Submit; Retrieve / Re-retrieve | Compact spinner centred in header row (`catalog_spinner_target`); tools log has no spinner; table untouched | Submit: step text via `progress=` → `lc_discovery_search_status` |
| **GP** `/gp` | GP / MAVKA / Parabola batch runs | No | Live review cards via `progress=` / `set_progress` (must keep) |
| **Processor** `/lc_processor` | None | — | Out of scope for this ticket |

### Proposed approach

**Do not** invent per-page spinner widgets or `dcc.Loading` page shells.
**Do** promote TESS’s `dbc.Spinner` wrap into one shared factory, then
attach it page by page after each phase’s discussion.

```text
 skvo_veb/components/loading.py
   wrap_with_spinner(children, …) → dbc.Spinner
     SPINNER_STYLE_COMPACT / SPINNER_STYLE_CENTERED match TESS
           │
           ▼
 Pages: wrap existing reserved slots only
   Outputs that should show “busy” must live under that Spinner
```

**Trigger rule:** a background callback shows the spinner only if it
updates an Output that is a descendant of the Spinner’s `children`.

**Layout rule:** wrap slots that already reserve space (alert strip,
results panel, status row). Never insert a spinner row that appears and
disappears.

### Phases

#### Phase 0 — Shared helper (+ TESS / cutout refactor)

- **Start with discussion:** factory name/module, default props, whether
  Phase 0 also refactors `/tess_lc` and `/tess_cutout` onto the helper or
  leaves them as the visual reference only.
- Add a thin shared wrapper around `dbc.Spinner` with TESS-matching
  defaults.
- Document the trigger and layout rules (above) for later phases.
- **Done:** `skvo_veb/components/loading.py` (`wrap_with_spinner`,
  `SPINNER_STYLE_COMPACT`, `SPINNER_STYLE_CENTERED`); `/tess_lc` and
  `/tess_cutout` use it (no raw `dbc.Spinner`). Phase 3 optional align
  step is therefore unnecessary.

#### Phase 1 — Discovery `/lc_discovery`

- **Start with discussion:** which slots to wrap (tools column, status
  strip, Retrieve zone, or TESS-style split); how spinner coexists with
  `lc_discovery_search_status` progress text; which Submit/Fetch Outputs
  must sit inside the wrap.
- Add spinner(s) for catalogue Submit and Retrieve / Re-retrieve.
- **Must preserve** the search status step text (`progress=` channel).
- **Done (Proposal A → header centre):** Compact spinner reserved in the
  **centre** of the catalogue header row (`lc_discovery_catalog_spinner_target`,
  `size='sm'` + `SPINNER_STYLE_COMPACT`). Shared by Submit and Retrieve.
  Tools-side status text has **no** spinner. Table / Aladin are not wrapped.
  Search + fetch Bootstrap alerts share one under-table slot
  (`lc_discovery_catalog_alert`); truncation, tools status, and plot alert
  unchanged.
#### Phase 2 — Extrema modeller `/gp`

- **Start with discussion:** where to wrap relative to live review /
  results UI; how spinner coexists with `set_progress` live cards; whether
  one wrap covers GP + MAVKA + Parabola or separate zones.
- **Waived:** GP / MAVKA / Parabola already expose live review cards via
  `progress=` / `set_progress`. No extra spinner — the cards are the
  busy feedback. Do not replace or duplicate them with `wrap_with_spinner`.

#### Phase 3 (optional) — Align TESS / cutout onto the shared helper

- **Cancelled:** completed as part of Phase 0.

### Out of scope

- Legacy ASAS-SN (`/asassn`).
- Lightcurve Processor (no background callbacks today).
- Spinners for non-background callbacks (see Ticket 6 for upload busy UX).
- Full-page or toast-style loading overlays.
- Replacing Discovery status text or GP live cards with a spinner alone.

### Acceptance

1. Background long ops on migrated pages (TESS, cutout, Discovery) show a
   TESS-like spinner without layout jump where a spinner was agreed.
2. Discovery search status progress text still updates during Submit.
3. GP live review progress remains the sole busy UI for batch runs (no
   spinner added).
4. Shared helper is the only new spinner factory; pages do not invent a
   second pattern.
5. Each phase’s implementation follows a prior discussion of that page’s
   slot and Output placement.

### Status

**Done.** Phases 0–1 implemented; Phase 2 waived (GP live cards sufficient);
Phase 3 cancelled into Phase 0. Upload busy feedback is **Ticket 6**, not
this ticket.

---

## Ticket 6 — Professional busy feedback for long lightcurve uploads

**Audience:** agents. Think first; implement only when asked. Apply the
**same** pattern on Extrema modeller (`/gp`) and Lightcurve Processor
(`/lc_processor`).

**Related:** Ticket 5 (background spinners — done; upload was out of scope);
GP `upload_lc` / `_gp_upload_status`; Processor `upload_lightcurve` /
`_upload_status`; `skvo_veb/components/loading.py` (`wrap_with_spinner`).

### Problem

Large lightcurve files can take a long time after drop/select. Today both
pages use an ordinary (non-background) upload callback: the UI looks idle
until parse + session-cache write finish, then the chip flips to ok/error.

### Goal

Immediate, professional busy feedback on upload — fixed slot, no layout
jump, clear success/failure — matching the spirit of Ticket 5 without
inventing a full-page overlay.

### Options (pick one before coding)

| Option | Mechanism | Pros | Cons |
|--------|-----------|------|------|
| **A** | Promote upload to `background=True`; reserved Output under `wrap_with_spinner` (chip/status slot) | Same family as Discovery Retrieve; Cancel possible | More plumbing; need careful Outputs / `running=` |
| **B** | Keep sync upload; clientside (or instant chip) “Reading / ingesting `filename`…” as soon as `contents` arrive; server clears to ok/error | Cheap; works today; same recipe both pages | No true Cancel; no byte progress; sync still blocks the worker |

True byte-level progress bars are a poor fit: `dcc.Upload` already holds
the file in the browser before the server callback runs; slowness is
mostly decode / parse / cache write.

### Decision

**Option B** chosen. Option A deferred unless Cancel / worker starvation
becomes a real problem.

### Shared building blocks

- `skvo_veb/components/upload_status.py` — chip (always with icon),
  ``?`` failure detail + collapse, busy clientside registration, shared
  MATCH callbacks for show/toggle
- `skvo_veb/assets/upload_status.css` — ``skvo-upload-*`` layout
- `skvo_veb/assets/upload_status_clientside.js` — ``skvoUpload.buildBusyChip``

**One contract:** hourglass busy chip → ok/error icon chip; failures use a
titled detail behind ``?`` (collapse starts closed). Pages pass upload ids
and detail indexes only.

### Implementation plan

1. **Done:** Shared pattern (icons + hourglass + ``?``).
2. **Done (GP):** LC, intervals, and O-C timings uploads.
3. **Done (Processor):** Same pattern on ``lc-processor-upload-lc``.
4. Sync server upload callbacks still write ok / error (and clear detail).
5. No `wrap_with_spinner`, no background upload, no full-page overlay.

### Out of scope

- Fitting / batch runners on `/gp` (Ticket 5 Phase 2 waived).
- Full-page overlays, toasts, or a second spinner design language.
- ASAS-SN.
- Option A (background upload).

### Status

**Done.** Unified upload status pattern on GP and Processor (Option B busy +
GP-style icons / ``?`` failure detail).

---

## Ticket 7 — Photcal coherence, domain-switch policy, and shared calibration UI

**Audience:** agents. Think first; implement only when asked, **one phase
at a time**. Every phase starts with a short discussion of policy and
placement. Scientific integrity rules apply: **no silent unit promotions**,
no invented zeropoints unless the developer explicitly chooses an
**explicit** fallback policy in Phase 1.

**Pages:** Lightcurve Processor (`/lc_processor`) first; Extrema modeller
(`/gp`) for the same domain-switch / photcal rules; Discovery
(`/lc_discovery`) optional for the shared calibration editor.

**Related:** `skvo_veb/utils/lc_bridge.py` (`volc_to_curvedash`,
`photcal_from_metadata`, `apply_phot_domain_view`);
sibling ``volightcurve.lightcurve.PhotCal``;
`CurveDash.convert_to_mag` / `convert_to_flux`;
`docs/lightcurve_data_flow.md` (may be stale on fallbacks).

### Context (do not re-derive)

Processor / Discovery CurveDash path:

```text
file or archive → VOLightCurve → volc_to_curvedash
  → metadata['photcal'] + native domain on CurveDash
  → session cache
domain switch → apply_phot_domain_view → PhotCal mag↔flux
```

Honest science: few providers ship a coherent photcal GROUP. Ingest
copies what exists; it does **not** convert. Mag↔flux fails when ZP
pair or units are incomplete / incoherent. Soft demotion of invalid ZP
units to dimensionless (in `PhotCal`) conflicts with the no-silent-fallback
rule and must be addressed under this ticket’s policy decision.

GP uses a related but not identical ingest path (`pack_uploaded_lightcurve`
/ transport JSON). Domain / photcal **policy** from Phase 1 still applies
there; do not invent a second calibration object.

### Goal

1. Surface incomplete or incoherent photcal clearly (especially at domain
   switch), with an explicit product decision on mismatch handling.
2. Provide a **shareable** calibration edit UI/workflow (not page-hardcoded
   markup) that writes into `metadata['photcal']` via the existing
   dataflow.
3. Leave room for non-classical magnitude kinds later (e.g. luptitudes).

### Phases

#### Phase 1 — Coherence check + domain-switch policy (Processor + GP)

**Decision (locked):**

| Case | Policy |
|------|--------|
| Unit mismatch / invalid ``zp_flux_unit`` | **Warn** via ``status_alert``, **proceed**; flux column unit **wins**; write corrected ``zp_flux_unit`` into photcal; message states this explicitly |
| Incomplete photcal (missing ZP pair) | Apply **application defaults** from ``volightcurve/photcal_defaults.py``; comprehensive warning; write into photcal |
| GP | **Same** shared path — **no** GP-local defaults |
| Invalid ZP unit string | Same as unit mismatch (flux column wins) |
| When to warn | Ingest **and** retrieve (and domain switch when corrections still apply) |
| Pages | Shared helper first; wire **Processor** (+ GP align, Discovery retrieve/mag); TESS later |

**Done:**

- ``volightcurve.photcal_defaults`` (sibling package)
- ``skvo_veb/utils/photcal_coherence.py`` (``reconcile_*``)
- ``PhotCal`` raises on invalid units (no silent demotion)
- ``apply_phot_domain_view`` inspects then converts (no invent); incomplete → raise
- Processor upload + domain switch alerts
- GP upload reconcile + ``resolve_gp_photcal`` uses shared policy
- Discovery: **no** photcal reconcile / **no** photcal warnings on retrieve;
  mag↔flux uses stored provider photcal; failure → error alert below
  Delete selected; unitless ``---``→``None`` at VO→CurveDash ingest only

#### Phase 2 — Shareable calibration editor (Processor, optional Discovery)

- **Start with discussion:** panel placement, which photcal fields are
  editable, how Apply writes `metadata['photcal']` and re-validates.
- Build **shared** layout + callbacks/helpers (component or utils module),
  not a one-off block inside `lightcurve_processor.py` alone.
- Processor adopts first; Discovery optionally mounts the same editor on
  a fetched CurveDash.
- Edit → validate (Phase 1 helper) → `write_serialized_lc` (or GP
  equivalent write-through). Success updates or clears the warning.

#### Phase 3 (future) — Other magnitude kinds

- Think through non-classical systems (e.g. luptitudes / asinh mags):
  metadata representation, whether `PhotCal` / domain toggle still apply,
  and UI labelling.
- **No implementation** until Phases 1–2 are settled and the developer
  asks to open this phase.

### Out of scope

- Silent “assume Jy / AB / dimensionless” fixes without an explicit
  Phase 1 decision.
- Parallel photcal stores beside `CurveDash.metadata['photcal']`.
- Converting to a “standard” domain at ingest to hide bad units.
- ASAS-SN unless later named in.

### Acceptance

1. Domain switch on Processor and GP uses one photcal policy; user always
   sees why conversion is blocked or which **explicit** fallback was
   applied.
2. No silent ZP-unit promotion remains that contradicts that policy.
3. Calibration editing (when Phase 2 lands) is shareable code used by
   Processor (and Discovery if opted in), writing through the existing
   CurveDash photcal dataflow.
4. Phase 3 stays design-only until requested.

### Status

**Open.** Phase 1: Processor/GP still use shared reconcile helpers. Discovery
does **not** rewrite or warn on provider photcal (retrieve/mag switch). Phase 2
next when asked. TESS retrieve/upload still to adopt the helper where appropriate.

### Hazard — invent helpers (track)

**Policy:** invent only on GP upload (`reconcile_photcal_dict` + `status_alert`)
and Processor form fill/Apply. Domain switch uses `inspect_*` only —
`apply_phot_domain_view` no longer calls `reconcile_curve_photcal`. Cutout
has no magnitude switch (uncalibrated flux only).

| Entry | Path | Warnings shown? | Notes |
| --- | --- | --- | --- |
| `reconcile_curve_photcal` | unused in production | n/a | Reserved; do not wire into domain switch |
| `reconcile_photcal_dict` | GP upload (`gp_for_oc`) | **yes** | Intended invent path |
| `reconcile_photcal_dict` | `gp.flux.resolve_gp_photcal` | logger only | Second-chance after upload |
| `reconcile_photcal_dict` | Processor form adopt | **yes** (Apply) | Via `photcal_dict_from_form_values` |
| `apply_phot_domain_view` | TESS archive / ASAS-SN / … | raises | Inspect + refuse; no invent. Cutout has no mag switch |

**Unitless encoding (shared dataflow):** Internal storage uses ``None`` for
dimensionless units (CurveDash / photcal / PhotCal). File export keeps a present
``unit`` attribute with the empty string (`VO_DIMENSIONLESS_WIRE` in
`volightcurve/vo_unit_codec.py` — change only there). Astropy’s ``unit="---"``
sentinel is mapped to ``None`` on ingest and rewritten to ``unit=""`` on write.
UI labels use ``to_display`` (never bare ``None``).

---

## Ticket 8 — volightcurve owns lightcurve file I/O; preserve metadata on all formats

**Audience:** agents. **Think first; implement only when asked.** Every
phase and every non-trivial step **must be discussed and agreed before
coding** — no drive-by moves of parsers/writers.

**Related:** [lightcurve_data_flow.md](lightcurve_data_flow.md),
[dat_lightcurve_comments.md](dat_lightcurve_comments.md),
[volightcurve_io_contract.md](volightcurve_io_contract.md) (Phase 0),
sibling ``volightcurve`` package
(``/home/voz/projects/UPJS/volightcurve`` — ``VOLightCurve``,
``write_vo_lightcurve``, ``apply_non_votable_heuristics``, ``io_keywords``),
`skvo_veb/utils/lc_bridge.py`
(`ingest_volightcurve_file`, `export_curvedash`, `_read_dat_upload_table`,
`_build_ecsv_metadata`), Processor export
(`pages/lightcurve_processor.py` → `export_curvedash`).

### Goal

1. **First and last file steps live in ``volightcurve``** — upload parse and
   download serialise for lightcurve products are an independent, Plotly-free
   toolkit usable outside this app.
2. **Preserve metadata on every format the app offers for download/upload**
   (VOTable, ECSV, CSV, commented-header / ``.dat``, …) — photcal / zero
   points, time origin (JD0 / TIMESYS), period, epoch, filter/band, and other
   fields already carried on ``CurveDash`` / ``VOLightCurve`` after ingest.
   **Do not** paper over gaps with UX “metadata not included” warnings;
   **fix the codecs** so round-trip keeps the science metadata.
3. ``lc_bridge`` stays the thin ``VOLightCurve`` ↔ ``CurveDash`` mapper;
   pages never invent format-specific metadata writers.

### Context (do not re-derive)

Today ingest can be rich (VOTable PhotDM; ``.dat`` ``# MAG0=`` / ``JD0=`` /
… via heuristics) while non-VOTable export in ``export_curvedash`` is lossy:
ECSV keeps only a thin header (ZPs excluded by design today); CSV /
``ascii.commented_header`` clears ``tab.meta`` entirely. ``.dat`` **read**
understands comment vocabulary; **write** does not emit it. Part of ``.dat``
parsing still sits in ``lc_bridge`` (``_read_dat_upload_table``), not next to
volightcurve heuristics.

### Locked constraints

1. **Discuss before every implementation step** (phase plan, API shape,
   which keys map to which format headers/comments, move order). No silent
   refactors.
2. **No Dash / Plotly / CurveDash imports inside ``volightcurve``.**
3. **Metadata preservation is mandatory** for all user-facing LC download
   formats — not optional, not “warn and drop”.
4. Scientific integrity: no invented photcal or time origins on write;
   write what the working product actually holds.
5. British English in any new user-facing strings; technical format tokens
   stay as-is.

### Phases (start here; refine in discussion)

#### Phase 0 — Agree inventory and codec contract — **Done**

Documented in [volightcurve_io_contract.md](volightcurve_io_contract.md) and
[dat_lightcurve_comments.md](dat_lightcurve_comments.md); vocabulary constants in
`volightcurve/io_keywords.py`.

**Locked decisions:**

1. First-class non-VO keys only for photometric / time calibration; other
   comments → description / re-emitted ``#`` lines.
2. Tier B (timescale, COOSYS, facility, …) omitted on non-VOTable formats.
3. ``EPOCH`` always shares the same ``JD0`` / timeorigin as the time column.
4. CSV and ``ascii.commented_header`` use the same ``# KEY = value`` vocabulary
   as ``.dat`` (one codec).
5. Full PhotCal on ``.dat``/CSV via extended keywords (``ZP_*``, ``MAG_SYS``,
   filter extras); ``MAG0`` / ``BAND`` remain read aliases.
6. ECSV uses **flat** ``meta`` keys with that same vocabulary (no nested
   ``photcal:`` schema).
7. Public API: ``read_lightcurve`` / ``write_lightcurve``; no CurveDash names
   inside ``volightcurve``.
8. **Photometry domain (non-VO):** no ``DOMAIN=`` keyword. Write explicit
   ``mag``/``mag_err`` or ``flux``/``flux_err``. Ambiguous columns default to
   **magnitude**. (Contract §4b; implementation when asked — not Phase 3
   ``CurveDash.download``.)

#### Phase 1 — Move first and last I/O into volightcurve — **Done**

- ``read_lightcurve`` / ``write_lightcurve`` / ``assemble_volightcurve`` in
  ``volightcurve/io.py``; strict ``.dat`` reader in ``io_dat.py``.
- ``ingest_volightcurve_file`` / tabular ``export_curvedash`` are thin wrappers.
- Dash-free round-trip tests in ``tests/volightcurve/test_io_roundtrip.py``.

#### Phase 2 — Wire app pages / docs / smoke — **Done**

Scoped as **(ii)** docs + audit + smoke fixes A/B/C (``CurveDash.download``
left for Phase 3).

**Page audit (all UI downloads/uploads already on bridge):**

| Surface | Upload | Download |
|---------|--------|----------|
| Processor | `ingest_lightcurve_file` | `export_curvedash` |
| Discovery | (session / providers) | `export_curvedash` |
| GP | `ingest_volightcurve_file` (gp ingest) | `export_curvedash` |
| TESS srv | `ingest_lightcurve_file` | `export_curvedash` (+ profile) |
| Cutout / ASAS-SN | — | `export_curvedash` (+ profile) |

No page call site bypasses ``export_curvedash`` / ``ingest_*`` for LC files.

**Smoke / fixes:**

- **A:** Processor-style ingest→export→re-ingest tests (calibration + narrative).
- **B:** Narrative ``#`` comments via ``metadata['file_comments']`` round-trip.
- **C:** ECSV writes flat calibration keys only; GP/export tests accept ``PERIOD``.

**Docs:** ``lightcurve_data_flow.md`` diagrams updated for
``read_lightcurve`` / ``write_lightcurve``.

#### Phase 2b — Explicit mag/flux column names on non-VO I/O — **Done**

- Write CSV / ``.dat`` / ECSV with ``mag``/``mag_err`` or ``flux``/``flux_err``
  (never ambiguous ``phot``/``flux_error``).
- No ``DOMAIN=`` keyword.
- Ambiguous ingest (``phot``, no unit/UCD) defaults to **magnitude**.
- Round-trip tests cover mag CSV and legacy ``phot`` → mag.

#### Phase 3 — Retire divergent paths — **Done**

- ``CurveDash.download`` implementation removed; method now always raises
  ``PipeException`` directing callers to ``lc_bridge.export_curvedash``.
- No page or test called the old path (audit confirmed).
- Docs updated; regression test ``test_curvedash_download_retired.py``.

### Status

**Done.** Phases 0–3 complete. One codec owns user-facing LC file I/O
(``volightcurve`` read/write via thin ``lc_bridge`` wrappers).

---

## Ticket 9 — Extract ``volightcurve`` as a sibling editable Python package

**Audience:** agents and developer. **Think first; implement only when
asked, one phase at a time.** Every phase starts with a short discussion
and stops for agreement before coding the next phase.

**Hard constraints:**

- Do **not** commit, push, create, or alter any GitHub repository unless the
  developer explicitly orders that step in a later phase.
- Keep day-to-day editing in Cursor: the library must remain a **local
  tree** opened beside ``skvo_veb_2``, installed into the app venv with
  ``pip install -e`` (editable). Do **not** rely on a plain (non-editable)
  install into ``site-packages`` as the normal workflow.
- PyPI “publish” is **out of scope** until the developer asks (optional
  later phase). “Publish” here only ever meant “make installable,” not
  “upload to PyPI.”

**Related (library + host):**

- Sibling package ``/home/voz/projects/UPJS/volightcurve`` (code, README,
  ``TESTING.md``, ``docs/io_contract.md``, ``examples/``)
- ``skvo_veb/utils/lc_bridge.py`` (only allowed consumer of the library
  from the app side for CurveDash ↔ VOLightCurve)
- ``skvo_veb/tests/volightcurve/`` (host integration tests; pure suite lives
  with the sibling package — see its ``TESTING.md``)
- Ticket 8 (I/O contract); [skvo_veb_2](https://github.com/olgavoz1971/skvo_veb_2)

### Goal

1. ``volightcurve`` becomes an independent **Python package** (directory of
   modules), importable as ``import volightcurve``.
2. ``skvo_veb_2`` depends on it via **editable local install** so library
   edits stay in the library tree and track in that package’s own git
   (when the developer creates it).
3. Nested ``skvo_veb/volightcurve/`` is removed from the app **only after**
   the app runs cleanly against the external package.
4. Pure regression tests and the basic example travel with the package;
   CurveDash / mission / bridge tests stay in ``skvo_veb_2``.
5. Mag↔flux conversion (``mag_to_flux`` / ``flux_to_mag``) is a **documented
   public API** of the package, not only an internal ``PhotCal`` detail used
   by column helpers.

### Target layout (end state)

```text
~/projects/UPJS/
  volightcurve/                 ← separate local project (own git when ready)
    pyproject.toml              ← package name: volightcurve
    README.md
    docs/io_contract.md
    examples/basic_workflow.py
    src/volightcurve/           ← or flat volightcurve/ (decide in Phase 0)
      __init__.py
      io.py
      lightcurve.py
      …
    tests/                      ← pure package tests only
  skvo_veb_2/                   ← existing app repo
    skvo_veb/
      pages/, utils/, …         ← no nested volightcurve/
    requirements.txt            ← editable path or VCS ref to volightcurve
```

App venv:

```text
pip install -e /home/voz/projects/UPJS/volightcurve
```

Imports:

```text
# before
from skvo_veb.volightcurve import read_lightcurve, …

# after
from volightcurve import read_lightcurve, …
```

### Non-goals (unless later asked)

- PyPI upload / versioned public release process.
- Agent-created GitHub remotes, pushes, or PRs.
- Rewriting scientific behaviour of ``PhotCal`` / I/O codecs (Ticket 8 stands).
- Moving ``lc_bridge`` or Dash pages into the library.

### Phases (stop and discuss after each)

#### Phase 0 — Agree packaging shape (discussion only)

Decide and record in this ticket:

1. **Tree layout:** ``src/volightcurve/`` vs top-level ``volightcurve/``.
2. **Local path** for the sibling project (default proposal:
   ``/home/voz/projects/UPJS/volightcurve``).
3. **Dependency line** for ``skvo_veb_2`` (editable path in
   ``requirements.txt`` or a small ``requirements-dev.txt`` / documented
   ``pip install -e`` step).
4. **Git ownership:** developer creates the new GitHub repo when ready;
   agents do not touch remotes unless explicitly ordered.
5. Confirm **editable install** as the only supported day-to-day link.

**Exit:** written decisions below (fill when agreed). No file moves yet.

**Decisions (Phase 0 — agreed):**

- **Layout:** ``src/volightcurve/`` (src-layout). Keeps project root clean
  (``tests/``, ``docs/``, ``examples/``, ``README`` beside ``src/``); avoids
  accidentally importing a half-copied tree from the repo root. Package
  import name remains ``volightcurve``.
- **Local path:** ``/home/voz/projects/UPJS/volightcurve`` (sibling of
  ``skvo_veb_2``; path currently free).
- **How skvo_veb_2 declares the dependency:**
  1. Documented one-liner for the app venv:
     ``pip install -e /home/voz/projects/UPJS/volightcurve``
  2. Plus a comment (or ``requirements-local.txt`` / documented note in
     app README) so the editable path is not forgotten — **not** a hard
     PyPI pin. Prefer **not** putting a machine-specific absolute path into
     committed ``requirements.txt`` if others clone the app; use a short
     ``docs`` / README install step, or a gitignored
     ``requirements-local.txt``. Exact file choice confirmed with developer
     if they prefer the path committed for a single-machine lab.
- **Day-to-day link:** editable install (``-e``) only.
- **When GitHub remote is created:** developer-owned, **Phase 6 only**;
  agents do not create remotes, push, or open PRs unless explicitly ordered.
- **Shadowing (Phase 2–3):** keep nested ``skvo_veb/volightcurve/`` until
  Phase 4; switch imports in Phase 3 only after ``import volightcurve``
  is proven against the sibling. Avoid leaving two live import paths.

**Phase 0 status:** **Done** (developer confirmed all rows).
#### Phase 1 — Scaffold the sibling package (local only) — **Done**

- Created ``/home/voz/projects/UPJS/volightcurve`` with ``pyproject.toml``
  (src-layout), README, ``TESTING.md``, ``docs/io_contract.md``,
  ``examples/basic_workflow.py``.
- Copied package sources into ``src/volightcurve/``; internal imports are
  ``volightcurve.*`` (no ``skvo_veb.volightcurve``).
- Pure tests under sibling ``tests/`` (I/O roundtrip, keywords, unit codec,
  write VO, PhotDM ingest, TIMESYS helpers + shared ``fixtures_votable``).
  Host/bridge/mission tests remain in ``skvo_veb_2``.
- Proven: ``pytest -q`` → 21 passed; ``examples/basic_workflow.py`` runs
  (``PYTHONPATH=src``, ``MPLBACKEND=Agg``).
- Nested ``skvo_veb/volightcurve/`` **still present** (unchanged).

**Exit:** sibling package works in isolation; nested copy still present.
**Phase 1 status:** **Done**.

#### Phase 2 — Editable install + dual-import safety check — **Done**

- Installed into ``skvo_veb_2`` venv:
  ``pip install -e /home/voz/projects/UPJS/volightcurve`` (editable;
  ``direct_url`` shows ``editable=True``).
- Verified dual imports (safe until Phase 3 retarget):
  - ``import volightcurve`` →
    ``…/UPJS/volightcurve/src/volightcurve/__init__.py``
  - ``import skvo_veb.volightcurve`` → nested app copy (still used by the
    app; **not** switched in this phase).
  - Distinct module objects / files (no accidental shadowing of the bare
    ``volightcurve`` name by the nested package).
- Documented install: app ``README.md`` Getting Started step 3;
  comment at end of ``requirements.txt``; committed
  ``requirements-local.txt.example``; gitignored ``requirements-local.txt``.
- **Import switch deferred to Phase 3** (Phase 0 preference).

**Exit:** editable install proven; developer can edit sibling in Cursor
and see changes in the app venv for ``import volightcurve``.
**Phase 2 status:** **Done**.

#### Phase 3 — Retarget ``skvo_veb_2`` imports — **Done**

- Replaced ``skvo_veb.volightcurve`` → ``volightcurve`` in app consumers:
  ``skvo_veb/utils/``, ``skvo_veb/lc_providers/``, ``skvo_veb/tests/``,
  ``scripts/``. Nested ``skvo_veb/volightcurve/`` left in place (unused
  dead copy until Phase 4).
- Verified ``lc_bridge`` loads ``VOLightCurve`` from sibling
  ``…/UPJS/volightcurve/src/volightcurve/lightcurve.py``.
- Pytest: ``skvo_veb/tests/volightcurve`` + tabular/GP/ASAS-SN/Discovery
  export/load suites → **91 passed**; provider tests also run.
- Smoke: ``from skvo_veb import app`` succeeds.

**Exit:** app uses only ``import volightcurve``; nested tree unused but
may still exist as dead code until Phase 4.
**Phase 3 status:** **Done**.

#### Phase 4 — Remove nested copy from ``skvo_veb_2`` — **Done**

- Deleted ``skvo_veb/volightcurve/`` from the app tree (no longer
  importable as ``skvo_veb.volightcurve``).
- Code/test consumers already use ``import volightcurve`` (Phase 3).
  Remaining nested-path strings are historical Ticket 9 narrative only.
- Docs retargeted: ``lightcurve_data_flow.md``, ``structure.md``,
  ``volightcurve_io_contract.md``, ``dat_lightcurve_comments.md``,
  GP / provider / Ticket 7–8 pointers.
- Pytest: sibling pure suite **21 passed**; host
  ``skvo_veb/tests/volightcurve`` + tabular/GP/ASAS-SN/Discovery suites
  **91 passed**; ``from skvo_veb import app`` smoke OK.

**Exit:** single source of truth — the sibling package.
**Phase 4 status:** **Done**.

#### Phase 5 — PhotDM-aligned ``PhotCal`` as sole mag↔flux engine — **Done**

**Locks applied in coding:**

- Nested PhotDM: ``PhotCal`` façade + ``ZeroPoint`` subtypes (``photdm.py``).
- Pogson live on ``PogsonZeroPoint``; ``AsinhZeroPoint`` /
  ``LinearFluxZeroPoint`` stubs (Asinh keeps ``softening_parameter``).
- CurveDash remains single ``metadata['photcal']`` (documented debt).
- ASAS-SN trees not remediated.
- Error helpers first-class on ``PhotCal`` façade.

**Package (sibling ``/home/voz/projects/UPJS/volightcurve``):**

- ``src/volightcurve/photdm.py`` — nested types.
- ``PhotCal`` delegates conversion to ``self.zero_point``; flat ctor still
  builds ``PogsonZeroPoint``.
- Exported in ``__all__``; README documents API + IVOA PhotDM client link.
- Pure tests: ``tests/test_photcal_conversion.py``; example calls
  ``pc.mag_to_flux`` directly.
- Sibling pytest: **26 passed**.

**Call-site inventory (non–ASAS-SN):**

| Site | Status |
|------|--------|
| ``CurveDash.convert_to_*`` | OK — ``PhotCal`` |
| ``lc_bridge`` domain-view helpers | OK — ``PhotCal`` |
| ``gp/flux.py``, ``plot_data.py``, ``manual_detrend.py`` | OK — ``PhotCal`` |
| Pages (Discovery, Processor, …) | OK — via CurveDash |
| ``lc_providers/shared/gaia_epoch_mag_error.py`` | **Fixed** — uses ``PhotCal.flux_err_to_mag_err`` |
| TESS photcal tests | OK — oracle ``-2.5 log10`` in assert only |
| ASAS-SN | Deferred (out of scope) |

**Debts (follow-up, not Phase 5):**

- Per-column PhotCals on CurveDash (stop collapsing Gaia mag+flux).
- Implement Asinh / Linear conversion maths.
- VOTable write/read of ZeroPoint ``dmtype``.

**Phase 5 status:** **Done**.

#### Phase 6 — Optional GitHub remote (developer-driven)

- Developer creates the GitHub repository and pushes the sibling project
  when ready.
- Optionally switch ``skvo_veb_2`` dependency from local editable path to
  ``git+https://…`` **or** keep local ``-e`` for development and document
  both.
- Agents must not create remotes, push, or open PRs unless the developer
  explicitly requests that in this phase.

**Exit:** library has its own remote (if desired); editable local workflow
still documented as the default for Cursor work.

#### Phase 7 (optional, later) — PyPI

Only if asked: versioning, classifiers, publish workflow. Not required for
the app to use the package.

### Acceptance

1. ``import volightcurve`` works in the ``skvo_veb_2`` venv from an
   **editable** local checkout.
2. Editing the sibling package in Cursor is the normal way to change I/O
   behaviour; no need to dig in ``site-packages``.
3. ``skvo_veb_2`` contains **no** nested ``skvo_veb/volightcurve/`` after
   Phase 4.
4. Pure tests live with the package; host/bridge/mission tests remain in
   ``skvo_veb_2``.
5. No unsolicited GitHub commits/pushes by agents.
6. Phase 5: ``PhotCal`` is the sole mag↔flux (+ error) engine; API
   documented/tested; non–ASAS-SN call sites audited; no local formulae;
   per-column / subclass direction recorded (implementation of subclasses
   and dual PhotCal may follow).

### Status

**Open.** Phase 0–5 **done**. Library is sibling editable ``volightcurve``
with PhotDM-nested ``PhotCal`` / ``PogsonZeroPoint``. Optional next:
**Phase 6** GitHub remote (developer-driven), **Phase 7** PyPI. Follow-ups
outside those phases: CurveDash per-column photcal; Asinh maths.

---

## Ticket 10 — Extract lightcurve discovery toolkit as a sibling package

**Audience:** agents and developer. **Think first; implement only when
asked, one phase at a time.** Every phase starts with a short discussion
and stops for agreement before coding the next phase.

**Hard constraints** (same spirit as Ticket 9):

- Do **not** commit, push, create, or alter any GitHub repository unless the
  developer explicitly orders that step in a later phase.
- Day-to-day editing in Cursor: sibling **local tree** beside ``skvo_veb_2``,
  editable install into consumer venvs (``pip install -e``). Do **not** treat
  a plain ``site-packages`` install as the normal workflow.
- PyPI upload is **out of scope** until the developer asks.
- Package product is **VO / archive only**: ``search`` returns the
  catalogue table; ``fetch`` returns calibrated VOTable **bytes**. Do
  **not** move Dash pages, AgGrid, Aladin, Plotly, ``CurveDash``, or
  ``lc_bridge`` into the new package. ``VOLightCurve`` is built in the
  app, in ``lc_discovery_load``, after ``fetch``.
- Must depend on sibling **``volightcurve``** (Ticket 9). Do not reimplement
  PhotCal / I/O / column discovery inside providers.

**Related:**

- Page entry: ``skvo_veb/pages/lightcurve_discovery.py`` (UI only; calls
  into utils + providers)
- Docs: [adding_a_lightcurve_provider.md](discovery/adding_a_lightcurve_provider.md),
  [mission_lightcurve_providers.md](discovery/mission_lightcurve_providers.md),
  [lightcurve_data_flow.md](lightcurve_data_flow.md),
  [lc_discovery_css.md](lc_discovery_css.md) / [lc_discovery_messages.md](lc_discovery_messages.md)
  (UI-only; stay with the app),
  [caching_architecture.md](caching_architecture.md)
- Code today: ``skvo_veb/lc_providers/`` (ABC, registry, missions, TAP),
  ``skvo_veb/utils/lc_discovery_search.py``,
  ``skvo_veb/utils/lc_discovery_time_bounds.py``,
  ``skvo_veb/utils/simbad_resolver.py``, ``skvo_veb/utils/coord.py``
  (candidates); **not** ``lc_discovery_load`` / ``lc_bridge`` / ``curve_dash``
  / ``lc_session_cache`` / ``lc_figure`` (app edge)
- Ticket 9 (``volightcurve``); Ticket 1 (Discovery shared fetch cache —
  may land in this package or remain app-wrapped; decide in Phase 0)
- Prior isolation discussion: VO boundary already documented; plugin ABC
  is sound; static ``PROVIDERS`` dict is the extension point today

### Goal

1. Lightcurve **discovery toolkit** becomes an independent Python package
   usable from notebooks and other apps (not only ``skvo_veb_2``).
2. Public contract: ``list_missions``, ``search``, ``fetch``. ``fetch``
   returns calibrated VOTable bytes. Providers remain pluggable behind
   that surface.
3. ``skvo_veb_2`` Lightcurve Discovery page becomes a **consumer**: UI +
   ``volc_to_curvedash`` + session cache stay in the app; science fetch
   imports the sibling package.
4. Keep the **plugin** approach (``MissionLightcurveProvider`` ABC +
   registry). Prefer evolving toward explicit ``register()`` / entry points
   so third parties can add missions without editing core (Phase 0 decides
   how far to go in the first cut).
5. Equip the package with a **Cursor Agent skill** (self-contained
   ``SKILL.md`` + ``references/``, same pattern as ``volightcurve``): agents
   use the public discovery API + ``volightcurve``, not ad-hoc archive
   scrapers or Dash types.
6. Peel app-only import tangles (``PipeException`` / ``my_tools``, selected
   ``lc_config`` constants, Simbad result types) into package-local errors
   / config so the library does not depend on ``skvo_veb.*``.

### Target cut (end state)

```text
~/projects/UPJS/
  volightcurve/                 ← Ticket 9 (dependency)
  <discovery-package>/          ← NEW sibling (name in Phase 0)
    pyproject.toml
    README.md
    docs/                       ← provider how-to, architecture notes
    examples/                   ← notebook-friendly search+fetch
    .cursor/skills/<name>/      ← Agent skill + references/
    src/<import_name>/
      providers/                ← ABC, registry, missions, tap, lc_key, …
      search.py                 ← orchestration (optional in first cut)
      …
    tests/                      ← pure package tests (no Dash)
  skvo_veb_2/
    skvo_veb/
      pages/lightcurve_discovery.py   ← UI only
      utils/lc_bridge.py, curve_dash, lc_session_cache, …
      lc_providers/                   ← removed after cutover (or thin re-export)
```

App / notebook:

```text
pip install -e /path/to/volightcurve
pip install -e /path/to/<discovery-package>
```

```text
from lc_discovery import list_missions, search, fetch
missions = list_missions()
catalog = search(...)          # astropy Table, one row per light curve, opaque lc_key
payload = fetch(lc_key)        # bytes: calibrated VOTable
```

The Dash app keeps ``lc_discovery_load``: those bytes become a
``VOLightCurve``, then ``volc_to_curvedash``. A notebook that wants a
``VOLightCurve`` uses ``volightcurve`` on the same bytes.

### Non-goals (unless later asked)

- Moving ``CurveDash``, ``lc_bridge``, Dash page, CSS, Aladin, AgGrid, or
  plot tools into the package.
- Freezing today's fetch products and moving them unchanged. Before the
  package exists, providers keep every science column (magnitude and flux
  together when the file has both) and attach only calibration that is
  researched and documented. See Phase 0.
- Leaving Discovery export and the shared fetch cache as they are today.
  Both are in scope below.
- PyPI / agent-owned GitHub remotes (optional late phases, developer-driven).
- Merging this package into ``volightcurve`` (keep I/O vs discovery separate).

### Current state (do not re-derive)

- Reviewed plugins return calibrated VOTable bytes. ``lc_discovery_load``
  parses those bytes into a ``VOLightCurve``, then ``volc_to_curvedash``.
  The ABC annotation on ``fetch_lightcurve`` still says ``VOLightCurve``;
  that annotation is behind the code.
- Registry is a static dict in ``lc_providers/registry.py`` (edit to add a
  mission); not setuptools entry points yet.
- ``gaia_debug`` exists for tests and is unregistered.
- Shared archive fetch cache for Discovery is still missing. It is in
  scope for this ticket, for all providers (Ticket 1).
- Host couples providers to ``PipeException``, ``lc_config``, Simbad types.

### Phases (stop and discuss before each)

#### Phase 0 — Retrieved product vs the volightcurve contract (discussion, then fixes)

Do this in ``skvo_veb/lc_providers/`` **before** any file move. One fetch
is still one catalogue row (one passband). Multi-column means that product
keeps time, magnitude, flux, both errors, and labels when the file has
them. It does not mean merging every filter into one table. The app may
still copy one series into ``CurveDash``. The provider must not drop the
other photometry column first.

Calibration on a discovery product is **not** the volightcurve ingest
rule. The provider's job is a complete description of the retrieved
series. When the archive omits or mis-states a zero point, unit, filter,
or another photcal field, the provider may correct it from published
instrument knowledge (the developer's own reduction and the literature).
That assignment is research, not a silent default.

The correction is the same shape for **all** providers. It is not a
constant on a service, and it is not keyed by an SSA collection name.
Each provider has its own config. A correction applies to every product
of that provider. The zero point is chosen by
``photDM:PhotometryFilter.identifier`` on the product. Magnitude and flux
stay separate when the file has both. One ``PhotCal`` is not pasted onto
every column.

After the archive product is parsed, and before the error-column link:

1. Keep every photcal field as the file published it.
2. Look up a correction for this provider and this filter identifier. No
   matching row means change nothing.
3. Apply only the fields that row names (fill a gap, or replace a wrong
   value). Do not use ``photcal_defaults`` (``zp_flux=1``, ``zp_mag=20``)
   and do not fill ``zp_flux=1`` / ``zp_mag=0`` just so conversion runs.
4. Record each applied change: provider, filter identifier, column, field,
   value, unit, and source (paper, instrument handbook, or this project's
   reduction).
5. Then link an unlinked error column to the single corrected parent.
   An error column the archive already linked is left as it is.

A correction row lives in that provider's config. The numbers are
supplied per filter identifier; they are not invented here.

A service-wide magnitude zero point, and a zero point keyed by an
invented collection name, are the wrong grain and are withdrawn.

**Discovery page export.** Export from the Discovery page keeps the
original column names and every column of the retrieved table, including
a multi-column table (time, magnitude, flux, both errors, labels). It
does not rewrite the series into ``jd`` / ``flux`` / ``flux_err`` or
``mag`` / ``mag_err``, and it does not drop columns that were not chosen
as the plotted series.

**Fetch cache.** All providers use one shared archive fetch cache.
A second retrieve of the same product reads the cache. ``force_refresh``
bypasses it and replaces the stored product. The session cache of the
working ``CurveDash`` stays separate.

**Exit:** the correction table (provider, filter identifier, column,
field, value, unit, source) agreed here. Code of the fixes waits until
the developer says go. No package tree yet.

**Decisions (Phase 0):**

- Calibration corrections apply to all products of a provider.
- The zero point is keyed by ``photDM:PhotometryFilter.identifier``.
- A missing lookup row leaves the published photcal unchanged.
- Each row names the fields it sets or replaces, and the source.
- Magnitude and flux calibrations are independent.
- The earlier service-wide ``zp_mag = 0.0`` is withdrawn.
- An SSA collection name is not a calibration key.

#### Phase 1 — Agree packaging shape and cut line (discussion only)

Decide and record in this ticket:

1. **Package / import name** (proposals: ``lc_discovery``,
   ``skvo_lc_discovery``, or other).
2. **Local path** (default proposal:
   ``/home/voz/projects/UPJS/<package>`` beside ``skvo_veb_2``).
3. **What moves in the first cut:**
   - Required: ``lc_providers/*`` (base, registry, catalog_schema, lc_key,
     tap, all registered missions).
   - Optional same cut: ``lc_discovery_search``, time bounds, Simbad,
     coord (recommended if notebooks should search without the app).
4. **What stays in ``skvo_veb_2``:** page, CSS, messages, Aladin, AgGrid,
   ``lc_discovery_load``, ``lc_bridge``, ``CurveDash``, session cache,
   figures / interaction.
5. **Error / config strategy:** package-local exception type vs thin shared
   util; which ``lc_config`` symbols move vs re-export from ``volightcurve``.
6. **Plugin registration:** keep static dict for v1 vs add ``register()`` /
   entry points immediately.
7. **Ticket 1 relationship:** shared fetch cache owned by package, by app,
   or deferred until after cutover.
8. **Editable dependency** declaration for ``skvo_veb_2`` (same pattern as
   Ticket 9: README / ``requirements-local.txt.example``, not a hard
   machine path in committed ``requirements.txt`` unless agreed).
9. Confirm **Cursor skill** ships with the package (mandatory for this
   ticket’s Definition of Done).

**Exit:** written decisions below. No file moves yet.

**Decisions (Phase 1):**

1. Package and import name: ``lc_discovery``.
2. Local path: ``/home/voz/projects/UPJS/lc_discovery``, beside
   ``skvo_veb_2`` and ``volightcurve``.
3. First cut moves ``skvo_veb/lc_providers/`` (ABC, registry, catalogue
   schema, ``lc_key``, TAP, registered missions) and the search
   orchestration a notebook needs (``lc_discovery_search`` target
   resolution, time bounds, Simbad, coordinates). Status sentences,
   AgGrid row conversion, and page markdown stay in the app.
4. The app keeps the page, CSS, messages, Aladin, AgGrid,
   ``lc_discovery_load``, ``lc_bridge``, ``CurveDash``, session cache,
   and figures.
5. Public surface is only ``list_missions()``, ``search(...)``, and
   ``fetch(lc_key) -> bytes``. ``DiscoveryFetchContext`` does not cross
   this surface. A mission option such as ZTF quality, if it remains,
   is an argument of ``fetch`` or ``search``, not a Dash context.
6. Static registry for the first cut. ``register()`` waits until a
   third party must add a mission without editing the package.
7. Shared fetch cache stays out of this extraction (Ticket 1).
   ``force_refresh`` may remain on ``fetch`` as a flag with no cache
   behind it yet.
8. Editable install, same as Ticket 9: ``pip install -e`` the sibling;
   document it in the app README and ``requirements-local.txt.example``.
   No machine path in committed ``requirements.txt``.
9. A Cursor skill ships with the package, after the import cut, same
   as ``volightcurve``.

**Extraction, same path as ``volightcurve`` (Ticket 9). No file moves
until the developer says go.**

1. Scaffold ``/home/voz/projects/UPJS/lc_discovery`` with ``pyproject.toml``
   (src layout), README, and ``src/lc_discovery/``. Copy the provider
   tree. Internal imports become ``lc_discovery.*``. Depend on sibling
   ``volightcurve``. Nested ``skvo_veb/lc_providers/`` stays and remains
   what the app runs.
2. ``pip install -e /home/voz/projects/UPJS/lc_discovery`` into the app
   venv. Prove ``import lc_discovery`` loads the sibling and
   ``import skvo_veb.lc_providers`` still loads the nested copy. Do not
   switch the app in this step.
3. Retarget app imports from ``skvo_veb.lc_providers`` to ``lc_discovery``.
   Leave the nested tree as a dead copy. ``lc_discovery_load`` still
   parses ``fetch`` bytes into ``VOLightCurve``.
4. Delete ``skvo_veb/lc_providers/`` and retarget the discovery docs to
   the sibling. Pure provider tests move with the package. Dash and
   ``CurveDash`` tests stay in ``skvo_veb_2``.

#### Phase 2 — Scaffold sibling package (local only)

- Create sibling tree (``pyproject.toml``, README, docs pointers,
  ``examples/``, empty or copied provider tree).
- Depend on ``volightcurve`` (editable / VCS as agreed).
- Pure smoke: import package; list registered missions; one offline or
  mocked search/fetch path if feasible.
- Nested ``skvo_veb/lc_providers/`` still present and authoritative for the
  running app until Phase 5.

**Exit:** sibling imports in isolation; app unchanged.

#### Phase 3 — Editable install + dual-import safety

- ``pip install -e`` into ``skvo_veb_2`` venv (and a scratch notebook venv).
- Prove ``import <name>`` vs ``import skvo_veb.lc_providers`` do not
  accidentally shadow until Phase 4.
- Document install steps (app README + local requirements example).

**Exit:** editable link proven; import switch still deferred.

#### Phase 4 — Retarget ``skvo_veb_2`` imports

- Point Discovery search/load and any other consumers at the sibling
  package; leave nested tree as dead copy until Phase 5.
- Host keeps ``volc_to_curvedash`` at the edge.
- Pytest: provider / Discovery load-export suites green; app smoke import.

**Exit:** app uses sibling for discovery VO path; nested tree unused.

#### Phase 5 — Remove nested ``skvo_veb/lc_providers/`` (and moved utils)

- Delete moved modules from the app; fix docs that still say nested paths.
- Retarget [adding_a_lightcurve_provider.md](discovery/adding_a_lightcurve_provider.md)
  and [mission_lightcurve_providers.md](discovery/mission_lightcurve_providers.md) to
  the sibling package as the home for new missions.

**Exit:** single source of truth for providers.

#### Phase 6 — Public notebook API + Cursor Agent skill

- Document and export a small public surface (list / search / fetch /
  register as agreed).
- Example notebook or script: ``list_missions`` → ``search`` → ``fetch``
  bytes → optional ``VOLightCurve`` via ``volightcurve``.
- Add ``.cursor/skills/<name>/`` with ``SKILL.md`` + ``references/``
  (self-contained; no ``../../../`` into the package root). Skill must
  teach: use package + ``volightcurve``; discover columns via
  ``volightcurve`` helpers; never invent archive parsers or Dash types;
  version self-check idiom.
- Re-copy / install notes for consumer projects (skills are not installed
  by pip).

**Exit:** a fresh project can ``pip install -e`` both packages, copy the
skill, and drive discovery without opening ``skvo_veb_2``.

#### Phase 7 — Optional GitHub remote (developer-driven)

- Developer creates remote / tags; agents do not push unless ordered.
- Optionally document ``git+https://…`` install beside local ``-e``.

#### Phase 8 (optional) — Stronger plugins / shared fetch cache

- Entry points or documented third-party ``register()``.
- Ticket 1 archive fetch cache if Phase 1 parked it here.
- PyPI only if asked.

#### Phase 9 — Discovery VOTable export button

- Remove the debug write of the issued VOTable under the system
  temporary directory (``lc_tmp_N.vot`` per mission).
- Add a Discovery-page button that downloads that same calibrated
  VOTable. The button is the export; the temporary file is not.

### Acceptance

1. Editable sibling package provides ``list_missions``, ``search``, and
   ``fetch`` → calibrated VOTable bytes, without importing ``skvo_veb``.
2. ``skvo_veb_2`` Discovery page still works via bridge + session cache;
   no nested provider tree after Phase 5.
3. ``lc_discovery`` does not depend on ``volightcurve``. The Dash app
   still parses ``fetch`` bytes with ``volightcurve``. The AIP magnitude
   error is the Pogson line ``(2.5 / ln(10)) / SNR``.
4. Cursor skill ships with the package and is documented for consumers.
5. Pure tests live with the package; Dash / CurveDash tests stay in
   ``skvo_veb_2``.
6. No unsolicited GitHub commits/pushes by agents.

### Status

**Open.** Sibling no longer imports ``skvo_veb``. ``PipeException``,
photcal keys, ``JD_TO_MJD``, and the Simbad result type live in
``lc_discovery``. Unused ``VOLightCurve`` builders are removed.
``JD_TO_MJD`` is the constant ``2400000.5`` inside the package.
``skvo_veb/lc_providers/`` is deleted. The app imports ``lc_discovery``.
Discovery docs in the app and in the sibling name ``lc_discovery/providers/``.
Package regression tests live in ``lc_discovery/tests`` and import only ``lc_discovery``. Aladin, search chrome, session cache, and CurveDash tests stay in ``skvo_veb/tests``. Phase 9 (drop ``/tmp``
VOTable debug, add an export button) is written and not started.
Shared fetch cache stays in Ticket 1.

---

## Ticket 11 — Rough extrema drawer: intervals on the client (``dcc.Store``)

**Page:** Lightcurve Processor (`/lc_processor`), Rough extrema accordion.
`skvo_veb/pages/lightcurve_processor.py`,
`skvo_veb/utils/lc_processor/intervals.py`,
`skvo_veb/assets/lc_processor_clientside.js` (`lcpSelect` / `lcpExtrema`).

**Related:** [caching_architecture.md](caching_architecture.md) (hybrid
client–server; Store size limits), AGENTS.md (`dcc.Store` for lightweight
UI state only; max ~5MB; no large datasets), Ticket 2 (client mark /
server mutate pattern for intervals on TESS — different page, same
ownership question).

### Goal

Today rough **intervals** are a **server session blob**
(`INTERVALS_BLOB` = ``intervals``, key
``lc_processor_{user_tab_id}_intervals`` via ``write_page_blob``). Manual
add (box select), delete (pointer pick), Generate, Show, and Export all
round-trip through that disk cache and a plot revision bump.

Move the **intervals list** (and the related Rough-extrema *interaction*
state that belongs with it) onto the **client**: ``dcc.Store`` (+
clientside helpers), so marking / showing / editing intervals does not
require a server blob write on every drag. Keep heavy photometry and
working CurveDash on the server cache (unchanged).

### Current state (do not re-derive)

- **Server blobs (processor namespace):** ``EXTREMA_BLOB``,
  ``INTERVALS_BLOB``, ``REF_EXTREMA_BLOB``, plus smooth / detrend.
- **Intervals CRUD:** ``edit_intervals_on_plot`` /
  ``generate_rough_intervals`` → ``write_page_blob(..., INTERVALS_BLOB)``.
- **Plot 1:** reads intervals from the server blob when Show intervals
  is on; ``dragmode=select`` for Add interval; zoom via
  ``uirevision`` + zoom store.
- **Export intervals:** ``format_cached_intervals_download`` from the
  server blob (surviving list, sorted by start JD) — not regenerated
  from extrema at export time.
- **Client already:** knot / extrema / interval *tool radios*, show
  toggles, zoom store, extrema/interval *pick* stores (ephemeral),
  ``lcpSelect`` / ``lcpExtrema`` clientside. The **interval list itself**
  is not in a Store.

### Locked constraints (draft — confirm before coding)

1. **Do not put the light curve in ``dcc.Store``.** Working photometry
   stays in the server LC session cache.
2. Intervals payload stays **small** (list of
   ``{id, start_jd, end_jd, origin}``). Enforce Store size discipline
   (AGENTS.md ~5MB); fail fast if an upload/export path would abuse it.
3. **Export** must still write from the **surviving** interval list
   (sorted by start JD), whether that list lives in Store or was
   synced — no silent re-generation from extrema at download time.
4. Preserve plot-1 zoom when adding/deleting intervals (same spirit as
   today’s ``uirevision`` / zoom store).
5. Mutual exclusion of knot / extrema / interval tools stays.
6. Uploaded **reference** extrema and **working** rough extrema may stay
   on the server for this ticket unless Phase 0 explicitly expands
   scope; the primary move is **intervals**.
7. Fail fast; no invented default intervals. British English UI.
8. Think / discuss Phase 0 before implementing.

### Proposed direction (when asked to code)

1. **Phase 0 — agree ownership:** which pieces move to client Stores:
   - intervals list (required);
   - show-intervals / interval-tool (already client widgets — confirm
     no server mirror);
   - whether Generate still writes server-side then copies into Store,
     or computes client-side from extrema Store / a one-shot callback
     result;
   - whether Export reads Store directly (preferred) or a one-time
     server snapshot.
2. Add ``dcc.Store`` for intervals (JSON-safe). Wire Add / Delete /
   Generate / Show / Export to that Store. Drop or stop writing
   ``INTERVALS_BLOB`` once the client path is authoritative.
3. Clientside: keep box-select → bounds; prefer updating the Store with
   minimal or no full figure rebuild where Plotly shapes can be patched
   clientside (discuss; do not break zoom).
4. Clear the intervals Store on LC upload / fit-blob clears (same
   lifetime rules as today’s server clear).
5. Tests: Store round-trip, export from Store contents, no regression
   on Generate / manual / sort-by-start.

### Out of scope (unless later asked)

- Moving the full working light curve or smooth overlay into Store.
- Smooth drawer / knots (still separate).
- Ticket 2 TESS interval cleaning (different page).
- Putting intervals back into ``volightcurve``.

### Agent checklist

- [ ] Phase 0 ownership agreed with the developer (what moves, what stays server).
- [ ] Intervals authoritative in ``dcc.Store``; server ``INTERVALS_BLOB`` retired or read-only bridge removed.
- [ ] Export uses surviving client list, sorted by start JD.
- [ ] Zoom and tool mutual exclusion still work.
- [ ] Tests cover add / delete / generate / export / clear-on-upload.
- [ ] No code until the developer says go after Phase 0.

### Status

**Open.** Phase 0 next (agree client vs server cut for intervals and
related Rough-extrema state).

---

## Ticket 12 — volightcurve: photometric calibration validation for domain conversion

**Package:** sibling ``volightcurve`` (``PhotCal`` / PhotDM live here).
**Consumers:** ``skvo_veb`` ``CurveDash.convert_to_mag`` /
``convert_to_flux``, ``lc_bridge.photcal_from_metadata``,
``photcal_coherence.inspect_*``, GP flux helpers — must not duplicate
conversion-readiness rules long term.

**Related:** ``volightcurve/docs/io_contract.md`` §4 (keywords),
``photcal_defaults.py`` (defaults are for **host apps only**, not silent
library promotion), Ticket 7 (skvo photcal coherence / Processor Apply),
Ticket 13 (§8 ingest validation; separate from conversion readiness).

### Goal

Shift **calibration readiness for mag↔flux conversion** into
``volightcurve``: one transparent, fail-fast check before calling
``PhotCal.mag_to_flux`` / ``flux_to_mag`` (and error helpers). Ingest may
succeed with incomplete ``FILTER`` / ZP; conversion must raise a clear
library exception — not invent zero points, not fill columns with NaN.

``PhotCal`` **is** part of volightcurve (``volightcurve.lightcurve.PhotCal``
→ ``photdm.PogsonZeroPoint``). Validation should live next to that API,
not only in ``skvo_veb``.

### Current state (locked findings — do not re-derive)

| Layer | What happens today |
|-------|-------------------|
| **`PhotCal(...)` constructor** | Defaults ``zp_flux=1.0``, ``zp_mag=0.0`` if caller omits args — **not** fail-fast. |
| **`photcal_from_metadata` (skvo ``lc_bridge``)** | ``ValueError`` if ``zp_flux`` or ``zp_mag`` missing — **skvo**, not volightcurve. |
| **`inspect_photcal_dict` (skvo ``photcal_coherence``)** | Returns problem **strings**; UI blocks domain switch without throwing. |
| **`CurveDash.convert_to_*`** | Builds ``PhotCal`` via ``photcal_from_metadata``, then **does** call ``photcal.mag_to_flux`` / ``flux_to_mag`` (volightcurve maths). Wraps ``UnitsError`` / ``ValueError`` as ``PipeException``. |
| **`PogsonZeroPoint` conversion** | ``UnitsError`` when column units ≠ ZP units; can still run with numeric ZPs that are merely incomplete scientifically. |
| **`VOLightCurve` column helpers** (e.g. add flux from mag) | If no PhotDM for column: **logs warning**, fills new column with **NaN** — opposite of fail-fast (legacy; not the same as NaN **cells** in uploaded tables). |

There is **no** single volightcurve API today that means “safe to convert
domain” with a stable exception type.

### Phases

#### Phase 0 — Time column names — **Done**

The product table keeps the names it was given. Roles come from UCDs
(``time.epoch``), not from a column called ``jd``. Absolute JD is a value
plus a time origin. VOTable write may shift those values to MJD and set
TIMESYS; the field name stays. Non-VO write encodes the time role as
``jd`` only on the way out. ``CurveDash`` stores one absolute-JD series in
its own column ``jd`` at the host edge.

**Rejected:** forcing every ingest path to rename the product time column
to ``jd``.

#### Phase 1 — Conversion, inspect, recovery — **locked, not coded**

1. **Constructor.** ``PhotCal()`` with no arguments must store a calibration
   that domain conversion refuses. It must not store a usable pair
   (``zp_flux=1``, ``zp_mag=0``). The constructor does not raise.
2. **Inspect.** One library call returns a list of specific problems
   (missing zero point, unit that is not a unit, flux-column unit not
   equivalent to the zero-point flux unit). It does not write defaults.
   Domain switch must call this library inspect. A second rule set in
   ``inspect_photcal_dict`` is not allowed once the library call exists.
3. **Recovery.** Suggested constants stay in
   ``volightcurve.photcal_defaults``. The only writer is
   ``reconcile_photcal_dict``. Pages call it through one ``CurveDash``
   method and must show every returned warning. ``lc_bridge`` does not
   gain a filler. Domain switch does not call recovery.
   ``gp.flux.resolve_gp_photcal`` must not invent calibration in the log.
   On the GP page, every touch of calibration warns the user.
   Keeping calibration correct when the page transforms the light curve
   (detrend, fold, and the rest, except cleaning) is **Ticket 15**.
4. **Conversion.** ``flux_to_mag``, ``mag_to_flux``, and the error helpers
   are the only maths, inside volightcurve. They raise with the same
   reasons inspect returns, before the arithmetic. No Dash or Plotly
   wording in the exception. The app catches it, keeps the scientific
   sentence, and adds the screen hint.

#### Phase 2 — Implement and wire (when asked to code)

### Locked direction (when asked to code, after Phase 0–1)

1. Add volightcurve validation for **conversion readiness** (exact API from
   Phase 1).
2. Exception: transparent message (missing ZP pair, bad units, flux column
   unit vs ZP flux unit mismatch). Prefer reusing or extending
   ``LightcurveIOError`` / a dedicated ``PhotCalError`` — one style for
   hosts to map to UI.
3. **Do not** use ``photcal_defaults`` inside volightcurve conversion paths
   (defaults remain for explicit host fill + warning only).
4. Skvo may thin-wrap volightcurve validator in ``inspect_photcal_dict`` /
   ``photcal_from_metadata`` over time; avoid two divergent rule sets.
5. Revisit ``VOLightCurve`` NaN-fill helpers: align with fail-fast or mark
   deprecated for scientific pipelines (separate from §8 cell NaN rules).

### Out of scope

- §8 table structure / censored ``>mag`` / column selection (separate contract work).
- Inventing ZP on Processor Apply (Ticket 7 / skvo policy).
- VOTable export ``filter_identifier`` (skvo export gate).

### Agent checklist

- [x] Phase 0: time column naming agreed (no product-wide ``jd`` rename).
- [x] Phase 1: constructor refuses nothing; inspect is a library report;
  recovery is ``reconcile_photcal_dict`` via ``CurveDash``; conversion
  raises in volightcurve. Domain switch must not keep a second inspect.
- [x] Phase 2: ``inspect_conversion_photcal`` and ``PhotCalError`` in volightcurve, with tests.
- [x] ``CurveDash.convert_to_*`` uses ``PhotCal`` conversion and surfaces ``PhotCalError``.
- [x] ``inspect_photcal_dict`` calls the library inspect. No second rule set.
- [x] Code written after the developer said go. ``VOLightCurve`` NaN-fill helpers were not part of this pass.

### Status

**Done** for the locked Phase 1 scope. Empty ``PhotCal`` does not carry a
usable zero point. ``inspect_conversion_photcal`` is the only inspect.
``reconcile_photcal_dict`` remains the only writer; ``CurveDash.reconcile_photcal``
is the session entry. GP flux conversion no longer fills calibration quietly.
Ticket 15 still owns calibration updates when a page rewrites the curve.

---

## Ticket 13 — volightcurve: §8 product validation on ingest (structure + cells)

**Package:** sibling ``volightcurve`` (``read_lightcurve``, ``VOLightCurve``,
``apply_non_votable_heuristics``, VOTable promote path).

**Consumers:** every host that calls ``read_lightcurve`` / ``from_table`` /
``_ingest`` — including ``skvo_veb`` ``ingest_volightcurve_file`` /
``lc_bridge``. **Do not** duplicate this policy in ``lc_bridge`` unless the
developer explicitly agrees a thin error-mapping wrapper only.

**Related:** ``volightcurve/docs/io_contract.md`` **§9** (cells and
``SENTINEL``; §8 is export). Ticket 14: the library does not drop extra
science columns. A single plotted series is a host (``CurveDash``) copy.

### Goal

One **format-agnostic** validation bottleneck **after** normalisation
(``apply_non_votable_heuristics`` / VOTable column promotion) and **before**
the issued ``VOLightCurve`` is considered valid for plotting and science
pipelines. Product behaviour must **not** depend on which source codec ran.

**Fail only** (``LightcurveIOError`` or agreed subtype); no warnings on
``VOLightCurve`` for ingest validation.

Ingest may succeed with **incomplete photcal** (ZP / filter). That is
Ticket 12, not §8.

### Locked ingest rules (revised — see ``io_contract`` §9)

**Library.** Do **not** drop extra time, magnitude, flux, or error columns.
Do **not** rename columns to ``jd``.

**Cells (non-VO only).** Finite floats stay. ``nan`` and empty numeric
fields become NaN. A leading ``<`` / ``>`` in an otherwise numeric column
becomes NaN and does not fail the file. Optional repeated
``SENTINEL=<float>`` lists values that become NaN. Compare with a close
test (absolute tolerance), not ``==``. Undeclared numbers such as
``99.990`` stay numbers. The list is stored and written back on non-VO
formats. Incomplete photcal does not fail ingest. An all-NaN magnitude
column does not fail the file when flux still has finite values.

**VOTable cells.** Do **not** apply ``SENTINEL`` or the ``<`` / ``>`` rule.
Those keywords are a non-VO comment convention; inventing a VOTable
equivalent is out of scope. Astropy's VOTable reader already turns an empty
``<TD>`` and the text ``NaN`` into a masked numeric cell. A declared number
such as ``99.99`` stays that number. No second pass in ``_ingest_votable``.

**No finite photometry.** Out of scope for this package. Whether an empty
magnitude or flux column is usable is the host's working-domain choice
(magnitude versus flux), already above ``read_lightcurve``.

**Host.** ``CurveDash`` keeps one series. If magnitude is all NaN and flux
has finite values, select flux. Extra columns never enter that object, so
an app download will not contain them. That loss is the host boundary, not
a volightcurve round-trip.

**Hooks (implementation placement when asked to code)**

- End of ``from_table``; ``_ingest_votable``; non-VOTable ``_ingest`` after
  heuristics — shared ``finalize`` helper, one rule set.

### Explicitly out of scope / rejected for §8

- **Renaming** the product time column to ``jd`` (or any single global time
  name) on ingest for all codecs. Time **naming** is **Ticket 12 Phase 0**.
- Photometric calibration completeness at ingest (Ticket 12).
- Host ``photcal_defaults`` / Processor Apply inventing ZP (Ticket 7).
- ``VOLightCurve`` legacy helpers that fill whole columns with NaN when
  PhotCal is missing (Ticket 12; agreed separate from cell-level NaN).

### Phases

#### Phase 0 — Contract — **Done**

``io_contract`` §4 ``SENTINEL`` and §9 (keep all columns; cell rules on
non-VO). VOTable nulls stay with the VOTable reader (see locked rules).
“No finite photometry” is host scope, not a library check.

#### Phase 1 — Cells and ``SENTINEL`` — **Done**

Non-VO only. Repeated ``SENTINEL`` values become NaN via ``np.isclose``
(absolute tolerance ``1e-5``), not ``==``. A leading ``<`` / ``>`` in an
otherwise numeric column becomes NaN and does not fail the file. Columns
are not dropped. VOTable ingest does not run this pass.

#### Phase 2 — Host series pick — **Done**

``_resolve_photometry_column`` keeps magnitude when it has a finite value.
If magnitude is all NaN and flux is not, the series uses flux.

### Agent checklist

- [x] Cell rules drafted in ``io_contract.md`` §9 (no ``jd`` rename mandate).
  Export naming stays in §8.
- [x] Ticket 12 Phase 0 time naming deferred: the product time column is
  not renamed. Further naming stays on Ticket 12.
- [x] Non-VO cell pass lives in ``apply_non_votable_heuristics``. VOTable
  is excluded on purpose (no invented sentinel vocabulary). “No finite
  photometry” is not a library failure.
- [x] No ``lc_bridge`` cell-validation fork. The host only chooses the
  working photometry column for one series.
- [x] Code was written only after the developer said go.

### Status

**Done** for the revised scope. Non-VO cells, sentinels, and the host
series pick are in place. VOTable nulls are left to the VOTable reader.
An all-empty photometry column is the application's decision.

---

## Ticket 14 — volightcurve: preserve VO column names; UCD-aware export; label/sector ingest

**Package:** sibling ``volightcurve`` (``io.py``, ``lightcurve.py`` /
``write_vo_lightcurve``, ``read_lightcurve``, ``.dat`` codec).

**Related:** sibling ``volightcurve/README.md`` (in-memory product, UCD vs
names); Ticket 12 Phase 0 (no product-wide
rename); Ticket 13 (§8); ``docs/io_contract.md`` §5 (non-VO write names);
``skvo_veb`` ``lc_bridge.volc_to_curvedash`` (label resolution by name only).

**Audience:** agents. **Think first; implement only when the developer asks.**

### Goal

1. **VOTable-shaped products:** When columns already carry **UCDs** (and units)
   that define roles, **do not rename** those columns on ingest or on
   VOTable export merely to match ``obs_time`` / ``phot`` / ``flux_error``
   spellings. Roles live in metadata; names may stay archive-native.
2. **Export remapping:** Where a wire layout is still required (MJD
   ``obs_time``, FIELD UCDs on write), resolve source columns with the
   **same UCD discovery API** as ingest (`get_time_colnames`, ``get_mag_*``,
   ``get_flux_*``, error helpers) — not hard-coded name lists alone.
3. **Per-epoch labels / sectors:** Audit and fix how string identifier columns
   round-trip through volightcurve so users do not **lose labels** when the
   column is not literally named ``label``, ``sector``, or ``flag``.

### Current state (locked findings — do not re-derive)

**In-memory product (intended):** Column **names** vary by format; **UCDs** on
``table[col].info.meta`` express time / mag / flux / error roles (see package
README).

**VOTable export — two behaviours today:**

| Situation | What happens |
|-----------|----------------|
| ``volc.table`` already has ``obs_time`` | ``_table_for_votable_codec`` copies table **unchanged** (Path 1). |
| No ``obs_time`` but ``jd`` / ``time`` + ``phot``/``mag``/``flux`` names | Builds a **new** table; renames to ``obs_time``, ``phot``, ``flux_error`` (Path 2). Uses ``_photometry_columns_for_votable`` — **name literals only**, not UCD discovery. |

**``write_vo_lightcurve``** (low-level writer) always runs a **rename block**
toward ``obs_time`` / ``phot`` / ``flux_error`` / ``label`` (and renames
``sector`` → ``label``), plus positional fallbacks — even when the input
table already had valid VO FIELD names and UCDs.

**Non-VOTable export:** CSV / ``.dat`` write ``volc.table`` colnames as-is
(UCDs not on wire; §5 contract expects canonical ``jd``/``mag``/… at write —
separate from this ticket’s VOTable preservation rule).

**Labels / sectors:**

| Layer | Behaviour |
|-------|-----------|
| **``.dat`` ingest** | Role ``other`` columns keep **header names** (``label``, ``Observ``, custom text). Values stay strings. Contract: no closed allowlist of free-text names. |
| **VOTable ingest** | Columns keep file names + UCDs; no volightcurve helper like ``get_label_colnames`` from UCD (e.g. ``meta.id``, ``meta.dataset``). |
| **`_table_for_votable_codec` Path 2** | Copies only a column named ``label`` into output; ignores other string columns. |
| **`write_vo_lightcurve``** | Only ``label`` / ``sector`` (sector renamed to ``label``) in the slim output table; other annotation columns dropped from ``t_out``. |
| **`lc_bridge.volc_to_curvedash``** | Sets ``CurveDash.label`` only if a column is named ``label``, ``sector``, or ``flag`` — **not** UCD-based. |

**Symptom:** A valid VO or ``.dat`` file with a per-epoch ID column under
another name (or VO UCD but not ``label``) can ingest into ``volc.table`` yet
**hosts see no labels** after bridge/export.

### Locked export policy (Phase 0 — developer, 2026-09-23)

1. **UCD is the first source of truth** for column roles on the product
   (assigned and promoted at **ingest**, not at export).
2. **Export does not add validation.** Do not refuse a VOTable (or any
   format) because the table has several time, mag, flux, or error columns,
   missing photcal, or a layout the writer would prefer. Multiple science
   columns are **allowed** (IVOA-compatible). PhotCals, when present, stay
   bound to the columns they belong to on ``volc.photdms``.
3. **Export describes what the product already holds:**
   - **UCD-capable wire (VOTable):** write the table **as stored** — column
     **names preserved**, **UCDs** (and units) written on FIELDs. Do not
     force a rename to ``obs_time`` / ``phot`` / ``flux_error`` when UCDs
     already mark roles.
   - **Non-UCD wire (CSV, ``.dat``, …):** write the data we have; encode
     roles of the **main** columns (time, mag, flux, errors) in **column
     names** per the I/O contract. Do not invent UCDs at write time.
4. **Ingest** owns structural checks, name→UCD promotion, and standards
   alignment. Export must not repeat that burden.
5. Multi-column ingest is **not** required to finish this ticket’s export
   rules; the writer must not assume a single time or single photometry
   column forever.

### Decisions (Phase 0 — agreed, written in volightcurve ``docs/io_contract.md`` §8)

1. **Label:** leftmost column whose UCD matches the label-role list
   (``meta.code``, ``meta.id``; list may grow). If none, leftmost column
   that is not time / flux / mag / error. All columns are still exported.
2. **Non-VO names:** do not drop columns. One column per role keeps
   ``jd`` / ``mag`` / ``flux`` / ``mag_err`` / ``flux_err``. Several of one
   role: ``mag-1``, ``mag-2``, and the same pattern for the other roles.
3. **VOTable time values:** may convert to MJD and set TIMESYS (``JD0``
   sense). Field name and UCD stay.
4. **``write_vo_lightcurve``:** retire rename-and-keep-only
   ``obs_time`` / ``phot`` / ``flux_error`` / ``label``. Write the product
   table plus its metadata.

### Locked direction (when asked to code)

1. Remove export-time **forced renames** and **name-only** column picking
   that drop or relabel VO-annotated columns (``_table_for_votable_codec``
   Path 2, ``write_vo_lightcurve`` rename / slim ``t_out``).
2. VOTable write: serialise existing colnames, UCDs, units, and
   ``photdms`` links; no extra schema gate.
3. Non-VO write: map roles → contract column names from **existing** UCDs
   (ingest already set them); do not re-validate.
4. Label/sector: keep columns through export; add discovery once item 1
   above is agreed; ``lc_bridge`` stays a thin caller.
5. Do not fail export solely because more than one time or photometry
   column is present.

### Out of scope

- Ticket 13 §8 structural validation (finite photometry, censored cells).
- Ticket 12 PhotCal conversion readiness.
- Renaming every ingest path to a single global time column name on the
  product (rejected in Ticket 12 Phase 0).

### Phases

#### Phase 0 — Agree policy (discussion)

Export philosophy is **locked** (see above). Remainder: label discovery,
non-VO multi-column names, optional JD→MJD value remap, retire legacy writer
renames. Then write the policy into ``io_contract`` + README.

#### Phase 1 — VOTable export / writer — **Done**

``write_vo_lightcurve`` and ``_table_for_votable_codec`` keep column names
and extra columns. Absolute JD time columns are written as MJD with TIMESYS
when ``JD0`` is zero. Existing UCDs are written through. No export-time
schema gate.

#### Phase 2 — Label discovery, non-VO names, bridge — **Done**

``get_label_colnames`` (UCD ``meta.code`` / ``meta.id``, else leftmost
non-science column). CSV / ``.dat`` / ECSV export renames main-role columns
to ``jd`` / ``mag`` / ``flux`` / ``*_err``, numbering repeats as ``mag-1``.
``volc_to_curvedash`` uses ``get_label_colnames``. Discovery does **not**
write a label UCD onto the column.

#### Phase 3 — No strong validation on export — **Done**

VOTable export no longer refuses a missing filter identifier. The
``filterIdentifier`` PARAM is omitted when the product has none. Host
``build_votable_kwargs_from_metadata`` no longer raises for that case.

#### Phase 4 — Store a label-role UCD at ingest — **Done**

``assign_label_column_ucd`` runs at the end of non-VO heuristics and after
VOTable promotion. The designated label column receives ``meta.id`` when it
has no ``meta.code`` / ``meta.id`` UCD. The column name is unchanged. An
existing label-role UCD is kept.

#### Phase 5 — VOTable export of the label column — **Done**

``volc_to_curvedash`` stores ``label_column_name`` and ``label_column_ucd``.
Export writes that name (not a forced ``label``) and that UCD. The working
``CurveDash`` column stays ``label``.

### Agent checklist

- [x] Phase 0 policy written (``io_contract`` §8 + README pointer).
- [x] VOTable export preserves VO-annotated column names; value-only time remap where required.
- [x] ``get_label_colnames`` covers per-epoch label/sector columns.
- [x] Tests for label UCD, non-science fallback, and ``mag-1`` / ``mag-2`` CSV names.

### Status

**Open.** Phases 0–5 **done**.

---

## Ticket 15 — Calibration stays correct when a page changes the light curve

**Package:** ``skvo_veb`` pages that transform a loaded curve (GP for O-C,
Lightcurve Processor, and any later page that rewrites photometry).

**Related:** Ticket 7 (photcal coherence), Ticket 12 (conversion readiness;
does not cover this). Cleaning points (drop rows, interval trim) is out of
scope: the calibration of the remaining points does not change.

### Goal

Every operation that changes the light curve, other than cleaning, must
update photometric calibration to match the new numbers, or refuse to run
until the user has set that calibration. The same curve must not be treated
as calibrated on one page and broken on the next.

### Why this ticket exists

GP upload already warns when it fills missing zero points
(``reconcile_photcal_dict`` → ``gp-lc-photcal-alert``). The flux fit then
calls ``gp.flux.resolve_gp_photcal``, which can fill calibration again and
write the warning only to the log. That second fill is a sign that a page
tool changed the curve (or its units) without a matching calibration
update. Ticket 12 only requires the GP page to **show** a warning whenever
it touches calibration. This ticket is the work that stops the calibration
going stale in the first place.

### Locked direction (when asked to code)

1. List every page action that rewrites time or photometry (detrend, fold,
   normalise, domain view, manual edit). Cleaning is excluded.
2. For each action, record what must happen to ``metadata['photcal']`` and
   ``flux_unit`` (scale zero points with the data, clear them, or block).
3. One shared updater. Pages must not each invent a private repair.
4. If the updater changes calibration, the page shows the warning. A log
   line is not enough.

### Out of scope

- Ticket 12 conversion validator, constructor defaults, and the library
  inspect.
- Inventing zero points inside ``flux_to_mag`` / ``mag_to_flux``.
- Row cleaning and interval trimming.

### Agent checklist

- [ ] Inventory of curve-changing actions and the calibration each one needs.
- [ ] Shared updater; GP flux fit no longer repairs calibration in the log.
- [ ] UI warning whenever that updater writes.
- [ ] No code until the developer says go after the inventory is agreed.

### Status

**Open.** Inventory first. No code.
