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
| 4 | Unified dismissable / timed status alerts (all LC pages) | Open (Phases 0–2 done) |

## Done

| ID | Title | Status |
|----|-------|--------|
| 3 | Unify server session LC (common base, then page-by-page) | Done (phases 0–4; ASAS-SN + cutout out of scope) |

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
`info_alert` (no dismiss, no duration) still used by Discovery / TESS /
ASAS-SN until later phases.

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
| **TESS** `/tess_lc` | Same `message.*` pattern; several alert divs (tools / search / download / plot) | Same as Discovery |
| **Legacy ASAS-SN** `/asassn` | Same `message.warning_alert` + show/hide div | Same; lower priority if Discovery supersedes |

`components/message.py` is the shared factory for Discovery/TESS/ASAS-SN and
is the main reason those pages never got Processor’s dismiss/timer rules.

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

#### Phase 4 (optional) — Legacy ASAS-SN

- Only if `/asassn` stays in active use; otherwise leave until removed.

### Out of scope

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

**Open.** Phases 0–2 done: shared `status_alert` in
`skvo_veb/components/message.py`; Processor, Extrema modeller (`/gp`), and
Discovery (`/lc_discovery`) use it. Discovery alert slots are children-only
(no display style Outputs). Legacy `warning_alert` / `info_alert` remain for
TESS / ASAS-SN until Phases 3–4. Next: Phase 3 (TESS).

