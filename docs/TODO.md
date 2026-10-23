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
| 15 | Calibration stays correct when a page changes the light curve | Open |
| 19 | TESS photcal: mag column plus absolute flux (Jy) on VOTable export | Open |
| 20 | TESS search Exptime: ghelp for cadence vs CRM effective time | Open |
| 22 | TESS page: use the ``lc_discovery`` issued VOTable; column choice by role; no invented values | Open |
| 29 | Help popovers and UI consistency on the TESS pages (host app) | Open (backend B1 to B12 done; UI phases T2 to T5 on hold) |

## Done

| ID | Title | Status |
|----|-------|--------|
| 18 | TESS archive: honest retrieve errors, generic HLSP read, TARS profile | Done (Phases 1 to 3) |
| 16 | TESS cutout: lock shared Lightkurve TPF downloads (no concurrent clobber) | Done (SPOC TPF and FFI) |
| 21 | Export original TESS pipeline light-curve FITS from the server cache | Done |
| 17 | TESS archive: remove all stitching from ``/tess_lc`` | Done |
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

---

## Ticket 16 — TESS cutout: lock shared Lightkurve TPF downloads (no concurrent clobber)

**Page:** TESS cutout (`/tess`). Same race applies to any other page that
calls Lightkurve ``SearchResult.download()`` into the shared
``~/.lightkurve/cache/mastDownload`` tree (production:
``/var/www/.lightkurve/cache``).

**Related:** `skvo_veb/utils/tess_processor.py`
(``download_selected_pixel`` SPOC TPF branch),
`skvo_veb/pages/tess_cutout.py` (``download_sector``),
`skvo_veb/utils/lightkurve_cache.py`, Lightkurve
``search.SearchResult._download_one``.

### Goal

Two browser tabs (or two users) retrieving the **same** SPOC TPF at the
same time must not corrupt the shared cache file. The second waiter should
block until the first download has finished, then **open the complete
file**, not start a second MAST write into the same path.

### Why this ticket exists

Lightkurve treats ``os.path.exists(path)`` as a cache hit and skips MAST.
Astroquery creates the FITS path as soon as the download starts and
streams into it. A second worker therefore opens a half-written TPF:
the header is valid, HDU 1 (PIXELS) is too short, NumPy raises
``TypeError: buffer is too small for requested array``, and Lightkurve
wraps that as “file may be corrupt due to an interrupted download”.

Fast-cadence TPFs make this easy to hit (large, slow). The cutout page’s
purge-and-retry on ``LightkurveError`` can **delete the file the other
worker is still writing**, which makes the race worse.

### Locked direction (when asked to code)

Use **one lock per product** plus **atomic publish**. Do not give each
session its own cache directory (that fights the shared-archive-cache
rule).

1. **Lock** keyed by ``obs_id`` / product filename (POSIX ``flock`` beside
   the FITS, or equivalent). The second request waits and then reads.
   It does not call MAST while the lock is held by a writer.
2. **Download to a temp name**; ``os.rename`` onto the Lightkurve final
   path only after ``TessTargetPixelFile`` has opened successfully.
   ``exists(final_path)`` then means complete.
3. **Purge/retry only under the lock**, and only the temp or a file this
   worker produced. Never unlink a path another worker is filling.
4. Stale locks: prefer ``flock`` so the lock dies with the process. If a
   sidecar lock is used, expire it when the holder is gone, then
   re-download into a temp file.
5. TESScut FFI uses a different cache layout; apply the same pattern if
   two tabs can retrieve the same cutout.

Fail fast if the published file still cannot be opened. Do not invent
photometry or silently ignore the error.

### Out of scope

- Changing Lightkurve itself.
- Per-tab Lightkurve cache directories.
- UI-only “already retrieving” without a server-side lock (Dash state is
  per session and cannot see the other tab).

### Agent checklist

- [ ] No code until the developer says go.
- [ ] SPOC TPF path in ``download_selected_pixel``: lock + temp + rename.
- [ ] Purge-and-retry no longer deletes another worker’s in-flight file.
- [ ] Decide whether TESScut FFI needs the same lock in this ticket.
- [ ] Document the behaviour (timeout / wait) in British English if a
      user-facing wait message is added.

### Status

**Done 2026-10-17 (under Ticket 29, B9 and B12).** `lightkurve_cache.fetch_spoc_tpf` (SPOC TPF) and
`fetch_tesscut_pixel_file` (FFI) use a per-product `flock`, download into a private temp
folder, open the file there, then publish with `os.replace`. The unreadable-file purge runs only
under the lock. Not covered: other code that calls Lightkurve `download()` directly on the
shared tree. Live MAST check not run.

---

## Ticket 17 — TESS archive: remove all stitching from ``/tess_lc``

**Page:** TESS Lightcurve Tool (`/tess_lc`, `skvo_veb/pages/lightcurve_tess_srv.py`).

**Related:** `skvo_veb/utils/tess_lc_builder.py`
(``create_lc_from_selected_rows``),
`skvo_veb/utils/mission_config/tess.py` (``resolve_photcal(..., stitched=)``,
magnitude refusal, export provenance),
`skvo_veb/utils/lc_bridge.py` (``stitched`` metadata on ingest/export),
`skvo_veb/tests/test_tess_photcal.py`,
`skvo_veb/tests/volightcurve/test_tess_export.py`,
[lightcurve_data_flow.md](lightcurve_data_flow.md), [tess.md](tess.md) §1.3.

### Goal

The archive page **does not stitch**. There is no Stitch switch and there
must be **no** Lightkurve ``LightCurveCollection.stitch()`` path, no
``metadata['stitched']`` written by retrieve/rePlot, and no remaining
``if stitch`` / relative-flux branch on this page.

Retrieve one search row (table is already ``singleRow``). Keep native
pipeline flux and photcal (SPOC e⁻ s⁻¹, QLP/TARS ``TESSMAG``, etc.).

### Why the old ticket was rewritten

The previous goal (calibrated stitch modes: relative flux / calibrated
flux / calibrated magnitude) is **cancelled**. We will not add stitch
options. Cleanup only.

### Done

- Plot-tab **Stitch curves** switch and Flux-options collapse (earlier).
- ``tess_lc_builder``: no ``.stitch()``, no ``stitch`` argument, no
  ``relative flux`` unit, no ``lcd.metadata['stitched']``.
- Archive builder calls ``resolve_photcal(authors, tess_mag=...)`` only.
- ``lc_bridge`` / ``tess.py`` still ingest old ``stitched=true`` VOTables
  and refuse magnitude without inventing zero points.
- Docs: ``lightcurve_data_flow.md``, ``tess.md`` §1.3.

### Agent checklist

- [x] Delete ``LightCurveCollection.stitch()`` and all ``stitch`` arguments
      from the archive retrieve/rePlot path.
- [x] Stop writing ``metadata['stitched']`` from ``/tess_lc``.
- [x] Update photcal/export tests and docs; do not add stitch-mode tests.

### Status

**Done.** Product: no stitch on ``/tess_lc``.

---

## Ticket 18 — TESS archive: honest retrieve errors, generic HLSP read, TARS profile

**Page:** TESS Lightcurve Tool (`/tess_lc`).

**Related:** `skvo_veb/utils/lightkurve_cache.py`,
`skvo_veb/utils/tess_lc_builder.py`,
`skvo_veb/utils/tess_flux_column_registry.py`,
`skvo_veb/utils/mission_config/tess.py` (``resolve_photcal``),
Lightkurve ``io.detect`` / ``io.generic`` / ``SearchResult.download``.

### Goal

Unknown HLSPs (first seen: **TARS**) must not be reported as a corrupt
cache file. Retrieve, flux radio, and photcal must not pretend there is a
single “default pipeline profile”. Support is three explicit steps.

### Why this ticket exists

TARS (TESS All-Sky Rotation Survey) FITS is a small ``TIME`` + ``FLUX``
table: no ``ORIGIN`` / ``CREATOR``, no ``QUALITY``, no flux error.
Lightkurve types it as **``generic``**. ``SearchResult.download()`` always
passes ``quality_bitmask="default"``. The generic reader rejects that
keyword (``TypeError``). Lightkurve wraps it as “file may be corrupt due
to an interrupted download”. Our purge-and-retry deletes a **complete**
file and fails again.

There is no named default profile. Three fallbacks disagree:

- Reader: Lightkurve ``generic``.
- Flux radio: ``FLUX_COLUMN_REGISTRY`` has **no** TARS entry (hard fail).
- Photcal: ``resolve_photcal`` silently returns passband-only.

### Phases (one at a time; do not skip)

#### Phase 1 — Honest message; purge only truncated FITS — **done**

Classify Lightkurve retrieve failures from the **exception cause chain**,
not from Lightkurve’s canned “interrupted download” sentence (that text
is attached to every ``read()`` failure).

- Truncated / ``buffer is too small``: purge cache and retry (existing).
- Unsupported reader / unexpected keyword / generic layout: **do not
  purge**. British English message: the product is not a recognised TESS
  pipeline light curve; the file is not treated as corrupt.
- Other errors: show the inner exception; strip the canned corrupt
  sentence.

TARS still does not plot after this phase. Fail fast; no invented
photometry.

#### Phase 2 — Stable generic read — **done**

Archive retrieve no longer uses ``SearchResult.download()`` for mastDownload
light curves (that call always passes ``quality_bitmask``). It caches or
fetches the FITS, then ``open_lightcurve_product``:

- Typed Kepler/TESS products: ``read(path, quality_bitmask='default')``.
- Generic HLSPs: ``read(path)`` only when HDU 1 has ``TIME`` and ``FLUX``.
- Missing those columns: Phase 1 unsupported-product message; no purge.

MAST ``author`` is copied onto the Lightkurve object when Lightkurve left
``AUTHOR`` empty. Do not invent ``QUALITY``, ``PDCSAP_FLUX``, or flux
errors. Flux radio / photcal for TARS are Phase 3.

#### Phase 3 — TARS profile — **done**

Adopted QLP-like photometry: ``TIME`` + dimensionless ``FLUX``,
``PhotCal`` zero-point magnitude from ``TESSMAG`` (``ZP_FLUX=1``,
dimensionless). Period from header ``PER1`` (days). Epoch from
``TMIN1`` (BTJD) stored as absolute JD (``TMIN1 + 2457000``) on
``CurveDash``; the TESS archive ``Epoch-{2400000.5}`` field shows MJD.
Retrieve fills those fold controls. No invented flux errors.

### Locked constraints

1. No silent photcal or flux-column invention.
2. British English in user-facing strings.
3. Do not change Lightkurve itself.
4. Ticket 16 (TPF lock) is a different race; do not merge.

### Agent checklist

- [x] Phase 1: classify failures; no purge on unsupported generic read.
- [x] Phase 1 tests for truncated vs unsupported vs stripped canned text.
- [x] Phase 2: generic retrieve without ``quality_bitmask``.
- [x] Phase 3: TARS registry + QLP-like photcal + PER1/TMIN1 (MJD in UI).

### Status

**Done.** Phases 1–3 implemented.

---

## Ticket 19 — TESS photcal: mag column plus absolute flux (Jy) on VOTable export

**Pages:** TESS Lightcurve Tool (`/tess_lc`) and TESS cutout (`/tess_cutout`)
exports; any other TESS curve that already carries instrument or TESSMAG
photcal.

**Related:** [tess.md](tess.md) §1, `skvo_veb/utils/mission_config/tess.py`,
sibling ``volightcurve`` ``PhotCal`` / VOTable photcal GROUP, Ticket 7
(photcal policy; do not invent zeropoints), Ticket 12 (domain conversion
validation), Ticket 17 (no stitch on ``/tess_lc`` — separate).

### Goal

Improve TESS light-curve photometric calibration so a **magnitude** column
can also carry **absolute flux** calibration (jansky).

The intended **exported VOTable** (when we later agree how to represent it)
would present **two photometric columns**, each with its own linked photcal:

1. **Flux** in **electron s⁻¹**, with photcal that converts that flux into
   **TESS magnitude** (the instrument / pipeline pair we already document:
   20.44 at 1 electron s⁻¹, or TESSMAG for normalised pipelines, as
   applicable).
2. **Magnitude**, with a **second** photcal that converts that magnitude
   into **absolute flux in jansky**.

### Why this ticket exists

Today TESS curves are stored and switched in one photometric domain at a
time. Photcal on the curve is the pair that supports **flux ↔ TESS mag**.
Export follows that single group. There is **no** agreed product yet for
keeping native electron s⁻¹ **and** a mag column whose photcal opens a
path to **Jy**.

This ticket records that product wish. It does **not** choose a data model
(one vs two ``PhotCal`` objects, which column is native, AB vs Vega, how
GROUP ``ref``s attach in VOTable, whether the in-app Magnitude switch
changes).

### Locked for now

1. **No design and no code** until the developer asks to open the topic.
2. Do not invent a jansky zeropoint, a second photcal helper, or a dual-column
   export layout in passing while working on other TESS tickets.
3. Do not treat this as a silent extension of Ticket 7 Phase 2 (calibration
   editor) or Ticket 17 (stitch removal).
4. Fail-fast / no silent fallbacks still apply when this is eventually
   specified.

### Out of scope until specified

- Choosing constants, references, or formulae for TESS mag → Jy.
- Changing the in-app flux/magnitude switch behaviour.
- Non-TESS missions.

### Agent checklist

- [ ] No implementation until asked.
- [ ] When opened: discuss representation and export contract first; then
      code only what was agreed.

### Status

**Open.** Backlog only. Discussion later.

---

## Ticket 20 — TESS search Exptime: ghelp for cadence vs CRM effective time

**Pages:** TESS cutout (`/tess_cutout`) search results table first; TESS
archive (`/tess_lc`) if the same Exptime column is shown.

**Related:** [tess.md](tess.md) §3.

### Goal

Put the documented meaning of **Exptime** into the in-app **ghelp** (`?`
popover): the column is MAST/Lightkurve **cadence** (`t_exptime` /
`TIMEDEL`), not CRM-shortened photon time (`NREADOUT * INT_TIME`).

### Locked for now

1. **No UI until asked.** Do not invent popover placement or rewrite the
   column header in passing.
2. Help copy must follow [tess.md](tess.md) §3; do not invent a second
   explanation.
3. Do not change what the table stores (still Lightkurve `exptime`).

### Agent checklist

- [ ] No implementation until asked.
- [ ] When opened: reuse the page `?` / ghelp pattern; British English.

### Status

**Open.** Documentation is in ``docs/tess.md`` §3. Ghelp later.

---

## Ticket 21 — Export original TESS pipeline light-curve FITS from the server cache

**Pages:** TESS Lightcurve Tool (`/tess_lc`) first. Cutout page is **not**
in scope as a download target (see below).

**Related:** `skvo_veb/utils/lightkurve_cache.py`, `skvo_veb/utils/tess_cache.py`
(``save_lc_fits`` / Lightkurve mastDownload), existing CurveDash export
(`export_curvedash` — VOTable / ASCII of the **working** curve, not the
archive FITS).

### Goal

Let an **advanced** in-app user obtain the **original pipeline light-curve
FITS** that we already hold in the TESS server cache after Retrieve. Today
those files sit on the server and are unreachable from the UI. Existing
export is our processed `CurveDash` product, not the MAST/Lightkurve FITS.

### Why this ticket exists

Retrieve already downloads (or cache-hits) the ready-made light-curve FITS.
That file is the archival product (SPOC, QLP, TARS, …) with native columns
and headers. Advanced users may want that FITS on their own machine. The
browser session never offers it.

### Doubtful extra: cutout FITS download

**Do not** add a control that sends FFI/TPF **cutouts** to the user’s
computer. Pixel cubes are large, are not “ready-made light curves”, and
are not a product we intend to ship this way.

Recorded only so it is not “discovered” later as an obvious sibling
feature. Flag: **doubtfully reasonable**. Leave it closed unless the
developer explicitly reopens it.

### Locked (shipped)

1. Existing **Download** is the working ``CurveDash`` product (VOTable /
   ASCII). **Download MAST FITS** is an extra archive copy.
2. No public URL, no zip, no FITS bytes in the session cache (pointer
   only: ``obs_collection``, ``obs_id``, ``product_filename``).
3. Missing or unreadable shared Lightkurve/MAST file: ask the user to
   retrieve again. Cutout pixel FITS stay out of scope.

### Agent checklist

- [x] Discussed: original MAST FITS vs issued VO product; cutout out of
      scope.
- [x] **Download MAST FITS** on ``/tess_lc`` Plot tab; original MAST
      filename; pointer in session cache; fail-fast if the FITS is gone.

### Status

**Done.** Advanced users can download the pipeline FITS from the shared
MAST cache after Retrieve. Cutout FITS download remains closed.

---

## Ticket 22 — TESS page: use the ``lc_discovery`` issued VOTable; column choice by role; no invented values

**Page:** TESS Lightcurve Tool (`/tess_lc`, `skvo_veb/pages/lightcurve_tess_srv.py`).

**Related:** `skvo_veb/utils/tess_lc_builder.py`,
`skvo_veb/utils/tess_flux_column_registry.py`,
`skvo_veb/utils/mission_config/tess.py`,
`skvo_veb/utils/lightkurve_cache.py`, `skvo_veb/utils/lc_bridge.py`,
sibling package `lc_discovery`
(`providers/tess/{tess_fetch,fetch_metadata,columns}.py`,
`docs/providers/tess.md`), Tickets 17, 18, 19.

### Goal

The TESS page uses the **same approach as the Discovery TESS provider**:
the product is read once, issued as a calibrated VOTable with roles and
PhotCal read from the file, and the page only **chooses a column** from
that table. No second copy of the registry, no unit or PhotCal rules
derived from the author tag, no invented values.

### Why this ticket exists

Comparison of `/tess_lc` with the Discovery provider (agreed with the
developer):

1. **Hardcoded units by author.** `storage_flux_unit_for_selection`
   returns `electron s-1` for any unknown pipeline and for background,
   and hardcodes `{"QLP", "TGLC", "TARS"}` as dimensionless.
   `archive_flux_unit_for_pipeline` forces QLP/TARS dimensionless and
   turns ppm into ``None``.
2. **PhotCal by author name.** `resolve_photcal` (`is_spoc_pipeline`,
   `uses_tessmag_catalog_photcal`) ignores the unit in the file.
3. **Invented data.** `flux_err` is filled with NaN when the product has
   no error column. `sector = -1` is substituted when the sector is
   missing. (The ``corr_flux`` error formula
   ``corr_flux * raw_flux_err / raw_flux`` was removed from
   ``apply_flux_column_selection``; ``CORR_FLUX`` now falls into the NaN
   branch until this ticket removes that branch too.)
4. **Unknown pipelines are unreachable.** `list_available_photometry_specs`
   returns ``[]`` for an author outside the registry, so only "Default"
   is offered.
5. **Duplicate retrieval code.** The page has its own search, cache and
   generic-HLSP reader (`open_lightcurve_product`, Ticket 18). The
   plugin has the same fix (`_download_generic_product`). Two
   implementations will drift.
6. **Time assumed.** `TESS_TIMEORIGIN` is applied without checking the
   Lightkurve time format and scale (the plugin checks BTJD / TDB).
7. **Registry copied.** The plugin's `columns.py` is documented as a copy
   of the host registry.
8. **Leftover stitching traces.** Ticket 17 is Done, but traces remain:
   `create_lc_from_selected_rows` still concatenates several rows
   (the table is ``singleRow``, so only one is ever used); the
   ``stitched`` flag is still read and written in `lc_bridge.py`
   (ingest, export, `_is_stitched_lightcurve`, title prefix
   ``Stitched curve``); `resolve_photcal(..., stitched=)` and the
   "stitched" magnitude refusal in `mission_config/tess.py`; export
   provenance text about stitching; tests in `test_tess_photcal.py` and
   `volightcurve/test_tess_export.py`. Ticket 17 kept legacy ingest on
   purpose; this ticket **removes it** on the developer's instruction
   ("no stitching, no tracks").

### Decisions (agreed with the developer)

1. The page consumes the plugin's issued VOTable (single source for
   search, download, TARS handling, time check, roles, PhotCal).
2. The page offers, as flux choices, the columns whose role in the
   VOTable is **flux**, **mag** or **background**. Columns without a
   role are not selectable.
3. **Background** can be selected as the plotted series
   ("background light curve"). The user selects it explicitly; it is never
   chosen by default.
4. Default choice is not made in the plugin. The page picks the default
   from the VOTable roles (the flux column Lightkurve declares through
   ``FLUX_ORIGIN``), not from a name table.
5. Units, errors and zero points come from the issued VOTable. A missing
   error column stays absent: no NaN column, no formula. How the plot and
   export show "no error" is part of Phase 3.
6. PhotCal is read from the VOTable PhotCal group of the chosen column.
   It is not recomputed from the author.
7. **No stitching, no traces**: one product per Retrieve; the
   ``stitched`` flag, parameter, branches, texts and tests are deleted.
   Old VOTables that carry ``stitched=true`` are not specially handled.
8. User-facing strings: British English. No hardcoded defaults for
   units, errors or sector.

### Phases (one at a time; do not skip)

#### Phase 0 — Contract in docs — **done**

