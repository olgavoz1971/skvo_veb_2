# TESS background handling: Lightkurve and skvo_veb pages

This note records how **background** photometry is defined in Lightkurve for official TESS products and for user-built cutout light curves, and how the two TESS Dash pages in this repository consume that information.

**Related code:** `skvo_veb/utils/tess_flux_column_registry.py`, `skvo_veb/utils/tess_processor.py`, `skvo_veb/utils/tess_lc_builder.py`, `skvo_veb/utils/mission_config/tess.py`.

**Related docs:** [lightcurve_data_flow.md](lightcurve_data_flow.md) (layering and export profiles), [caching_architecture.md](caching_architecture.md) (archive page server cache vs cutout session stores).

**Last updated:** 2026-08-02.

---

## Part 1 — How Lightkurve handles background

Lightkurve exposes background in two different shapes depending on whether you open a **pre-built light-curve FITS product** or a **target pixel file (TPF / cutout)**.

### 1a) Ready-made light curves: SPOC, TESS-SPOC, and QLP

These are `TessLightCurve` objects returned by `search_lightcurve(...).download()` (or equivalent MAST paths). Each file carries many FITS columns; Lightkurve maps them to lower-case `LightCurve` column names (for example `pdcsap_flux`, `sap_bkg`).

#### Target (science) flux

| Author | Typical Lightkurve default (`lc.flux`) | Registry photometry columns (FITS names) | Calibration |
|--------|----------------------------------------|------------------------------------------|-------------|
| **SPOC** | `pdcsap_flux` | `PDCSAP_FLUX`, `SAP_FLUX` (+ errors) | Physical, e⁻ s⁻¹ |
| **TESS-SPOC** | Same convention as SPOC | Same as SPOC | Physical, e⁻ s⁻¹ |
| **QLP** | Sector-dependent (`kspsap_flux` S1–55, `det_flux` S56+ in registry) | `SAP_FLUX`, `KSPSAP_FLUX`, `DET_FLUX`, `SYS_RM_FLUX`, … | Normalised catalog flux (dimensionless), anchored via `TESSMAG` |

The application registry in `tess_flux_column_registry.FLUX_COLUMN_REGISTRY` documents these pairs and sector ranges. **`FLUX_METHOD_DEFAULT`** in the UI means “keep whatever column Lightkurve already assigned to `lc.flux`”, resolved via `resolve_default_flux_origin(lc)`.

#### Pipeline background columns (archive “background” product)

For light-curve FITS files, background is **not** inferred at read time; it is a **stored column** when the pipeline provides one:

| Author | FITS background column | FITS error | Lightkurve-style name | Notes |
|--------|------------------------|------------|------------------------|-------|
| **SPOC** | `SAP_BKG` | `SAP_BKG_ERR` | `sap_bkg` | Per-cadence sky/aperture background, e⁻ s⁻¹ |
| **TESS-SPOC** | `SAP_BKG` | `SAP_BKG_ERR` | `sap_bkg` | Same as SPOC |
| **QLP** | `SAP_BKG` | `SAP_BKG_ERR` | `sap_bkg` | Catalog-normalised background; may be negative in difference imaging |

Registry entry: `BACKGROUND_COLUMN_REGISTRY` in `tess_flux_column_registry.py`. Selecting **`background`** (`FLUX_METHOD_BACKGROUND`) copies that column (and error, when present) onto `lc.flux` / `lc.flux_err` via `apply_flux_column_selection()`.

#### Physical relationship on official SPOC products

On **official Kepler/TESS target pixel files**, Lightkurve documents that pixel **`FLUX`** is already **background-subtracted** using the pipeline estimate stored in **`FLUX_BKG`** (pixel level). The light-curve product therefore separates:

- **Target photometry** — e.g. `PDCSAP_FLUX` (systematics-corrected aperture sum).
- **Reported background level** — `SAP_BKG` (same cadence, aperture-related background metric).

