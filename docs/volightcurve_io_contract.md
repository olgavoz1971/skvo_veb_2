# volightcurve file I/O contract (Ticket 8 Phase 0)

**Status:** Agreed (Phase 0). Phase 1 implements `read_lightcurve` /
`write_lightcurve` under this contract. Do not invent alternate formats or
nested application schemas.

**Related:** [dat_lightcurve_comments.md](dat_lightcurve_comments.md),
[lightcurve_data_flow.md](lightcurve_data_flow.md),
sibling package ``volightcurve``
(``/home/voz/projects/UPJS/volightcurve`` — ``io_keywords.py``),
Ticket 8 in [TODO.md](TODO.md).

---

## 1. Goals

1. Upload parse and download serialise for lightcurve products live in the
   sibling ``volightcurve`` package (no Dash, Plotly, or CurveDash).
2. Every UI download format preserves **photometric and time calibration**
   metadata that the working product already holds.
3. Do **not** invent private file formats. Non-VO carriers reuse one plain
   keyword vocabulary; VOTable keeps IVOA PhotDM / TIMESYS.

## 2. Formats in scope

| UI option | Format id | Metadata carrier |
|-----------|-----------|------------------|
| VOTable binary / text | `votable_binary` / `votable_text` | TIMESYS, PhotDM GROUP, PARAMs |
| ECSV | `ascii.ecsv` | Flat keys in standard ECSV `meta:` YAML |
| ASCII commented header (`.dat`) | `ascii.commented_header` | `# KEY = value` comments (same codec as `.dat` upload) |
| CSV | `csv` | `# KEY = value` preamble (same vocabulary as `.dat`) |

`ascii.commented_header` download and `.dat` upload are **one codec**.

## 3. What is first-class vs description

**First-class** (must round-trip when present): only fields needed for
**photometric calibration** or **time calibration** (including fold period /
epoch that share the time origin).

**Not first-class on non-VO formats** (Tier B omitted): timescale,
refposition, COOSYS, facility, instrument, publication id, rich VO
descriptions as structured fields.

**Free text:** any other `#` comment lines (or leftover narrative) are stored
on the table as description / comment list and re-emitted as `# …` lines on
download. They must not be parsed as calibration keywords.

## 4. Shared keyword vocabulary (non-VO)

Case-insensitive on read. Write using the canonical uppercase names below.
Emit a key **only when the value is present** on the product — never invent
zero points or origins on write.

| Keyword | Meaning | Maps to (internal) |
|---------|---------|--------------------|
| `JD0` | Time origin added to the time column to obtain absolute JD | `timesys.timeorigin` |
| `EPOCH` | Reference epoch in the **same units and origin as the time column** | `table.meta['epoch']` (file-native); absolute JD after ingest normalisation |
| `PERIOD` | Folding period in days | `table.meta['period']` |
| `MAG0` | Legacy compact reference magnitude | `PhotCal.zp_mag` (read alias) |
| `ZP_MAG` | Zero-point magnitude | `PhotCal.zp_mag` |
| `ZP_MAG_UNIT` | Unit for `ZP_MAG` (typically `mag`) | `PhotCal.zp_mag_unit` |
| `ZP_FLUX` | Zero-point flux | `PhotCal.zp_flux` |
| `ZP_FLUX_UNIT` | Unit for `ZP_FLUX`; empty / omitted ⇒ dimensionless | `PhotCal.zp_flux_unit` (`None` internal) |
| `MAG_SYS` | Magnitude system (e.g. `Vega`, `AB`) | `PhotCal.mag_sys` |
| `FILTER` | Filter / bandpass identifier | `PhotometryFilter.filter_id` |
| `BAND` | Alias of `FILTER` on read | same |
| `FILTER_NAME` | Human-readable filter name (optional) | filter name metadata |
| `EFFECTIVE_WAVELENGTH` | Filter spectral location value (optional) | PhotometryFilter wavelength |
| `EFFECTIVE_WAVELENGTH_UNIT` | Unit for the wavelength (optional) | e.g. `m`, `nm` |

### Read aliases

- `MAG0` → same slot as `ZP_MAG`. If both appear, prefer `ZP_MAG`.
- `BAND` → same slot as `FILTER`. If both appear, prefer `FILTER`.