Update `tess.md` and `lightcurve_data_flow.md`: the page works from the
issued VOTable and chooses columns by role. Link to `lc_discovery`
`docs/providers/tess.md`.

#### Phase 1 — Remove stitching traces — **done**

Delete every item in "Why" point 8. One row per Retrieve. Remove or
rewrite the tests. No behaviour change otherwise. Run the full
`skvo_veb/tests`.

#### Phase 2 — Retrieve through the plugin — **REVERTED on the page (developer decision)**

**Done instead (page-local):** unknown pipelines list every flux-like column (name contains `flux`, `<name>_err` paired); units come from the file column (no author guess); a missing sector stays empty (no `sector=-1`); a time system other than BTJD/TDB logs a warning and shows it in the page alert (absolute JD from astropy `Time`). NaN `flux_err` stays (no error bars). Author-based PhotCal (`resolve_photcal`) and reading the file on row selection are NOT changed yet.

**Decision.** The `/tess_lc` page does not use the `lc_discovery` plugin. The page was restored to the earlier Lightkurve-object code (snapshot `tmp/arj`), and only the agreed stitching removal was re-applied. The plugin-side work below stays in `lc_discovery` for Discovery. The XML round trip made series switches slow; do not reintroduce it.


**What was built, and where it differs from the plan below.**

- Plugin: new `providers/tess/archive_cache.py` (path, hit, astroquery
  miss, classification, one purge and retry only for truncated FITS,
  generic HLSP opened only with `TIME` and `FLUX`, British English
  `ValueError` messages) and `tess_fetch.download_archive_product` /
  `redownload_archive_product`. The `mast_*` TABLE PARAMs are written by
  `votable_from_lightcurve(mast_pointer=...)`. Tests:
  `lc_discovery/tests/test_tess_archive_cache.py`.
- Deviation 1: the page does **not** yet parse the issued VOTable. Until
  Phase 3 it builds `CurveDash` from the Lightkurve object that the
  plugin returns, and takes the pointer from the plugin return value
  (stored in `CurveDash.metadata["mast_fits_pointer"]`). The VOTable
  PARAMs are in place for Phase 3. The page does not build an `lc_key`.
- Deviation 2: the page passes its own one-row search result to the
  plugin, so no second MAST search happens (the plan only needed the
  identity). Without a search store the retrieve now fails fast; the old
  own-search branch and its `sector=-1` substitute are deleted.
- `skvo_veb/utils/lightkurve_cache.py` now only serves the original FITS
  (Ticket 21) and resolves the path through the plugin
  (`archive_cache.pointer_path`). Its old tests are replaced by four
  tests of that reader; the moved tests live in the plugin suite.
- Not done: a server-side `flask_caching` layer keyed by TIC, sector,
  author, exptime. The shared Lightkurve file cache is the cache.
- Verified: plugin tests 29 passed; `skvo_veb/tests` 599 passed and the
  same 5 failures as before this work. No live MAST retrieve or UI click
  test was run.

Original plan:

Replace the page's own search / download / generic-HLSP reading with the
plugin fetch (cached through the shared server cache; cache key from TIC,
sector, author, exptime).

**Decision (Ticket 21 pointer): the pointer travels inside the issued
VOTable.**

- The plugin writes three TABLE PARAMs in the issued VOTable, taken from
  the same one-row Lightkurve search result it downloads:
  `mast_obs_collection`, `mast_obs_id`, `mast_product_filename`
  (the same fields Ticket 21 stores today).
- The page calls the plugin with the product identity it already has from
  its own search table (TIC, sector, author, exptime; the same payload as
  `lc_key`), reads the three PARAMs from the returned VOTable, and stores
  the pointer in the session cache exactly as
  `remember_retrieved_mast_fits_pointer` does now.
- "Download MAST FITS" is unchanged: it resolves
  `<lightkurve cache>/mastDownload/<obs_collection>/<obs_id>/<product_filename>`
  and fails fast when the file is gone.
- Plugin API stays `fetch_lightcurve(lc_key) -> bytes`; no new return
  type. The page builds the `lc_key` with the plugin's own encoder.
- Both sides use Lightkurve's default cache directory
  (`lightkurve.config.get_cache_dir()`). TARS is downloaded by the plugin
  into the same directory layout, so the pointer resolves there as well.
- Rejected: a second MAST query on the page to recompute the pointer
  (extra request, can drift), and a richer return type from the plugin
  (breaks the shared provider contract).

**Decision (cache maintenance): it moves into the plugin.** The plugin
owns everything about getting a readable FITS from the shared Lightkurve
cache; the page keeps none of it. The plugin package does not import
`skvo_veb` and raises `ValueError` / `RuntimeError`, not `PipeException`;
the page turns those into its own alerts.

Moves from `skvo_veb/utils/lightkurve_cache.py` into
`lc_discovery/providers/tess/tess_fetch.py` (or a sibling module in the
same provider):

- Expected-path lookup and cache hit
  (`<cache>/mastDownload/<obs_collection>/<obs_id>/<productFilename>`),
  and the astroquery download on a miss (`ensure_mast_product_fits`).
  This replaces the plugin's current `_download_generic_product`, so the
  plugin has one download path for all authors.
- Failure classification from the exception cause chain
  (`truncated_cache`, `unsupported_product`, `other`) and the canned
  "interrupted download" sentence stripping.
- Purge and one re-download **only** for a truncated FITS. Never purge
  for an unsupported or generic-reader failure.
- Opening: typed products with `quality_bitmask='default'`; generic HLSPs
  (TARS) with `read(path)` only when HDU 1 has `TIME` and `FLUX`.
- Honest British English error messages for those classes.

Stays or is deleted in the page:

- `mast_pipeline_fits_pointer`, `_path_from_mast_fits_pointer` and the
  FITS download resolver stay (Ticket 21; they only read the pointer and
  the file).
- The rest of `lightkurve_cache.py` (search-row download with recovery,
  classification, open) is deleted after the plugin takes over. Move the
  related tests (`test_lightkurve_cache.py`) to the plugin test suite.

Locked: one retry at most; no silent fallback to another author or
product; the pointer PARAMs in the VOTable are written from the same
search row the plugin downloaded.

#### Phase 3 — Choose the column from VOTable roles — **REVERTED on the page (developer decision)**

The Series radio, `tess_series.py` and the VOTable path were removed from the page. The registry, the NaN error fill, the `sector=-1` substitute and the author-based units are back, awaiting a decision. Background selection on the page needs a new design.


**What was built.**

- Plugin: table PARAM `flux_origin`; a background error now shares the
  background PhotCal group.
- `volightcurve`: a column with a declared UCD (for example
  `instr.background`) is no longer picked as the label column and its UCD
  is no longer overwritten with `meta.id`. This bug made the background
  column the row label.
- Page: new `utils/tess_series.py` (roles by UCD, default from
  `flux_origin`), `lc_bridge.paired_error_column` and
  `volc_to_curvedash(phot_col=)`, `tess_lc_builder.curvedash_from_issued_votable`.
  A "Series" radio on the Plot tab lists the columns; rePlot uses it.
  Period and epoch (TARS) come from the table PARAMs.
- Deleted: `resolve_photcal`, `archive_flux_unit_for_pipeline`,
  `serialise_lightkurve_flux_unit`, `is_*_pipeline`, the NaN error fill,
  the `sector=-1` substitute, `flux_radio_options_for_rows`, and the whole
  `tess_flux_column_registry.py` with its test (this covers Phase 4's
  deletion; see Phase 4). Tests that needed author-based PhotCal use
  `tests/tess_photcal_fixtures.py`.
- Verified with the real cached SPOC files (default `pdcsap_flux`, its
  error, `electron s-1`, options `pdcsap_flux`, `sap_flux`, `sap_bkg`);
  `skvo_veb/tests` 582 passed, same 5 failures as before; plugin tests pass.
  No browser click-through was done.

**Open points to decide.**

- "No error" is shown in the radio label, but `CurveDash` still stores a
  missing error as zeros (flux errors `<= 0` become NaN). Making it truly
  absent needs a `CurveDash` change that also touches plots, export and
  GP code.
- When a product has several flux columns and declares no
  `FLUX_ORIGIN`, the retrieve fails with a message listing the columns,
  because the radio exists only after a retrieve.

Original plan:

- Build the flux radio from the VOTable: flux, mag, and background
  columns, labelled with the file's column names.
- Build the `CurveDash` from the chosen column, its error column (if any,
  by the shared PhotCal group) and its unit.
- Delete `storage_flux_unit_for_selection`,
  `archive_flux_unit_for_pipeline`, the NaN error fill, the `-1` sector,
  and the author-based `resolve_photcal` branches.
- Show "no error" explicitly for columns without one.

#### Phase 4 — Remove the duplicate registry — **not done (registry restored)**

Done: `tess_flux_column_registry.py` and its test are deleted;
`parse_sector_from_mission_label` moved to `tess_lc_search.py`. Left:
the TESS-specific constants and comments in `mission_config/tess.py`
that no code uses, the plugin `columns.py` header, and the older docs
(`tess_background_lightkurve.md`, `scripts/tess_*registry.py`).

Original plan:

Delete `tess_flux_column_registry.py` and the TESS-specific parts of
`mission_config/tess.py` once nothing imports them. Keep only what the
cutout page still needs (check `tess_cutout.py` before deleting).
Update the plugin `columns.py` header (no longer "copied from host").

### Locked constraints

1. No silent defaults: no invented unit, error, flux column, or sector.
2. The choice of the plotted column is the page's job. The plugin issues
   everything it understood and never chooses.
3. Do not change Lightkurve itself.
4. Ticket 16 (TPF lock) is a different race; do not merge.
5. The cutout page (`/tess_cutout`) is out of scope except where it still
   imports TESS helpers that Phase 4 would delete.

### Agent checklist

- [x] ``corr_flux`` error formula removed from
      ``apply_flux_column_selection``.
- [x] Phase 0: docs (`tess.md`, `lightcurve_data_flow.md` describe the target contract; old registry marked *(current)*).
- [x] Phase 1: remove stitching traces; tests green (done: builder takes exactly one row, `stitched` parameter/flag/branches/text and `_is_stitched_lightcurve`, `_strip_zero_points_from_photcal`, `merge_flux_radio_options`, `effective_flux_method_for_selection` deleted; stitching tests removed).
- [ ] Phase 2: reverted on the page (no plugin on /tess_lc).
- [ ] Phase 3 (reverted; to be redesigned with the developer): column choice by VOTable roles; background option;
      no invented values.
- [ ] Phase 4: delete the duplicate registry and author-based rules.

### Status

**Open.** Plan agreed; implement phase by phase when the developer asks.


---

## Ticket 23 — lc_discovery (SEPARATE PACKAGE): agent-ready public API, discovery helpers, plot recipe

**Applies to the separate package** `/home/voz/projects/UPJS/lc_discovery`, **not** to this
application. Recorded here because this is the developer's task list. Nothing in `skvo_veb`
is to change for it, except where the host later adopts a new call.

**Think a lot before implementing each phase.** Every phase changes the public contract
that agents and applications depend on. Discuss the design, the names and the failure
behaviour with the developer first. Do not start a phase without an explicit request.
No silent fallbacks; no invented values.

### Why this ticket exists

A role-play review (a user who runs no code, an agent with empty context that has
installed the package and read the skills and docs) with three questions: which
sources exist; what exists for "AA And" with points in the first half of 2020 and in
which filters; retrieve one curve and plot it. Findings:

1. **Sources.** `list_missions()` gives only `mission_id`, `display_name`,
   `export_profile` and capability flags. No description, coverage, bands or data
   kind. The human summary is in `docs/providers/*.md`, which the skill does not
   point to.
2. **Object to ids.** No public call resolves a name to coordinates and Simbad
   identifiers. `archive_id_from_identifiers` needs that list, and the skill does
   not say where it comes from.
3. **Time window.** Only `gaia_dr3_veb`, `ogle_ocvs`, `personal_ts`, `tess`,
   `upjs_ts` accept it. For `asassn`, `gaia_dr3_aip`, `gaia_dr3_ari`,
   `panstarrs1_dr2`, `ztf_dr24` the call raises; coverage must be read from
   optional `t_min` / `t_max`, which can be empty (then it is known only after
   `fetch`). Nothing helps an agent combine these cases or report "unknown".
4. **Many missions.** Each caller writes its own loop over missions and search kinds.
5. **Reading the product.** `Table.read` keeps UCDs in `col.meta['ucd']`
   but drops `TIMESYS` (the time column is only `d`, origin 2400000.5 is lost) and
   the PhotCal groups. The skill shows OGLE column names, not UCD-based selection.
   Several photometry columns (SAP, KSPSAP, background) have no selection rule.
6. **Stale sample.** `auxiliary/lc_discovery_test/data/aa_and_tess_sector16/*.vot`
   labels background `phot.flux;obs.background`; the plugin and `docs/providers/tess.md`
   say `instr.background`. Regenerate it.

### Phases (each needs a design discussion first)

- [x] **Phase A: mission descriptor (done).** `description` is a mandatory text on every
      provider, returned by `list_missions()`. Template in
      `docs/adding_a_lightcurve_provider.md` section 2.1 (what it is, where from,
      bands, time coverage, sky, id lookup, reference; free text, `TO CONFIRM` for
      unchecked facts).
- [x] **Phase B: object resolution (done, as advice only).** Decision: no algorithm and
      no Simbad client in the package for now (an agent can query Simbad itself).
      The package states what a naive agent cannot guess: per mission, the "Id lookup"
      line in `description` (which id, an example, which Simbad identifier to take, or
      "Simbad does not list it, use a cone search"). The skill `lc-discovery` has a
      "Finding an object" section with the advised order and a "Time windows" section
      (warn that some missions cannot filter by time at search; offer them as possible
      sources only; fetching each curve to check is slow, never for a long list).
      Postponed: a Simbad resolver in the package.
- [x] **Phase C: multi-mission search (done, as a skill recipe only).** Decision: no
      `search_all(...)` for now. The skill `lc-discovery` section "Searching several
      missions" sets the default goal "return every light curve that could possibly
      contain at least one point in the window; better extra than missed", and rules:
      never drop a mission silently ("not supported" is not "no data"; tell the user
      and ask); pass the window only where the mission filters by time, mark the rest
      "unknown coverage" (possible sources); never fetch light curves in bulk to check
      (heavy traffic and time; ask the user); a failing mission does not stop the run
      but is reported with its message; report truncation from
      `discovery_may_be_truncated`; once Ticket 24 coverage exists, skip a mission only
      when its stated coverage explicitly excludes the request (say why), otherwise do
      not skip and warn. Includes a worked example. Postponed: a public `search_all`.
- [ ] **Phase D: reading and plotting recipe.** Decide between a skill recipe
      (select by UCD, take time from `TIMESYS` as an astropy `Time`, pair errors,
      state which column is plotted) and a public reader that returns the whole
      structure (time, series, errors, units, calibration), not a flat table.
      Open: rule for choosing among several flux columns.
      **Idea to describe in the skill (not implemented yet):** the simplest way to
      recognise column roles is by UCD (`col.meta['ucd']`), for example `time.*` for
      time, `phot.flux*` and `phot.mag*` for series, `stat.error` (with the matching
      series) for errors, `instr.background` or `phot.flux;obs.background` for
      background. The agent lists the flux and magnitude columns it found (name, UCD,
      unit) and asks the user to choose one to plot; it never picks silently when
      there are several. The chosen column and its unit are stated with the plot.
- [ ] **Phase E: housekeeping.** Regenerate the stale sample VOTable. Keep the
      skill's example in line with the real calls after each phase.

### Already done (not part of the phases)

- `purge_cache(lc_key)` and `supports_cache_purge` (TESS, Gaia AIP); TESS
  `force_refresh` now purges and downloads again.
- Host-specific text and names removed from the package docs and source;
  `catalog_row_to_aggrid_dict` renamed `catalog_row_to_indexed_dict`.
- Skills: worked example, errors section, local-cache rules.
- Time-window filter in `gaia_dr3_veb`, `upjs_ts`, `personal_ts`, `ogle_ocvs` now
  keeps products whose time span overlaps the window (`t_max > start`,
  `t_min < end`), not only those fully inside it (`t_min` / `t_max` are the start and
  end of the series). TESS already did. Docs, skill and test updated.
- `gaia_dr3_veb` description corrected: the search does apply time windows.

### Status

**Open.** Phases A, B and C done (see above). Phases D and E wait for the developer's
explicit request.

---

## Ticket 24 — lc_discovery (SEPARATE PACKAGE): space and time coverage attributes on every provider

**Applies to the separate package** `/home/voz/projects/UPJS/lc_discovery`, **not** to this
application. Recorded here because this is the developer's task list. Nothing in `skvo_veb`
is to change for it, except where the host later reads the new fields.

**Think a lot before implementing.** This changes the public `MissionDescriptor` that
`list_missions()` returns. Discuss names, types and missing-data behaviour with the
developer first. Do not start without an explicit request. No silent fallbacks; no
invented footprints or dates. Use `TO CONFIRM` until a bound is checked.

### Why this ticket exists

Ticket 23 Phase A added a free-text `description` (bands, time coverage, sky in prose).
That is enough for a human to read. An agent that must decide *before search* whether
a mission can possibly cover a requested sky position or time window still has to parse
English. The per-row catalogue fields `t_min` / `t_max` are only the start and end of
that one time series, and they exist only after a search (sometimes only after `fetch`).
They are not the mission's coverage.

### What to add (intent)

A **mandatory structured coverage attribute on every provider**, returned by
`list_missions()`, covering the archive or survey as a whole (not one product):
**space, time and spectrum** (with the waveband term). The free-text `description`
stays; it does not replace these attributes.

### Approach: follow the IVOA Registry model (decided 2026-10-16)

We follow the way the VO Registry describes coverage, on purpose: in the future
candidate providers will also be found through the Registry (and TAPRegExt), so the
package should speak the same model. References (read on 2026-10-16):

- **VODataService 1.2**, IVOA Recommendation 2021-11-02, section 3.2 "Coverage in Space,
  Time, and Spectrum", element `vs:Coverage`:
  <https://www.ivoa.net/documents/VODataService/20211102/REC-VODataService-1.2.html>
  - `spatial`: a MOC in the ASCII serialisation, ICRS; at least order 6 (about 1 deg);
    keep it to a few dozen kB; a finer MOC goes to a separate `footprint` URL. All sky
    is written `0/0-11` (example in the document).
  - `temporal`: one or more intervals, two MJD numbers each, TDB at the solar system
    barycentre; a union; authors pad the limits (the time resolution of the Registry is
    about 10 minutes). The NED example uses an arbitrary upper limit of 100000 for
    "ongoing acquisition".
  - `spectral`: intervals in joules (messenger energy), a union, solar system barycentre.
  - `waveband`: a term from the IVOA messenger vocabulary (Radio, Infrared, Optical, ...).
  - `regionOfRegard`: an angle in degrees by which a positional query is blurred.
  - `STCResourceProfile` is deprecated.
- **RegTAP 1.2**, IVOA Recommendation 2024-10-02, sections 8.15 to 8.17 (tables
  `rr.stc_spatial`, `rr.stc_temporal`, `rr.stc_spectral`) and the query example in
  section 10.13; time is compared with `ivo_interval_overlaps`, space with `CONTAINS` /
  `INTERSECTS` on the MOC (same overlap idea as our product time filter):
  <https://www.ivoa.net/documents/RegTAP/20241002/REC-RegTAP-1.2.html>
- **MOC 2.0**, IVOA Recommendation 2022-07-27 (the MOC and its ASCII serialisation):
  <https://www.ivoa.net/documents/MOC/index.html>

Decisions:

1. **Registry model.** Coverage entry with `spatial` (MOC string), `temporal`
   (MJD intervals, union), `spectral` (joules, union) and `waveband` (messenger term).
   `regionOfRegard`: **not included** (developer, 2026-10-16: no use for it so far).
2. **Spectral and waveband are included.** The data come from the filter lists of the
   providers; where a limit is not known, ask the developer (`TO CONFIRM`).
3. **MOC library.** The package stores the IVOA **string** only and has no MOC
   dependency (Option A). The skill describes how an agent can read the string with a
   MOC library (for example MOCpy) when it needs to test a position; the package does
   not require it.
4. **Where the spatial MOC comes from:**
   - All-sky missions (the Gaia providers, ASAS-SN): all sky, as the Registry does it
     (`0/0-11`, or the full-sky MOC of the chosen order). Gaia epoch photometry only for
     sources flagged as having it; that is a source selection, not a sky restriction,
     and goes in the description.
   - ZTF and Pan-STARRS1: the sky north of about -30 deg declination, declared as a MOC.
   - OGLE, UPJS and the personal collections: taken from the Registry records, which
     already describe them. Retrieved **once** and stored in the provider config (the
     mission plug-in approach); not fetched at runtime. Note the Registry record they
     came from.
   - TESS: one MOC for the whole mission, built from the sector footprints (see
     "TESS sectors" below).
   - **One spatial coverage and one temporal coverage per mission**, as in the Registry
     (no per-sector, per-field or per-collection entries; for a mission made of several
     collections the union is declared).
