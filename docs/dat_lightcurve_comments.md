# Lightcurve comment / flat-meta conventions (``.dat``, CSV, ECSV)

ASCII lightcurve products may carry **photometric and time calibration**
metadata as plain ``KEY = value`` fields. The same vocabulary is used for:

- **``.dat``** / **``ascii.commented_header``** — ``#`` comment lines
- **CSV** — ``#`` preamble before the header row (same vocabulary)
- **ECSV** — **flat** keys in the standard ``meta:`` YAML map (same names;
  no nested ``photcal:`` schema)

Full codec contract (API, time-origin rules, Tier B omission): 
[volightcurve_io_contract.md](volightcurve_io_contract.md).

Keyword constants: ``skvo_veb/volightcurve/io_keywords.py``.

Ingest entry points use ``volightcurve.io.read_lightcurve`` (pages still go
through ``lc_bridge.ingest_volightcurve_file``). Download uses
``write_lightcurve``. Heuristics that apply comment / flat-meta calibration live
in ``apply_non_votable_heuristics``.

## First-class keywords

All matching is case-insensitive on read. Writers use the canonical names
below and emit a key **only when present** (no invented ZP / JD0 on write).

| Pattern | Effect |
|---------|--------|
| ``JD0 = <float>`` | Time-system origin (`timesys.timeorigin`) added when resolving absolute Julian Date. Default **0** on ingest if no line matches. |
| ``EPOCH = <float>`` | Reference epoch in the **same units and origin as the time column** (same ``JD0``). Converted to absolute JD on ingest. |
| ``PERIOD = <float>`` | Folding period in **days** (`table.meta['period']`). |
| ``MAG0 = <float>`` | Legacy alias for ``ZP_MAG`` on read. Prefer ``ZP_MAG`` when both appear. Legacy-only ``MAG0`` may still imply instrumental ``ZP_FLUX = 1`` dimensionless on ingest. |
| ``ZP_MAG = <float>`` | Zero-point magnitude (`PhotCal.zp_mag`). |
| ``ZP_MAG_UNIT = <str>`` | Unit for ``ZP_MAG`` (typically ``mag``). |
| ``ZP_FLUX = <float>`` | Zero-point flux (`PhotCal.zp_flux`). |
| ``ZP_FLUX_UNIT = <str>`` | Unit for ``ZP_FLUX``; empty / omitted ⇒ dimensionless (`None` internal). |
| ``MAG_SYS = <str>`` | Magnitude system (e.g. ``Vega``, ``AB``). |
| ``FILTER=<id>`` or ``BAND=<id>`` | Filter / bandpass identifier. ``BAND`` is a read alias of ``FILTER``. |
| ``FILTER_NAME = <str>`` | Optional human-readable filter name. |
| ``EFFECTIVE_WAVELENGTH = <float>`` | Optional filter spectral location. |
| ``EFFECTIVE_WAVELENGTH_UNIT = <str>`` | Optional unit for that wavelength. |

### Strict time-origin contract

``EPOCH`` (and any epoch-like value in the file) **must** share the same
``JD0`` / time origin as the time column. See the I/O contract doc.

### Free-text comments

``#`` lines that are **not** first-class ``KEY = value`` assignments are kept
as description / comment text and re-emitted on download. They are not
parsed as calibration.

## Photometry columns (no ``DOMAIN`` keyword)

Non-VO files express mag vs flux by **column names** only:

| Domain | Columns |
|--------|---------|
| magnitude (usual simple ``.dat``) | ``jd``, ``mag``, ``mag_err`` |
| flux | ``jd``, ``flux``, ``flux_err`` |

Writers must use those names (not ambiguous ``phot`` / ``flux_error``).
On read, ambiguous names (``phot``, legacy ``col2``, …) **default to
magnitude**. Do not invent a ``DOMAIN=`` comment key. Full rules:
[volightcurve_io_contract.md](volightcurve_io_contract.md) §4b.

## Column naming (``.dat``)

Metadata lines use ``KEY = value``. They must **not** be the only ``#`` line
before data if you use Astropy’s ``commented_header`` reader; this application
reads ``.dat`` with all ``#`` lines stored as comments, then:

1. A comment line whose **number of words equals the number of data columns**,
   and which is **not** a ``KEY=value`` metadata line, is treated as column
   names (after stripping ``#``).
2. Otherwise a positional fallback applies for generic ``col1``… columns:
   column 1 → ``obs_time``, column 2 → ``mag``, column 3 → ``mag_err``.

## Row validation (strict, ``.dat``)

Every non-comment data line must contain the same number of whitespace-separated
fields:

- If a ``#`` comment line lists column names (not ``KEY=value`` metadata) and
  its word count matches the data width, that width is required on every row.
- Otherwise legacy ``.dat`` files must have exactly **three** columns per row
  (no padding).
- Ragged or non-numeric rows fail ingest with ``PipeException`` and a **line
  number** (GP/TESS upload ``?`` help shows the message).
- Columns named ``label``, ``sector``, or ``flag`` may contain arbitrary
  strings; other columns must be numeric (``NaN`` is allowed for missing
  photometry errors).

## VOTable

**VOTable** (``.vot`` / ``.xml``): full VO metadata (TIMESYS, PhotDM, PARAMs).
Non-VO Tier B fields (timescale, refposition, COOSYS, facility, …) stay on the
VO path only; they are not required on ``.dat`` / CSV / ECSV.

## GP page note

The GP extremum fit uses **normalised instrumental flux** internally; timing
(JD) and timing uncertainties are the scientific outputs. Default magnitude
zero point for uploads without complete calibration is configured in
``skvo_veb/utils/lc_config.py`` (`DEFAULT_REFERENCE_MAG`) and
``volightcurve/photcal_defaults.py``.