Plotting `sap_bkg` is **not** the same as plotting “raw target before subtraction”; it is the pipeline’s background track. Residual sky after imperfect subtraction is a separate problem (see §1b `estimate_background`).

#### QLP specifics

QLP target flux columns are **dimensionless** catalog-normalised values, not e⁻ s⁻¹. Background (`SAP_BKG`) follows the same normalisation. Magnitude conversion in skvo_veb uses `TESSMAG` zero-point metadata when flux columns are catalog-calibrated; background selections set `is_background_flux` and **block** magnitude conversion (see `validate_tess_magnitude_conversion` in `mission_config/tess.py`).

---

### 1b) Light curves extracted from a TPF or FFI cutout

The cutout workflow uses `lightkurve.targetpixelfile.TessTargetPixelFile` (whether the file is a **SPOC TPF** or a **MAST TESScut FFI** stack). Photometry is **computed in software** from the pixel cube, not read as a single pre-extracted LC row.

#### Target flux from a user aperture

```text
pixel_data.to_lightcurve(aperture_mask=user_mask)
```

- Sums **`FLUX`** over all pixels where `user_mask` is true (handmade, threshold, or pipeline mask on the cutout page).
- Applies Lightkurve’s usual quality handling on the TPF.
- Units: e⁻ s⁻¹ per pixel, summed to e⁻ s⁻¹ in the aperture (same convention as `to_lightcurve` for TESS).

#### Pipeline background summed in the **same** aperture

```text
pixel_data.get_bkg_lightcurve(aperture_mask=user_mask)
```

- Sums **`FLUX_BKG`** (and combines **`FLUX_BKG_ERR`** in quadrature) over the **same** `user_mask`.
- This is the natural counterpart to custom-aperture target flux: same geometry, background pixel values from the FITS cube.
- On TPFs where `FLUX_BKG` is defined, this aligns with the **`SAP_BKG`** idea at pixel level, integrated over the user’s aperture rather than the pipeline’s default aperture.

Lightkurve exposes cube accessors:

- `TargetPixelFile.flux_bkg` → `FLUX_BKG` for good cadences (e⁻ s⁻¹ per pixel).
- `TargetPixelFile.flux_bkg_err` → `FLUX_BKG_ERR`.

#### Residual background estimate (`estimate_background`)

```text
pixel_data.estimate_background(aperture_mask='background')
```

Lightkurve uses this when:

- Official products may still contain **residual** sky after pipeline subtraction, or
- **Community / TESScut** pixel files were **never** pipeline background-subtracted.

Behaviour (from Lightkurve docstrings):

- **SPOC TPF:** estimates **residual** background (often near zero if subtraction was good).
- **TESScut FFI:** provides a **first-order** background level because cutouts are not pre-subtracted.

This method uses pipeline **background pixels** (the `'background'` aperture mask), not the user’s target mask. It returns a **per-cadence scalar** background flux density (per pixel), not an aperture sum.

#### TPF (SPOC) vs FFI (TESScut)

| Aspect | SPOC TPF | TESScut FFI (`author == TESScut`, `pixel_type == FFI`) |
|--------|----------|--------------------------------------------------------|
| Download path | `SearchResult[row].download()` | MAST cutout service, cached as FFI FITS |
| Pixel `FLUX` | Pipeline background-subtracted | Not pipeline-subtracted |
| `FLUX_BKG` in cube | Present for standard products | May be missing or all-NaN |
| `get_bkg_lightcurve(user_mask)` | Usual path when `FLUX_BKG` is finite | May be empty or uninformative if `FLUX_BKG` is NaN |
| `estimate_background` | Residual sky | Primary background estimate for cutouts |

skvo_veb does **not** yet expose a separate “plot background” mode on the cutout page; it only uses `estimate_background` when the user enables **Sub bkg** (see Part 2).

#### Sub bkg on the cutout page (distinct from `get_bkg_lightcurve`)

In `tess_processor.process_lightcurve_computation`, when **Sub bkg** is enabled:

```text
bkg = pixel_data.estimate_background(aperture_mask='background')
flux_target = lc.flux - bkg.flux[quality_mask] * mask.sum() * u.pix
```

So subtraction uses **`estimate_background` × number of pixels in the user mask**, not `get_bkg_lightcurve`. That choice removes a **residual sky estimate** tied to pipeline background pixels, which can differ from summing **`FLUX_BKG`** inside the user aperture.

**Summary for implementers**

| Intent | Lightkurve API | Matches archive “background” radio? |
|--------|----------------|-------------------------------------|
| Target in custom aperture | `to_lightcurve(user_mask)` | N/A (user photometry) |
| Pipeline bkg in custom aperture | `get_bkg_lightcurve(user_mask)` | Conceptually similar to plotting `sap_bkg` with matching aperture |
| Residual sky / TESScut first order | `estimate_background('background')` | No — used for **Sub bkg** only today |

---

## Part 2 — How this appears in skvo_veb scripts

Two pages cover TESS light curves with different data sources and storage models.

| Page | Module | Data source | Background in UI today |
|------|--------|-------------|-------------------------|
| TESS archive | `skvo_veb/pages/lightcurve_tess_srv.py` | Pre-built `TessLightCurve` FITS | **Flux options** radio: default / explicit flux columns / **background** |
| TESS cutout | `skvo_veb/pages/tess_cutout.py` | TPF or TESScut FFI + user mask | **Sub bkg** only (subtract residual); always stores target flux |

---

### 2a) `lightcurve_tess_srv.py` — archive light curves

#### UI

Under **Plot → Flux options** (`html.Details`):

- `dcc.RadioItems` **`flux_tess_lc_srv_switch`** — options built dynamically from the registry (`update_flux_radio_options` callback).
- Default value: **`FLUX_METHOD_DEFAULT`** (`"default"`).
- When the downloaded file contains the pipeline background column, an extra option **`background`** appears (`FLUX_METHOD_BACKGROUND`).
- Additional switches: stitch, magnitude view, time axis (MJD / date).

Callbacks **`update_flux_radio_options`** and **`reset_flux_on_new_search`** keep the radio list in sync with the AgGrid selection and MAST search store.

#### Build path (scientific)

1. User selects sector row(s) and clicks replot / download.
2. **`create_lc_from_selected_rows`** in `tess_lc_builder.py` downloads each row via Lightkurve (with cache helpers).
3. For each sector, **`apply_flux_column_selection(lc, author, sector, flux_method)`** mutates `lc.flux` / `lc.flux_err` according to the radio value.
4. Arrays are copied into **`CurveDash`** (`jd`, `flux`, `flux_err`, sector labels in `label`).
5. Metadata recorded on `lcd.metadata`:
   - **`flux_origins`** — column names actually plotted (e.g. `pdcsap_flux`, `sap_bkg`).
   - **`flux_method`** — radio value used for the build.
   - **`is_background_flux`** — `True` if any sector used **`background`**.
   - **`authors`**, **`sectors`**, **`stitched`**, TESS photometric calibration via **`resolve_photcal`**.

Multi-row selection **forces** `FLUX_METHOD_DEFAULT` (`effective_flux_method_for_selection`) so a single-row background choice does not silently apply to a stitch of mixed products.

#### Storage and plotting

- Serialised **`CurveDash`** JSON is stored in the **server-side user cache** keyed by tab UUID (see [caching_architecture.md](caching_architecture.md)); the browser holds a cache key, not the full series.
- Plot callbacks load from cache and use **`apply_tess_phot_domain_view`** when the magnitude switch is toggled; background light curves fail magnitude conversion by design.
- Export / download repeats the same **`flux_method`** so the file matches the on-screen column choice.

#### Registry module (shared logic)

All column names and the **`background`** branch live in **`skvo_veb/utils/tess_flux_column_registry.py`** (not in the page file). The page imports:

- `flux_radio_options_for_rows`, `effective_flux_method_for_selection`, `FLUX_METHOD_DEFAULT`.