5. **Ongoing surveys:** the upper limit is 100000 MJD (as in the Registry example).
6. **Mandatory but possibly empty.** A provider must declare each coverage part; an
   explicit "unknown" is allowed (shown as `TO CONFIRM` in the notes), a missing
   declaration is an error. An unknown coverage never makes the agent skip a mission
   (see the multi-mission rules): it warns the user.
7. **Time system and rounding.** TDB MJD as in the Registry. Timing is not precise:
   round the start **down** and the end **up** to whole days (extend the window).

### TESS sectors (to design)

Need a spatial MOC and temporal intervals of the TESS sectors. Ideas, to discuss:

- **From MAST footprints (preferred idea).** The TESS full-frame images in MAST carry an
  `s_region` polygon per camera and CCD. Query them with `pyvo` (TAP, obscore or CAOM),
  union the polygons per sector into a MOC, and union the sectors for the whole mission.
  These are the real footprints, with no pointing arithmetic of our own.
- **From a pointing table.** The published sector pointings (RA, Dec, roll per sector;
  four cameras of 24 x 24 deg) plus a camera model. More work and more risk of error;
  the `tesswcs` / `tess-point` packages model the cameras, but they would be one more
  dependency for a build step only. Only if the MAST footprints are not enough.
- **Time.** A single interval for the whole mission: from the start of the first
  sector (rounded down to a whole day) to 100000 MJD while the mission is ongoing. No
  intervals per sector.
- **Build step, not runtime.** A script run by the developer (outside the package
  dependencies, MOCpy allowed there) writes the MOC string and the intervals into the
  provider; it is re-run when new sectors appear. The note states "valid up to sector N".
- **Registry approach kept.** One spatial coverage and one temporal coverage for the
  mission, as in the Registry. The MOC therefore does not say which sector covers which
  part of the sky; this is accepted (a time-and-space MOC of MOC 2.0 is not used).

### Second item: relations between providers (same data, subsets)

**Implemented (2026-10-16)** in the package: descriptor fields `data_group`, `is_subset`,
`subset_description`, `group_rank` (mandatory class attributes on every provider,
read by `descriptor()`), group checks in `list_missions()` (`validate_mission_groups`),
`tests/test_mission_groups.py`, provider template section 2.2, README table, both
skills (multi-mission rules and loop example). Groups today: ARI (rank 1) and AIP
(rank 2) full, VEB subset of `gaia_dr3_epoch_photometry`; all other missions alone.
`subset_description` of VEB has `TO CONFIRM` for the exact selection. The coverage
part of this ticket is still open.

Some providers serve the same content, so an agent that loops over all missions gets
duplicates and wastes requests. Agreed with the developer (2026-10-16):

- **Formal, mandatory fields on the descriptor** (and in the provider template, so a
  new provider must state them; a provider without them fails in `list_missions()`,
  like a missing `description`). No dependence between providers (no `subset_of=<id>`):
  - `data_group`: id of the shared content, for example `gaia_dr3_epoch_photometry`.
    A provider with unique content uses its own `mission_id`.
  - `is_subset`: bool. ARI `False`; VEB `True`.
  - `subset_description`: text, used when `is_subset` is true (for example "all
    eclipsing-binary candidates from ...").
  - `group_rank`: integer among the non-subset members (lower = ask first).
  The shared TAP host does not matter; different collections on one service are
  different data (UPJS serves OGLE, Gaia VEB, UPJS and personal collections).
- **Package checks (a test):** ranks are unique among the non-subset members of a
  group; a subset needs at least one non-subset member in its group.
- **Current groups:** `gaia_dr3_ari`, `gaia_dr3_aip` serve the same Gaia DR3 epoch
  photometry. `gaia_dr3_veb` is a true subset of both (eclipsing binaries only,
  confirmed by the developer). No other groups exist today.
- **Rank:** the developer's decision per provider (not speed or caching). The package
  does not state a reason and the template gives no rank rule; the rank is a plain
  number. Today ARI is ranked before AIP.
- **Agent rules (for the skill, after the fields exist):**
  - Same data: ask the lowest rank; move to the next one if the first one **fails**
    or **does not support** the requested search kind (unsupported is not "no data",
    but between mirrors the next rank can answer; report it). An empty answer is an
    answer. Say which one answered.
  - Subset: **inform the user** that the mission is a subset (with its
    `subset_description`). By default it is asked **last**, and skipped when a
    non-subset member of its group answered (say so: "skipped, already covered by the
    group"). If the user asks explicitly for what the subset holds (for example
    eclipsing binaries), the agent **suggests starting the search with that subset**,
    but does **not limit** the loop to it: if the subset fails, or returns nothing
    (the star may simply not be in the subset), the agent continues with the
    non-subset members of the group and says so.
  - **Report subset-only results.** Whenever rows come from a subset alone (the
    non-subset members were skipped, failed or not asked), the agent tells the user
    that the result covers only the subset (with its `subset_description`) and may be
    incomplete. This matters most for a cone search: neighbouring stars outside the
    subset are missing, so the field looks emptier than it is.
  - If no non-subset member answered: warn the user and go on with the subset mission
    (no stop); say it covers only part of the sources.
  - Fetch failure: the failover covers search only. If a fetch fails, report the error;
    the skill may suggest that the user repeat the search on another member of the
    group (the `lc_key` values differ), but the agent does not do it silently.
  - Deduplicate rows by archive id when rows from a group arrive together.
  - Advice for the skill: use the subset mission on purpose when the user wants
    eclipsing binaries specifically, and say why.

### Still open (discuss before any code)

- **Spectral limits per provider (decided):** the filters come from the photcal that
  every issued light curve already carries (filter identifier; see the provider notes).
  The photcal gives one effective wavelength per filter, but the Registry wants
  intervals, so the interval limits are taken from the **SVO Filter Profile Service** for
  the same filter identifier (the identifiers are SVO ids), retrieved once and stored in
  the provider config (like the MOCs). No invented widths. Convert to joules with
  `astropy.units` (spectral equivalencies), not by hand; round outward as for time.
  The spectral coverage of a mission is the union of its filters' intervals. Where a
  filter has no SVO profile, ask the developer (`TO CONFIRM`).
- **Field names (decided):** one small coverage object that mirrors the Registry's
  `vs:Coverage` element (spatial, temporal, spectral, waveband), stored on the
  descriptor.
- **Relation to search:** the coverage is a cheap pre-filter ("this mission cannot have
  points in 2010"). It does not replace `supports_discovery_time_filter` or the overlap
  test on product `t_min` / `t_max`.
- **Skills and docs:** after the fields exist, `lc-discovery` must say: read coverage
  from the descriptor first, do not guess from the description text; skip a mission only
  if its declared coverage excludes the request (say why); an unknown coverage is never
  a reason to skip. The docs state that the model follows the VO Registry, with the
  references above, and the skill explains how to test a MOC string with a MOC library.

### Status

### Coverage values and work plan (agreed 2026-10-16)

Coverage object: `MissionCoverage(spatial, temporal, spectral, waveband)`, all four
required, `None` = unknown (module `lc_discovery/coverage.py`). "End date" means the end of
that day. The UPJS-served missions (`ogle_ocvs`, `upjs_ts`, `personal_ts`, `gaia_dr3_veb`)
take their space and time from the UPJS TAP (astro.upjs), retrieved once and stored in the
provider config; `gaia_dr3_veb` is all sky with the same time as ARI and AIP.

| Provider | Space | Time (MJD) |
|---|---|---|
| `gaia_dr3_ari`, `gaia_dr3_aip`, `gaia_dr3_veb` | all sky | 56863 to 57902 (25 Jul 2014 to 28 May 2017) |
| `asassn` | all sky | 56293 (1 Jan 2013) to 100000 |
| `ztf_dr24` | dec > -30 deg | 58178 (1 Mar 2018) to 60971 (end of 22 Oct 2025) |
| `panstarrs1_dr2` | dec > -30 deg | 55197 (start of 2010) to 56748 (end of 31 Mar 2014) |
| `tess` | MOC from `tess-point` sector pointings (all sky at order 6) | 58324 (25 Jul 2018) to 100000 |
| `ogle_ocvs`, `upjs_ts`, `personal_ts` | UPJS TAP | UPJS TAP |

Waveband is "Optical" for all (TESS included). Spectral intervals: SVO filter limits.

Build script: `lc_discovery/tools/`, shipped with the package but **not** a public method.
It uses `pyvo` and MOCpy, which the package itself does not require (an optional extra, for
example `tools`, to be added with the script). Note: `src/lc_discovery/tap/client.py`
imports `pyvo` but `pyvo` is not listed in `pyproject.toml` dependencies; to be checked.

Work plan (in order):

1. [x] **Done 2026-10-16.** Dataclass, mandatory `coverage` attribute, validation,
   tests (`tests/test_mission_coverage.py`), provider template section 2.3, README, provider
   skill. All providers declare `None` (nothing claimed yet).
2. [x] **Done 2026-10-16.** Simple values declared in the providers: Gaia ARI, AIP and VEB
   (all sky, 56863 to 57902; shared in `shared/gaia_dr3_coverage.py`); ASAS-SN (all sky,
   56293 to 100000); PS1 (zone above -30 deg, 55197 to 56748); ZTF
   (zone above -30 deg; time `None` until the end of DR24 is confirmed); TESS (time 58324
   to 100000; space `None` until step 4). The zone is the MOC string in
   `shared/sky_zones.py` (order 6, built with MOCpy `from_zone`; none of 400000 random
   points above -30 deg was outside it; it reaches a little south of -30 deg). Constants
   `ALL_SKY_MOC` and `ONGOING_MJD_END` in `coverage.py`. Tests extended (201 pass).
3. [x] **Done 2026-10-16 (OGLE time and spectrum still open).** The UPJS records are in
   RegTAP (`http://reg.g-vo.org/tap`, ivoids `ivo://astro.upjs/<x>/q/ssa`). Tool
   `lc_discovery/tools/fetch_registry_coverage.py` (pyvo; not a package dependency)
   reads `rr.stc_spatial`, `rr.stc_temporal`, `rr.stc_spectral` and writes
   `providers/<mission>/registry_coverage.py` with the ivoid, the service and the date.
   Stored for `upjs_ts` (time 58726 to 59520) and `personal_ts` (36804 to 59496), both
   with Registry spectral intervals. Gaia ARI, AIP and VEB: all sky, 56863 to 57902 and
   the Registry spectral interval of `gaiadr3_eb/q/ssa` (shared constant). **OGLE: the
   Registry record has no coverage rows**; the MOC supplied by the developer is stored in
   `providers/ogle_ocvs/coverage_data.py`; time and spectrum are `None` (question below).
   Waveband "Optical" is declared for all ten providers. Tests extended (207 pass).
   Update 2026-10-16: OGLE time declared as 48622 (1 Jan 1992) to 100000 (open end); ZTF
   DR24 ends 22 Oct 2025 (MJD 60971). OGLE spectrum confirmed (step 6).
4. [x] **Done 2026-10-16 (changed approach).** TESS space is built by
   `lc_discovery/tools/build_tess_coverage.py` from `tess-point` (`tess_stars2px`: sector
   pointings and the camera focal-plane model), not from MAST footprints: outlines of all
   16 CCDs per sector, united over the 134 regular sectors (special 3I/ATLAS pointing left
   out) into `providers/tess/coverage_data.py`. Result: the union covers the whole sky at
   order 6 (77% after sector 26, 92% after 55, 100% at 134, planned sectors included), so
   the declared MOC is all sky and TESS space can never exclude a target. Needs `tess-point`
   (installed into the project `.venv`; not a package dependency).
5. [x] **Done 2026-10-16.** `lc_discovery/tools/build_sky_zones.py` (MOCpy, not a package
   dependency) now generates `shared/sky_zones.py` from declared declination bands (today
   one: dec above -30 deg, used by ZTF and PS1). The regenerated MOC string is identical to
   the one built by hand earlier; tests unchanged (207 pass). A new zone is one more entry
   in `ZONES`.
6. [x] **Done 2026-10-16 (rough values).** `lc_discovery/tools/fetch_filter_coverage.py`
   (pyvo) reads `filters.main` (`ivo://astro.upjs/filters/q/main`) and writes
   `shared/filter_spectral_coverage.py` (joules, via `astropy.units.spectral`). The table
   lacks the survey filters, so developer-chosen stand-ins are used and written into the
   module: ASAS-SN = Bessell V + SDSS g (3798 to 6875 A); ZTF = SDSS g r i (3798 to 8400 A);
   PS1 = SDSS g r i plus the developer-given limits of z (8030 to 9350 A) and y (9100 to 10878 A),
   union 3798 to 10878 A; TESS = TESS filter (5803 to 11171 A); OGLE =
   Bessell V + I (4733 to 9167 A). Used by the five providers; tests extended (208 pass).
7. [x] **Done 2026-10-16.** Skill `lc-discovery`: rule 7 and a new section "Coverage of a
   mission" (how to test space with a MOC library, time overlap, spectrum, waveband; skip
   only on explicit exclusion; `None` never skips; coverage is mission-wide and approximate;
   report every skip). Provider skill, provider guide (tools table in 2.3) and README
   updated. Optional extra `tools = [pyvo, mocpy, tess-point]` added to `pyproject.toml`.

### Status

**Done 2026-10-16 (steps 1 to 7).** Nothing open in the coverage data. Resolved later the same day: OGLE spectrum (Bessell V and I stand-ins) confirmed by the developer; PS1 z and y limits given by the developer; ASAS-SN
start confirmed as 1 Jan 2013; `pyvo` added to the package dependencies. TESS space is all sky (it cannot exclude a target; a per-target test would need
`tess-point`).

---

## Ticket 25: VSX resolver for variable stars unknown to Simbad (lc_discovery)

**Done 2026-10-16.** `lc_discovery/scripts/vsx_resolve.py` (new `scripts/` folder for
agent-facing helpers, not public API): one request to the VSX `api.object` view (XML), returns
name, OID, J2000 position, type, period, epoch, magnitudes; an unknown name raises
`VsxNotResolvedError`. No HTML scraping (the "Other names" list is not read; its entries are
VSX spellings, often not Simbad identifiers) and no contact address in requests (User-Agent
`lc_discovery`). Skill `lc-discovery`, section "Variable stars that Simbad does not know":
VSX name, then position, then Simbad cone search (few arcsec), then Simbad `main_id` and
identifiers, then `archive_id_from_identifiers` or a cone search; zero or several Simbad
matches go to the user; report that the position came from VSX. Tested on
`TCP J23580961+5502508` (Simbad name lookup fails; the cone search gives
`Gaia DR3 1993876650919517440`). Tests: `tests/test_vsx_resolve_script.py` (parsing, no network).
VizieR `B/vsx` for bulk lookups is deliberately left out. 

**Simbad helper, done 2026-10-16.** `lc_discovery/scripts/simbad_resolve.py` (extra `scripts`,
needs `astroquery`): `resolve_simbad_name(name)` and `find_simbad_objects(ra, dec, radius)`,
both returning the existing `SimbadResolveResult` payload (main id, identifiers, ICRS
position), so the result goes straight into `archive_id_from_identifiers`. Fail-fast: unknown
name or empty position raises `SimbadNotResolvedError`; no Sesame fallback (unlike the host
`skvo_veb/utils/simbad_resolver.py`, which has one); a position search returns all objects
inside the radius with separations and fails if there are more than `max_candidates`, instead
of cutting the list. Tested live: `AA And` (V* AA And, Gaia DR3 1936512041221649536) and the
VSX position of `TCP J23580961+5502508` (one object, 0.03 arcsec). Skill updated (Finding an
object, step 2; VSX section, step 1). Tests: `tests/test_simbad_resolve_script.py` (no network).

---

## Ticket 26: search-row columns in descriptions, skill rules for reading them (lc_discovery)

**Done 2026-10-16.** Trigger: in a user test an agent fetched three ZTF VOTables to measure
them, ignoring most search-result columns (ZTF rows already carry `n_points`, `mag`, `filter_name`;
`t_min` and `t_max` are empty, so the time span needs a fetch). Changes: every mission
description now ends with a `Search row columns:` paragraph (filled and empty columns, meaning,
rows per star), checked against real searches (AA And region); provider guide section 2.1
point 8 and the provider skill require it for new missions; test
`tests/test_mission_descriptions.py` checks that each description has it. Skill `lc-discovery`:
new sections "What a search row tells you" (every column is meaningful, read the table and the
paragraph, show useful columns, answer from the table before fetching, say what "longest"
means) and "Plotting a fetched light curve (advice)" (scatter, inverted magnitude axis,
calendar dates via astropy, filter in the title). Also fixed the ZTF description: time
coverage 1 March 2018 to 22 October 2025. Not verified live: columns of `ogle_ocvs`,
`upjs_ts`, `personal_ts` (no objects near the test star); their paragraphs come from the code.

---

## Ticket 27: ASAS-SN provider depends on the maintainer's Sky Patrol fork (lc_discovery)

**Done 2026-10-16.** Trigger: the ASAS-SN download failed with "integer division or modulo by
zero" because the archive's `get_block_servers` returned `[]` (a server-side outage); fixed in
the fork `olgavoz1971/skypatrol` (explicit `ConnectionError`), commit pushed by the developer.
Package: extra `asassn = ["skypatrol @ git+https://github.com/olgavoz1971/skypatrol.git@master"]`
in `pyproject.toml`; the `ImportError` of `skypatrol_client.py` names the fork and why; the ASAS-SN
description, `docs/providers/asassn.md` (section 0), the README and the skill (Errors) say that
upstream is not enough. The host app still needs `skypatrol` (old page `lightcurve_asassn.py`,
`request_asassn.py`), so its `requirements.txt` line stays. Note: with an unchanged version
number `pip` keeps the old copy; reinstall with `--force-reinstall --no-deps`.

---

## Ticket 28: remove the old ASAS-SN page (host app)

**Done 2026-10-16.** Removed `skvo_veb/pages/lightcurve_asassn.py` (already unregistered, marked
obsolete) and `skvo_veb/utils/request_asassn.py` (its only user; pickle cache `ASASSN_CACHE_DIR`).
Kept: `skvo_veb/utils/mission_config/asassn.py` and `tests/test_asassn_export.py` (used by
`lc_bridge` for the Discovery export profile `asassn`), `requirements.txt` `skypatrol` line (now
needed only by the `lc_discovery` ASAS-SN provider and `scripts/skypatrol_discovery_probe.py`).
Docs updated: `docs/caching_architecture.md` (section C), `docs/production_apache_celery.md`
(`ASASSN_CACHE_DIR` line). Checked: the app imports, 59 related tests pass. Possible clean-up
(not done): `resolve_target_identifier` in `mission_config/asassn.py` and some `my_tools`
helpers were used by the old page; the first is still used by the export profile. The server
environment may still define `ASASSN_CACHE_DIR`; it is now unused.

---

## Ticket 29: help popovers and UI consistency on the TESS pages (host app)

**Opened 2026-10-17.** Pages: `skvo_veb/pages/lightcurve_tess_srv.py` (`/tess_lc`) and
`skvo_veb/pages/tess_cutout.py` (`/tess`). The two pages use `dbc.Tooltip` (hover, one on
`/tess_lc`, seven on `/tess`) while the other pages use a click-triggered `?` with a popover.
Goal: the same `?` on both TESS pages, written for a remote user who knows nothing about
the server internals. Rules: `.cursor/rules/dash-page-ui.mdc`. Process agreed with the
developer: discuss, ticket, discuss each phase, code only on explicit permission, no commits
until asked.

Decisions (2026-10-17):
- One `?` per group, plus an individual `?` on non-obvious items (every flatten parameter,
  periodogram parameters, period and epoch, Shift to min).
- One shared helper in `skvo_veb/components/help.py`; neutral CSS classes in
  `assets/style.css`. `gp_for_oc.py` and `lightcurve_discovery.py` keep their own copies
  until a later migration ticket.
- Popover texts are user-facing, British English, sentence case, and must be checked
  against what the code really does before use.

Phases:

1. [x] **T1 Shared help component. Done 2026-10-17 (8 tests pass; not yet used by any page).** `components/help.py`: `click_help(prefix, help_id,
   title, body, placement='bottom')` returning `(button, popover)`; IDs
   `{prefix}_help_{help_id}_btn` and `..._popover`; body as string or list of components;
   `trigger='legacy'`; `role='button'`, `tabIndex=0`, `aria-label`. CSS `page-help-btn` and
   `page-help-popover` in the new `assets/page_help.css` (same look as the existing
   `lc-discovery-help-*`; `style.css` is a minified Bootstrap copy, so it is not used).
   Acceptance: opens on click, closes on outside click, reachable by keyboard, slugs
   validated (bad prefix or id raises `ValueError`), no page migrated, unit tests in
   `skvo_veb/tests/test_help_component.py`. Uniqueness of IDs across the app is the caller's
   job (distinct prefix per page); a global duplicate registry was rejected because layout
   functions rebuild on every page load.
2. [ ] **T2 `/tess_lc` popovers.** Clean cache and ReRetrieve first (texts below), then
   Radius (replaces the tooltip), group `?` for Search, Plot, Flux options, Folding and
   Periodogram, individual `?` for Object and Resolve, Magnitude, MJD or Date, rePlot,
   Trim selected, Download MAST FITS, Period, Epoch, Fold, Recalc phase, Shift to min and the
   periodogram parameters. Acceptance: no `dbc.Tooltip` left.
3. [ ] **T3 `/tess` popovers.** FFI or TPF, Clean cache, Radius, Size, Mask (Auto or
   Handmade, pipe or thresh, threshold), Plot options (Scale, Sum, Frame), Curve tools
   (Sub bkg, Flatten with window, break gap, order and Display each), Curve 1 to 3, Compare,
   and a page-level `?` replacing the `dcc.Markdown` instruction block. Acceptance: all seven
   `dbc.Tooltip` removed.
4. [ ] **T4 CSS tokens for both pages.** Page class, new `assets/tess_cutout.css`, extend
   `assets/tess_lc_srv.css`; remove inline styles, the `Silver` background and fixed pixel
   heights (use `clamp()`).
5. [ ] **T5 Button roles and sentence case.** Clean cache secondary outline, no `warning`
   colour, Cancel as danger outline, `size="sm"`, sentence-case labels and accordion titles.

Draft texts (to verify against the code before T2 and T3):
- **Clean cache:** "Removes the saved copies of this target's data from our server: the
  list of sectors and the downloaded files. Use it if the results look outdated or
  incomplete. The next search will fetch everything again from the archive, so it may take
  longer. The target is taken from the Object, or RA, DEC and Radius, fields above."
  To check: `tess_cache.delete_target_cache` (what is removed, matching by coordinates); the
  claim that uploaded files are not affected; the radius used on each page.
- **ReRetrieve:** "Deletes our saved copy of the selected sector(s) and downloads it again
  from the MAST archive. Use it if a sector failed to load or looks corrupted. Select at
  least one row in the table first. It does not draw the curve; use Retrieve curve
  afterwards." To check: `lightkurve_cache.purge_and_redownload_row`.
- **FFI or TPF:** TPF is a small image cut-out recorded for this star (only for stars chosen
  for it, best time resolution); FFI is a cut-out we make from the full-sky images (any
  star, coarser sampling, cut-out size in pixels).

Deferred (not approved): plot-sidebar restructure and `/tess` layout (description column,
three open accordions), removal of commented-out code and the invalid `display: row`,
silent radius fallbacks in both Clean cache callbacks (`None` on `/tess_lc`, `11.0` on
`/tess`; against the fail-fast rule, to be discussed), migration of `gp_for_oc.py` and
`lightcurve_discovery.py` to the shared helper.

**Backend and caching phase (no UI change), approved 2026-10-17:**
- [x] B1 `tess_lc_search.resolve_native_id` (split out of `search_lightcurves_cached`),
  `tess_lc_search.delete_cached_search`, `tess_cache.delete_cached`; tests in
  `tests/test_tess_lc_search_cache_clean.py` (4 pass).
- [x] B2 `/tess_lc` Clean cache removes the sector list plus `delete_target_cache`; the alert
  reports both. Downloaded MAST FITS are never touched by Clean cache (decision: they are
  removed per light curve by ReRetrieve).
- [x] B4 Invalid Clean cache radius gives a warning alert and uses the default 11 (both
  pages; on `/tess_lc` an empty radius stays "no cone"). Approved by the developer as an
  explicit exception to the fail-fast rule.
- [x] B5 `/tess` Clean cache now uses the shared `tess_processor.resolve_search_target`
  with `store_resolved_coords`, like `/tess_lc` (same target as the search).
- [x] B6 `tess_lc_search.resolve_native_id` remembers query to native id (prefix
  `lc_native_id_lookup`, key: normalised query, radius, search mode; no `target` key, so no
  coordinate tolerance) and skips the MAST lookup on repeats. Clean cache on `/tess_lc`
  forgets the entry too. 7 tests pass.

- [x] B7 ReRetrieve (`/tess_lc`) now runs the same path as Retrieve curve
  (`_retrieve_selected_curve(..., fresh_from_mast=True)`): purges the cached FITS of the selected
  row, downloads it again, plots it and switches to the Plot tab; same spinner and Cancel. It no
  longer writes to the search alert, so the results table is not covered by the spinner. The
  message "Fresh data downloaded from MAST: TIC, sector, author, exposure" appears below the
  table for 60 s (`status_alert(..., duration_ms=...)`), and is cleared by a new Search, a new
  row selection or the next Retrieve. Tests: `tests/test_tess_reretrieve.py`.

- [x] B8 Same for `/tess`: new ReRetrieve button next to Retrieve sector. It deletes every
  cached copy of the selected cutout (SPOC TPF: Lightkurve cache `mastDownload`; FFI: our
  `ffi_data` FITS plus the Lightkurve `tesscut` file for that sector, size and position),
  then runs the Retrieve sector path (`_retrieve_selected_sector(..., fresh_from_mast=True)`),
  same spinner, Cancel and tab switch. Message below the table for 60 s; cleared by a new
  Search or a new row selection. Clean cache still never touches TPF or cutout downloads
  made by Lightkurve. Tests: `tests/test_tess_cutout_reretrieve.py`. Not yet checked live
  against MAST.

- [x] B9 `/tess` cutouts: one shared copy, in the Lightkurve cache (option B, multiuser safe).
  Our `ffi_data` copy is no longer written or read (it also matched up to 72 arcsec and
  +-1 px away from the request). `lightkurve_cache.fetch_tesscut_pixel_file`: lookup by sector,
  exact size and position (0.001 deg); a miss or ReRetrieve downloads into a private temporary
  folder inside the cache directory and moves the file in with an atomic rename; a per-sector
  `flock` makes simultaneous requests share one download; an unreadable cached file is
  removed and downloaded again (logged); a failed download leaves the old file untouched.
  ReRetrieve of an FFI row therefore never leaves a moment without a file (other users keep
  working). SPOC TPF: unchanged (purge, then download). `LIGHTKURVE_CACHE_DIR` in `.env` is
  applied at start-up (`configure_lightkurve_cache_dir`); add it to `/var/www/flask/.env`.
  Manual cleanup guide: `docs/server_cache_cleanup.md`. Cleanup policy (age limit) deferred.
  Tests: `tests/test_tess_cutout_reretrieve.py` (all mocked; real cache lookup and read of a
  cached cutout checked by hand; a real MAST download was not run).

- [x] B10 `tess_cache.extract_coords` read sexagesimal RA (`23:05:22.84 +47:40:34.72`) as degrees
  (23.09 instead of 346.35 deg), so the new cutout lookup never matched and every Retrieve
  downloaded again. Strings with colons, h/d/m/s letters or four or more numbers are now read as
  hours and degrees first; decimal pairs stay degrees. Old coordinate-named cache files of such
  targets are orphaned (see `docs/server_cache_cleanup.md`). Tests:
  `tests/test_tess_cache_extract_coords.py`. Known, not changed: a comma pair such as
  `346.3, 47.6` is not parsed as coordinates (falls through to a name lookup).

- [x] B11 `/tess_lc`: removed the Upload button, the Append switch and the `handle_upload`
  callback, plus the imports only they used (`base64`, `io`, `ingest_lightcurve_file`,
  `format_user_upload_error`, `resolve_catalog_epoch`). Left on purpose: `CurveDash.get_extension_list`
  (no caller now), `tests/volightcurve/test_tess_upload.py` (tests the `lc_bridge` round trip, not
  the page), and the imports that were already unused before (`ClientsideFunction`, `LightkurveError`,
  `jd0_tess`, `lk`, `pd`, `re`, `safe_none`; `safe_none` kept by decision).

**Status 2026-10-17:** The earlier UI attempt on `/tess_lc` and the T1 helper were reverted by
the developer (the `?` click caused jerking and a visible page reload that was not reproduced
in headless tests); T1 files no longer exist. T2 to T5 are on hold; the UI must be redesigned
from the `lightcurve_processor.py` pattern before any new attempt.
- [x] B12 `/tess`: SPOC TPF retrieve goes through `fetch_spoc_tpf` (Ticket 16). ReRetrieve no longer
  deletes the file first: the new file replaces the old one only after it opens. `purge_spoc_tpf` and
  the old purge-and-retry in `download_selected_pixel` were removed. Six new tests.

---

## Ticket 29: skill advice from the multi-star TESS test (lc_discovery)

**Done 2026-10-18.** Trigger: a naive agent, asked which of nine stars have TESS light curves,
kept only a summary of the search result (so it searched again for follow-up questions) and
showed a table of counts (products, sectors, pipelines) without exposure time and dates. Skill
`lc-discovery`, section "What a search row tells you": item 3 rewritten (show every column that
has a value except `lc_key`; empty columns named in one line; constant columns stated once; no
ranking or product recommendation unless asked; a summary must not reduce columns to a count);
new item 6 (save every search table as ECSV, tell the path, answer follow-ups from the file;
checked that `meta` including tuples survives an ECSV round trip) and item 7 (many targets: one
line per target that still uses the columns, targets with no rows named explicitly, full table on
request). New section "Folded light curves: period and epoch": look for `period` and `epoch`
PARAMs in the VOTable first, then VSX through `scripts/vsx_resolve.py`; never invent a period;
epoch optional; always tell the user the source of each element; check the time system (VSX
epochs are JD, TESS is BTJD) and the epoch type (minimum for eclipsing, usually maximum for
pulsating). Not done: a worked check of the TESS example against live data.


**Update 2026-10-18 (verification).** Nine-star TESS example checked against live data: seven stars
resolve through Simbad to a TIC and return rows as in the skill example. Fold test attempted with
a hardcoded offset (BTJD guessed), which was wrong: the issued TESS time column is MJD-like
(about 58738 for sector 16); the provider writes TIMESYS (`refposition`, `timescale`,
`timeorigin`) and the agent must read it, not assume. VSX facts (VizieR B/vsx, AAVSO forum): the
epoch is documented as HJD, old entries are JD, some BJD; the web service returns a bare number
with no label (so no time-system field in `vsx_resolve.py`). Testing the epoch against the data is
not meaningful (changing periods, other effects). Skill `lc-discovery` changed: new section
"Respect the metadata of the product" (never hardcode or assume offset, time scale, zero point or
unit unless the user asks; TIMESYS/COOSYS/PHOTCAL hints; `volightcurve` recommended, not required;
non-Pogson magnitude systems); folded-curve items 5 and 6 rewritten. Cross-mission time
consistency postponed until a real use case. Not done: ECSV round-trip with real rows was not
read (the run was cut), corrected fold test not repeated; the second problem raised by the user
is postponed.

---

## Ticket 30: choice of the photometry column on the discovery page

**Status:** implemented 2026-10-18 (not yet checked in the browser by the developer).

**Problem.** A light curve issued by `lc_discovery` is a calibrated multi-column VOTable. TESS SPOC
carries `sap_flux` and `pdcsap_flux` (plus a background column), other providers carry other sets
of magnitude and flux columns. The app takes one of them: `pack_volc_to_json(lc, primary_col=None,
error_col=None)` in `skvo_veb/utils/lc_bridge.py` defaults to the first magnitude column, else the
first flux column. For TESS SPOC this is `pdcsap_flux` only because it is listed first. The user
cannot choose.

**Constraints (agreed with the developer).**
- No change to `CurveDash` and no multi-column serialised data. The selection is made once, at the
  getting stage, between the VOTable parse and the `CurveDash` build.
- Minimal change to data structure and flow. Scope: `lightcurve_discovery.py` only. `lc_processor`
  (uploads) later, reusing the same helper.
- Must stay cheap on the server (user files may have tens of thousands of rows).
- No global state; the only new state is the chosen column name in a small `dcc.Store`.

**Decision: option A, re-parse on every switch.** Changing the column re-reads the (already cached)
VOTable bytes, parses to `VOLightCurve`, and rebuilds the `CurveDash`. No new server cache.
Option B (a `flask_caching` entry holding the parsed `VOLightCurve` keyed by `lc_key`) is the
fallback if the developer's own timing on a large VOTable shows the parse is too slow.

**Plan.**
1. **Candidate listing (utils, pure function).** Given a `VOLightCurve`, return the candidate
   photometry columns: name, domain (mag or flux), unit, UCD, filter and magnitude system from the
   `PHOTCAL` group. Use `volightcurve` discovery (`get_mag_colnames`, `get_flux_colnames`), not
   name guessing. Background columns (UCD `instr.background`) are not candidates.
2. **Error column pairing.** The error column of a chosen photometry column is the error-UCD
   column with the same `PHOTCAL` reference. This is not an IVOA standard, but our providers
   write it consistently. If no column is found, report "no error column for this photometry
   column"; never borrow another column's errors. Check first how `volightcurve` exposes the
   reference per error column (`photdms` is keyed by photometry column).
3. **Bridge.** `volc_to_curvedash` gets an optional `primary_col` (and the paired `error_col`) and
   forwards it to `pack_volc_to_json`, which already accepts both. Default behaviour unchanged.
4. **Loader.** `curvedash_from_catalog_row` (`skvo_veb/utils/lc_discovery_load.py`) accepts the
   optional column and passes it to the bridge; `drop_invalid_photometry_rows` keeps working on the
   active domain.
5. **Page.** A "Photometry column" dropdown in the lightcurve tools panel, filled by the fetch
   callback with the candidates (label: column, unit, filter). Hidden when there is one candidate,
   so single-column missions look as today. The page UI rules in `.cursor/rules/dash-page-ui.mdc`
   apply (one widget pattern, sentence-case British English copy).
6. **Callback.** One new callback, one input (the dropdown): rebuild the curve with that column,
   write the serialised curve, bump `store_lc_discovery_lc_revision`. Same spinner pattern as the
   fetch; make it a background callback only if the developer's timing shows it is slow.
7. **Tests.** Candidate listing and pairing for a multi-column VOTable (TESS SPOC style) and a
   single-column one; missing error column; default column unchanged when no choice is given;
   switching the column changes `flux` and `flux_err` consistently and the unit and photcal follow.

**Known consequences.**
- Switching the column resets point edits (deleted points) and the fold state: `SAP` and `PDCSAP`
  can be missing at different rows, so row indices do not map between columns. The UI says so.
- The default (first magnitude column, else first flux column) stays; TESS therefore starts with
  `pdcsap_flux` as before.

**Decisions on the former open questions (developer, 2026-10-18).**
- The dropdown mixes magnitude and flux columns.
- Background columns are not offered (decision: discarded). Candidates are magnitude and flux
  photometry columns only.
- Scope: `lightcurve_discovery.py` only. Other pages that load user files (`lc_processor` and
  similar) can reuse the same candidate-listing helper and the optional `primary_col` bridge
  argument later; that is a separate ticket.

**Implementation notes (2026-10-18).**
- `lc_bridge.py`: `list_photometry_candidates`, `paired_error_column`, `_photometry_columns_by_domain`;
  `volc_to_curvedash(..., primary_col=None)` (default path unchanged; an explicit column is
  validated and takes its error column through the shared `PhotDM`; when no pairing exists the
  curve has no errors and a warning is logged).
- `lc_discovery_load.py`: `curvedash_with_candidates` (parse once, choose the column, return
  curve, candidates and used column), `photometry_select_options`; `curvedash_from_catalog_row`
  is a wrapper. A choice equal to the default goes through the unchanged default path.
- Page: `lc_discovery_photometry_select` (hidden below two candidates), store
  `store_lc_discovery_photometry_choice` (lc_key, the catalogue row, candidates, active column),
  callbacks `show_lc_discovery_photometry_select` and `change_lc_discovery_photometry_column`
  (re-parses the cached VOTable, keeps period, epoch and fold flag from the previous curve,
  clears the point selection and zoom, drops point edits). The mag switch follows through the
  existing revision sync. CSS in `assets/lc_discovery.css`.
- Tests: `skvo_veb/tests/test_lc_photometry_choice.py`. Full suite: 644 passed.
- The page intro no longer mentions the removed ASAS-SN page (fixed 2026-10-18).

**Update 2026-10-18 (export description).** The VOTable exported from the discovery page kept the
source product description ("All registered flux and background columns ... are issued"), which
is false after one photometry column was chosen, and the FIELD is named `flux` without telling
which source column it is. `lc_bridge.py`: `volc_to_curvedash` records
`metadata['photometry_source']` (source column, unit, filter, error column, columns not carried);
`build_votable_kwargs_from_metadata` prefixes the table and VOTable descriptions with a statement
of the kept column and quotes the original text as "Description of the source product".
Curves without that record (TESS and ASAS-SN pages) are unchanged. Not done: ECSV/CSV exports do
not carry this statement. Seen on the way: the TESS `sap_bkg` column is picked as the per-epoch
label column by `get_label_colnames` (it is carried into `CurveDash`, not omitted).

**Correction (2026-10-18).** The first export-description change went into
`build_votable_kwargs_from_metadata`, which the discovery page's Download does not use (it goes
through `export_curvedash` and `_curvedash_to_export_volc`, which writes the `vo_envelope`
descriptions). The statement is now applied in `_curvedash_to_export_volc`; a test exports through
`export_curvedash` and reads the written VOTable. A curve cached before this change has no
`photometry_source` record, so it must be retrieved again.