### Write preference

- When rich photcal is present, write the full ZP set (`ZP_FLUX`,
  `ZP_FLUX_UNIT`, `ZP_MAG`, `ZP_MAG_UNIT`, `MAG_SYS`) plus `FILTER` /
  optional filter extras.
- Still accept legacy files that only have `MAG0` (heuristic
  `ZP_FLUX = 1` dimensionless remains an **ingest** behaviour for that
  legacy case only — not invented on write of incomplete products).

### ECSV shape

Use **flat** `meta:` entries with the same keyword names (e.g. `JD0`,
`ZP_FLUX`). Do **not** nest a private `photcal:` mapping — nested YAML is
legal ECSV but invents an application schema; flat keys stay ordinary table
meta for generic readers.

### CSV / `.dat` shape

```text
# JD0 = 0
# ZP_MAG = 20.0
# ZP_FLUX = 1.0
# ZP_FLUX_UNIT =
# FILTER = TESS/TESS.Red
# PERIOD = 1.23
# EPOCH = 2459000.25
# optional free-text description lines
# jd mag mag_err
2459000.0 12.1 0.01
```

(Empty `ZP_FLUX_UNIT` means dimensionless on the wire; see
`volightcurve/vo_unit_codec.py`.)

## 4b. Photometry domain (non-VO) — locked

**No `DOMAIN=` keyword.** Domain is carried only by **column names** (and by
VOTable unit/UCD on the VO path).

### Write (CSV / `.dat` / commented-header / ECSV data columns)

| Session domain | Time | Photometry | Error |
|----------------|------|------------|-------|
| magnitude | `jd` | `mag` | `mag_err` |
| flux | `jd` | `flux` | `flux_err` |

Do **not** write ambiguous `phot` / `flux_error` for these formats (that name
pair drops domain on re-ingest).

### Read

1. Explicit `mag` / `mag_err` → magnitude.
2. Explicit `flux` / `flux_err` → flux.
3. **Ambiguous** cases (`phot`, bare `col2`, unit/UCD absent) → **default
   magnitude** (`mag` / `mag_err` semantics), matching common simple `.dat`
   practice.
4. Never infer domain from `ZP_*` alone.

VOTable continues to use unit + UCD (`phot.mag` vs `phot.flux`).

## 5. Strict time-origin contract

For every format:

1. The time column is interpreted relative to an explicit origin (`JD0` /
   TIMESYS `@timeorigin`).
2. **`EPOCH` (and any epoch-like PARAM) must use that same origin** as the
   time column in the file.
3. After ingest, session storage may hold absolute JD; export must convert
   epoch back to the file time system so re-ingest restores the same
   absolute times.
4. Missing `JD0` on legacy `.dat` ingest still defaults to `0` (documented
   heuristic). Writers must not invent a non-zero origin.

VOTable export may continue to serialise `obs_time` as MJD with
`timeorigin = 2400000.5` provided epoch PARAMs use that same origin.

## 6. Public API (volightcurve)

```text
read_lightcurve(source, *, filename | format) -> VOLightCurve
write_lightcurve(volc, format, stream_or_path, *, ...) -> bytes | None
```

- No CurveDash types or names inside `volightcurve`.
- App bridge (`lc_bridge`) maps `VOLightCurve` ↔ `CurveDash` only.
- Package errors are plain / local; the bridge maps to `PipeException` for UI.

Constants for the keyword vocabulary live in the sibling package
``volightcurve.io_keywords`` (``/home/voz/projects/UPJS/volightcurve``).

## 7. Phase boundary

| Phase | Deliverable |
|-------|-------------|
| **0** | Inventory, vocabulary, API names, carriers agreed and documented |
| **1 (done)** | ``read_lightcurve`` / ``write_lightcurve`` under ``volightcurve``; Dash-free round-trips |
| **2 (done)** | Page audit; docs; narrative ``file_comments``; Processor-style smoke |
| **2b (done)** | Explicit ``mag``/``flux`` column names; ambiguous ``phot`` → mag |
| **3 (done)** | Retire ``CurveDash.download`` (raises; use ``export_curvedash``) |