Tests: `skvo_veb/tests/test_tess_flux_column_registry.py`.

---

### 2b) `tess_cutout.py` — TPF / FFI aperture photometry

#### UI

**Curve Tools** (not the pixel “Plot options” block):

- **`sub_bkg_switch`** — checklist/switch **Sub bkg** → passes `sub_bkg` into computation.
- **Flatten**, **Magnitude**, time axis, trim, export format.
- **Plot Options** — **`star_tess_switch`** selects which of three curves is updated (**Curve 1 / 2 / 3**); compare divide/subtract between slots.

There is **no** flux-column radio and **no** `tess_flux_column_registry` integration on this page.

#### Build path (scientific)

1. User downloads a sector (`download_sector` → **`tess_processor.download_selected_pixel`**).
   - **SPOC:** TPF FITS, `pixel_metadata['pixel_type'] == 'TPF'`.
   - **TESScut:** FFI cutout, `pixel_type == 'FFI'`.
2. User defines **`mask_store`** on the pixel graph and clicks **rePlot curve**.
3. Callback **`create_lightcurve`** calls **`tess_processor.process_lightcurve_computation`** with mask, **Sub bkg**, flatten settings.
4. Returns only **one** photometric series today: target **`flux`**, **`flux_err`**, **`flux_unit`**, plus **`flux_correction`** tokens (`backgrounded`, `flattened`, `Trend`, …).
5. **`CurveDash`** is built with **`active_domain=DOMAIN_FLUX`**, then **`enrich_cutout_curvedash`** (`mission_config/tess.py`):
   - **`mission`**: cutout mission id.
   - **`authors`**: `[user]` pipeline tag for export.
   - **`cutout_source`**: `TPF` or `FFI`.
   - **`mask_mode`**: handmade / threshold / pipeline.
   - **No** `flux_method`, **no** `is_background_flux`, **no** separate background array.

#### Storage and plotting

- Three session stores: **`store_tess_cutout_lightcurve`**, **`lc2_store`**, **`lc3_store`** (browser session JSON).
- **`plot_lightcurve`** deserialises stores and builds figures via **`create_lightcurve_figure`** → **`build_curvedash_scatter_figure`**; y-axis is always the stored **`lcd.flux`** (or magnitude after **`apply_phot_domain_view`**).
- Export: **`download_tess_lightcurve`** → **`prepare_lcd_for_export`** → **`export_curvedash(..., profile='cutout')`**. Profile **`cutout`** omits archive zero points (uncalibrated user photometry).

#### Pixel display (context only)

**Cutout Tools → Plot options** controls the **image** (gamma, sum, frame slider), not the light-curve y-axis. Flux cubes come from **`load_cutout_flux_cube`** (`pixel_data.flux` time stack).

---

## Cross-page comparison

```text
                    lightcurve_tess_srv              tess_cutout
                    -------------------              -----------
Lightkurve product  TessLightCurve FITS            TessTargetPixelFile
Background source   FITS column (sap_bkg, …)       estimate_background (Sub bkg)
                    via registry                   [future: get_bkg_lightcurve]
User aperture       N/A (pipeline aperture)        mask_store on pixel graph
Registry            tess_flux_column_registry      not used
Stored metadata     flux_method, is_background_flux flux_correction string
                    flux_origins                   cutout_source, mask_mode
Cache               server user_cache              dcc.Store (session)
Export profile      tess                           cutout
```

---

## Planned cutout enhancement (context)

A **Flux / Background** control in **Curve Tools → Plot Options** (per curve slot) would likely:

- Plot target: existing `to_lightcurve` output (default).
- Plot background: prefer **`get_bkg_lightcurve(user_mask)`** when `FLUX_BKG` is usable; define explicit TESScut fallback policy when the cube has no background extension.

That behaviour should be documented here when implemented; **`Sub bkg`** should remain documented as the **`estimate_background`** path so users are not confused by two different background definitions.