**Update 2026-10-18 (server cache of the fetched VOTable).** Found while testing with wifi off:
changing the photometry column hung. The assumption behind "option A, no new cache" was wrong:
`lc_discovery.fetch` for TESS runs a live MAST search on every call
(`tess_fetch._unique_search_result`) because the path of the cached FITS comes from the search
result, and then rebuilds the VOTable from the FITS. Only the FITS is cached, not the issued
VOTable. Fix in the app (option 1): `fetch_discovery_votable_bytes` in `lc_discovery_load.py`
keeps the fetched bytes in the shared server `diskcache` (`get_lc_user_cache`, `USER_CACHE_DIR`,
not per tab), key `lc_discovery_votable_<lc-discovery version>_<sha256(lc_key)>`, 24 h expiry
(diskcache size limit and eviction apply). Retrieve, a column switch and "Download entire votable"
read it; "Re-retrieve" (`force_refresh`) bypasses and replaces it; failures are not cached.
Tests in `test_lc_discovery_load.py` (650 passed). Still open, separate `lc_discovery` ticket:
make the TESS provider local-first (put the FITS pointer into `lc_key` at search time so a cached
product opens without a MAST search, also offline). Other providers were not checked for the
same per-call archive request; with the app cache they are hit once per product and day.

## Ticket 31: programmatic access (MCP server and HTTP API) over a shared service layer

**Status:** proposal 2026-10-18, discussion only, nothing implemented. Open decisions are listed at the end.

**Goal.** Give agents (MCP) and programs (HTTP) access to the capabilities of `lc_discovery` and
`volightcurve` on the production server, next to the Dash site, without three separate
implementations. Starting with light curve discovery; later packages must fit the same scheme.

**What we found in the current code.**
- `lc_discovery` offers primitives only (`list_missions`, `search`, `resolve_target`,
  `archive_id_from_identifiers`, `fetch`, `purge_cache`). The real workflow lives in the host app:
  `run_catalog_search` (coordinates, else name: provider resolve, Simbad, archive id, Simbad cone,
  main-name retry) in `skvo_veb/utils/lc_discovery_search.py`. It is tied to the UI (status
  callbacks, markdown, `PipeException`).
- The same workflow exists a third time as prose advice in the skill ("Finding an object"), so an
  agent re-invents it on every run. Simbad resolution exists in the host
  (`skvo_veb/utils/simbad_resolver.py`) and in `lc_discovery/scripts/simbad_resolve.py`.
- Other host logic that an API also needs: the server cache of fetched VOTable bytes
  (`fetch_discovery_votable_bytes`, Ticket 30), listing photometry columns and pairing the error
  column (`lc_bridge.list_photometry_candidates`, `paired_error_column`; this is VOTable knowledge
  and belongs in `volightcurve`).
- `import skvo_veb` runs `skvo_veb/__init__.py`, which builds the whole Dash app, Celery manager
  and pages. Another process (MCP, API) cannot reuse any `skvo_veb.utils` function without booting
  Dash. The shared logic therefore must leave the host package.
- Production: Apache `mod_wsgi` daemon (5 threads) serves Dash at `/igebc`; Redis + Celery serve
  `background=True` callbacks; `/var/www/flask/.env`; shared `diskcache` in `USER_CACHE_DIR`.
  mod_wsgi cannot serve an MCP streamable-HTTP endpoint (ASGI, streaming).
- `personal_ts` reads `personal.*` tables in a database. It must not be exposed publicly by default.

**Decision 1: one service layer, three thin adapters (not three implementations).**
```
 Dash page (WSGI)      MCP adapter        HTTP adapter (optional)
        \                  |                  /
         \                 |                 /
          service layer (no Dash, no web framework, no UI text)
             |                         |
        lc_discovery              volightcurve
```
- Dash calls the service layer in process. It does not call our own HTTP API (extra hop, loses
  background callbacks and shared memory, adds a failure mode).
- MCP and HTTP adapters are in one ASGI process, each a few dozen lines per operation, because they
  only translate arguments, results and errors.
- Python users who only want the code can `pip install lc_discovery`. The HTTP API exists for
  users who want our server cache and our Simbad/VSX resolution. Build it only if a real user asks;
  the MCP server is the first adapter.

