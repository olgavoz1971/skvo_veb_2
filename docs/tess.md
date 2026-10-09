# TESS photometry in this application

This note describes how TESS archive products (`/tess_lc`) and user FFI/TPF
cutouts (`/tess_cutout`) are calibrated and how pipeline-specific columns are
selected. Implementation lives in `skvo_veb/utils/mission_config/tess.py` and
`skvo_veb/utils/tess_flux_column_registry.py`. Pages must not duplicate zero
points or column names.

---

## 1. Photometric calibration

TESS data reach the app in two photometric families. The PhotCal group on
`CurveDash` follows the stored **flux unit**, not a single global TESS
magnitude scale.

### 1.1 Electron per second (instrument zero point 20.44)

When the stored flux is **electron s-1** (photoelectrons per second),
magnitudes use the TESS instrument conversion

```text
mag = -2.5 log10(F / 1 electron s-1) + 20.44
```

with `ZP_FLUX = 1 electron s-1` and `ZP_MAG = 20.44` (Vega; TESS defined to
match Cousins I). The zero-point uncertainty is **0.05 mag**.

This is the TESS Instrument Handbook formula. A public restatement, including
the same number and uncertainty, is the MIT TESS Transients README:

<https://tess.mit.edu/public/tesstransients/pages/readme.html>

Constants and the helper `instrument_electron_s_photcal()` live in
`mission_config/tess.py`. The same pair is used for:

- unstitched **SPOC** and **TESS-SPOC** archive light curves;
- user **TPF/FFI cutout** aperture sums (author tagged `user`).

It is **not** applied to dimensionless QLP/TARS flux, TASOC `FLUX_CORR` (ppm
stored as dimensionless), legacy stitched relative flux, or background columns.

Cutout provenance must say that 20.44 makes magnitudes commensurable with
SPOC **on the same unit**. A user mask aperture sum is not SPOC pipeline
photometry; crowding and background residuals remain. The MIT page describes
subtraction photometry with a reference-image offset; our cutout path does
not copy that recipe (no `reference_flux` header, no 3-sigma mag upper
limits with `e_mag = 99.9`).

### 1.2 Normalised (dimensionless) pipelines and TESSMAG

**QLP** and **TARS** issue **normalised**, dimensionless flux (order unity,
not electron s-1). For those products we do **not** use 20.44.

If Lightkurve metadata supplies a finite **TESSMAG** (FITS header, catalogue
TESS magnitude), PhotCal is

```text
ZP_FLUX = 1 (dimensionless)
ZP_MAG = TESSMAG
mag = TESSMAG - 2.5 log10(flux)
```

If TESSMAG is missing or invalid, photcal is **passband only** (TESS filter
identifier and effective wavelength). Magnitude conversion is **refused**;
we do not invent a zero point.

**TASOC** headers may also carry TESSMAG. That value is catalogue metadata
only. `FLUX_CORR` is CBV residual in **ppm**, stored here as dimensionless
**without** a TESSMAG zero point. `FLUX_RAW` keeps electron s-1 units and
does not currently receive the 20.44 instrument pair unless we decide that
explicitly later.

### 1.3 Stitching

The archive page (`/tess_lc`) does **not** stitch sectors. Retrieve copies
native pipeline flux from the selected search row. There is no
`LightCurveCollection.stitch()` path and no `metadata['stitched']` on
new products.

Older VOTables that still carry `stitched=true` (relative flux
normalisation) are ingested defensively: PhotCal keeps passband metadata
and omits pipeline zero points, and magnitude conversion is refused. We
do not invent zero points for those files. 

### 1.4 Background

Background time series (for example `SAP_BKG`, `FLUX_BKG`) are not target
photometry. Magnitude conversion is refused. A missing background **error**
column does not hide the background radio; `flux_err` is then NaN.

---

## 2. Pipeline products: columns and metadata

MAST/Lightkurve authors do not share one flux column. The archive Search tab
offers **one selected row**. Flux radios and PhotCal come from an explicit
registry, not from guessing column names.

### 2.1 Registry

`FLUX_COLUMN_REGISTRY` and `BACKGROUND_COLUMN_REGISTRY` in
`tess_flux_column_registry.py` list, per author (and sometimes sector
range):

- photometry column and optional error column;
- calibration class (`physical` electron s-1 vs `normalized_catalog`
  dimensionless);
- optional `zp_mag_source` (`TESSMAG` for QLP/TARS photometry columns).

Unknown authors fail at ingest. We do not invent `PDCSAP_FLUX` for a generic
HLSP.

### 2.2 How ingest uses the file

`tess_lc_builder.create_lc_from_selected_rows` downloads via
`lightkurve_cache`, then `apply_flux_column_selection`. Flux **units** on
`CurveDash` follow the selected Lightkurve column, except:

- QLP and TARS stay dimensionless even if Lightkurve labels differ;
- **ppm** is stored as dimensionless;
- other physical units (electron / s) are preserved via
  `serialise_lightkurve_flux_unit`.

`resolve_photcal` in `tess.py` then attaches PhotCal from author and
optional TESSMAG collected from product `meta`.

