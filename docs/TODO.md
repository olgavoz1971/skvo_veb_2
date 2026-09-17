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
`skvo_veb/volightcurve/lightcurve.py` (`PhotCal`);
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

- ``skvo_veb/volightcurve/photcal_defaults.py``
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
`skvo_veb/volightcurve/` (`VOLightCurve`, `write_vo_lightcurve`,
`apply_non_votable_heuristics`, `io_keywords`), `skvo_veb/utils/lc_bridge.py`
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