**Decision 2: where the service layer lives.** In `lc_discovery` itself (module such as
`lc_discovery.workflow`), not in a new package, because we are alone and the workflow is the
package's missing half. Contents:
- `find_lightcurves(target | ra, dec, missions, radius, time bounds, ...) -> SearchResult` (the
  moved `run_catalog_search`, returning data and a list of "what was tried" records, never
  markdown or status callbacks).
- Simbad resolver moved from the host (optional extra `simbad`, needs `astroquery`); the host and
  the script import it from there. No fallback to another resolver (AGENTS: fail fast).
- Product cache for fetched VOTable bytes (injected cache object or `LC_DISCOVERY_CACHE_DIR`), so
  Dash, MCP and the API hit the same files. Cache key as in Ticket 30.
- A typed error family (`DiscoveryError` with a stable `code` and a user-readable message) replacing
  `PipeException` in this path. Adapters map it: Dash alert, MCP `isError` content, HTTP 4xx, or
  502 for an archive that is down.
- `volightcurve` gains `list_photometry_candidates`, `paired_error_column`, and a `describe()`
  summary (rows, time span, TIMESYS, columns with UCD/unit/photcal). The host keeps only CurveDash,
  Plotly and the export wording.
- The host then shrinks to adapters; the Dash behaviour must not change (existing tests are the
  safety net).

**Decision 3: MCP surface (small, summaries first).**
- Tools: `list_missions` (with coverage), `resolve_object`, `search_lightcurves`,
  `fetch_lightcurve` (returns a summary and a reference, not the table), `get_lightcurve_points`
  (server-side column choice, time window, `max_points`; never more than a hard cap),
  `describe_lightcurve`. Later: fold with a given period and epoch, photcal conversions through
  `volightcurve`.
- Light curves of tens of thousands of rows must not pass through the model context. Full products
  are exposed as an MCP resource or a token-protected download URL (VOTable, as `fetch` already
  produces); tools return counts, columns and a link.
- The guidance in `SKILL.md` becomes the server `instructions` and an MCP prompt/resource, so any
  client gets it without copying a skill file. The rule "respect the metadata, never assume
  offset, time scale or zero point" stays the first line.
- Public missions only by default (allow-list in settings). `personal_ts` and other private
  sources only behind an explicit setting and a token scope.

**Decision 4: deployment on the existing server.**
- Separate systemd unit (like `celery-skvo-veb-2.service`) running an ASGI server (uvicorn) on
  `127.0.0.1:<port>`, same virtualenv and `.env`, `stateless_http` MCP mode (no session affinity).
- Apache reverse-proxies one path (for example `/igebc/mcp` and `/igebc/api`, or a separate
  host name) with `mod_proxy_http`, buffering off for the streaming response, longer timeouts. The
  ProxyPass lines must win over `WSGIScriptAlias /igebc`; to be tested on the server, not assumed.
- Shared `USER_CACHE_DIR` diskcache is process-safe; size limit (1 GiB) is shared with session
  blobs, so the product cache needs its own directory or limit before public use.
- Slow archive calls (MAST can take a minute): run blocking calls in a thread pool with a
  concurrency limit; on timeout raise an explicit error telling the client to retry (the warmed
  cache answers the second call). No job queue in the first version; the service layer stays
  callable from a Celery task if needed later.
- Access control: bearer tokens from the environment (hashed, one per user), per-token rate limit,
  request logging through the standard logger. Full OAuth is out of scope until there is a reason.
  The cache protects the archives from repeated calls but not from many different objects.

**Order of work (each step is releasable and keeps Dash working).**
1. Move the workflow, resolver, product cache and error family into `lc_discovery`; host imports
   them. Remove the duplicates (host `simbad_resolver`, script). Tests move with the code.
2. Move photometry-column helpers and `describe()` into `volightcurve`; host imports them.
3. MCP adapter with `list_missions`, `resolve_object`, `search_lightcurves`, `fetch_lightcurve`,
   `get_lightcurve_points`; run locally over stdio and test with an MCP client.
4. Deployment: systemd unit, Apache proxy, tokens, rate limit, cache limits; check from a remote
   client.
5. Only on demand: HTTP adapter mirroring the same operations (VOTable for tables); TESS
   local-first provider (separate `lc_discovery` ticket, Ticket 30 note).

**Risks.** Step 1 touches the live search path (regression risk, covered by 650 tests); the
`mcp` and ASGI dependencies enter `requirements.txt` with loose lower bounds only; a public
endpoint adds an abuse surface (tokens and limits before it is advertised); Apache path
precedence unverified.

**Open decisions for the developer.**
- Is the service layer inside `lc_discovery` (proposed) or a separate package?
- MCP under `/igebc/mcp` or on its own host name?
- Public missions only, or tokens with a scope for private ones?
- Does the HTTP API wait for a real user (proposed)?

### Ticket 31, addendum A (DRAFT, 2026-10-22): layers, the outer level, minimal steps

**DRAFT. This addendum must be discussed with the developer before any code is written. Nothing
here is decided. It amends the first text of Ticket 31 where they differ.**

**Agreed layers (after discussion).**
1. Archives (MAST, ZTF, ASAS-SN, Pan-STARRS1, OGLE, Gaia, UPJS TAP, personal collections).
2. `lc_discovery`: an independent client library with provider plug-ins and a local cache. It is
   installed and used on its own by any script with internet access. It must never depend on Dash,
   MCP, ASGI or any web framework. `volightcurve` follows the same rule (out of scope for now).
3. Servers that use it as one component among others: the Dash application (the web application
   server for browser users) now; an MCP server and an optional HTTP API later. These live in the
   host repository or a small separate one, never inside `lc_discovery`.
4. Users: browsers, agents, programs.

**Corrections to the first text.**
- No provider in `lc_discovery` logs in (no credentials, tokens or login in the source); all are
  anonymous and the data are public. `personal_ts` is the developer's public TAP service. The idea
  of private missions behind token scopes is dropped. A server token, if any, only limits abuse of
  the archives through the server's address; it does not protect confidential data. Whether the
  first version needs tokens at all is open; a rate limit is the main protection.
- Terms of use and citation conditions (for example ASAS-SN Sky Patrol, ZTF) and archive
  rate limits were not checked and are a to-do before a public endpoint.
- Adapters (MCP, HTTP) are not part of `lc_discovery`.

**Approach to agents (discussed).** Primitives plus a skill plus example scripts is the right base
for a dialog with a researcher, because the agent composes the steps and the researcher can steer
it. Its weakness: each agent re-implements the same outer logic, results vary, and a client without
the skill file never sees the rules. Rule of thumb for what goes where:
- Deterministic, one right answer (resolution order, caching, error classification): code.
- Needs judgement (which mission, which column, period and epoch, what the data mean, respect the
  metadata of the product): skill.
If the skill contains an algorithm that every agent must follow identically, it is code in prose.
Two additions help the dialog: every step returns a trace ("what was tried, what was found"), and
errors name the next options, so the agent can explain a failure to the researcher.

**The outer level.** It already exists in three copies (host `run_catalog_search`, the
`simbad_resolve.py` and `vsx_resolve.py` scripts, and prose in the skill). Proposal: build it once
as small named steps in the same repository as `lc_discovery`, in a separate namespace and an
optional extra (Simbad needs `astroquery`), so the core stays a pure primitive client. No UI text,
no framework. Each step returns data and a trace. A convenience cascade may call the steps, but it
is not the only way in. Dash shows the trace as status text; an MCP server exposes the steps as
separate tools so the agent decides the order; scripts import them.

**Proposed minimal set of steps (to be discussed).** Existing primitives are unchanged:
`list_missions`, `search`, `resolve_target` (mission-specific name), `archive_id_from_identifiers`,
`fetch`, `purge_cache`.
1. `resolve_simbad(name)`: position, identifiers, main identifier. Several matches or none is
   reported as such, never silently chosen. Moved from the host and the script.
2. `resolve_vsx(name)`: position, period, epoch, type, as VSX publishes them. The epoch is a bare
   number; the time system is not asserted (see the skill). Moved from the script.
3. `resolve_position(text)`: parse and validate coordinates (decimal or sexagesimal, with a frame),
   so "name or coordinates" is decided in one place.
4. `find_lightcurves(...)`: optional cascade over steps 1 to 3 and the primitives (coordinates give
   a cone; a name goes through the mission resolver, Simbad, archive id, cone). Returns the search
   rows, the identity that was used, and the trace.
5. Error family: `DiscoveryError` with a stable `code` and a readable message, replacing the host
   `PipeException` on this path; adapters map it (Dash alert, MCP error content, HTTP status).

**Policies that are silent in the host today and must be made explicit (decide each).**
- When a name search finds nothing, is the main-name retry done automatically or offered?
- Order between a mission resolver, Simbad and a cone search; which radius, who may change it.
- Several Simbad matches: stop and ask, or take the first (proposal: stop and report).
- Whether VSX is consulted automatically when Simbad fails, or only when asked.
- What the cascade does after the first mission with results (continue or stop).

**Not decided here.** Where the product cache for fetched VOTable bytes lives (package or host),
what the MCP tool list is, deployment details (see first text of Ticket 31). The photometry-column
helpers and `describe()` for `volightcurve` stay as written above and are out of scope for this
addendum.

**Next step.** Discussion only. After agreement: a second addendum with the final step list and
signatures, then implementation in small releasable steps (Dash behaviour unchanged, 650 tests as
the safety net).

## Ticket 32 (DRAFT, 2026-10-22): volightcurve (SEPARATE PACKAGE): separate the strict core from interpretation

**DRAFT. Every phase below must be discussed with the developer and agreed before any code is
written. Nothing here is decided. The work is in the separate repository `volightcurve`; this
ticket lives here with the other cross-package tickets.**

**Purpose of the package (developer's statement).**
- A) A strict core: the IVOA light curve annotation proposal plus the parts borrowed from
  PhotDM that the proposal lacks. Every protocol or agreement that may change sits there and only
  there. Other code (applications, `lc_discovery`) reads, writes, XML-serialises and converts
  magnitude and flux only through its public methods.
- B) Interpretation: reality differs from the protocols, so data that are not VO-compliant must be
  brought into a form the core accepts, WITHOUT inventing calibration and WITHOUT throwing data away.

**Problem: A and B are mixed.**
- `lightcurve.py` is one file of about 2350 lines. It holds the strict model (`PhotometryFilter`,
  `PhotCal`, `PhotDM`, `CooSys`, `TimeSys`), the extraction of declared groups from a VOTable,
  column discovery, the guessing code (`_promote_to_vo_standards`, `_pickup_*`,
  `_recover_lc_colnames`, `apply_non_votable_heuristics`), the class `VOLightCurve` and the writer.
- `VOLightCurve._ingest` serves both worlds, and a declared value and an inferred one end up in the
  same attribute with no record of which was which.
- The dividing line is NOT the file format. A third-party VOTable without `PHOTCAL` needs B; a
  text file with a full header may need little. The line is: VO-compliant (everything the core
  needs is declared) or not.

**Criterion for where a rule belongs.** Does it use only what the file declares (a UCD, a
`TIMESYS`, `COOSYS` or `PHOTCAL` group, a FIELD reference, units)? Then it is A. Does it use column
names, comments, unit text in a header or a convention? Then it is B.

**Principles (agreed in discussion).**
1. Absent stays absent. A missing zero point, filter, time system or coordinate system is `None`
   (or an explicit "absent" state) in memory, and it is written back as absent in a round trip.
   No "all or nothing" requirement: a light curve with magnitudes only and no calibration is valid
   and must work happily as such.
2. An operation that needs absent data raises, naming what is missing. Example: magnitude to flux
   without zero points raises `PhotCalError`; the caller who never converts is never disturbed.
3. Check methods tell the caller what is missing for a given operation (which zero points, which
   metadata), before the operation is tried.
4. Provenance per attribute: declared, inferred (rule and evidence), or absent. Interpretation
   never writes into the core by stealth; it fills the same model and marks what it inferred.
5. The dependency runs one way: interpretation imports the core, never the reverse. A strict mode
   (interpretation off) rejects anything undeclared.

**Findings from a first look (to be verified in phase 0).**
- *Two models of the calibration?* Not two parallel ones. `PhotCal` is a facade over a nested
  `ZeroPoint` (`PogsonZeroPoint`, with Asinh and Linear stubs) and `MagnitudeSystem` in
  `photdm.py`. Leftovers: compatibility aliases (`_zp_flux`, `_zp_mag`, ... on `PhotCal`), a flat
  constructor path next to the nested one, and `PhotometryFilter` held by both `PhotCal` and
  `PhotDM` (which also has `filter_id`, `filter_name`, `mag0`). The developer's wish is to check
  and exclude duplication; the remaining duplication is this surface, and it needs a decision
  (one canonical path, the other removed or deprecated).
- *Already in line with the principles:* omitted zero points stay missing; `conversion_problems`
  and `PhotCalError` exist (`photcal_check.py`).
- *Possibly in conflict with principle 1 (to verify):* `VOLightCurve.__init__` and `from_table`
  set `self.timesys = TimeSys()`, whose constructor default is HELIOCENTER, origin 0.0, UTC, and
  the writer (`time_reference.py`, `default_timesys`) falls back to it. A light curve whose time
  system is undeclared may therefore be reported, and written, as declared. `CooSys` also defaults
  to ICRS. Both would invent metadata.
- `photcal_defaults.py` holds optional defaults (zero-point flux 1.0, reference magnitude 20.0,
  Vega) "for host applications". It contradicts the spirit of principle 2 even though the writer
  does not use it. Decide: keep, move out of the package, or delete.

**Proposed approach (structure only; names and layout to be agreed).**
- Two parts in the same repository and the same wheel (sub-packages), not two packages: the strict
  core (model, reading of declared metadata, writing, conversions, check methods) and
  interpretation (everything that uses names, comments or conventions). A thin reader calls
  interpretation on the input, then hands the result to the core.
- The model classes carry per-attribute provenance and an explicit absent state.
- `lightcurve.py` is split along the same line; public import paths stay compatible until the
  developer decides otherwise.
- Tests split along the line: core against the specification and fixtures; interpretation against
  a corpus of untidy real files. Skills split too: reading, writing and converting (core); what is
  guessed and how to check it (interpretation).

**Phases (each is discussed and agreed before it starts).**
0. Inventory, no code. List every public name and who uses it (`lc_discovery`, the host
   `lc_bridge`, scripts). Classify each function and attribute as A or B by the criterion above.
   Settle the two findings above (calibration surface, invented time and coordinate defaults).
1. Decisions on the design: how provenance and the absent state are represented; whether the
   split is two sub-packages; what happens to the compatibility aliases and `photcal_defaults.py`;
   strict mode behaviour. Output: a short design addendum here.
2. Core: remove invented defaults, add check methods for time system, coordinate system and
   calibration (what is missing for which operation), keep round trips faithful to absence.
3. Move interpretation out of the core; the reader composes the two; provenance recorded.
4. Downstream: `lc_discovery` and the host use only public core and reader methods
   (see the next ticket on the relation between `lc_discovery` and `volightcurve`).
5. Documentation and skills updated; old import paths removed after one release if agreed.

**Safety net.** The existing tests of the package (about 15 modules) and the host suite
(650 tests) stay green at the end of every phase; round-trip tests for absent values are added
before the core is changed (phase 2).

**Out of scope here.** The relation between `lc_discovery` and `volightcurve` (next discussion),
MCP, and any change to the IVOA specification text itself.

## Ticket 33 (DRAFT, 2026-10-22): lc_discovery depends on volightcurve (producer uses the protocol library)

**DRAFT. Every phase must be discussed with the developer and agreed before any code is written.
Nothing here is decided beyond the direction (option 2). Start slowly. It depends on Ticket 32
(clean strict core in `volightcurve`) for its later phases. Both repositories are separate.**

**Decision taken.** `lc_discovery` will require `volightcurve`. The dependency runs one way:
`lc_discovery` imports the strict core of `volightcurve`; `volightcurve` never imports
`lc_discovery`. `lc_discovery` uses only the strict core (Ticket 32, part A), never the
interpretation part (part B): a provider knows what it has, declares it, and declares what it does
not know as absent.

**What we have (checked 2026-10-22).**
- `lc_discovery` does not import `volightcurve` anywhere; it is not in its `pyproject.toml`. The
  skill only recommends it, for readers.
- Five providers build the VOTable XML by hand with ElementTree, each in its own
  `fetch_metadata.py`, including `TIMESYS` and the `PhotCal` `GROUP` elements: `tess`, `ztf`,
  `asassn`, `panstarrs1_dr2`, `gaia_dr3_aip`.
- Five providers patch a VOTable received from a server in `enrich_votable`: `ogle_ocvs`,
  `gaia_dr3_veb`, `gaia_dr3_ari`, `upjs_ts`, `personal_ts`.
- `photcal_keys.py` holds dictionary keys (`zp_flux`, `zp_mag`, `mag_sys`, filter keys) that mirror
  the `PhotCal` arguments of `volightcurve`; nothing enforces that they match.
- The protocol knowledge is therefore copied about ten times in the producer. A change of the
  annotation would have to be followed in every provider. The consumers (host `lc_bridge`, agents)
  already read the products through `volightcurve`.

**Cost to settle before the dependency becomes required.**
- `volightcurve` depends on `pyOpenSSL` and three GAVO packages installed from tarballs at
  soft.g-vo.org (not PyPI). `lc_discovery` would inherit them, against the aim of an easy install
  on any machine. Not yet checked: whether the writing side of the core needs GAVO at all (it may
  be needed only for reading). If the core can write with astropy alone, the dependency stays light.
- `volightcurve` is not on PyPI; the dependency would be a git URL (as `skypatrol` already is),
  with a minimum version.
- Providers must stop using any default the core currently invents (time system, coordinate
  system; see Ticket 32). Until then, issuing through the core could write undeclared values as
  declared.

**Phases (each discussed and agreed before it starts).**
0. Baseline, no change to any writer. Add `volightcurve` to the dev dependencies of `lc_discovery`
   only. A test reads every issued product of every provider (recorded or synthetic payloads, no
   network in the test suite) with `volightcurve` and reports: what parses, what the check methods
   say is missing (time system, coordinate system, calibration per flux or magnitude column),
   what differs between providers. Output: a short table of findings in this ticket. This shows
   today what each provider gets wrong; it is the baseline for everything after.
1. Decisions, after Ticket 32 phase 0 to 1: the install weight (GAVO on the write path or not),
   the form of the data a provider hands over (table, units, UCDs, time-system parameters,
   per-column calibration, with absent as absent), where the provider-level description lives
   (a small declarative structure per provider, replacing the dictionary keys of
   `photcal_keys.py`). Output: a design addendum here.
2. One pilot provider (proposal: `tess`, the richest, with a recorded payload) issues through the
   core. Its output is compared with the old output: same declared values, nothing added, nothing
   lost. The strict read test of phase 0 must pass.
3. The other four hand-built providers, one at a time, each its own release step.
4. The five `enrich_votable` providers: decide case by case whether to enrich through the core or
   to leave the server-side VOTable as it is and only validate it (a product issued by our own
   DaCHS service may be compliant already).
5. Make the dependency required in `pyproject.toml`; remove `photcal_keys.py` and the duplicated
   XML code; update the skill (`volightcurve` is then part of the producing side; readers may still
   use plain astropy and the skill keeps saying so); a strict-read test over all providers stays
   in the suite for good.

**Safety net.** The `lc_discovery` suite and the host suite (650 tests) stay green at the end of
every phase. Phases 2 and later compare old and new output before the old writer is removed.

**Out of scope.** The cleaning of `volightcurve` itself (Ticket 32), MCP and the service layer
(Ticket 31), the local-first TESS provider.

### Ticket 32, addendum A (2026-10-22): phase 0 inventory of `volightcurve` (read-only, nothing changed)

Source: `volightcurve` at the baseline `v0.1.0` (commit 85d048f). Line numbers refer to that commit.
Criterion A (strict core): uses only what the file declares. B (interpretation): uses column
names, comments, unit text or conventions. "Mixed" means one function does both.

**1. Module and function classification.**

