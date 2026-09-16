# Lightcurve Discovery — messages and alerts

User-facing status text, warnings, and Bootstrap alerts on **`/lc_discovery`**.  
Layout IDs live in `skvo_veb/pages/lightcurve_discovery.py`. Styling for the search progress strip is in `skvo_veb/assets/lc_discovery.css` (see also [lc_discovery_css.md](lc_discovery_css.md)).

This document defines **lifetimes** so messages do not outlive the action or dataset they describe.

---

## Lifetimes (policy)

| Lifetime | Meaning | Clear when |
|----------|---------|------------|
| **Job** | Shown only while a background task runs | Task finishes (success, error, or cancel) |
| **Result set** | Describes the current catalogue search | New search **completes** (Submit) |
| **Last fetch** | Describes the last Retrieve / Re-retrieve on the Search tab | New search starts, or a new fetch attempt |

Search failures and fetch failures share **`lc_discovery_catalog_alert`**
(one slot under the table); lifetimes above still govern when that slot is cleared.

---

## Search tab — tools column (left)

### `lc_discovery_search_status`

- **Type:** Plain text bar (`.lc-discovery-search-status`). No spinner wrap
  (progress text alone is the Submit feedback).
- **Lifetime:** **Job** (catalogue background search).
- **Appears:** Step messages from `run_catalog_search` via the submit callback `progress` channel (Simbad resolve, cone query, etc.).
- **Hidden:** When the background search callback returns (success or `PipeException`). Not used for fetch.

### `lc_discovery_object_card` / `lc_discovery_object_card_markdown`

- **Type:** Card with Markdown (coordinates, identifiers, optional magnitudes).
- **Lifetime:** **Result set**.
- **Appears:** Successful catalogue search (`resolved_markdown`).
- **Hidden:** At the start of a new Submit (before the job runs), on successful search, and when the search fails before a new card is shown.

Changing the **Data provider** radio does **not** clear the card, table, or Aladin; only a completed Submit replaces them.

---

## Search tab — results column (catalogue panel)

### `lc_discovery_catalog_truncation_notice`

- **Type:** Small warning under the results header.
- **Lifetime:** **Result set**.
- **Appears:** When provider metadata reports `catalog_may_be_truncated` (cone row cap).
- **Hidden:** When the current outcome is not truncated; updated on each successful search.

Changing the **Data provider** radio does **not** clear truncation text; the next Submit replaces it.

### `lc_discovery_catalog_alert`

- **Type:** Bootstrap alert via `status_alert` (dismissable; warning sticky).
- **Placement:** Single slot **under** the catalogue table / Aladin row.
- **Lifetimes:** Shares one physical slot for:
  - **Result set** — search validation / orchestration failures (`PipeException`).
  - **Last fetch** — Retrieve / Re-retrieve failures (missing row, mission
    mismatch, provider errors).
- **Appears:** Submit errors, or Retrieve / Re-retrieve errors.
- **Hidden:** Cleared to empty `children` at Submit start, on successful
  catalogue search, at Retrieve job start, and after a **successful** fetch
  (UI switches to the Light curve tab; no persistent banner).
- **Spinner:** Compact `wrap_with_spinner` (`size='sm'`, `SPINNER_STYLE_COMPACT`)
  on `lc_discovery_catalog_spinner_target` in the **centre** of the catalogue
  header row (Submit + Retrieve). Table / Aladin are not wrapped. Tools status
  log is separate (text only).

Changing the **Data provider** radio does **not** clear this alert; the next
Submit clears it at job start.

Successful loads are logged server-side; the plot tab reflects the loaded curve.

---

## Search tab — layout notes

- **Aladin hint** (`lc-discovery-aladin-hint`): Static help text, not a dynamic alert.
- **Catalogue header** (`lc_discovery_catalog_header`): Title line (target / cone), not an alert.

---

## Light curve tab (Plot)

### `lc_discovery_plot_alert`

- **Type:** Bootstrap alert via `status_alert` (dismissable; warning sticky).
- **Appears:** Plot / fold / mag / delete / download failures on the Light curve tab.
- **Hidden:** Cleared to empty `children` on successful replot, fold, mag switch,
  delete, or download.

`lc_discovery_fold_warning_label` remains a plain visibility-toggled label when
period is missing after fetch — not a `status_alert`.

---

## Implementation checklist (for developers)

When adding a new message region:

1. Assign one of the lifetimes above.
2. Clear it in every callback that **invalidates** that lifetime (same places as catalogue `rowData` / `store_lc_discovery_resolved_target`).
3. Prefer **one** channel per concern (avoid duplicating the same text in a label and an alert).
4. Use `status_alert(text, colour)` and set **`children` only** (empty/`None` clears; do not toggle `display` style on alert slots).
5. Do not add orphan `html.Div` placeholders without callbacks.

Related code:

- Catalogue orchestration: `skvo_veb/utils/lc_discovery_search.py`
- Submit: `submit_catalog_search` (replaces catalogue, columns, card, Aladin store, messages)
- Fetch: `fetch_lc_discovery_lightcurve` (background)

**Data provider** (`lc_discovery_mission_switch`) only selects which adapter the **next** Submit or Retrieve uses. It does not reset the results panel.
