# Lightcurve Discovery — CSS tuning how-to

Simple guide for adjusting look and layout on the **Lightcurve Discovery** page (`/lc_discovery`).

**Main file:** `skvo_veb/assets/lc_discovery.css`  
**Page layout:** `skvo_veb/pages/lightcurve_discovery.py` (class names only — sizes live in CSS)

After editing CSS, hard-refresh the browser (**Ctrl+Shift+R**) to avoid stale cached styles.

---

## One rule: change tokens first

Most tuning happens in **one block** at the top of the CSS file:

```css
.lc-discovery-page {
    font-size: 0.85rem;                        /* default text on this page */
    --lc-discovery-select-font-size: 0.85rem;  /* dropdowns */
    --lc-discovery-text-xs: 0.75rem;           /* status bar */
    --lc-discovery-text-sm: 0.85rem;           /* hints, card, popovers */
    --lc-discovery-panel-height: clamp(15rem, 45vh, 30rem);  /* table + Aladin area */
    --lc-discovery-graph-height: clamp(17.5rem, 55vh, 35rem); /* Light curve tab graph */
    --lc-discovery-card-max-height: clamp(5rem, 22vh, 10rem); /* result card under Submit */
    /* spacing tokens: --lc-discovery-space-xs … --lc-discovery-space-xl */
}
```

The page container in Python uses `className='lc-discovery-page'`. Everything inside inherits these settings.

**You usually do not put font sizes in Python.** Python gives components a **class name**; CSS applies the size.

---

## What to change for common tasks

| You want to… | Edit this |
|--------------|-----------|
| Make **all page text** slightly smaller/larger | `.lc-discovery-page` → `font-size` |
| Resize **dropdowns** (radius unit, MJD/JD/date) | `--lc-discovery-select-font-size` (already wired to `.lc-discovery-field-unit`) |
| Resize **status bar** under Submit | `--lc-discovery-text-xs` |
| Resize **result card** text | `--lc-discovery-text-sm` and/or `--lc-discovery-card-max-height` |
| Taller/shorter **catalogue table + Aladin** panel | `--lc-discovery-panel-height` |
| Taller/shorter **light curve graph** (other tab) | `--lc-discovery-graph-height` |
| Resize **catalogue table** font | `.lc-discovery-catalog-aggrid` → `--ag-font-size` |
| Compact **table rows** | same block → `--ag-row-height`, `--ag-header-height` (use `rem`) |
| More padding in **table cells** | `--ag-cell-horizontal-padding` (keep small; `2px` is normal) |

---

## Units — why px, rem, and clamp mixed?

Not dangerous — each unit has a job:

| Unit | Use on this page | Why |
|------|------------------|-----|
| **rem** | Page font, spacing, dropdowns, table font | Scales with user browser font / zoom |
| **clamp(rem, vh, rem)** | Panel heights | Works on small laptops and short windows |
| **px** | Ag Grid cell padding (1–2px) | Hairlines; grid library expects pixel metrics |
| **rem** | Ag Grid row height | Row height and font scale together |

**Table note:** row height and font size are both in **rem** inside the Ag Grid block so they stay in proportion when the user enlarges text.

---

## Component map (where things live)

### Python (`lightcurve_discovery.py`) — class names only

| UI part | Class name in Python |
|---------|----------------------|
| Page wrapper | `lc-discovery-page` |
| Text inputs (target, radius, times) | `lc-discovery-field-input` |
| Dropdowns | `lc-discovery-field-unit` |
| Result card under Submit | `lc-discovery-object-card` |
| Catalogue AgGrid | `lc-discovery-catalog-aggrid` |
| Page title | `fs-4 fs-md-3` (Bootstrap — headings only) |
| Catalogue title | `fs-5` (Bootstrap) |

Dropdown example in Python — **no font size here**, only the class:

```python
dbc.Select(..., className='lc-discovery-field-unit')
```

### CSS — sizes and layout

| UI part | CSS selector |
|---------|--------------|
| Dropdown font | `.lc-discovery-page .lc-discovery-field-unit` |
| Result card scroll + font | `.lc-discovery-object-card .card-body` |
| Table font & row height | `.lc-discovery-catalog-aggrid.ag-theme-balham` |
| Vertical centre in table cells | `.ag-cell` / `.ag-header-cell` flex rules below the grid block |

---

## Small screens

Extra rules at the bottom of `lc_discovery.css`:

- **Narrow phone** (`max-width: 575.98px`) — shorter panels and card
- **Short window** (`max-height: 720px`) — catalogue, graph, and card shrink

Adjust those media-query blocks if the page feels too tall on a small monitor.

---

## What not to do

1. **Do not** set table fonts/padding in Python — use the Ag Grid CSS block.
2. **Do not** mix random `px` and `rem` for the same kind of thing (e.g. all margins should use `--lc-discovery-space-*` tokens).
3. **Do not** edit global `style.css` for Discovery-only tweaks — keep changes in `lc_discovery.css`.
4. After changing CSS, if the table looks wrong on reload but fine after server restart, **hard-refresh** — the browser may cache old CSS.

---

## Quick checklist after a CSS change

1. Edit token or rule in `skvo_veb/assets/lc_discovery.css`
2. Ctrl+Shift+R in the browser
3. Check: tools column, dropdowns, result card, catalogue table, Aladin panel
4. Optionally resize the browser window (narrow + short) to test media queries

---

## Files reference

| File | Role |
|------|------|
| `skvo_veb/assets/lc_discovery.css` | All Discovery page styling |
| `skvo_veb/pages/lightcurve_discovery.py` | Layout, IDs, class names |
| `skvo_veb/assets/style.css` | Global Bootstrap (whole app — avoid for page-only tweaks) |