| Where | What | Class |
|---|---|---|
| `photdm.py` | `ZeroPoint`, `PogsonZeroPoint`, `AsinhZeroPoint`, `LinearFluxZeroPoint`, `MagnitudeSystem` | A |
| `photcal_check.py` | `PhotCalError`, `inspect_conversion_photcal` | A |
| `vo_unit_codec.py` | `to_wire`, `to_internal`, `to_display`, constants | A |
| `lightcurve.py` | `PhotometryFilter`, `PhotCal` (conversions, `conversion_problems`) | A |
| `lightcurve.py` | `PhotDM`, `TimeSys`, `CooSys` | A with invented defaults (section 2) |
| `lightcurve.py` | `extract_photdm`, `extract_coosys`, `extract_timesys`, GAVO tree helpers | A (reading declared groups) |
| `lightcurve.py` | `get_time/mag/flux/error_colnames`, `find_columns_by_ucd`, `is_mag_column`, `is_flux_column`, `column_main_role` | A when the UCD is declared; the name fallbacks inside (`is_observation_time_column`, `is_magnitude_phot_column`) are B |
| `lightcurve.py` | `get_label_colnames`, `assign_label_column_ucd`, `assign_photometry_column_semantics` | Mixed (assigns UCDs the file did not declare) |
| `lightcurve.py` | `_promote_to_vo_standards` (UCD and unit from column names), `_recover_lc_colnames` (positional names), `_pickup_*` (JD0, period, epoch, filter from comments), `apply_non_votable_heuristics` | B |
| `lightcurve.py` | `VOLightCurve` (`_ingest_votable`, `_ingest`, `from_table`) | Mixed (section 3) |
| `lightcurve.py` | `VOLightCurve.add_flux_column_from_mag`, `add_mag_column_from_flux`, `write_votable`, `write_vo_lightcurve` | A with invented defaults and limits (section 4) |
| `time_reference.py` | `extract_*_from_gavo`, `export_absolute_jd_as_time_offset`, `absolute_jd_to_time_offset` | A with invented defaults |
| `time_reference.py` | `time_offset_to_absolute_jd` (value above 2400000.5 is taken as absolute JD), `resolve_observation_timesys` (falls back to columns named `obs_time`, `time`, `jd`, `mjd`), `resolve_timesys_for_table_param` ("assumes the same TIMESYS") | Mixed |
| `io_keywords.py`, `io_meta.py` (comment and flat-meta parsing), `io_dat.py` | `KEY=value` vocabulary, sentinels, `.dat` reading and header rules | B |
| `io.py` | `read_lightcurve`, `write_lightcurve`, `assemble_volightcurve`, `_votable_kwargs_from_volc` | Facade over both, today without a visible seam |
| `photcal_defaults.py` | Constants 1.0, 20.0, Vega | Neither: policy for hosts (section 5) |

**2. Metadata invented by the code today (conflicts with "absent stays absent").**
- `TimeSys()` default: HELIOCENTER, 0.0, UTC (`lightcurve.py` 487). `VOLightCurve.__init__` and
  `from_table` create it for every curve (1539, 1614).
- `_timesys_from_gavo_attrs` (`time_reference.py` 39 to 54): a declared `TIMESYS` with no
  `refposition`, `timescale` or `timeorigin` gets HELIOCENTER, UTC, 0.0. A declared `timeorigin`
  of 0 and an absent one cannot be told apart.
- `extract_timesys_metadata_from_gavo` (160 to 163): a VOTable without any `TIMESYS` gets `TimeSys()`
  as if declared.
- `_ingest_votable` (1594 to 1595): if `timeorigin` is falsy it is filled from table comments
  (`_pickup_jd0_from_table`), which returns 0.0 when nothing is found (1213 to 1227). A declared
  origin of 0 is therefore overwritten by a comment guess.
- `resolve_observation_timesys` (200): `volc.timesys or TimeSys()`.
- `PhotDM.filter_id` returns the string "Unknown" without a filter (412); `PhotDM.mag0` returns 0.0
  without a calibration (441). Both are invented values returned as data.
- `apply_non_votable_heuristics` (1449): `mag_sys` becomes "Vega" and the magnitude unit "mag"
  when only some calibration keywords are present.
- `write_vo_lightcurve` defaults (1971 to 1983): BARYCENTER, TCB, origin 0, magnitude system
  Vega. A `TIMESYS` is always written, and `magnitudeSystem` is always written. The method
  `VOLightCurve.write_votable` has different defaults (HELIOCENTER, UTC, 1865 to 1867), so the same
  light curve is written with a different time system depending on the entry point.
- `CooSys` default system ICRS exists only in the constructor; `extract_coosys` correctly returns
  `None` when nothing is declared (good as it is).
- `PhotometryFilter`: not checked in detail.

**3. Where A and B meet on the VO-compliant path (so file format is not the line).**
`_ingest_votable` first reads the declared groups (A), then always runs `_promote_to_vo_standards`
(UCD and units from column names), `assign_label_column_ucd` and the JD0 comment guess (B). A fully
compliant VOTable is therefore also touched by guesses, and the result does not record which
values were declared. Only the non-VOTable branch is a clean "B only" path (`from_table`, `.dat`).

**4. Writer limits relevant to Ticket 33.**
- The writer takes flat keyword arguments, not the `TimeSys`, `PhotDM` or `CooSys` objects; the
  mapping is in `io._votable_kwargs_from_volc`. The model and the writer are not connected.
- It writes ONE photcal `GROUP` (`phot_def`) for all photometry columns. Products with several
  calibrations (TESS SAP and PDCSAP, as `lc_discovery` issues them) cannot be written by it
  without losing the per-column photcal. A per-column writer is a prerequisite of Ticket 33.
- It contains TESS-specific names (`sectors`, `flux_origins`, `cutout_source`, `mask_mode`) and
  always writes `facility_name` and `instrument_name` params (empty when absent).
- It uses only `astropy.io.votable.tree` (`TimeSys`, `CooSys`, `Group`, `Param`, `FieldRef`).

**5. GAVO.** GAVO is used only to read metadata (`votparse`, `tableparser`, `stanxml`
walkers). Yet `lightcurve.py` imports `gavo.votable` at module top (lines 19 and 20), so importing
`volightcurve` for any purpose, writing included, needs the GAVO packages and `pyOpenSSL`.
Consequence for Ticket 33: the install weight can be removed from a write-only consumer by making
the GAVO import lazy or by placing the reader in its own module; the write path needs no GAVO.
(AGENTS.md prefers GAVO for reading VOTables; this does not change.)

**6. Calibration surface (the "two models" question).** One model, not two:
`PhotCal` holds a `zero_point` (`ZeroPoint`) and a `magnitude_system`; the flat constructor
arguments and the private aliases `_zp_flux`, `_zp_mag`, `_zp_*_unit_text`, `_zp_*_unit_unparsed`
exist for compatibility. `PhotDM` repeats `filter_id`, `filter_name` and `mag0` over its nested
`PhotCal` and `PhotometryFilter`; `PhotCal` also holds a `photometry_filter`, so the filter can be
reached by two paths. Proposal for phase 1: one canonical path (nested objects), aliases deprecated.

**7. Who uses what (outside `volightcurve`).**
- `lc_discovery`: nothing (Ticket 33).
- Host app `lc_bridge`: `VOLightCurve`, `PhotCal`, column discovery helpers,
  `assign_photometry_column_semantics`, `is_magnitude_phot_column`, `write_vo_lightcurve`,
  `io.read/write/assemble`, `read_dat_table`, `narrative_file_comments`,
  `normalise_table_epoch_to_absolute_jd`, `export_absolute_jd_as_time_offset`, unit codec.
- Host `lc_config`: `photcal_defaults` and `JD_TO_MJD`, `TIME_OFFSET_ABSOLUTE_JD_THRESHOLD`.
- Host `photcal_coherence.py`: `photcal_defaults`. It FILLS an incomplete zero-point pair with the
  defaults and warns, which is against the fail-fast rule and the principles of this ticket; it is
  a host decision to revisit separately, but it is the reason `photcal_defaults.py` cannot just be deleted.
- Host `curve_dash`, `mission_config/tess`: unit codec. `gp/flux`, `gp/plot_data`: `PhotCal`,
  `PhotCalError`. `lc_discovery_load`: `VOLightCurve`, `time_offset_to_absolute_jd`.
- Private names used by scripts and tests: `extract_photdm`, `extract_timesys_metadata_from_gavo`,
  `_gavo_votable_tree_from_source`. The package exports with `from .lightcurve import *`, so the
  public surface is partly accidental.

**8. Proposed decisions for phase 1 (to discuss, none taken).**
1. Representation of absence and provenance: a small marker per attribute (declared, inferred with
   rule and evidence, absent), kept beside the value, not in a parallel model.
2. Remove every invented default in section 2; `TimeSys` and `CooSys` fields become optional with
   `None` as absent; `timeorigin` 0 and absent become distinguishable.
3. One writer that takes the model (time system, coordinate system, one photcal per column) and
   writes only what is declared; the flat-keyword function stays as a thin wrapper if still needed.
4. A reader with an explicit mode: strict (no part B) and tolerant (part B, with provenance).
   `_ingest_votable` stops running B on top of declared data in strict mode.
5. Check methods: `missing_for(operation)` style answers for time, coordinates and calibration,
   built on the existing `conversion_problems`.
6. `photcal_defaults.py` and the host fill in `photcal_coherence.py`: keep in the host only, or
   remove; the library must not offer defaults.
7. Public surface: an explicit `__all__` for core and for interpretation; GAVO import lazy.
8. Behaviour tests (characterisation) to add BEFORE any change: round trip of an absent time
   system, an absent calibration, `timeorigin` 0 versus absent, per-column photcal, one entry point
   per default of section 2.

**Not checked in phase 0.** `PhotometryFilter` internals; `io.py` read path beyond the facade;
whether existing tests depend on the invented defaults (to be answered by the characterisation tests).

### Ticket 32, addendum B (2026-10-22): phase 1 decisions (agreed in discussion; still no code)

This replaces the "provenance states" idea of the first text and of addendum A section 8. Every
later phase is still discussed before it starts.

**Principles after discussion.**
1. A value is present or `None` (absent). There are no declared, inferred or assumed states in the
   model or in the XML. The product is a compliant VOTable that carries values and descriptions
   only. A value that the user sets is the user's responsibility.
2. Interpretation never invents. It reads evidence the file already contains in a loose form: the
   `KEY=value` comments (`JD0`, `FILTER`, `PERIOD`, `EPOCH`, `ZP_*`), and column roles taken from
   column names (agreed: this belongs in the interpretation part). Whatever it interpreted adds a
   plain sentence to the description of the product (as the photometry source sentence of
   Ticket 30). The sentences travel as description text through `CurveDash` and export.
3. Reasonable defaults are never written by the library on its own. They exist as a table of
   SUGGESTIONS (plain data, with a one-line reason each) that a host UI or an agent shows to the
   user. The user applies them, edits them, or overwrites a declared value, through an explicit
   action (an input or a button such as "fill the empty fields"). Named profiles are not needed
   now; one suggestion table is enough.
4. Automatic interpretation fills only what is absent and never overwrites a declared value
   (today `_pickup_jd0_from_table` overwrites a declared `timeorigin` of 0). Only an explicit user
   action overrides a value.
5. Absent and zero differ: `timeorigin` 0 is a value, `None` is absence.

**Suggestion table (values agreed).** Time system: reference position HELIOCENTER, time scale UTC,
time origin 0 (for hand-made legacy data). Calibration: reference magnitude `mag0` = 0 (the
earlier library constant was 20.0; the change affects every flux derived from a magnitude by the
suggestion, and the host tests that assert the old constants, see Ticket 34), zero point flux
1.0 dimensionless, magnitude system Vega. These come from `photcal_defaults.py` and from the
invented defaults listed in addendum A section 2; `photcal_defaults.py` is replaced by the
suggestion table.

**Decisions.**
1. No provenance states (see principles).
2. Remove every invented default in addendum A section 2 from the core: `TimeSys` and `CooSys`
   fields optional, `PhotDM.filter_id` and `mag0` return `None`, the writer writes a `TIMESYS`
   only when a time system is declared, and the two writer entry points stop disagreeing.
3. One writer that takes the model: time system, coordinate system, one photcal per column,
   only what is present, description sentences appended. The flat-keyword function remains a thin
   wrapper or is deprecated (decide in the phase that does it).
4. The reader never invents, so tolerant reading (evidence from comments and names, with
   description sentences) can stay the default and no breaking change is needed. A strict mode
   (no reading of names and comments) is kept for tests and for validating products issued by
   `lc_discovery` (Ticket 33).
5. Check methods: for each operation, what is missing (time system, coordinate system,
   calibration per column), built on `conversion_problems`. They are plain data for the host and
   for agents.
6. Suggestion table and check methods are data only; they change nothing.
7. Explicit public surface (`__all__` for core and interpretation); GAVO import lazy, so that a
   write-only consumer does not need GAVO.
8. Characterisation tests before any change (absent versus 0 `timeorigin`, absent calibration,
   per-column photcal, one test per invented default of addendum A section 2).

## Ticket 34 (DRAFT, 2026-10-22): host app: no automatic filling of calibration; ask the user

**DRAFT. To be discussed before any code. Depends on Ticket 32 (suggestion table in
`volightcurve`); the host can use a local copy of the suggestions until then.**

**Rule (developer).** The application never fills missing zero points or other metadata on its
own. It shows what is missing and what the suggested values are, and the user decides, with an
input or a button.

**What we have.**
- `lightcurve_processor.py`, section Calibration: already the right pattern. The editor shows the
  fields; the "defaults" action (`fill_missing_photcal_form_values`) only completes EMPTY
  zero-point fields in the form and never overwrites file values; "Apply calibration" writes them
  into the curve. Nothing changes except the suggested constants (`mag0` 0).
- `gp_for_oc.py` (callback around line 4218): calls `reconcile_photcal_dict` automatically on
  ingest; an incomplete zero-point pair is filled from `photcal_defaults` (1.0, 20.0, Vega) and a
  warning is shown in `gp-lc-photcal-alert`. A warning after the fact is not enough (developer).
  `reconcile_photcal_dict` also does other things (unit reconciliation; flux column wins on a unit
  mismatch), which are not about defaults and need a separate look.
- `lc_config.py` (`DEFAULT_REFERENCE_MAG`, `DEFAULT_ZP_FLUX_DIMENSIONLESS`) and
  `test_extrema_modeller_grid.py` assert the old constants.

**Proposal (to be discussed).**
- `gp_for_oc.py` stops filling on ingest. If the calibration cannot convert, the page shows what
  is missing (check methods) and a button "Use suggested zero points" that applies the suggestion
  table to the empty fields only, or the user types values; the GP actions that need the
  conversion stay disabled until then, with an explicit message. Same wording and pattern as the
  Calibration section of the processor, ideally the same component.
- The `mag0` suggestion becomes 0. Before changing it: check which host numbers depend on it
  (GP length-scale guess, flux display scales, tests), because flux derived from magnitudes
  with zero point 0 is a very small number for a star of magnitude 12.
- The separate parts of `reconcile_photcal_dict` (unit reconciliation) stay, or move to
  `volightcurve` where they belong; decide with Ticket 32.

**Not in scope.** The processor Calibration section (already correct), `lc_discovery`.

### Ticket 32 addendum B and Ticket 34: update 2026-10-22 (suggestion values for observers' files)

**Ground truth (developer).** Compliant providers deliver flux with `zp_flux`, the flux of a
magnitude-0 star, so `mag0` is silently 0. Observers' ASCII files almost always carry calibrated
magnitudes; flux is only needed when an operation asks for it.

**Suggestion table for observers' files (agreed; it is a suggestion, never applied by the library).**
- Magnitude system: Vega.
- Flux scale: relative flux, dimensionless (no physical unit).
- `mag0` (reference magnitude): 0.
- `zp_flux`: 1.0 (dimensionless): a magnitude-0 star has relative flux 1. Chosen over a Jy or
  counts per second value because a physical unit with a zero point of 1 would claim a calibration
  nobody made. The flux is then comparable only within this light curve.
- Time system (legacy hand-made data): HELIOCENTER, UTC, origin 0 (unchanged).
- The values replace the old 20.0 reference magnitude; old tests that assert the old constants are
  changed, with the reason noted in the test and here.

**Possible later additions (not now).** AB magnitudes with flux in Jy (zero point 3631 Jy for every
band) when the user states the system; Vega zero points per filter from a lookup by filter
identifier (for example the SVO Filter Profile Service).

**Consequence to check (Ticket 34).** Relative flux of a magnitude-12 star is about 1.6e-5.
Look at the GP length-scale guess, flux display scales and any thresholds in the host that assume
flux of order 1 or larger; normalise for display or modelling where needed.

**User prompt (proposal, not yet confirmed).** A user working only in magnitudes is never asked.
When an operation needs the magnitude to flux conversion and the calibration is incomplete, the
page shows what is missing and offers the suggestion as an explicit choice, for example "Relative
flux, Vega magnitudes (magnitude 0 = 1, no physical units)" and "Enter my own zero point", with the
consequence stated in plain words. The wording is deliberately visible ("scare them a little").

### Ticket 32: phase 0 characterisation tests (2026-10-22)

Added `volightcurve/tests/test_characterisation_current_behaviour.py` (27 tests; the package suite
is now 76 passed, was 49). Nothing in `src/` changed. The tests pin the behaviour of baseline
`v0.1.0`:
- `KEEP` tests: behaviour in line with the agreed principles (conversion without zero points
  raises `PhotCalError` and `conversion_problems` lists what is missing; an absent `COOSYS` stays
  `None` and is not written; absent zero points are not written; one calibration per column is
  read from several photcal groups; a declared `TIMESYS` is read exactly; `JD0` and `ZP_FLUX`
  comments are read as evidence; roles from names are applied and recorded). They must stay true.
- `INVENTED` tests: current invention, numbered as in addendum A section 2. They pass today and
  are EXPECTED TO FAIL when phase 2 removes the invention; each is then rewritten to assert the new
  behaviour (absent as `None`, no element written) with the reason noted. A failing `INVENTED`
  test is a signal, not a regression.
- Limit and mixed tests: one photcal group for all photometry columns (the writer limit for
  Ticket 33); name-based UCD assignment on a compliant VOTable; the absolute-JD threshold.

**Correction to addendum A, section 2, item 2.** A declared `TIMESYS` with missing attributes is
NOT read as HELIOCENTER and UTC. The GAVO parser supplies its own defaults, so it is read as
`UNKNOWN`, `UNKNOWN` and origin 0.0 (the HELIOCENTER and UTC fallbacks in
`_timesys_from_gavo_attrs` are not reached on this path). The string `UNKNOWN` is the VOTable
vocabulary's own marker and is not an invention by `volightcurve`; the origin 0.0 still is. The
test records this. The "no `TIMESYS` at all" case does give HELIOCENTER, UTC and 0.0 as written.

**New fact from the tests.** Absent calibration does not survive a round trip: the writer always
writes `magnitudeSystem` Vega, and the reader returns a `PhotCal` with magnitude system Vega, no zero
points, and filter identifier "" (an empty string, not `None`) for a file in which none of these was
declared. Phase 2 must fix both ends.

Not run: tests of the host app (no code there changed). The new file uses only fixtures built
inside the module, no network.

### Ticket 32: developer corrections of 2026-10-22 (recorded before decision 3)

1. BARYCENTER and TCB must not be defaults anywhere, including the writer. A time system is
   written only if it is declared.
2. `facility_name` and `instrument_name` are desirable, not obligatory. When empty they are not
   written (today they are always written empty; pinned by an `INVENTED` test).
3. "One photcal group for all photometry columns" is a BIG MISTAKE of the writer. Correct model:
   different columns may share one photcal, including several flux columns and a flux with its
   error (the shared reference is the hint "this error belongs to that flux"); a table may hold
   several photcal groups; a column may have no photcal at all, and no photcal is required for
   all columns. Today the writer links only the photometry column and never the error column
   (a new `LIMIT` test pins this: package suite 77 passed).

### Ticket 32: decision 3 discussion, round 1 (2026-10-22)

**Checked against the standard.** VOTable 1.4 schema (`VOTable.v1.4.xsd` shipped with astropy):
`TIMESYS` has `ID` required, `timescale` required, `refposition` required (no schema default),
and `timeorigin` "MUST be given unless the time's representation contains a year of a calendar
era" (values: a number, or `JD-origin` / `MJD-origin`). The IVOA vocabularies of `timescale` and
`refposition` (ivoa.net/rdf) both contain the term `UNKNOWN`. So the earlier statement "refposition
and timescale default to UNKNOWN" was wrong for the schema: they are required, and `UNKNOWN` is a
legal vocabulary value. The `UNKNOWN` seen on reading comes from the GAVO parser. Consequence:
an unknown time scale or reference position is written as `UNKNOWN`; an unknown `timeorigin`
has no valid representation (see open question in the next round).

**Developer decisions of this round.**
- Every flux, magnitude and error column is tied to a photometric calibration (`PhotDM`), possibly
  an empty one; ONE empty calibration may be shared by all of them. (This withdraws the proposal
  to create entries only where a calibration is declared.)
- The writer references the error column in the same photcal group as its flux.
- The title of the table is part of what the writer takes.
- All parameters present in the ingested table (a compliant VOTable, or the agreed parameters
  from commented rows of an ASCII file) are written as table PARAMs; no closed list. Mission names
  (`sectors`, `flux_origins`, `cutout_source`, `mask_mode`) leave the core writer.
- A calibration with nothing declared is NOT dropped: the existing "absent value" convention is
  used (which one exactly is an open question).
- The group count follows the calibrations: columns with the same calibration share one `GROUP`;
  extra groups appear only when calibrations really differ (for example SAP and PDCSAP).

### Ticket 32: decision 3 discussion, round 2 (2026-10-22)

**Developer.** TESS SAP and PDCSAP have the same photcal. An unknown `timeorigin` means no `TIMESYS`
is written (agreed).

