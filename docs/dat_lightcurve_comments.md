# `.dat` lightcurve comment conventions

ASCII lightcurve files with extension **`.dat`** may carry metadata in ``#`` comment lines.
The same rules apply wherever user uploads are ingested through
``ingest_volightcurve_file()`` in ``lc_bridge`` (TESS lightcurve page, GP O-C page, and
future upload surfaces).

Implementation lives in ``skvo_veb/volightcurve/lightcurve.py`` (``apply_non_votable_heuristics``).

## Supported comment patterns

All matching is case-insensitive on the comment text.

| Pattern | Effect |
|---------|--------|
| ``JD0 = <float>`` | Sets the time-system origin (`timesys.timeorigin`) added when resolving absolute Julian Date. Default **0** if no line matches. |
| ``MAG0 = <float>`` | Sets a reference magnitude on the heuristic ``PhotCal`` attached to mag/flux columns (paired with dimensionless instrumental zero-point flux **1.0**). |
| ``PERIOD = <float>`` | Folding period in **days** (`table.meta['period']`; shown in UI period field after upload). |
| ``EPOCH = <float>`` | Reference epoch in the **same units and time scale as the time column** (same ``JD0`` as ``jd``); converted to absolute JD on ingest. UI fold fields on MJD pages show ``Epoch-2400000.5`` offsets. |
| ``FILTER=<id>`` or ``BAND=<id>`` | Stores a filter or band identifier on photometry metadata. |

## Column naming

Metadata lines use ``KEY = value`` (``JD0``, ``MAG0``, ``PERIOD``, ``EPOCH``, ``FILTER``, ``BAND``).
They must **not** be the only ``#`` line before data if you use Astropy’s ``commented_header``
reader; this application reads ``.dat`` with all ``#`` lines stored as comments, then:

1. A comment line whose **number of words equals the number of data columns**, and which is **not**
   a ``KEY=value`` metadata line, is treated as column names (after stripping ``#``).
2. Otherwise a positional fallback applies for generic ``col1``… columns: column 1 → ``obs_time``,
   column 2 → ``mag``, column 3 → ``mag_err``.

## Formats other than `.dat`

- **VOTable** (``.vot`` / ``.xml``): full VO metadata (TIMESYS, PhotDM, PARAMs).
- **ECSV / CSV**: structured header metadata in ``table.meta`` (e.g. ``period``, ``epoch``, ``name``); comment-line ``JD0`` / ``MAG0`` conventions are **not** used.

## GP page note

The GP extremum fit uses **normalised instrumental flux** internally; timing (JD) and timing
uncertainties are the scientific outputs. Default magnitude zero point for uploads without
complete calibration is configured in ``skvo_veb/utils/gp/config.py`` (`DEFAULT_REFERENCE_MAG`).
