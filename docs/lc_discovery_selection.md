# Lightcurve Discovery: table, Aladin, and Retrieve selection contract

Page: `skvo_veb/pages/lightcurve_discovery.py` (`/lc_discovery`).
Helpers: `skvo_veb/utils/lc_discovery_aladin.py`. Styles: `skvo_veb/assets/lc_discovery.css`.

This contract applies to every provider, whether one source has one catalogue row
(for example Gaia with a single band) or many (Gaia G/BP/RP, or TESS with several
sectors, authors, and exposures).

## 1. Identities

Three different jobs need three different identities. They must never be mixed.

| Job | Identity | Unique per | Source |
|-----|----------|------------|--------|
| Retrieve / Download target | **product**: `lc_key` | table row | provider |
| Sky marker and table grouping | **source**: `object_name` | star | catalogue core field |

- `lc_key` is opaque. The page only compares it for equality.
- `object_name` identifies the sky source. Rows of one source share `object_name`
  and (to within catalogue precision) the same `ra_deg`, `dec_deg`.
- Sector, exposure, and author never appear in any key. They only distinguish rows
  inside the table, and `lc_key` already does that.
- `filter_name` is never overloaded to make anything unique.

Provider contract: within one search result, `object_name` must identify the sky
source. A provider that reuses one `object_name` for different positions is wrong;
the page logs a warning when rows of one source are more than 10 arcsec apart.

## 2. Selection and focus

| Concept | Meaning | Rows | State |
|---------|---------|------|-------|
| **Selected row** (highlighted) | The product Retrieve will fetch | exactly one, or none | AgGrid `selectedRows` (single-row mode) |
| **Focused source** (map pin only) | The star currently shown on the map | none; not highlighted in the table | `store_lc_discovery_focus_source` |

- AgGrid native selection is the only writer of the product.
  `store_lc_discovery_selected_key` is derived from `selectedRows`
  (the selected row's `lc_key`, or `None`). Retrieve, Re-retrieve, and Download
  read that store. No other callback writes it, except the new-search reset.
- Selecting a row sets the focus source to that row's `object_name`.
- The selected row uses AgGrid's `ag-row-selected` class, styled in `lc_discovery.css`.
- Sibling rows of the focused source are **not** tinted. Nothing may write
  `dashGridOptions` after the layout is built: a runtime patch replaces the whole
  options object and drops `rowSelection` and `getRowId`. Dynamic state goes through
  `rowData`, `selectedRows`, `scrollTo`, or stores only.

## 3. Aladin markers

- One marker per distinct `object_name`, named by `object_name`.
- Position is taken from the first catalogue row of that source.
- `selectedStar.name` is therefore a source name. Retrieve never goes through the map.

## 4. User flows

**Table to map and Retrieve**

1. The user clicks a row. It gets the strong highlight.
2. Its source becomes the focus and the pin is selected on the map.
3. Retrieve fetches that row.

**Map to table**

1. The user clicks a pin. Its source becomes the focus and the table scrolls to the
   first row of that star.
2. If the currently selected row already belongs to this source, selection is kept.
3. Otherwise the first row of the source is selected (strong highlight, Retrieve
   enabled). The user can pick another row of the same star by clicking it.
4. Scrolling uses `scrollTo={'rowId': lc_key}`, so it stays correct after sorting.

**New search or restored session**

Focus source, selected row, and selected key are cleared.

## 5. Callbacks (one job each)

| Callback | Input | Output |
|----------|-------|--------|
| `update_lc_discovery_selection_state` | table `selectedRows` | `store_lc_discovery_selected_key`, `store_lc_discovery_focus_source` |
| `update_lc_discovery_focus_from_aladin` | Aladin `selectedStar` | focus source, table `selectedRows`, table `scrollTo` |
| `sync_lc_discovery_focus_to_aladin` | focus source | Aladin `selectedStar` |
| `refresh_lc_discovery_aladin` | search stores | map, and clears selection and focus |

Loop guard: a table click sets the focus, which selects the pin, which fires the
Aladin callback; that callback leaves `selectedRows` untouched when the selected
row already belongs to the focused source.

## 6. Removed

`aladin_name` row field, `find_catalog_row_by_aladin_name`, `catalog_row_from_cell_clicked`,
`store_lc_discovery_highlight_name`, any use of `cellClicked` for selection, the
soft sibling-row tint, and the clientside `lcDiscoveryCatalogHighlightRules` callback.