**Check of the TESS provider (`lc_discovery`).** It writes one `GROUP` per flux column
(`photcal_<flux column>`), but for the SPOC family (electron per second) the payload of SAP and
PDCSAP is identical (same filter, magnitude system and zero points from `config`), so one shared
calibration is enough. The background columns use a different one (filter only, no zero points).
Two other cases (`ZP_MAG_TESSMAG`, `_unknown_flux_photcal`) can give a column its own calibration.
For Ticket 33 pilot: one calibration object for SAP, PDCSAP and their errors, and a separate
filter-only one for background. Sharing is by calibration object (explicit); the writer does not
merge groups that merely look alike.

**Absent-value convention (selected).** In memory: `None`. On the wire, by datatype:
- `double` PARAM or FIELD: `NaN` (the VOTable null for floating point; both readers accept it).
- `char` PARAM: the empty string.
The reader maps `NaN` and `""` back to `None`. Not used: `""` for a `double` (the present reader
fails with `ValueError: could not convert string to float`), `NaN` for text.
Checked with a small VOTable through the present reader: `NaN` zero points are read as
`Quantity(nan)`, not `None`, and an empty `magnitudeSystem` is read as "Vega". Both reader
behaviours must be fixed in phase 2 (map to `None`; never replace an empty magnitude system).

### Ticket 32: decision 3, round 3: target XML layout (2026-10-22, DRAFT for review)

Derived from the agreed rules. Both examples parse with astropy and with the present reader. The
XSD validation was NOT run (`lxml` is not installed here). They are examples of what the new
writer should produce, not a specification.

**Rules behind the examples.**
- One `GROUP name="photcal"` per distinct calibration object. Every flux, magnitude and error
  column carries `ref` to its group and is listed as `FIELDref` in it; columns that share a
  calibration share the group; one empty calibration may serve all.
- A group always carries the four core PARAMs: `filterIdentifier` (char), `zeroPointFlux`
  (double), `zeroPointReferenceMagnitude` (double, unit `mag`), `magnitudeSystem` (char). An absent
  value is `NaN` (double) or `""` (char). A `unit` attribute on an absent value is not written,
  except `mag` on the magnitude, which is fixed by the definition. Optional PARAMs
  (`filterName`, `effectiveWavelength`, ...) are written only when present.
- `TIMESYS` only when declared, and only with a known `timeorigin`; `refposition` and `timescale`
  are written as `UNKNOWN` when unknown. A time column has a `ref` only when a `TIMESYS` exists.
- No `COOSYS` unless declared. No `facility_name` or `instrument_name` when empty. Any other
  table parameter present in the ingested table is written as a table `PARAM`.

**Example A: TESS-like product (SAP and PDCSAP share one calibration with their errors;
background has a filter-only calibration).**
```xml
<RESOURCE>
  <TIMESYS ID="ts" refposition="BARYCENTER" timeorigin="2457000" timescale="TDB"/>
  <GROUP ID="photcal_target" name="photcal">
    <PARAM name="filterIdentifier" datatype="char" arraysize="*" utype="photDM:PhotometryFilter.identifier" value="TESS/TESS.Red"/>
    <PARAM name="zeroPointFlux" datatype="double" unit="electron s-1" utype="photDM:PhotCal.zeroPoint.flux.value" value="1.0"/>
    <PARAM name="zeroPointReferenceMagnitude" datatype="double" unit="mag" utype="photDM:PhotCal.zeroPoint.referenceMagnitude.value" value="20.44"/>
    <PARAM name="magnitudeSystem" datatype="char" arraysize="*" utype="photDM:PhotCal.magnitudeSystem.type" value="Vega"/>
    <FIELDref ref="sap_flux"/><FIELDref ref="sap_flux_err"/>
    <FIELDref ref="pdcsap_flux"/><FIELDref ref="pdcsap_flux_err"/>
  </GROUP>
  <GROUP ID="photcal_background" name="photcal">
    <PARAM name="filterIdentifier" datatype="char" arraysize="*" utype="photDM:PhotometryFilter.identifier" value="TESS/TESS.Red"/>
    <PARAM name="zeroPointFlux" datatype="double" utype="photDM:PhotCal.zeroPoint.flux.value" value="NaN"/>
    <PARAM name="zeroPointReferenceMagnitude" datatype="double" unit="mag" utype="photDM:PhotCal.zeroPoint.referenceMagnitude.value" value="NaN"/>
    <PARAM name="magnitudeSystem" datatype="char" arraysize="*" utype="photDM:PhotCal.magnitudeSystem.type" value="Vega"/>
    <FIELDref ref="sap_bkg"/>
  </GROUP>
  <TABLE name="TIC 394179296 sector 14">
    <FIELD ID="time" name="time" datatype="double" ucd="time.epoch" unit="d" ref="ts"/>
    <FIELD ID="sap_flux" name="sap_flux" datatype="double" ucd="phot.flux;em.opt" unit="electron s-1" ref="photcal_target"/>
    <FIELD ID="sap_flux_err" name="sap_flux_err" datatype="double" ucd="stat.error;phot.flux;em.opt" unit="electron s-1" ref="photcal_target"/>
    <FIELD ID="pdcsap_flux" name="pdcsap_flux" datatype="double" ucd="phot.flux;em.opt" unit="electron s-1" ref="photcal_target"/>
    <FIELD ID="pdcsap_flux_err" name="pdcsap_flux_err" datatype="double" ucd="stat.error;phot.flux;em.opt" unit="electron s-1" ref="photcal_target"/>
    <FIELD ID="sap_bkg" name="sap_bkg" datatype="double" ucd="phot.flux;em.opt" unit="electron s-1" ref="photcal_background"/>
    <!-- DATA ... -->
  </TABLE>
</RESOURCE>
```

**Example B: observer's file with two columns of magnitudes and nothing declared (no time system,
one empty calibration shared by the magnitude and its error).**
```xml
<RESOURCE>
  <GROUP ID="photcal" name="photcal">
    <PARAM name="filterIdentifier" datatype="char" arraysize="*" utype="photDM:PhotometryFilter.identifier" value=""/>
    <PARAM name="zeroPointFlux" datatype="double" utype="photDM:PhotCal.zeroPoint.flux.value" value="NaN"/>
    <PARAM name="zeroPointReferenceMagnitude" datatype="double" unit="mag" utype="photDM:PhotCal.zeroPoint.referenceMagnitude.value" value="NaN"/>
    <PARAM name="magnitudeSystem" datatype="char" arraysize="*" utype="photDM:PhotCal.magnitudeSystem.type" value=""/>
    <FIELDref ref="mag"/><FIELDref ref="mag_err"/>
  </GROUP>
  <TABLE name="observer file">
    <FIELD ID="jd" name="jd" datatype="double" ucd="time.epoch" unit="d"/>
    <FIELD ID="mag" name="mag" datatype="double" ucd="phot.mag" unit="mag" ref="photcal"/>
    <FIELD ID="mag_err" name="mag_err" datatype="double" ucd="stat.error;phot.mag" unit="mag" ref="photcal"/>
    <!-- DATA ... -->
  </TABLE>
</RESOURCE>
```

**What the present reader does with these (to be fixed in phase 2).** Example A is read as
intended: all five columns get a calibration, errors included, and the time system is TDB,
BARYCENTER, 2457000. Absent values come back as `Quantity(nan)` and the empty magnitude system as
"Vega"; in example B the missing time system comes back as HELIOCENTER, UTC, 0.0. In both cases the
target is `None` (and no time system in B).

**Open for the developer.**
- Is the fixed set of four PARAMs in every group acceptable, or should absent ones be omitted?
- `TIMESYS` of a TESS product: does `lc_discovery` keep writing BARYCENTER, TDB, origin 2457000
  (TESS BTJD) as today? (Not a writer decision; the provider declares it.)

### Ticket 32: decision 3, round 4: corrected target XML (2026-10-22, DRAFT)

Corrected after the developer pointed to a real export (`lc_discovery_TIC_394179296_SPOC_sector_54.xml`).

**Example A (single TESS series; a table with several series simply has more FIELDs and, where calibrations differ, more groups).**
```xml
<?xml version="1.0" encoding="utf-8"?>
<VOTABLE xmlns="http://www.ivoa.net/xml/VOTable/v1.3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="1.4" xsi:schemaLocation="http://www.ivoa.net/xml/VOTable/v1.3 http://www.ivoa.net/xml/VOTable/VOTable-1.4.xsd">
  <DESCRIPTION>One photometry series ... (text of the export description)</DESCRIPTION>
  <RESOURCE type="results">
    <TIMESYS ID="ts" refposition="BARYCENTER" timeorigin="2400000.5" timescale="TDB"/>
    <GROUP ID="photcal_target" name="photcal">
      <PARAM ID="photcal_target_filterIdentifier" arraysize="*" datatype="char" name="filterIdentifier" ucd="meta.id;instr.filter" utype="photDM:PhotometryFilter.identifier" value="TESS/TESS.Red"/>
      <PARAM ID="photcal_target_zeroPointFlux" datatype="double" name="zeroPointFlux" ucd="phot.flux;arith.zp" unit="electron.s-1" utype="photDM:PhotCal.zeroPoint.flux.value" value="1"/>
      <PARAM ID="photcal_target_zeroPointReferenceMagnitude" datatype="double" name="zeroPointReferenceMagnitude" ucd="phot.mag;arith.zp" unit="mag" utype="photDM:PhotCal.zeroPoint.referenceMagnitude.value" value="20.44"/>
      <PARAM ID="photcal_target_magnitudeSystem" arraysize="*" datatype="char" name="magnitudeSystem" ucd="meta.code" utype="photDM:PhotCal.magnitudeSystem.type" value="Vega"/>
      <PARAM ID="photcal_target_filterName" arraysize="*" datatype="char" name="filterName" ucd="meta.id;instr.filter" utype="photDM:PhotometryFilter.name" value="TESS/TESS.Red"/>
      <PARAM ID="photcal_target_effectiveWavelength" datatype="double" name="effectiveWavelength" ucd="em.wl.effective" unit="m" utype="photDM:PhotometryFilter.spectralLocation.value" value="7.453e-07"/>
      <FIELDref ref="flux" utype="adhoc:location"/>
      <FIELDref ref="flux_err" utype="adhoc:location"/>
    </GROUP>
    <TABLE ID="TIC_394179296_SPOC_sector_54" name="TIC 394179296 SPOC sector 54">
      <DESCRIPTION>The same description text as above, for the table.</DESCRIPTION>
      <FIELD ID="jd" datatype="double" name="jd" ref="ts" ucd="time.epoch" unit="d"/>
      <FIELD ID="flux" datatype="double" name="flux" ref="photcal_target" ucd="phot.flux;em.opt" unit="electron.s-1"/>
      <FIELD ID="flux_err" datatype="double" name="flux_err" ref="photcal_target" ucd="stat.error;phot.flux;em.opt" unit="electron.s-1"/>
      <PARAM ID="ra" datatype="double" name="ra" ucd="pos.eq.ra" value="289.774789454911"/>
      <PARAM ID="dec" datatype="double" name="dec" ucd="pos.eq.dec" value="38.3667924544941"/>
      <PARAM ID="period" datatype="double" name="period" ucd="src.var;time.period" unit="d" value="0.73095"/>
      <PARAM ID="name" arraysize="*" datatype="char" name="name" ucd="meta.id" value="TIC 394179296 SPOC sector 54"/>
      <!-- DATA, BINARY or TABLEDATA -->
    </TABLE>
  </RESOURCE>
</VOTABLE>
```

**Example B (observer file, nothing declared).**
```xml
<?xml version="1.0" encoding="utf-8"?>
<VOTABLE xmlns="http://www.ivoa.net/xml/VOTable/v1.3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="1.4" xsi:schemaLocation="http://www.ivoa.net/xml/VOTable/v1.3 http://www.ivoa.net/xml/VOTable/VOTable-1.4.xsd">
  <DESCRIPTION>Observer file read with column roles taken from the column names: mag as magnitude, jd as time.</DESCRIPTION>
  <RESOURCE type="results">
    <GROUP ID="photcal" name="photcal">
      <PARAM ID="photcal_filterIdentifier" arraysize="*" datatype="char" name="filterIdentifier" ucd="meta.id;instr.filter" utype="photDM:PhotometryFilter.identifier" value=""/>
      <PARAM ID="photcal_zeroPointFlux" datatype="double" name="zeroPointFlux" ucd="phot.flux;arith.zp" utype="photDM:PhotCal.zeroPoint.flux.value" value="NaN"/>
      <PARAM ID="photcal_zeroPointReferenceMagnitude" datatype="double" name="zeroPointReferenceMagnitude" ucd="phot.mag;arith.zp" unit="mag" utype="photDM:PhotCal.zeroPoint.referenceMagnitude.value" value="NaN"/>
      <PARAM ID="photcal_magnitudeSystem" arraysize="*" datatype="char" name="magnitudeSystem" ucd="meta.code" utype="photDM:PhotCal.magnitudeSystem.type" value=""/>
      <FIELDref ref="mag" utype="adhoc:location"/>
      <FIELDref ref="mag_err" utype="adhoc:location"/>
    </GROUP>
    <TABLE ID="observer_file" name="observer file">
      <DESCRIPTION>Observer file read with column roles taken from the column names: mag as magnitude, jd as time.</DESCRIPTION>
      <FIELD ID="jd" datatype="double" name="jd" ucd="time.epoch" unit="d"/>
      <FIELD ID="mag" datatype="double" name="mag" ref="photcal" ucd="phot.mag" unit="mag"/>
      <FIELD ID="mag_err" datatype="double" name="mag_err" ref="photcal" ucd="stat.error;phot.mag" unit="mag"/>
      <!-- DATA -->
    </TABLE>
  </RESOURCE>
</VOTABLE>
```

**What the first examples forgot (seen in the real export).**
- `DESCRIPTION` at the VOTABLE level and in the TABLE (the title of the table is the `TABLE`
  `name`; the descriptions carry the sentences of interpretation and of the photometry source).
- `RESOURCE type="results"`, the `xsi:schemaLocation` on `VOTABLE`.
- `ID` and `ucd` on every PARAM (`meta.id;instr.filter`, `phot.flux;arith.zp`, `phot.mag;arith.zp`,
  `meta.code`, `em.wl.effective`), and `utype` as in the real file; the optional PARAMs `filterName`
  and `effectiveWavelength` (present because the provider configuration supplies them).
- `FIELDref utype="adhoc:location"`.
- Unit strings on the wire are `electron.s-1` (the unit codec), not `electron s-1`.
- The `TIMESYS` of the real TESS product is BARYCENTER, TDB, **timeorigin 2400000.5** (the provider
  writes the time as an MJD-like offset), not 2457000 as written in the first example. Time system
  and photcal values are the provider's, taken from its configuration; the writer writes what the
  model carries.
- Table PARAMs carry `ID`, `ucd` and, where known, a `DESCRIPTION`.

**Seen in the real file, to decide (not changed).**
- `flux_err` has no `ref` and is not in the photcal group (the error-link rule fixes this).
- `epoch` is written as `value="0"` with `ref="ts"` while `period` is 0.73095. A zero epoch looks
  like a value nobody declared; where it comes from (host export) was not traced.
- Both `filter` (table PARAM) and `filterName` (group PARAM) carry the filter; `facility_name` and
  `instrument_name` are written empty (to be dropped); `title` ("Display title for the lightcurve
  figure") and `name` are written as table PARAMs. With "all parameters of the table are PARAMs"
  these four come from `table.meta`; display-only ones such as `title` should probably not be
  exported.
- The data are `BINARY`; the examples above use a placeholder.

### Ticket 32: decision 3, round 5: units on the wire (2026-10-22)

**Developer.** The provider's time system stays as configured (MJD-like offsets are for the user;
the main rule is a correct `timeorigin`, always). The items `epoch` 0, `filter` next to
`filterName`, empty `facility_name` and `instrument_name`, and the display-only `title` are
decisions of the PROVIDER and are out of scope here. Units must be compliant with VOUnits 1.1
(REC, 2023-12-15).

**What VOUnits 1.1 says (read from the document).**
- Product of units: only the period `.` (not whitespace, not `*`); no whitespace anywhere;
  division with `/` (at most one at top level); powers as `s-1` or `s**-1`.
- `electron.s-1` is therefore correct syntax; `electron s-1` is not valid.
- `electron` is NOT a known unit (only `eV`, electron volt). Unknown units are syntactically
  allowed, and a library "should not unilaterally reject" them; only a unit starting with a
  decimal prefix would need quoting, which `electron` does not. Known "concept" units are `count`
  / `ct`, `photon` / `ph`, `adu`; the document itself notes that counts and photons are concepts
  better carried by the UCD than by the unit.
- The empty string is NOT a valid unit string (change of 1.1). `1` positively indicates a
  dimensionless quantity. An application may read an empty string as dimensionless, unknown or
  an error, but the writer should not rely on it.
- `unknown` and `UNKNOWN` are reserved for "the unit is lost"; an absent `unit` attribute is also
  possible.

**What volightcurve does today (pinned by two characterisation tests, suite 79 passed).**
- `VO_DIMENSIONLESS_WIRE = ""`: a dimensionless zero point flux is written as `unit=""`, the
  pre-1.1 reading. Phase 2: write `1`.
- `to_internal(Unit dimensionless)` and `to_internal("")` give `None`, but `to_internal("1")`
  gives `"1"`. Phase 2: all of `1`, `""`, `---` and the dimensionless `Unit` read as `None`.
- Unit strings are not validated: `"electron s-1"` passes unchanged. astropy's own VOUnit
  formatter raises for `electron` (not part of the standard) and the codec falls back to the text.

**Proposal (to discuss).**
1. Keep `electron.s-1` as the provider's choice: valid syntax, an unknown but allowed unit.
2. A check method on units (per column and per PARAM): reports whitespace or `*` products,
   empty strings, `unknown` and units that are not in the VOUnits table (informative, not an error),
   with the wording of the standard.
3. Write dimensionless as `1`; an absent or unknown unit: no `unit` attribute. Never write `""`.
4. The suggestion table: relative flux has unit `1`.
**Decision (2026-10-22): the four points above are ACCEPTED by the developer.** Implementation
stays in Ticket 32 phase 2; the two OUTDATED unit tests are rewritten then.

**Decision (2026-10-22): the host asks the user for calibration only when a conversion needs it.**
ACCEPTED by the developer (Ticket 34). The fixed-or-omitted PARAM question is still open.

**Decision (2026-10-22): absent PARAMs are omitted from the photcal group.** ACCEPTED by the developer.
This replaces the earlier round 4 example of writing `NaN` and `""` for absent values in the
empty calibration of an observer file: such a group now holds no value PARAMs, only the
`FIELDref` links. The reader maps a missing PARAM to `None`. The `NaN`/`""` reading stays
only for tolerance of files written by older versions (to be confirmed in phase 2).

### Ticket 32: decision 3, round 6: PARAMref in the photcal group (2026-10-22)

Reference file: `data/o.xml` (DaCHS, OGLE, VOTable 1.5). Developer instruction: the reader MUST
understand this layout; the writer is NOT forced to copy it; the MIVOT block at the end is ignored.

What the file shows (checked):
- `TIMESYS ID="ts"` and `GROUP ID="phot_def" name="photcal"` sit at RESOURCE level, before the TABLE.
- The group holds one inline `PARAM` (`magnitudeSystem` = Vega), one `FIELDref` (`phot`,
  `utype="adhoc:location"`) and three `PARAMref` (`fps_filter_id`, `zeropoint`, `ssa_specmid`).
- The referenced values are ordinary table-level `PARAM`s with an `ID`. The link is by the
  `utype` on the `PARAMref` (`photDM:...`; the case differs between files, so match
  case-insensitively).
- `mag_err` has no `ref` and no `FIELDref`: an error column without its own link (the LIMIT test).
- The zero point is in `Jy` (a flux zero point of a magnitude, `zp_mag` absent).

Current behaviour: `read_lightcurve` already resolves this file: `photdms["phot"]` has
`zp_flux=2415.65 Jy`, filter `Generic/Bessell.I`, spectral location `8.02e-07 m`, Vega,
and the `TIMESYS` (UTC, HELIOCENTER, 2400000.5). So the PARAMref route works today.

Consequences for phase 2 (to keep, not to change):
1. Reader: a photcal value may be an inline `PARAM` OR a `PARAMref` to a table-level `PARAM`.
   Both give the same calibration. A missing one gives `None`.
2. Reader: unknown parts of the file (MIVOT, other `GROUP`s) are ignored without a warning.
3. Writer: stays with inline `PARAM`s (round 4); no MIVOT.
4. A characterisation test on `o.xml` (copied into the test data) is proposed, as a KEEP test.
   Not written yet; waiting for your word.

**Round 6 test added (2026-10-22):** `tests/test_characterisation_current_behaviour.py` has three
tests on the file `tests/data/ogle_dachs_paramref.xml` (a copy of `data/o.xml`): PARAMref values
resolved, TIMESYS read as declared, error column without calibration. Suite: 82 passed.

**Decisions (2026-10-22):** (1) the reader keeps accepting the old `NaN` and `""` PARAMs from
files of earlier versions (read as `None`). (2) The flat writer function stays for one release as a
deprecated wrapper over the new writer; its docstring is marked deprecated. Open points for
phase 2 are now closed; step 1 (absent stays `None`) waits for your word to start.