### 2.3 Pipeline notes (as implemented)

| Author | Typical flux | PhotCal |
|---|---|---|
| SPOC, TESS-SPOC | `PDCSAP_FLUX` / `SAP_FLUX`, electron s-1 | Instrument 20.44 |
| QLP | `SAP_FLUX`, `KSPSAP_FLUX`, `DET_FLUX`, … dimensionless | TESSMAG if present |
| TARS | `FLUX` only, no error column, dimensionless | TESSMAG if present; `PER1` (days) and `TMIN1` (BTJD) become period and absolute JD epoch (UI epoch is MJD, `Epoch-{2400000.5}`) |
| TASOC | `FLUX_CORR` ppm (dimensionless here); `FLUX_RAW` electron s-1; `FLUX_BKG` electron s-1 without required error | Passband only (no TESSMAG ZP) |
| TGLC, GSFC-ELEANOR-LITE, Kepler | See registry | Not TESSMAG-20.44; TGLC may cite GAIAMAG in notes |

TARS FITS is a generic `TIME`+`FLUX` HLSP. Retrieve must not pass
`quality_bitmask` into Lightkurve’s generic reader (Ticket 18).

### 2.4 Cutouts versus archive

Cutouts (`tess_processor` + `enrich_cutout_curvedash`) are user aperture
sums on a TPF or FFI stamp. There is no flux-column registry. PhotCal is
the **same electron s-1 instrument pair** as SPOC. Upload of a cutout
VOTable **keeps** an existing ZP pair; files without one receive the
instrument pair.

Archive HLSPs keep author-specific columns and the rules in §1–2.3.

### 2.5 What we do not do

- Silent fallbacks or dummy flux errors (NaN is allowed when the file has
  no error column).
- Applying 20.44 to normalised QLP/TARS flux.
- Applying TESSMAG PhotCal to TASOC `FLUX_CORR` ppm.
- Treating TESSMAG as a SPOC-style electron s-1 zero point.

For background extraction details on SPOC/QLP/cutout, see
[tess_background_lightkurve.md](tess_background_lightkurve.md).

---

## 3. Search table Exptime (cadence vs effective integration)

The **Exptime** column on `/tess_cutout` (and the same Lightkurve field on
`/tess_lc`) is **not** computed by this application. Both TPF and FFI search
rows copy Lightkurve `SearchResult.table["exptime"]`, which Lightkurve aliases
from MAST **`t_exptime`**, in seconds.

That catalogue field is the product **cadence** (`TIMEDEL` in the FITS PIXEL
header), not the photon live time after cosmic-ray mitigation (CRM).

### 3.1 Cadence (what the table shows)

| Product | Typical `TIMEDEL` / table Exptime |
|---|---|
| SPOC TPF short | 120 s |
| SPOC TPF fast | 20 s |
| TESS-SPOC TPF from 10 min FFI | 600 s |
| TESS-SPOC TPF from ~200 s FFI | 200 s |
| FFI / TESScut (by mission phase) | 1800 s, 600 s, or 200 s |

Frame timing on SPOC-family files: `INT_TIME = 1.98 s` (photon accumulation per
frame), `READTIME = 0.02 s`, `FRAMETIM = 2.0 s`, `NUM_FRM` frames stacked per
cadence, so `NUM_FRM * FRAMETIM = TIMEDEL`.

### 3.2 Effective integration (in the FITS header, not in the table)

Spacecraft CRM (`CRMITEN = True`) keeps **80%** of frames:
`NREADOUT / NUM_FRM = 0.8`. Per-cadence photon time is

```text
NREADOUT * INT_TIME
```

which is **0.792 × cadence** (0.8 of frames, then 1.98/2.0 for readout on the
frames that are kept). Checked on cached files:

| Product | Cadence | `NREADOUT * INT_TIME` | Ratio |
|---|---|---|---|
| SPOC 2 min TPF | 120 s | 95.04 s | 0.792 |
| TESS-SPOC 10 min TPF | 600 s | 475.2 s | 0.792 |
| TESS-SPOC ~200 s TPF | 200 s | 158.4 s | 0.792 |
| TESScut FFI (same cadences) | 1800 / 600 / 200 s | 1425.6 / 475.2 / 158.4 s | 0.792 |

**20 s SPOC TPF** does not use spacecraft CRM (`CRMITEN = False`,
`CRSPOC = True`): `NREADOUT = NUM_FRM`, so photon time is **19.8 s**
(0.99 × cadence).

`EXPOSURE` in the header is **not** interchangeable between products:

- **TPF:** `[d] time on source` for the **whole file**, not one cadence.
- **TESScut FFI PIXEL HDU:** about **one cadence** of effective time
  (for example ~475 s on a 600 s FFI), matching `NREADOUT * INT_TIME`.

### 3.3 UI note (ghelp later)

Do not relabel the column until in-app help exists. Copy this section into
the cutout (and archive, if the same column is shown) **ghelp** `?` popover
when that work is opened (Ticket 20). Until then, Exptime remains MAST
cadence.