### Ticket 32: phase 2, step 1 done in `volightcurve` (2026-10-22), host not adapted

Changes (uncommitted, in `volightcurve/src`): `TimeSys()` and `MagnitudeSystem()` hold `None`;
`PhotCal(mag_sys=None)`; `PhotDM.filter_id` and `mag0` return `None` without data;
`_pickup_jd0_from_table` returns `None`; a `TIMESYS` without `timeorigin` reads `None` (0 stays
0.0); the reader reads `NaN` and `""` PARAMs as `None` (`_declared_float`, `_declared_text`),
and no longer invents `filter_id=""` or `spectral_location=0.0`; `time_offset_to_absolute_jd`
and `absolute_jd_to_time_offset` raise `ValueError` when an offset needs an undeclared origin.
`UNKNOWN` in `refposition` and `timescale` comes from the GAVO parser (IVOA vocabulary term)
and is kept as it is. Tests: `test_invented_1` to `5` rewritten as `test_absent_*`, two added;
`volightcurve` suite 84 passed. The writer is untouched (step 2).

Host effect (checked): before the change the host suite passed (661). After it, 11 tests fail,
all by one cause: `lc_bridge.py` line 1786 `volc.timesys.timescale.lower()` on a file that
declares no time scale (`.dat` uploads and similar). Related: line 1304 `jd0 or 0.0` and the
`+ JD_TO_MJD` guess just below it hide an absent origin. Both belong to Ticket 34 (ask the
user, no silent fill); not patched, because that is a design decision for the host.
### Ticket 32: phase 2, step 2 done in `volightcurve` (2026-10-22): the writer

Changes (uncommitted): `write_vo_lightcurve` has no time or magnitude-system defaults.
`TIMESYS` is written only when `timeorigin` is known (declared position or scale without an
origin are dropped with a warning; an origin without position or scale writes the vocabulary
term `UNKNOWN`). `magnitudeSystem` is written only when declared. New argument `photdms`
(column name to `PhotDM`): one `GROUP name="photcal"` per distinct `PhotDM` object, holding only
declared PARAMs and a `FIELDref` for each of its columns (flux and error may share one); an empty
calibration still gives a group; unlisted photometry columns share one empty group; unlisted
error columns stay unlinked (pairing by name is interpretation, step 5). The flat calibration
arguments remain for one release and are marked DEPRECATED in the docstrings; they cannot be
combined with `photdms`. `facility_name` and `instrument_name` are written only with a value.
`VOLightCurve.write_votable` takes the time system and `photdms` from the instance. In `io.py`
an unknown origin stays `None` through `write_lightcurve`.
Tests: `test_invented_6_*` rewritten as `test_written_*`, new `photdms` tests; `volightcurve`
suite 90 passed. Host: the same 11 failures as after step 1 (cause unchanged, `lc_bridge.py`
line 1786). `lc_discovery`: 222 passed, 4 failed in `test_lc_providers_cone_search_live.py`
(live cone search; network, not related to this change, not investigated).
Not done yet: units on the wire (step 3), the TESS PARAM IDs of the round 4 example (the
writer writes PARAMs without `ID`), and name-based UCD fallback `phot`/`mag`/`flux` in the writer
(interpretation, step 5).
### Ticket 32: phase 2, step 3 done in `volightcurve` (2026-10-22): units on the wire

Changes (uncommitted): `VO_DIMENSIONLESS_WIRE` is `"1"`; `to_wire(None)` gives `1`; the export
rewrite turns Astropy's `unit="---"` into `unit="1"`; no `unit=""` is written. The reader maps
`1`, `""` (earlier files), `---` and a dimensionless `Unit` to `None`. An absent or unknown unit
writes no `unit` attribute. New `inspect_unit_string(text)` returns a `UnitReport` (`errors`,
`notes`, `ok`): empty string or `---`, the reserved word `unknown`, whitespace, `*` as a product
sign, a string Astropy cannot parse are errors; a unit outside the VOUnits table (`electron`) is a
note only. New `VOLightCurve.check_units()` lists findings per `column:<name>` and per
`photcal:<column>:<PARAM>`; empty when clean; never raises. `electron.s-1` stays as the provider
wrote it (valid syntax, unknown unit, noted). Astropy already writes the composite as
`electron.s-1` even from `electron s-1` input.
Tests: the two OUTDATED unit tests rewritten as `test_units_*`, five added. `volightcurve` suite
95 passed. `lc_discovery` 216 passed (live cone-search tests deselected). Host: the same 11
failures as before (`lc_bridge.py` line 1786).
Not done: the suggestion table with relative flux unit `1` (step 5); the host does not call
`check_units()` yet.
### Ticket 34: host fix after steps 1 to 3 of Ticket 32 (2026-10-22)

Done: `lc_bridge.py` (ingest to `CurveDash`) passes `timescale=None` when the file declares no
time scale, instead of calling `.lower()` on `None`. This is not a fallback: `lc_figure.py`
and the interval helpers already take `timescale: str | None` and state "never invented".
Host suite: 661 passed (the 11 failures are gone).
Still silent and left for the Ticket 34 decision (found by search, not changed):
- `lc_bridge.py` `_absolute_jd_from_time_column`: `jd0 or 0.0`, then a guess that small values
  are MJD (`+ JD_TO_MJD`) when the origin is not declared.
- `lc_bridge.py` line 603: `meta.get("timescale") or "utc"` (transport to `CurveDash`).
- `lc_bridge.py` line 2239: `... or "TCB"` when exporting.
These are the places where the host should ask the user (suggestion table, applied explicitly)
or raise, instead of filling.
### Ticket 32: phase 2, step 4 done in `volightcurve` (2026-10-22): check methods and raising

Changes (uncommitted): `add_flux_column_from_mag` and `add_mag_column_from_flux` no longer fill a
NaN column when the calibration is missing and no longer swallow conversion errors: they raise
`PhotCalError` (with `.problems`) and add no column; the `new_col_name=None` bug (column named
`None`) is fixed. New check methods, which report and never raise on data:
`VOLightCurve.conversion_problems(column)` (no calibration, missing `zp_flux` or `zp_mag`,
unit mismatch; `KeyError` for an unknown column), `VOLightCurve.time_problems()` (undeclared
origin only when offsets are present, undeclared time scale, undeclared reference position, no
time column), `PhotDM.conversion_problems()`. `PhotCal.conversion_problems` and the time
conversion errors (step 1) were already in place.
Tests: six `test_checked_*` added; `volightcurve` suite 101 passed; host 661 passed;
`lc_discovery` (live tests deselected) passed.
Open for step 5 (interpretation split) and Ticket 34: the host still has to call these checks and
ask the user (see the Ticket 34 list above).
### Ticket 32: phase 2, step 5 done in `volightcurve` (2026-10-22): interpretation split

Changes (uncommitted):
- New `interpretation.py` holds all part B code, moved unchanged: `_promote_to_vo_standards`,
  `_recover_lc_colnames`, `_pickup_*`, `_is_dat_metadata_comment_line`, `_mag0_declared_in_comments`,
  `apply_non_votable_heuristics`. The core imports it only lazily, from the tolerant reading path.
  The old private names still resolve from `volightcurve.lightcurve` (module `__getattr__`) for one
  release; `volightcurve.apply_non_votable_heuristics` still works.
- Strict mode: `VOLightCurve(file, strict=True)` and `read_lightcurve(..., strict=True)` read only
  what a VOTable declares (no UCD or unit from names, no label column, no `JD0` from comments) and
  reject a file that is not a VOTable. Tolerant stays the default.
- New `suggestions.py` (plain data, applied by nobody): `suggested_time_system()` (HELIOCENTER, UTC,
  0), `suggested_calibration()` (Vega, `zp_mag` 0, `zp_flux` 1.0 dimensionless), `SUGGESTION_REASONS`
  (one reason per value), `suggestions_for_missing(volc)` (only the absent fields; changes nothing).
  `photcal_defaults.py` is marked DEPRECATED; the host still imports it until Ticket 34.
- GAVO is imported lazily (only in `_gavo_votable_metadata_tree`); importing the package and writing
  need no GAVO (tested with `gavo` blocked).
Tests: seven `step 5` tests added; `volightcurve` suite 108 passed; host 661 passed; `lc_discovery`
(live tests deselected) 216 passed.
Not done: description sentences that record what interpretation did (the ticket asks for them; today
the record is `table.meta["promoted_by_name"]` and a warning log); an explicit `__all__` for the
core and for interpretation (the package still exports through `from .lightcurve import *`);
moving the name fallbacks inside `is_observation_time_column`, `is_magnitude_phot_column`,
`resolve_observation_timesys` and the writer's `phot`/`mag`/`flux` fallback into interpretation
(they are mixed into core functions; each needs its own decision).
**Decision (2026-10-22): interpretation records in the table description only.** What the
interpretation did is written as plain sentences into the table DESCRIPTION, and nowhere else (no
extra meta key, no separate channel). `table.meta["promoted_by_name"]` has no reader and is to be
removed when the sentences are written. Not implemented yet.

### Ticket 32 phase 2, step 5b: interpretation recorded in the table description (done)

- `table.meta["promoted_by_name"]` is removed. `interpretation.add_interpretation_note` appends one plain sentence per kind to `table.meta["description"]`: "Interpreted from the file, not declared in it (from column names | from column positions | from the header comment | from comments or metadata keywords | from the column values): ...". No `=` in the text, and the same sentence is never added twice.
- Covered: unit and UCD from column names, column names from the header or position, JD0, period, epoch, filter, zero points, magnitude system and wavelength read from comments or keywords, and the label column UCD (`assign_label_column_ucd` now returns the column name).
- Writers: the VOTable DESCRIPTION is the envelope text, else the description plus the narrative comments; dat, csv and ecsv write the description as comment lines. Strict mode writes no sentence.
- Tests: `volightcurve` 113, host 661 (1 skipped), `lc_discovery` 216 (live cone-search tests deselected).

### Ticket 34, host step 1: `_absolute_jd_from_time_column` no longer guesses (done)

- The `jd0 or 0.0` fill and the "small values are MJD" guess are removed. A declared origin is added to relative values; absolute values pass; relative values with no usable origin raise `ValueError` that tells the user to declare or confirm the origin.
- Tests: `skvo_veb/tests/test_lc_bridge_absolute_jd.py`; host suite unchanged otherwise (661 passed).
- Next host steps: line 603 `or "utc"`, line 2239 `or "TCB"`, `photcal_coherence.py` defaults, then the prompts using `suggestions_for_missing`.

### Ticket 34, host step 2: timescale and reference position fills removed (done)

- `lc_bridge.py`: the GP lightcurve no longer defaults the timescale to `utc`; the VOTable export no longer defaults the timescale to `TCB` or the reference position to `BARYCENTER`. An absent value stays `None` (the writer then writes `UNKNOWN`). Host suite: 664 passed, 1 skipped.
- Next: `photcal_coherence.py` defaults, then the prompts using `suggestions_for_missing`.

### Ticket 34, host step 3: `photcal_coherence.py` no longer invents calibration (done)

- `reconcile_photcal_dict` leaves a missing `zp_flux`/`zp_mag` missing and warns ("Nothing was assumed"). It also no longer rewrites an invalid ZP magnitude unit to `mag` (it warns and leaves it). The private flux-unit default helper is removed; the module no longer imports `photcal_defaults`.
- `fill_missing_photcal_form_values` (the explicit fill button) takes its values from `volightcurve.suggestions` (Vega, 0, relative flux 1) and the alert says "suggested values".
- Tests added in `test_photcal_form_filter.py`; host suite green.
- Still open: the GP upload and `lc_bridge` do not yet prompt with `suggestions_for_missing`, `check_units`, `conversion_problems` or `time_problems`; only warnings are shown. That is the last host step.

### Ticket 34, host step 4a: readiness report in `lc_bridge` (done, backend only)

- New `skvo_veb/utils/lc_readiness.py`: `readiness_report(volc, phot_col=None)` returns JSON-safe data from `time_problems`, `check_units`, `conversion_problems(phot_col)` and `suggestions_for_missing` (with the reasons). It changes nothing.
- `volc_to_curvedash` stores it in `lcd.metadata["readiness"]` (`METADATA_KEY_READINESS`), so it travels with the session curve and can be shown by any page.
- Tests: `skvo_veb/tests/test_lc_readiness.py`; host suite 668 passed, 1 skipped.
- Next (4b, UI): show the report on the GP upload and Processor pages, with "apply suggested" actions; and let the upload ask for a time origin instead of failing when `_absolute_jd_from_time_column` raises.

### Ticket 34, description and INFO loss, step 1 in `volightcurve` (done)

- Finding (OGLE LMC RRLYR 13820, Discovery export): the long text is the VOTABLE-level DESCRIPTION; the table has its own short one; the file also has `INFO` elements (19 `creator`, `legal`, `rights`, `publisher`, `contact`, `ivoid`, `reference_url`, `publication_id`, ...). The export kept only the short table text (wrapped in our note) and no INFO at all.
- `VOLightCurve` now has `votable_description` and `infos` (all INFO elements of the VOTABLE root, the RESOURCE and the table, in file order, repeated names kept). `write_vo_lightcurve(..., infos=...)` writes them back. `_votable_kwargs_from_volc` no longer copies one string into both description slots: VOTABLE description = envelope or the declared one; table description = envelope or the table text and comments; INFOs = envelope `infos` or the declared ones.
- ECSV, DAT and CSV carry no INFO and no VOTABLE description (decision: concise).
- Fixture `tests/data/ogle_lmc_rrlyr_13820_full.vot`; 3 new tests (116 in `volightcurve`).
- Removed the obsolete `mission_config/asassn.py`, its test and its profile hooks in `lc_bridge` (ASAS-SN lives only as an `lc_discovery` provider). Host suite 664 passed (4 ASAS-SN export tests gone).
- Next: step 2 in `lc_bridge`: `_extract_vo_envelope_meta` stores `votable_description`, `table_description` and `infos` separately; the host note goes last, only in the table description; remove the duplicated composition in `build_votable_kwargs_from_metadata`.

### Ticket 34, description and INFO loss, step 2 in `lc_bridge` (done)

- `_extract_vo_envelope_meta` stores `votable_description`, `table_description` and `infos` separately (new `VO_ENVELOPE_KEY_INFOS`); nothing is copied from one slot to the other any more.
- `photometry_source_description`: the source text first and unchanged, then one "Processing note:" block (kept column, error column, columns not included) last, in the table description only. A note from an earlier export is replaced, not stacked. The VOTABLE-level description is never touched. The duplicated composition in `build_votable_kwargs_from_metadata` now uses the same helper, and the old cross-copy between the two description slots is gone. `export_curvedash` (one path for Discovery, Processor and cutout) passes `infos` through to `write_vo_lightcurve`.
- `volightcurve` text writers (dat, csv, ecsv) write only the "Interpreted from the file..." sentences from the description, not the source text (concise by decision).
- Tests: `test_export_keeps_source_description.py` (OGLE fixture: long VOTABLE text, table text then note, 19 creators, legal, rights), updated `test_lc_photometry_choice.py`; `volightcurve` 117, host 668 (1 skipped), `lc_discovery` 216.

### Ticket 32 phase 2, step 7: the core no longer guesses roles from column names (partly done)

- `write_vo_lightcurve` takes roles from the UCDs only. It no longer gives `time.epoch` to a column named `obs_time`, `time`, `jd` or `mjd`, and no longer picks `phot`, `mag` or `flux` as photometry by name. A table with no `time.epoch` column or no `phot.mag`/`phot.flux` column raises `ValueError` ("does not guess roles ... use VOLightCurve.from_table or assign the UCDs first"). Products from the reader or `from_table` already carry UCDs, so every production path is unchanged.
- `resolve_observation_timesys` no longer falls back to column names; it raises when no `time.epoch` column exists.
- Removed the dead `is_observation_time_column` and `OBSERVATION_TIME_NAME_FALLBACKS`.
- Tests: bare test tables get UCDs through `annotate_vo_roles` (`tests/fixtures_votable.py`); new test that a bare table is rejected. `volightcurve` 118, host 668 (1 skipped), `lc_discovery` 216.
- Still open: `is_magnitude_phot_column` treats a bare `phot` column without unit or UCD as magnitude (used by interpretation, `assign_photometry_column_semantics` and three host call sites in `lc_bridge`); the host should ask instead of assuming.

### Ticket 34 and 32: host prompts, the magnitude guess and `__all__` (done)

- **Magnitude guess.** `is_magnitude_phot_column` (a bare `phot` with no unit and no UCD counts as magnitude) moved to `volightcurve.interpretation`. `assign_photometry_column_semantics` now needs `phot_col`, `error_col` and `force_magnitude`; nothing is guessed in the core. Removed the unused `resolve_votable_phot_field_labels`. In the host, `lc_bridge` decides the domain from the column UCD only (`is_mag_column`); the dead `tabular_table_to_curvedash` (it also guessed MJD from small values and filled absent errors with zeros) is deleted.
- **Prompts (first version).** `lc_readiness.readiness_message` turns the report into text: undeclared time system, unit errors, the calibration gap that blocks mag/flux conversion, and a line saying suggested values exist and are applied only on the user's choice. The Processor upload shows it as an info alert; the GP upload shows it next to the photcal warnings (`pack_volc_to_json` now carries the report in `meta["readiness"]`). The Processor "Fill missing" button remains the only way suggested values get applied.
- **Still open:** an input to give the time origin and retry when a relative time column has none (today the upload fails with the explicit message); readiness alert on the Discovery page; conversion of the GP page to apply suggestions.
- **`__all__`.** `volightcurve.lightcurve` lists the core names only; `volightcurve.interpretation` lists its four public names; `volightcurve/__init__.py` imports the core names explicitly instead of `import *`. Package-level names are unchanged apart from leaked helpers (`np`, `u`, `Table`, `ascii`, `logging`, `logger`, `main`, `is_votable`, `rewrite_astropy_empty_unit_attributes`).
- Tests: `volightcurve` 118, host 671 (1 skipped), `lc_discovery` 216.

- Readiness message shortened (user feedback): one sentence, "Some metadata is missing. Open Calibration to review it and apply suggested values." No details in the alert; they stay in `metadata["readiness"]`.

### Ticket 34: Calibration collapse on the GP page (done)

- `skvo_veb/utils/gp/photcal_form.py`: `photcal_form_values_for_packet` (stored values with gaps filled by the suggested values, packet untouched) and `apply_photcal_form_to_packet` (writes `meta["photcal"]` and, for a flux packet, `meta["flux_unit"]`; drops the stale readiness report; returns the unit warnings).
- GP page (`gp_for_oc.py`): "Calibration" collapse in the lightcurve sidebar using the shared `photcal_editor_body` (copy of the Processor pattern, no layout refactor). Callbacks: the form is filled from the packet on every revision (suggestions pre-filled), "Fill missing defaults" completes empty fields, "Apply calibration" rewrites the cached packet and bumps `store-gp-lc-revision` so every view rebuilds. The collapse toggle is a client-side callback.
- Upload no longer calls `reconcile_photcal_dict` (nothing is stored or rewritten at upload); the unit checks run on Apply. The upload alert is the short readiness sentence only.
- Tests: `test_gp_photcal_form.py` (prefill leaves the packet unchanged, apply stores values and keeps the data, GP conversion passes after apply). Dash dependency map builds; host suite green except the unrelated alert-duration test (`STATUS_ALERT_DURATION_MS`).

### Ticket 34: time origin input and cleanups (done)

- Removed `test_status_alert_duration_and_dismissable` (alert duration is a free UI setting).
- "Time origin (JD)" field in the shared calibration editor (Processor and GP collapses; not on Discovery). It is read by the page upload callback and passed as `time_origin` to `ingest_lightcurve_file` / `pack_uploaded_lightcurve`. `apply_time_origin` uses it only when the file declares no origin; a declared origin always wins (logged). The field is not cleared between uploads.
- `pack_volc_to_json` now fails fast on relative times without an origin (same rule and message as the Processor path); `meta["jd0"]` is `0.0` only when the times were validated as absolute.
- The relative-time error says: enter the time origin under Calibration and upload again.
- `volightcurve.time_reference.resolve_observation_timesys`: removed the `volc.timesys or TimeSys()` fallback; a missing object now raises.
- Not done on purpose: readiness alert and calibration on Discovery; TESS/cutout envelope; `ID` on PARAMs (not required by VOTable, only needed when something references the PARAM).

### Ticket 34: time origin UI removed (decision)

- The "Time origin (JD)" field, its "shown" store, `typed_time_origin`, `apply_time_origin`, `time_origin_form_value` and the `time_origin` upload arguments are removed again: a field that carries state between uploads leaked the previous file's origin into the next one.
- Relative times with no declared origin still fail fast on both pages, with one clear message that names the fix in the file: add the header row `# JD0=<value>` and upload again. No UI route, no guessed origin.
- Kept: `pack_volc_to_json` validates the time column (same rule), `resolve_observation_timesys` raises without a `TimeSys`, the `**` power fix in `vo_unit_codec`.
- Open if the user wants it later: an interpretation-layer rule that accepts values below 1e6 (for example reading them as JD minus 2400000) and says so in the description.
